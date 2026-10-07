import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.candidate_ranker import choose_best
from engine.cta_resolver import verify_cta
from engine.media_prefilter import prefilter
from engine.media_router import normalize_media_contract, validate_media_contract
from engine.longform_pipeline import DRAFT_REPAIR_POLICY_VERSION, _draft_blocker_text, _pid_alive, align_observable_evidence_contracts, apply_cta_end_screen_route, apply_persisted_draft_repairs, build_draft_repair_plan, checkpoint_resolution_compatible, create_asset, enforce_hard_route_priority, materialize_hybrid_shot, normalize_degraded_watchthrough, prepare_avatar_companion, restore_directed_repair_media, sanitize_avatar_companion, shot_input_signature, still_image_forbidden, upgrade_visual_plan, viewer_video_qa
from engine.evidence_set_qa import validate_set
from engine.provider_manager import ProviderManager, ProviderSpec
from engine.query_compilers import compile_all
from engine.retention_director import validate_retention
from engine import media_tools
from providers.core import MockProviders
from providers.cutout_video import validate_analysis as validate_cutout_analysis
from providers.deterministic_ui import materialize_shot


class RoutingV3Tests(unittest.TestCase):
    def test_clip_extractor_is_forbidden_for_generic_human_action(self):
        shot = {
            "shotId": "S0001",
            "chapterId": "C01",
            "tts": "Una mujer aplica crema corporal en su pierna.",
            "visualProof": "woman applying body cream",
        }
        normalize_media_contract(shot, {"route": "clip_extractor"})
        self.assertEqual("human_action", shot["proofKind"])
        self.assertNotIn("clip_extractor", shot["routePlan"])
        self.assertEqual([], validate_media_contract(shot))

    def test_camelcase_false_contract_values_are_preserved(self):
        shot = {
            "shotId": "S0000",
            "tts": "Antes de comprar otra crema, mira esto.",
            "visualProof": "open cosmetic jar with a realistic label",
            "proofKind": "product_inspection",
            "requiresReadableData": False,
            "requiresStateContinuity": False,
            "route": "image",
        }
        normalize_media_contract(shot, shot)
        self.assertFalse(shot["requiresReadableData"])
        self.assertFalse(shot["requiresStateContinuity"])
        self.assertEqual("image", shot["route"])

    def test_locked_product_inspection_is_not_reclassified_by_action_words(self):
        shot = {
            "shotId": "S0000",
            "tts": "Una mano abre el envase para revisar la crema.",
            "visualProof": "readable topical package",
            "proofKind": "product_inspection",
            "mediaNeedKind": "product_inspection",
            "proofKindLocked": True,
            "route": "image",
        }
        normalize_media_contract(shot, shot)
        self.assertEqual("product_inspection", shot["proofKind"])

    def test_locked_exact_ui_checklist_is_not_reclassified_as_packaging(self):
        shot = {
            "shotId": "S0008",
            "tts": "Revisa la etiqueta con esta regla de compra.",
            "visualProof": "deterministic purchase checklist",
            "proofKind": "exact_ui_state",
            "mediaNeedKind": "exact_ui_state",
            "proofKindLocked": True,
            "requiresReadableData": True,
            "route": "ui",
        }
        normalize_media_contract(shot, shot)
        self.assertEqual("exact_ui_state", shot["proofKind"])
        self.assertEqual(["ui"], shot["routePlan"])

    def test_real_commentary_has_no_synthetic_substitute(self):
        shot = {
            "shotId": "S0002",
            "chapterId": "C01",
            "tts": "Escucha el comentario público de esta dermatóloga.",
            "visualProof": "original public interview commentary",
        }
        normalize_media_contract(shot, {"proof_kind": "third_party_commentary", "route": "image"})
        self.assertEqual(["clip_extractor"], shot["routePlan"])
        self.assertEqual([], validate_media_contract(shot))

    def test_comparison_allows_small_contextual_faces(self):
        shot = {
            "shotId": "S0003",
            "tts": "Compara la misma persona desde dos ángulos.",
            "visualProof": "same person comparison",
        }
        normalize_media_contract(shot)
        self.assertEqual("comparison", shot["proofKind"])
        self.assertEqual("contextual", shot["peoplePolicy"])
        self.assertFalse(shot["presenterAllowed"])
        self.assertEqual(0.20, shot["maxFaceAreaRatio"])

        shot["peoplePolicy"] = "forbidden"
        normalize_media_contract(shot, {"proof_kind": "comparison", "people_policy": "forbidden"})
        self.assertEqual("contextual", shot["peoplePolicy"])

    def test_human_action_never_requires_presenter_face(self):
        shot = {
            "shotId": "S0004",
            "tts": "Aplica la misma cantidad en una zona pequeña y toma una foto.",
            "visualProof": "hands perform a controlled skin test",
            "peoplePolicy": "required",
        }
        normalize_media_contract(shot, {"proof_kind": "human_action", "people_policy": "required"})
        self.assertEqual("contextual", shot["peoplePolicy"])
        self.assertFalse(shot["presenterAllowed"])

    def test_multistep_human_action_uses_two_controlled_states_without_forcing_video(self):
        shot = {
            "shotId": "S0005",
            "tts": "Primero aplica la misma cantidad y luego toma una foto.",
            "visualProof": "controlled two-step skin test",
        }
        normalize_media_contract(shot, {"proof_kind": "human_action", "temporal_action": "multi_step"})
        compile_all(shot)
        self.assertEqual("initial_final", shot["temporalEvidenceMode"])
        self.assertEqual("image_pair", shot["route"])
        self.assertEqual(["image_pair", "pexels", "omni", "ui"], shot["routePlan"])
        self.assertFalse(shot["requiresObservedTransition"])

    def test_unjustified_continuous_hint_becomes_initial_final(self):
        shot = {
            "shotId": "S0005",
            "tts": "Usa la misma cantidad en una zona pequeña y toma una foto antes.",
            "visualProof": "two controlled states",
        }
        normalize_media_contract(shot, {
            "proof_kind": "human_action",
            "temporal_action": "multi_step",
            "temporal_evidence_mode": "continuous",
            "requires_observed_transition": True,
        })
        self.assertEqual("initial_final", shot["temporalEvidenceMode"])
        self.assertFalse(shot["requiresObservedTransition"])
        self.assertEqual("image_pair", shot["route"])

    def test_unjustified_continuous_hint_becomes_implied_for_single_state(self):
        shot = {"shotId": "S0004", "tts": "El calor no demuestra pérdida de grasa.", "visualProof": "surface sensation"}
        normalize_media_contract(shot, {
            "proof_kind": "physiological_mechanism",
            "temporal_action": "single",
            "temporal_evidence_mode": "continuous",
            "requires_observed_transition": True,
        })
        self.assertEqual("implied", shot["temporalEvidenceMode"])
        self.assertFalse(shot["requiresObservedTransition"])

    def test_stale_single_does_not_hide_two_observable_actions(self):
        shot = {
            "shotId": "S0006",
            "tts": "Usa la misma cantidad en una zona pequeña y toma una foto antes.",
            "visualProof": "controlled test",
            "temporalAction": "single",
        }
        normalize_media_contract(shot, {"proof_kind": "human_action", "temporalAction": "single"})
        self.assertEqual("multi_step", shot["temporalAction"])
        self.assertEqual("initial_final", shot["temporalEvidenceMode"])
        self.assertEqual("image_pair", shot["route"])

    def test_single_observable_state_may_use_animated_still(self):
        self.assertFalse(still_image_forbidden({"temporalAction": "single", "movingVisualRequired": True}))
        self.assertFalse(still_image_forbidden({"temporalAction": "multi_step", "temporalEvidenceMode": "implied"}))
        self.assertFalse(still_image_forbidden({"temporalAction": "multi_step", "temporalEvidenceMode": "initial_final"}))
        self.assertTrue(still_image_forbidden({"temporalAction": "multi_step", "temporalEvidenceMode": "continuous", "requiresObservedTransition": True}))

    def test_comparison_uses_two_separate_image_prompts(self):
        shot = {
            "shotId": "S0003", "chapterId": "C01", "startMs": 0, "endMs": 4000,
            "tts": "Compara la misma persona con la misma luz y otro ángulo.",
            "visualProof": "same person in two controlled viewpoints",
            "screenCopy": "MISMA LUZ",
            "continuityGroup": "controlled-angle-pair",
        }
        normalize_media_contract(shot, {"proof_kind": "comparison", "route": "image"})
        result = compile_all(shot)
        pair = json.loads(result["image_pair"][0])
        self.assertEqual("image_pair", shot["route"])
        self.assertIn("left", pair)
        self.assertIn("right", pair)
        self.assertNotEqual(pair["left"], pair["right"])
        self.assertEqual([], validate_media_contract(shot))

    def test_two_distinctions_use_editorial_image_with_remotion_labels(self):
        shot = {
            "shotId": "S0007",
            "tts": "No confundas hinchazón con grasa, ni piel luminosa con menos tejido adiposo.",
            "visualProof": "two separate body distinctions",
        }
        normalize_media_contract(shot, {"proof_kind": "comparison"})
        compile_all(shot)
        self.assertTrue(shot["complexComparison"])
        self.assertEqual("image", shot["route"])
        self.assertEqual("body-distinction", shot["hybridTemplate"])
        self.assertEqual("body-distinction", shot["uiTemplate"])
        self.assertEqual(["HINCHAZÓN ≠ GRASA", "PIEL LUMINOSA ≠ MENOS GRASA"], shot["uiItems"])

        shot.update({"route": "cutout_motion", "routePlan": ["cutout_motion", "ui", "image_pair"]})
        enforce_hard_route_priority(shot)
        self.assertEqual("image", shot["route"])
        self.assertNotIn("ui", shot["routePlan"])

    def test_controlled_angle_comparison_forces_image_pair(self):
        shot = {
            "shotId": "S0012",
            "tts": "No cambies el ángulo para fabricar una diferencia.",
            "visualProof": "same person controlled comparison",
            "continuityGroup": "protocol",
        }
        normalize_media_contract(shot, {"proof_kind": "comparison", "route": "ui"})
        enforce_hard_route_priority(shot)
        self.assertTrue(shot["controlledComparison"])
        self.assertEqual("image_pair", shot["route"])
        self.assertEqual("protocol-visual", shot["continuityGroup"])

        preparation = {
            "shotId": "S0011",
            "tts": "Mantén la misma luz, distancia y postura.",
            "visualProof": "controlled protocol instructions",
        }
        normalize_media_contract(preparation, {"proof_kind": "comparison", "route": "ui"})
        self.assertFalse(preparation["controlledComparison"])
        self.assertTrue(preparation["protocolComparisonSetup"])
        preparation.update({"route": "image_pair", "routePlan": ["image_pair", "ui"]})
        enforce_hard_route_priority(preparation)
        self.assertEqual("image", preparation["route"])
        self.assertEqual("process-steps", preparation["uiTemplate"])
        self.assertEqual("process-steps", preparation["hybridTemplate"])

    def test_verified_cta_route_marks_only_one_anchor(self):
        shots = [
            {"shotId": "S1", "tts": "Cierra el método."},
            {"shotId": "S2", "tts": "Ahora mira Video real:"},
            {"shotId": "S3", "tts": "qué aporta a la piel."},
        ]
        apply_cta_end_screen_route({"cta": {"verified": True, "target_video_title": "Video real", "screen_copy": "MIRA ESTE VIDEO"}}, shots)
        self.assertNotIn("ctaAnchor", shots[0])
        self.assertTrue(shots[1]["ctaAnchor"])
        self.assertNotIn("ctaAnchor", shots[2])
        self.assertNotIn("verifiedCtaEndScreen", shots[1])
        self.assertNotIn("uiTemplate", shots[1])

    def test_image_pair_materializes_both_sources_and_composite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            paths = {"public": root / "public"}
            (paths["public"] / "assets").mkdir(parents=True)
            shot = {
                "shotId": "S0004", "chapterId": "C01", "startMs": 0, "endMs": 4000,
                "tts": "Compara dos estados.", "visualProof": "same subject two states", "requiredEvidence": "same subject two states",
                "mediaNeedKind": "comparison", "proofKind": "comparison", "continuityGroup": "pair-test", "hookRequirement": "",
                "prompt": "", "screenCopy": "COMPARA",
            }
            normalize_media_contract(shot, shot)
            query = compile_all(shot)["image_pair"][0]
            _, output, media_type = create_asset(MockProviders(1920, 1080, 30), {"run_id": "pair-test"}, paths, shot, "image_pair", query_override=query)
            self.assertEqual("image", media_type)
            self.assertTrue(output.is_file())
            self.assertTrue(output.with_name("S0004_pair_a.png").is_file())
            self.assertTrue(output.with_name("S0004_pair_b.png").is_file())


class ProviderRecoveryTests(unittest.TestCase):
    def _manager(self, directory: str) -> ProviderManager:
        spec = ProviderSpec(
            name="cutout_motion",
            health_url="http://127.0.0.1:9999/health",
            managed=True,
            workdir=pathlib.Path(directory),
            argv=(sys.executable, "-c", "pass"),
            readiness_seconds=0.2,
        )
        return ProviderManager(pathlib.Path(directory) / "provider_manager.json", {"cutout_motion": spec})

    def test_cutout_off_is_started_and_becomes_healthy(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            manager._probe = mock.Mock(side_effect=[(False, "connection refused", None), (True, "ok", 200)])
            manager._start = mock.Mock(return_value=3210)
            result = manager.ensure("cutout_motion")
            self.assertEqual("healthy", result["status"])
            self.assertTrue(result["auto_started"])
            manager._start.assert_called_once()

    def test_successful_health_probe_clears_stale_circuit(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            manager.runtime.state["circuits"]["cutout_motion"] = {"until": 9999999999, "reason": "old failure"}
            manager.runtime._save()
            manager._probe = mock.Mock(return_value=(True, "ok", 200))
            result = manager.ensure("cutout_motion")
            state = json.loads(manager.runtime.path.read_text(encoding="utf-8"))
            self.assertEqual("healthy", result["status"])
            self.assertNotIn("cutout_motion", state["circuits"])

    def test_cutout_prop_matching_normalizes_hyphens(self):
        analysis = {
            "scenes": [{"motion": {"skin": "enter"}}],
            "asset_specs": [
                {"type": "background", "label": "beige studio"},
                {"type": "prop", "label": "skin cross section editorial"},
            ],
            "estimated_duration_seconds": 4,
        }
        self.assertEqual([], validate_cutout_analysis(analysis, {
            "expected_props": ["skin cross-section"],
            "stop_motion_intent": "technical_choreography",
            "why_stop_motion": "La coreografía separa las capas para que el mecanismo sea fácil de seguir.",
        }, 4))


class TechnicalQualityTests(unittest.TestCase):
    def test_compressed_nominal_1080p_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "compressed-1080.mp4"
            command = [
                media_tools.find_binary("ffmpeg"), "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=gray:size=1920x1080:rate=24",
                "-t", "1.2", "-c:v", "libx264", "-b:v", "180k", "-pix_fmt", "yuv420p", str(output),
            ]
            subprocess.run(command, check=True)
            report = prefilter(output, "video", {"proofKind": "human_action", "peoplePolicy": "contextual"}, "pexels")
            self.assertEqual("REJECT", report["status"])
            self.assertTrue(any("1080p comprimido" in error or "reescalado" in error for error in report["errors"]))

    def test_pexels_4k_wins_equal_semantic_score(self):
        candidates = [
            {"route": "pexels", "variant_index": 0, "ranking": {"score": 91, "quality": {"source_width": 1920, "source_height": 1080, "width": 1920}}},
            {"route": "pexels", "variant_index": 1, "ranking": {"score": 91, "quality": {"source_width": 3840, "source_height": 2160, "width": 1920}}},
        ]
        self.assertEqual(1, choose_best(candidates)["variant_index"])

    def _image(self, directory: str) -> pathlib.Path:
        path = pathlib.Path(directory) / "scene.jpg"
        cv2.imwrite(str(path), np.full((720, 1280, 3), 180, dtype=np.uint8))
        return path

    def test_contextual_face_is_accepted_when_evidence_remains_dominant(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch("engine.media_prefilter._face_metrics", return_value=(1, 0.08)), \
             mock.patch("engine.media_prefilter._ocr", return_value=("", True)):
            report = prefilter(self._image(directory), "image", {"proofKind": "human_action", "peoplePolicy": "contextual", "maxFaceAreaRatio": 0.20}, "image")
            self.assertFalse(any("presentador accidental" in error for error in report["errors"]))

    def test_accidental_presenter_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch("engine.media_prefilter._face_metrics", return_value=(1, 0.38)), \
             mock.patch("engine.media_prefilter._ocr", return_value=("", True)):
            report = prefilter(self._image(directory), "image", {"proofKind": "product_inspection", "peoplePolicy": "contextual", "maxFaceAreaRatio": 0.20}, "image")
            self.assertEqual("REJECT", report["status"])
            self.assertTrue(any("presentador accidental" in error for error in report["errors"]))


class GlobalGateTests(unittest.TestCase):
    def test_pid_liveness_detects_real_child_process(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            self.assertTrue(_pid_alive(child.pid))
        finally:
            child.terminate()
            child.wait(timeout=5)
        self.assertFalse(_pid_alive(child.pid))

    def test_avatar_fallback_does_not_require_a_presenter(self):
        shot = {
            "tts": "La sensación ocurre en la superficie.",
            "visualProof": "Distingue piel superficial de grasa subcutánea.",
            "companionRoutePlan": ["cutout_motion", "image", "omni"],
        }
        companion = sanitize_avatar_companion(shot, {
            "proofKind": "abstract_concept",
            "mediaNeedKind": "abstract_concept",
            "peoplePolicy": "required",
            "presenterAllowed": True,
            "requiredEvidence": "Trusted presenter delivers the approved narration.",
            "route": "cutout_motion",
            "routePlan": ["cutout_motion", "image", "omni"],
        })
        self.assertEqual("forbidden", companion["peoplePolicy"])
        self.assertFalse(companion["presenterAllowed"])
        self.assertNotIn("presenter", companion["requiredEvidence"].lower())

    def test_four_question_avatar_fallback_is_explicit_ui(self):
        shot = {"tts": "Cuando separas esas cuatro preguntas, la publicidad pierde poder", "screenCopy": "4 PREGUNTAS"}
        companion = sanitize_avatar_companion(shot, {"route": "motion-card", "routePlan": ["motion-card"]})
        self.assertEqual("ui", companion["route"])
        self.assertEqual("process-steps", companion["uiTemplate"])
        self.assertEqual(4, len(companion["uiItems"]))
        self.assertIn("¿TU PIEL LO TOLERA?", companion["uiItems"])

    def test_four_question_blocker_wins_over_generic_packaging_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            plan = {"shots": [{
                "shotId": "S0017",
                "tts": "Separa cuatro preguntas antes de comprar la crema.",
                "proofKind": "presenter",
                "route": "image",
                "routePlan": ["image"],
            }]}
            report = {"viewer": {"blockers": [{
                "label": "S0017",
                "reason": "No explica las 4 preguntas y muestra alimentos; no evidencia la etiqueta del producto tratado.",
            }]}}
            repaired = build_draft_repair_plan({}, plan, report, {"work": work})
            shot = repaired["shots"][0]
            self.assertEqual("ui", shot["route"])
            self.assertEqual("exact_ui_state", shot["proofKind"])
            self.assertEqual(4, len(shot["uiItems"]))
            self.assertFalse(shot["presenterAllowed"])
            self.assertNotIn("companionRoute", shot)
            self.assertFalse(str(shot.get("noveltyKey") or "").startswith("presenter-"))

    def test_same_area_blocker_pins_the_controlled_second_pair_when_available(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            data = {"run_id": "test-run"}
            plan = {"shots": [{"shotId": "S0015", "proofKind": "comparison", "route": "image_pair", "routePlan": ["image_pair"]}]}
            report = {"viewer": {"blockers": [{"label": "S0015", "reason": "No muestra same skin area comparison ni que el contorno permanezca igual."}]}}
            repaired = build_draft_repair_plan(data, plan, report, {"work": work})
            shot = repaired["shots"][0]
            self.assertEqual("controlled-same-area", shot["uiVariant"])
            self.assertEqual("image_pair", shot["route"])
            self.assertIn("MISMO CONTORNO", shot["uiValues"])

    def test_cropped_fictional_label_repair_preserves_purchase_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            plan = {"shots": [{
                "shotId": "S0009",
                "tts": "No pagues la promesa si la evidencia no la respalda.",
                "proofKind": "product_inspection",
                "route": "ui",
                "routePlan": ["ui"],
                "uiVariant": "claim-evidence",
                "uiItems": ["CLAIM", "EVIDENCIA", "DECISIÓN"],
                "uiValues": ["REDUCE CENTÍMETROS", "NO REDUCE GRASA", "NO COMPRES"],
                "requiredEvidence": "The panel ends in NO COMPRES beside the package.",
                "backgroundSource": "runs/test/assets/product.png",
                "backgroundMediaType": "image",
            }]}
            report = {"viewer": {"blockers": [{
                "label": "S0009",
                "reason": "El envase tiene una etiqueta poco clara y parcialmente ilegible.",
            }]}}
            shot = build_draft_repair_plan({}, plan, report, {"work": work})["shots"][0]
            self.assertEqual("claim-evidence", shot["uiVariant"])
            self.assertEqual("NO COMPRES", shot["uiValues"][-1])
            self.assertEqual("exact_ui_state", shot["proofKind"])
            self.assertNotIn("backgroundObjectPosition", shot)
            self.assertNotIn("backgroundSource", shot)

    def test_incidental_packaging_rejection_preserves_same_area_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            plan = {"shots": [{
                "shotId": "S0015",
                "tts": "Solo cambia la hidratación de la superficie.",
                "proofKind": "comparison",
                "route": "image_pair",
                "routePlan": ["image_pair"],
                "requiredEvidence": "The exact same skin area and contour appear on both sides; only surface hydration and sheen change.",
            }]}
            report = {"viewer": {"blockers": [{
                "label": "S0015",
                "reason": "Packaging generado con etiqueta parcialmente ilegible en el fondo.",
            }]}}
            shot = build_draft_repair_plan({"run_id": "test-run"}, plan, report, {"work": work})["shots"][0]
            self.assertEqual("comparison", shot["proofKind"])
            self.assertEqual("image_pair", shot["route"])
            self.assertEqual("controlled-same-area", shot["uiVariant"])
            self.assertIn("visible-packaging", shot["forbiddenSubstitutions"])

    def test_safety_repair_requires_full_use_to_stop_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            plan = {"shots": [{
                "shotId": "S0014",
                "tts": "Si irrita, suspéndelo.",
                "proofKind": "human_action",
                "route": "image_pair",
                "routePlan": ["image_pair"],
                "source": "viewer-rejected-irritation.png",
            }]}
            report = {"viewer": {"blockers": [{
                "label": "S0014",
                "reason": "Falta la acción de suspenderlo después de la irritación.",
            }]}}
            shot = build_draft_repair_plan({}, plan, report, {"work": work})["shots"][0]
            self.assertEqual("safety-sequence", shot["uiVariant"])
            self.assertEqual(["APLICA", "OBSERVA", "IRRITA", "SUSPENDE"], shot["uiItems"])
            self.assertIn("four-state visual sequence", shot["requiredEvidence"])
            self.assertNotIn("cutout_motion", shot["routePlan"])
            self.assertNotIn("pinnedAsset", shot)
            self.assertEqual("s0014-directed-repair", shot["continuityGroup"])

    def test_sensation_beat_uses_surface_diagram_not_impossible_internal_reaction(self):
        shot = {
            "proofKind": "human_action",
            "tts": "No juzgues el producto por calor, cosquilleo o sudor.",
            "requiredEvidence": "visible tingling reaction",
        }
        align_observable_evidence_contracts([shot])
        self.assertEqual("physiological_mechanism", shot["proofKind"])
        self.assertEqual("ui", shot["route"])
        self.assertIn("surface sensations", shot["requiredEvidence"])
        self.assertIn("not proof", shot["requiredEvidence"])

    def test_avatar_ui_companion_is_compiled_and_stale_card_is_rejected(self):
        shot = {
            "route": "avatar",
            "companionRoute": "ui",
            "companionRoutePlan": ["ui"],
            "screenCopy": "4 PREGUNTAS",
            "tts": "Cuando separas esas cuatro preguntas, la publicidad pierde poder",
            "companionContract": {
                "route": "ui",
                "routePlan": ["ui"],
                "mediaNeedKind": "abstract_concept",
                "uiTemplate": "process-steps",
                "uiVariant": "four-questions",
                "uiItems": ["¿QUÉ PROMETE?", "¿QUÉ CONTIENE?", "¿EN CUÁNTO TIEMPO?", "¿TU PIEL LO TOLERA?"],
                "uiValues": ["PROMESA", "INGREDIENTES", "PLAZO", "TOLERANCIA"],
            },
        }
        companion = prepare_avatar_companion(shot)
        self.assertEqual("process-steps", companion["uiSpec"]["template"])
        self.assertEqual("locked_narration", companion["uiSpec"]["dataSource"])
        self.assertFalse(checkpoint_resolution_compatible(shot, {"avatarFallback": True, "visualKind": "motion-card"}))
        self.assertTrue(checkpoint_resolution_compatible(shot, {"avatarFallback": True, "visualKind": "ui-card", "uiSpec": companion["uiSpec"]}))

    def test_nonexistent_cta_is_blocked(self):
        catalog = {
            "channel_id": "channel-real",
            "observed_at": "2026-07-17T00:00:00Z",
            "videos": [{"video_id": "abc123DEF45", "title": "Video real", "channel_id": "channel-real", "visibility": "public", "url": "https://youtu.be/abc123DEF45"}],
        }
        with self.assertRaisesRegex(RuntimeError, "CTA inexistente"):
            verify_cta({"target_video_id": "ZZZ999xxx00", "target_video_title": "Video inventado"}, catalog)

    def test_verified_cta_gets_thumbnail_from_verified_video_id(self):
        catalog = {
            "channel_id": "channel-real",
            "observed_at": "2026-07-17T00:00:00Z",
            "videos": [{"video_id": "abc123DEF45", "title": "Video real", "channel_id": "channel-real", "visibility": "public", "url": "https://youtu.be/abc123DEF45"}],
        }
        verified = verify_cta({"target_video_id": "abc123DEF45"}, catalog)
        self.assertEqual("https://i.ytimg.com/vi/abc123DEF45/hqdefault.jpg", verified["thumbnail_url"])

    def test_three_identical_media_beats_fail_diversity(self):
        shots = []
        for index in range(3):
            shots.append({
                "shotId": "S%04d" % (index + 1), "chapterId": "C01", "startMs": index * 4000, "endMs": (index + 1) * 4000,
                "provider": "deterministic-ui", "route": "ui", "visualKind": "ui-card", "uiSpec": {"template": "comparison"},
                "beatRole": "proof" if index == 0 else "explanation", "noveltyKey": "scene-%d" % index,
            })
        report = validate_retention({"shots": shots})
        self.assertEqual("FAIL", report["status"])
        self.assertTrue(any("mismo medio" in error or "misma plantilla" in error for error in report["errors"]))

    def test_real_image_interrupts_ui_template_sequence(self):
        shots = [
            {"shotId": "S0001", "visualKind": "ui-card", "provider": "image_pair+remotion", "uiSpec": {"template": "comparison"}, "beatRole": "proof", "noveltyKey": "a"},
            {"shotId": "S0002", "visualKind": "image", "provider": "library", "uiSpec": {"template": "comparison"}, "beatRole": "explanation", "noveltyKey": "b"},
            {"shotId": "S0003", "visualKind": "ui-card", "provider": "image_pair+remotion", "uiSpec": {"template": "comparison"}, "beatRole": "proof", "noveltyKey": "c"},
        ]
        report = validate_retention({"shots": shots})
        self.assertFalse(any("misma plantilla" in error for error in report["errors"]))
        self.assertEqual(1, report["metrics"]["max_same_template"])

    def test_modular_product_inspection_template_is_accepted(self):
        shot = {"uiSpec": {"template": "product-inspection", "state": "resolved", "headline": "MIRA EL ENVASE", "items": ["PROMESA"], "values": ["REVISA"], "dataSource": "locked_narration"}}
        self.assertEqual("ui-card", materialize_shot(shot)["visualKind"])

    def test_draft_repair_replaces_text_only_evidence_without_touching_other_shots(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            plan = {
                "cta": {"target_video_id": "abc123DEF45", "target_video_title": "Video real"},
                "shots": [
                    {"shotId": "S0001", "proofKind": "product_inspection", "mediaType": "image", "source": "runs/test/product.png"},
                    {"shotId": "S0002", "tts": "La grasa esta bajo la piel.", "visualProof": "anatomia", "route": "ui", "routePlan": ["ui"], "mediaNeedKind": "physiological_mechanism"},
                    {"shotId": "S0003", "tts": "Mira el envase.", "visualProof": "envase", "route": "ui", "routePlan": ["ui"], "mediaNeedKind": "product_inspection"},
                    {"shotId": "S0004", "route": "pexels", "routePlan": ["pexels"], "source": "keep.mp4"},
                ],
            }
            report = {"viewer": {"blockers": [
                {"label": "S0002", "reason": "Bloques abstractos sin anatomía clara de piel/grasa."},
                {"label": "S0003", "reason": "Dice mira el envase pero no muestra envase ni etiqueta."},
            ]}}
            repaired = build_draft_repair_plan({"cta": plan["cta"]}, plan, report, {"work": work})
            by_id = {shot["shotId"]: shot for shot in repaired["shots"]}
            self.assertEqual("anatomy-explainer", by_id["S0002"]["uiTemplate"])
            self.assertEqual("runs/test/product.png", by_id["S0003"]["backgroundSource"])
            self.assertEqual("keep.mp4", by_id["S0004"]["source"])

    def test_draft_repair_allows_an_illustration_when_motion_is_not_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            plan = {"shots": [{
                "shotId": "S0003",
                "proofKind": "physiological_mechanism",
                "mediaNeedKind": "physiological_mechanism",
                "route": "ui",
                "routePlan": ["ui"],
                "temporalAction": "multi_step",
                "movingVisualRequired": True,
            }]}
            report = {"viewer": {"blockers": [{
                "label": "S0003",
                "reason": "motion-card sustituye la evidencia requerida; para afirmar que la grasa está bajo la piel usa un esquema simplificado.",
            }]}}
            repaired = build_draft_repair_plan({}, plan, report, {"work": work})
            shot = repaired["shots"][0]
            self.assertEqual("image", shot["route"])
            self.assertEqual("image", shot["routePlan"][0])
            self.assertEqual("anatomy-explainer", shot["uiTemplate"])
            self.assertEqual("anatomy-explainer", shot["hybridTemplate"])
            self.assertEqual(["CREMA", "PIEL", "GRASA SUBCUTÁNEA"], shot["uiItems"])
            self.assertEqual("multi_step", shot["temporalAction"])
            self.assertEqual("implied", shot["temporalEvidenceMode"])
            self.assertFalse(shot["requiresObservedTransition"])

    def test_generic_upgrade_cannot_replace_viewer_approved_product_image_with_ui(self):
        shot = {
            "shotId": "S0006",
            "proofKind": "product_inspection",
            "mediaNeedKind": "product_inspection",
            "route": "ui",
            "routePlan": ["ui", "image"],
            "provider": "image",
            "visualKind": "image",
            "source": "runs/test/S0006_image.png",
            "requiresReadableData": True,
            "draftRepair": {"policy": "older-policy", "reason": "viewer required a real package"},
        }
        restored = restore_directed_repair_media(shot)
        self.assertEqual("image", restored["route"])
        self.assertEqual(["image", "ui"], restored["routePlan"])
        self.assertFalse(restored["requiresReadableData"])

    def test_draft_blocker_text_accepts_viewer_shot_reason(self):
        label, reason = _draft_blocker_text(
            {"label": "S0006", "shot": "ui-card sustituye el envase real"}
        )
        self.assertEqual("S0006", label)
        self.assertEqual("ui-card sustituye el envase real", reason)

    def test_upgrade_visual_plan_restores_persisted_avatar_fallback_as_anchor(self):
        plan = {
            "shots": [{
                "shotId": "S0017",
                "tts": "Cuatro preguntas antes de comprar.",
                "visualProof": "Shows four purchase questions",
                "route": "cutout_motion",
                "routePlan": ["cutout_motion", "image"],
                "proofKind": "abstract_concept",
                "mediaNeedKind": "abstract_concept",
                "avatarRequested": True,
                "avatarFallback": True,
                "noveltyKey": "presenter-S0017",
                "companionContract": {
                    "proofKind": "abstract_concept",
                    "mediaNeedKind": "abstract_concept",
                    "route": "ui",
                    "routePlan": ["ui"],
                },
            }],
            "rules": {},
        }
        data = {"run_id": "test-avatar-resume", "thumbnail_promise": "REVISA EL ENVASE", "title": "Cremas reductoras", "cta": {}}
        with mock.patch("engine.longform_pipeline.apply_persisted_draft_repairs", side_effect=lambda current, _: current):
            upgraded = upgrade_visual_plan(data, plan)
        self.assertEqual("avatar", upgraded["shots"][0]["route"])
        self.assertEqual(["avatar"], upgraded["shots"][0]["routePlan"])
        self.assertEqual("ui", upgraded["shots"][0]["companionRoute"])
        self.assertEqual(["ui"], upgraded["shots"][0]["companionRoutePlan"])

    def test_checkpoint_rejects_empty_card_for_direct_packaging_image(self):
        requested = {"route": "image", "proofKind": "product_inspection"}
        stale = {"visualKind": "ui-card", "source": "", "backgroundSource": ""}
        self.assertFalse(checkpoint_resolution_compatible(requested, stale))

    def test_checkpoint_accepts_persisted_avatar_fallback(self):
        requested = {"route": "avatar", "proofKind": "presenter"}
        fallback = {"visualKind": "ui-card", "avatarFallback": True}
        self.assertTrue(checkpoint_resolution_compatible(requested, fallback))

    def test_retention_distinguishes_composition_styles_within_still_images(self):
        shots = [
            {"shotId": "S0001", "visualKind": "image", "provider": "library", "compositionStyle": "lifestyle", "beatRole": "proof", "chapterId": "C01", "noveltyKey": "a"},
            {"shotId": "S0002", "visualKind": "image", "provider": "image", "compositionStyle": "single-package-macro", "beatRole": "proof", "chapterId": "C01", "noveltyKey": "b"},
            {"shotId": "S0003", "visualKind": "image", "provider": "image", "compositionStyle": "dual-package-contrast", "beatRole": "proof", "chapterId": "C01", "noveltyKey": "c"},
        ]
        report = validate_retention({"shots": shots})
        self.assertFalse(any("misma plantilla" in error for error in report["errors"]))
        self.assertEqual(1, report["metrics"]["max_same_template"])

    def test_degraded_watchthrough_requires_all_deterministic_audio_gates(self):
        raw = {"ok": True, "score": 88, "blockers": []}
        passed = normalize_degraded_watchthrough(raw, [{"status": "PASS"}] * 3, "quota", pathlib.Path("audio.mp3"), pathlib.Path("spectrum.png"))
        failed = normalize_degraded_watchthrough(raw, [{"status": "PASS"}, {"status": "FAIL"}, {"status": "PASS"}], "quota", pathlib.Path("audio.mp3"), pathlib.Path("spectrum.png"))
        self.assertFalse(passed["ok"])
        self.assertFalse(failed["ok"])
        self.assertTrue(passed["degraded_audio_review"])
        self.assertTrue(passed["publication_blocked"])

    def test_hybrid_process_keeps_generated_evidence_visible(self):
        shot = {"screenCopy": "PRUEBA CONTROLADA", "tts": "Mide y toma una foto", "mediaNeedKind": "human_action", "hybridTemplate": "process-steps", "uiItems": ["MIDE", "APLICA", "FOTO"]}
        materialize_hybrid_shot(shot, "runs/test/pair.png", "image", "image_pair")
        self.assertEqual("ui-card", shot["visualKind"])
        self.assertEqual("runs/test/pair.png", shot["backgroundSource"])
        self.assertEqual("image_pair+remotion", shot["provider"])

    def test_complex_comparison_keeps_directed_hybrid_repair(self):
        shot = {
            "shotId": "S0013", "complexComparison": True, "draftRepair": {"attempt": 1},
            "route": "image_pair", "routePlan": ["image_pair", "ui"], "preferredMedium": "image_pair",
            "hybridTemplate": "comparison", "uiTemplate": "comparison",
        }
        enforce_hard_route_priority(shot)
        self.assertEqual("image_pair", shot["route"])
        self.assertEqual("comparison", shot["uiTemplate"])

    def test_new_repair_policy_resets_attempt_and_rejects_facial_serum(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            (work / "07c_draft_repair_plan.json").write_text(json.dumps({"policy": "old-policy", "attempt": 2, "patches": {}}), encoding="utf-8")
            plan = {"shots": [{"shotId": "S0008", "route": "cutout_motion", "routePlan": ["cutout_motion"], "mediaNeedKind": "comparison"}]}
            report = {"viewer": {"blockers": [{"label": "S0008", "reason": "Muestra un gotero/serum facial y no el producto central del video."}]}}
            repaired = build_draft_repair_plan({}, plan, report, {"work": work})
            payload = json.loads((work / "07c_draft_repair_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(1, payload["attempt"])
            self.assertEqual("image_pair", repaired["shots"][0]["route"])
            self.assertEqual("surface-vs-permanent", repaired["shots"][0]["uiVariant"])
            self.assertIn("dropper", repaired["shots"][0]["forbiddenSubstitutions"])

    def test_new_repair_policy_does_not_reapply_stale_shot_repairs(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            (work / "07c_draft_repair_plan.json").write_text(
                json.dumps({"policy": "old-policy", "attempt": 2, "patches": {"S0003": {"route": "image"}}}),
                encoding="utf-8",
            )
            plan = {"shots": [
                {"shotId": "S0001", "proofKind": "product_inspection", "mediaType": "image", "source": "product.png"},
                {"shotId": "S0003", "proofKind": "physiological_mechanism", "route": "ui", "routePlan": ["ui"], "draftRepair": {"policy": "old-policy"}},
                {"shotId": "S0006", "proofKind": "product_inspection", "route": "ui", "routePlan": ["ui"]},
            ]}
            report = {"viewer": {"blockers": [{
                "label": "S0006",
                "shot": "ui-card sustituye el envase y packaging con claim",
            }]}}
            repaired = build_draft_repair_plan({}, plan, report, {"work": work})
            payload = json.loads((work / "07c_draft_repair_plan.json").read_text(encoding="utf-8"))
            by_id = {shot["shotId"]: shot for shot in repaired["shots"]}
            self.assertNotIn("S0003", payload["patches"])
            self.assertEqual("ui", by_id["S0003"]["route"])
            self.assertEqual("image", by_id["S0006"]["route"])

    def test_persisted_repair_ignores_stale_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            (work / "07c_draft_repair_plan.json").write_text(
                json.dumps({"policy": "old-policy", "attempt": 2, "patches": {"S0001": {"route": "image"}}}),
                encoding="utf-8",
            )
            plan = {"shots": [{"shotId": "S0001", "route": "ui", "routePlan": ["ui"]}]}
            repaired = apply_persisted_draft_repairs(plan, {"work": work})
            self.assertEqual("ui", repaired["shots"][0]["route"])

    def test_same_repair_policy_does_not_import_untracked_historical_repairs(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            (work / "07c_draft_repair_plan.json").write_text(
                json.dumps({"policy": DRAFT_REPAIR_POLICY_VERSION, "attempt": 1, "patches": {"S0006": {"route": "image"}}}),
                encoding="utf-8",
            )
            plan = {"shots": [
                {"shotId": "S0003", "proofKind": "physiological_mechanism", "route": "ui", "routePlan": ["ui"], "draftRepair": {"policy": "old-policy"}},
                {"shotId": "S0006", "proofKind": "product_inspection", "route": "ui", "routePlan": ["ui"]},
                {"shotId": "S0010", "proofKind": "comparison", "route": "ui", "routePlan": ["ui"]},
            ]}
            report = {"viewer": {"blockers": [{"label": "S0010", "shot": "toma una foto antes; debe fotografiar la zona"}]}}
            build_draft_repair_plan({}, plan, report, {"work": work})
            payload = json.loads((work / "07c_draft_repair_plan.json").read_text(encoding="utf-8"))
            self.assertEqual({"S0010"}, set(payload["patches"]))

    def test_protocol_repair_requires_direct_before_after_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            plan = {"shots": [{
                "shotId": "S0011",
                "proofKind": "comparison",
                "route": "ui",
                "routePlan": ["ui"],
                "source": "old-nearly-identical.png",
                "uiTemplate": "process-steps",
                "prompt": "old image prompt, no text",
                "imageBasePrompt": "old generated still",
                "query": "old stock query",
            }]}
            report = {"viewer": {"blockers": [{
                "label": "S0011",
                "shot": "mantener misma luz, distancia y postura, pero no muestra la toma de foto antes/después",
            }]}}
            repaired = build_draft_repair_plan({}, plan, report, {"work": work})
            shot = repaired["shots"][0]
            self.assertEqual("image_pair", shot["route"])
            self.assertEqual("comparison", shot["proofKind"])
            self.assertEqual("comparison", shot["mediaNeedKind"])
            self.assertEqual("protocol-measurement-diagram", shot["compositionStyle"])
            self.assertEqual("s0011-measurement-protocol", shot["continuityGroup"])
            self.assertNotIn("pinnedAsset", shot)
            self.assertEqual("process-steps", shot["hybridTemplate"])
            self.assertEqual("protocol-diagram", shot["uiVariant"])
            self.assertIn("standardized body-comparison setup", shot["prompt"])
            self.assertNotIn("old stock query", shot["imagePairPrompt"])
            self.assertEqual("image_pair", shot["routePlan"][0])
            self.assertIn("image_pair", shot["queryVariants"])

    def test_verified_cta_blocker_marks_metadata_owned_end_screen_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            data = {"cta": {"target_video_title": "Alimento rico en colágeno", "target_video_id": "nZ5KG52rfH8"}}
            plan = {"cta": data["cta"], "shots": [{"shotId": "S0018", "route": "ui", "routePlan": ["ui"]}]}
            report = {"viewer": {"blockers": [{
                "label": "S0018",
                "shot": "end screen lacks the verified next-video title and ID; catalog identity is missing",
            }]}}
            repaired = build_draft_repair_plan(data, plan, report, {"work": work})
            shot = repaired["shots"][0]
            self.assertTrue(shot["ctaAnchor"])
            self.assertNotIn("uiTemplate", shot)
            self.assertNotIn("uiValues", shot)

    def test_skin_evaluation_repair_uses_specific_deterministic_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            plan = {"shots": [{
                "shotId": "S0012",
                "tts": "textura de la piel, hidratación y comodidad. No cambies el ángulo.",
                "requiredEvidence": "Three evaluation frames",
                "route": "image_pair",
                "routePlan": ["image_pair"],
            }]}
            report = {"viewer": {"blockers": [{
                "label": "S0012",
                "shot": "envase tipo gotero y cosmética facial con etiqueta blanca ilegible",
            }]}}
            repaired = build_draft_repair_plan({}, plan, report, {"work": work})
            shot = repaired["shots"][0]
            self.assertEqual("exact_ui_state", shot["proofKind"])
            self.assertEqual("ui", shot["route"])
            self.assertEqual("evaluation-dashboard", shot["uiTemplate"])
            self.assertEqual("evaluation-grid", shot["uiVariant"])
            self.assertEqual(["TEXTURA", "HIDRATACIÓN", "COMODIDAD"], shot["uiItems"])

    def test_cta_route_keeps_catalog_id_out_of_shot_content(self):
        data = {"cta": {
            "verified": True,
            "target_video_title": "Alimento rico en colágeno",
            "target_video_id": "nZ5KG52rfH8",
            "screen_copy": "SIGUE CON ESTE VIDEO",
        }}
        shots = [{"shotId": "S0018", "tts": "Ahora mira Alimento rico en colágeno"}]
        apply_cta_end_screen_route(data, shots)
        self.assertTrue(shots[0]["ctaAnchor"])
        self.assertNotIn("uiTemplate", shots[0])
        self.assertNotIn("uiValues", shots[0])

    def test_hook_label_maps_to_first_shot(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            plan = {"shots": [{"shotId": "S0001", "route": "image", "routePlan": ["image"], "proofKind": "product_inspection"}]}
            report = {"viewer": {"blockers": [{"label": "HOOK-1S", "reason": "Packaging generado con texto fino mayormente ilegible en la etiqueta."}]}}
            repaired = build_draft_repair_plan({}, plan, report, {"work": work})
            payload = json.loads((work / "07c_draft_repair_plan.json").read_text(encoding="utf-8"))
            self.assertIn("S0001", payload["patches"])
            self.assertNotIn("HOOK-1S", payload["patches"])
            self.assertEqual("image", repaired["shots"][0]["route"])
            self.assertEqual("ANTES DE COMPRARLA", repaired["shots"][0]["screenCopy"])
            self.assertIn("no fine print", repaired["shots"][0]["prompt"].lower())

    def test_viewer_gate_does_not_vote_away_a_contextual_blocker(self):
        responses = [
            {"ok": False, "score": 58, "blockers": [{"label": "S0001", "reason": "visible objection"}]},
        ]
        sample = {"path": pathlib.Path("frame.jpg"), "at_ms": 1000, "label": "S0001", "shot": {"tts": "texto", "screenCopy": "PUNTO", "visualKind": "image"}}
        with mock.patch("engine.qa.call_ai_json", side_effect=responses):
            report = viewer_video_qa({"title": "Titulo", "thumbnail_promise": "Promesa"}, pathlib.Path("draft.mp4"), [sample], {"durationMs": 5000})
        self.assertFalse(report["ok"])
        self.assertEqual(58, report["score"])
        self.assertEqual("S0001", report["blockers"][0]["label"])
        self.assertEqual(1, report["batches"][0]["review_count"])

    def test_viewer_gate_discards_out_of_batch_blocker_label(self):
        responses = [
            {"ok": False, "score": 60, "blockers": [{"label": "S9999", "reason": "not in this batch"}]},
            {"ok": False, "score": 74, "blockers": [{"label": "S0001", "reason": "single dissent"}]},
            {"ok": True, "score": 92, "blockers": []},
        ]
        sample = {"path": pathlib.Path("frame.jpg"), "at_ms": 1000, "label": "S0001", "shot": {"tts": "texto", "screenCopy": "PUNTO", "visualKind": "image"}}
        with mock.patch("engine.qa.call_ai_json", side_effect=responses):
            report = viewer_video_qa({"title": "Titulo", "thumbnail_promise": "Promesa"}, pathlib.Path("draft.mp4"), [sample], {"durationMs": 5000})
        self.assertFalse(report["ok"])
        self.assertEqual(60, report["score"])
        self.assertEqual([], report["blockers"])
        self.assertEqual("S9999", report["batches"][0]["invalid_blockers"][0]["label"])
        self.assertEqual("single-neutral-composition-review-v2", report["policy"])

    def test_product_claim_repair_uses_concrete_readable_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            plan = {"shots": [
                {"shotId": "S0001", "proofKind": "product_inspection", "mediaType": "image", "source": "runs/test/product.png"},
                {"shotId": "S0006", "route": "ui", "routePlan": ["ui"], "mediaNeedKind": "product_inspection"},
            ]}
            report = {"viewer": {"blockers": [{"label": "S0006", "reason": "Mira el envase, pero no muestra una etiqueta real legible con tiempo, uso y límites."}]}}
            repaired = build_draft_repair_plan({}, plan, report, {"work": work})
            shot = next(item for item in repaired["shots"] if item["shotId"] == "S0006")
            self.assertIn("CLAIM DEL ENVASE", shot["uiItems"])
            self.assertIn("NO REDUCE GRASA", shot["uiValues"])
            self.assertEqual("package-claims", shot["uiVariant"])

    def test_image_pair_compiler_preserves_explicit_panels_and_people_policy(self):
        shot = {
            "tts": "Compara la misma zona.", "visualProof": "textura superficial", "requiredEvidence": "same forearm area",
            "mediaNeedKind": "comparison", "route": "image_pair", "routePlan": ["image_pair"], "peoplePolicy": "forbidden",
            "prompt": "Landscape 16:9 macro comparison. Left: dry forearm skin, no face. Right: hydrated forearm skin beside an open cream jar, no face.",
        }
        pair = json.loads(compile_all(shot)["image_pair"][0])
        self.assertIn("dry forearm skin", pair["left"])
        self.assertIn("hydrated forearm skin", pair["right"])
        self.assertIn("No face", pair["left"])

    def test_compiler_output_does_not_invalidate_approved_asset_checkpoint(self):
        plan = {"scriptHash": "abc", "providerMode": "real"}
        shot = {"shotId": "S0001", "prompt": "raw intent", "route": "image", "routePlan": ["image"], "queryVariants": {"image": ["compiled v1"]}, "imageBasePrompt": "compiled base"}
        first = shot_input_signature(plan, shot)
        shot["queryVariants"] = {"image": ["compiled v2"]}
        shot["imageBasePrompt"] = "compiled base v2"
        self.assertEqual(first, shot_input_signature(plan, shot))
        shot["prompt"] = "new raw intent"
        self.assertNotEqual(first, shot_input_signature(plan, shot))

    def test_product_inspection_without_visible_package_fails_global_qa(self):
        plan = {"shots": [{"shotId": "S0001", "proofKind": "product_inspection", "requiredEvidence": "Muestra el envase y la etiqueta", "visualKind": "ui-card", "provider": "deterministic-ui", "route": "ui", "uiSpec": {"template": "product-inspection"}}]}
        report = validate_set(plan)
        self.assertEqual("FAIL", report["status"])
        self.assertTrue(any("sin envase visual" in error for error in report["errors"]))

    def test_policy_upgrade_discards_untracked_historical_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            preserved = {"route": "image_pair", "uiTemplate": "comparison", "skipLibrary": True}
            (work / "07c_draft_repair_plan.json").write_text(
                json.dumps({"policy": "draft-evidence-repair-v22-older", "attempt": 2, "patches": {"S0011": preserved}}),
                encoding="utf-8",
            )
            plan = {"shots": [
                {"shotId": "S0011", "proofKind": "comparison", "route": "ui", "routePlan": ["ui"]},
                {"shotId": "S0019", "proofKind": "exact_ui_state", "route": "ui", "routePlan": ["ui"]},
            ]}
            report = {"viewer": {"blockers": [{"label": "S0019", "reason": "comentario no clasificable"}]}}
            build_draft_repair_plan({}, plan, report, {"work": work})
            payload = json.loads((work / "07c_draft_repair_plan.json").read_text(encoding="utf-8"))
            self.assertNotIn("S0011", payload["patches"])


if __name__ == "__main__":
    unittest.main()
