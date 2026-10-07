import copy
import hashlib
import json
import os
import pathlib
import tempfile
import time
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
os.sys.path.insert(0, str(ROOT))

from engine.longform_contract import full_script, script_hash, validate_approved_script
from engine.longform_pipeline import MAX_SHOT_MS, align_observable_evidence_contracts, apply_closing_distinction_route, apply_cta_end_screen_route, apply_early_context_broll, apply_filmable_overrides, apply_purchase_evidence_routes, assert_provider_mode, build_draft_repair_plan, cached_generated_request_matches, cached_media_fit, chunk_words, compact_pexels_query, create_asset, deterministic_fallback_route, effective_tts_speed, ffprobe, matching_user_clips, natural_voice_density_error, normalize_user_clip, perceptual_duplicate, provider_routes_before_deterministic, rank_visual_mix_repairs, resolve_support_asset, shot_input_signature, tts_voice_profile, validate_resolved_plan, visual_fingerprints, visual_mix_snapshot
from engine.media_router import assign_evidence_beats, balance_graphic_routes, normalize_media_contract, validate_media_contract
from engine.query_compilers import abstract_query, compile_all, compile_cutout, compile_image_pair, rejection_feedback
from engine.evidence_set_qa import validate_set
from engine.media_prefilter import prefilter, prefilter_search_thumbnail
import engine.media_prefilter as media_prefilter_module
from engine.provider_telemetry import ProviderTelemetry
from engine.provider_runtime import ProviderRuntime
from engine.retention_director import validate_retention
from providers.deterministic_ui import materialize_shot
from engine.suno_prompt import build_suno_request
from providers.core import MockProviders, RealProviders
from providers.cutout_video import CutoutVideoClient, namespace_script_assets, safe_client_ref, validate_analysis as validate_cutout_analysis
import providers.core as provider_core
from tools.build_approved_script import balanced_chapters, table_audio
from engine.qa import public_path


def approved_script():
    data = {
        "schema_version": "1.1",
        "run_id": "test-longform",
        "script_locked": True,
        "script_hash": "",
        "title": "La verdad sobre las cremas reductoras",
        "thumbnail_promise": "ANTES DE COMPRARLA",
        "hook": "Antes de comprar otra crema reductora, mira esto.",
        "target_minutes": 2,
        "language": "es",
        "audience_profile": "Mujeres hispanas adultas que quieren explicaciones prácticas, visuales y creíbles sin promesas milagrosas.",
        "avatar_feedback": "Quiero claridad y una prueba útil.",
        "avatar_appearances": 2,
        "cta": {"spoken_text": "Ahora mira Cómo comparar cambios reales. Ahí aprenderás el método completo.", "target_video_title": "Cómo comparar cambios reales", "screen_copy": "MIRA ESTE VIDEO", "end_screen_hold_seconds": 9},
        "user_clips": [],
        "chapters": [
            {"id": "C01", "title": "La promesa", "spoken_text": "Antes de comprar otra crema reductora, mira esto. La etiqueta puede sonar convincente, pero una sensación temporal no demuestra que la grasa haya desaparecido. Aquí revisamos qué sí puede cambiar y qué conviene mirar con calma. " * 4},
            {"id": "C02", "title": "La prueba", "spoken_text": ("Aplica la misma cantidad en una zona pequeña y compara con la misma luz. Observa textura, hidratación y comodidad, sin convertir una diferencia breve en una transformación permanente. Esta comparación sencilla reduce expectativas falsas. " * 3) + "Ahora mira Cómo comparar cambios reales. Ahí aprenderás el método completo."},
        ],
    }
    data["script_hash"] = script_hash(full_script(data))
    return data


def resolved_plan():
    shots = []
    for index in range(10):
        avatar = index in {2, 7}
        card = index == 5
        shots.append({
            "shotId": "S%04d" % (index + 1),
            "chapterId": "C01" if index < 5 else "C02",
            "startMs": index * 5000,
            "endMs": (index + 1) * 5000,
            "visualKind": "avatar-full" if avatar else ("motion-card" if card else "broll"),
            "source": "" if card else "runs/test/assets/source_%d.mp4" % index,
            "mediaType": "card" if card else "video",
            "sourceInMs": 0,
            "sourceOutMs": 0 if card else 5000,
            "sourceWidth": 1920 if avatar else 0,
            "sourceHeight": 1080 if avatar else 0,
            "screenCopy": "PROMESA" if index == 0 else "IDEA CLAVE",
            "subcopy": "Texto claro",
            "mediaNeedKind": "presenter" if avatar else ("abstract_concept" if card else "human_action"),
            "evidenceMode": "illustrative",
            "requiresReadableData": False,
            "requiresStateContinuity": False,
            "temporalAction": "single",
            "continuityGroup": "",
            "evidenceBeatId": "B%03d" % (index + 1),
            "route": "avatar" if avatar else ("motion-card" if card else "pexels"),
            "routePlan": ["avatar"] if avatar else (["motion-card"] if card else ["pexels", "clip_extractor"]),
            "queryVariants": {},
        })
    return {"schemaVersion": "2.0", "durationMs": 50000, "thumbnailPromise": "PROMESA", "shots": shots}


class ApprovedScriptTests(unittest.TestCase):
    def test_valid_contract_passes(self):
        self.assertEqual([], validate_approved_script(approved_script()))

    def test_script_mutation_is_blocked(self):
        data = approved_script()
        data["chapters"][0]["spoken_text"] += " Cambio no aprobado."
        self.assertTrue(any("script_hash" in error for error in validate_approved_script(data)))

    def test_unlocked_script_is_blocked(self):
        data = approved_script()
        data["script_locked"] = False
        self.assertTrue(any("script_locked" in error for error in validate_approved_script(data)))


class ResolvedPlanTests(unittest.TestCase):
    def test_valid_plan_passes(self):
        result = validate_resolved_plan(resolved_plan())
        self.assertEqual("PASS", result["status"], result["errors"])

    def test_source_reuse_is_blocked(self):
        plan = resolved_plan()
        plan["shots"][3]["source"] = plan["shots"][0]["source"]
        self.assertTrue(any("reutiliza" in error for error in validate_resolved_plan(plan)["errors"]))

    def test_vertical_avatar_is_blocked(self):
        plan = resolved_plan()
        plan["shots"][2]["sourceWidth"] = 1080
        plan["shots"][2]["sourceHeight"] = 1920
        self.assertTrue(any("avatar no 16:9" in error for error in validate_resolved_plan(plan)["errors"]))

    def test_avatar_failure_can_use_two_traceable_fallbacks(self):
        plan = resolved_plan()
        for index in (2, 7):
            plan["shots"][index].update({
                "visualKind": "motion-card",
                "source": "",
                "mediaType": "card",
                "sourceInMs": 0,
                "sourceOutMs": 0,
                "sourceWidth": 0,
                "sourceHeight": 0,
                "avatarRequested": True,
                "avatarFallback": True,
                "provider": "remotion-avatar-fallback",
            })
        result = validate_resolved_plan(plan)
        self.assertEqual("PASS", result["status"], result["errors"])
        self.assertEqual(2, result["metrics"]["avatar_fallback_count"])

    def test_consecutive_cards_are_blocked(self):
        plan = resolved_plan()
        for shot in plan["shots"][3:6]:
            shot.update({"visualKind": "motion-card", "source": "", "mediaType": "card", "sourceOutMs": 0})
        self.assertTrue(any("consecutivas" in error for error in validate_resolved_plan(plan)["errors"]))

    def test_varied_ui_graphics_are_not_plain_text_cards(self):
        plan = resolved_plan()
        for index in range(3, 6):
            plan["shots"][index].update({"visualKind": "ui-card", "source": "", "mediaType": "card", "sourceOutMs": 0, "provider": "deterministic-ui", "uiSpec": {"template": "comparison", "state": "resolved", "headline": "COMPARA", "items": ["A", "B"], "values": [], "dataSource": "locked_narration"}})
        result = validate_resolved_plan(plan)
        self.assertFalse(any("tarjetas de texto" in error for error in result["errors"]))

    def test_timeline_rejects_one_repeated_template(self):
        plan = resolved_plan()
        for shot in plan["shots"]:
            was_avatar = shot["visualKind"] == "avatar-full"
            shot.update({"visualKind": "ui-card", "source": "", "mediaType": "card", "sourceOutMs": 0, "provider": "deterministic-ui", "uiSpec": {"template": "concept", "state": "resolved", "headline": "IDEA", "items": ["IDEA"], "values": [], "dataSource": "locked_narration"}})
            if was_avatar:
                shot.update({"avatarRequested": True, "avatarFallback": True})
        for index, shot in enumerate(plan["shots"]):
            shot.update({"noveltyKey": "ui-%d" % index, "beatRole": "proof" if index in {0, 5} else "explanation"})
        result = validate_retention(plan)
        self.assertTrue(any("misma plantilla" in error for error in result["errors"]))

    def test_production_metadata_is_blocked_from_tts(self):
        data = approved_script()
        data["chapters"][0]["spoken_text"] += " Mini-payoff: ahora sigue."
        data["script_hash"] = script_hash(full_script(data))
        self.assertTrue(any("metadata prohibida" in error for error in validate_approved_script(data)))

    def test_hook_overlay_must_equal_thumbnail_promise(self):
        plan = resolved_plan()
        plan["shots"][0]["screenCopy"] = "OTRA COSA"
        self.assertTrue(any("thumbnailPromise" in error for error in validate_resolved_plan(plan)["errors"]))

    def test_mojibake_on_screen_is_blocked(self):
        plan = resolved_plan()
        plan["shots"][1]["screenCopy"] = "ALERTA RÃPIDA"
        self.assertTrue(any("texto corrupto" in error for error in validate_resolved_plan(plan)["errors"]))


class AssetPolicyTests(unittest.TestCase):
    def test_avatar_runtime_result_does_not_change_shot_input_signature(self):
        plan = {"scriptHash": "hash", "providerMode": "real"}
        shot = {"shotId": "S0001", "route": "avatar", "tts": "Texto aprobado"}
        before = shot_input_signature(plan, shot)
        resolved = {**shot, "visualKind": "motion-card", "mediaType": "card", "provider": "remotion-avatar-fallback", "avatarRequested": True, "avatarFallback": True, "avatarFailure": "provider unavailable", "visualMixRepair": True}
        self.assertEqual(before, shot_input_signature(plan, resolved))

    def test_clip_extractor_no_candidate_is_not_repeated_in_same_run(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = ProviderRuntime(pathlib.Path(directory) / "provider_runtime.json")
            runtime.telemetry.emit(provider="clip_extractor", scene="S0015", query_or_prompt="exact query", result="failed", rejection_reason="No candidate clip matched the request")
            call = mock.Mock(return_value="unexpected")
            with self.assertRaisesRegex(RuntimeError, "negative-cache historico"):
                runtime.call("clip_extractor", "signature", call, scene="S0015", query_or_prompt="exact query")
            call.assert_not_called()

    def test_empty_image_stream_opens_only_short_transient_circuit(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = ProviderRuntime(pathlib.Path(directory) / "provider_runtime.json")
            with self.assertRaisesRegex(RuntimeError, "without an image"):
                runtime.call("image_pair", "signature", lambda: (_ for _ in ()).throw(RuntimeError("Codex image stream completed without an image result")))
            until = runtime.state["circuits"]["image_pair"]["until"]
            self.assertGreater(until, time.time())
            self.assertLessEqual(until, time.time() + 121)

    def test_visual_mix_repair_targets_middle_of_longest_graphic_run(self):
        kinds = ["ui-card", "motion-card", "image", "motion-card", "broll", "motion-card", "motion-card", "ui-card", "ui-card", "broll", "motion-card", "motion-card", "ui-card", "ui-card", "motion-card", "ui-card", "motion-card", "motion-card", "ui-card"]
        candidates = {1, 5, 11, 14, 17}
        shots = [
            {
                "shotId": "S%04d" % (index + 1),
                "visualKind": kind,
                "mediaType": "video" if kind == "broll" else ("image" if kind == "image" else "card"),
                "filmableOverride": index in candidates,
                "mediaNeedKind": "human_action" if index in candidates else "abstract_concept",
                "requiresReadableData": False,
            }
            for index, kind in enumerate(kinds)
        ]
        self.assertEqual(9, visual_mix_snapshot(shots)["max_consecutive_graphics"])
        ranked = rank_visual_mix_repairs(shots)
        self.assertEqual("S0015", ranked[0]["shotId"])
        shots[14].update({"visualKind": "broll", "mediaType": "video"})
        self.assertEqual("S0006", rank_visual_mix_repairs(shots)[0]["shotId"])

    def test_provider_output_without_fit_sidecar_is_reused_for_qa(self):
        with tempfile.TemporaryDirectory() as directory:
            public = pathlib.Path(directory)
            (public / "assets").mkdir()
            shot = {"shotId": "S0001", "startMs": 0, "endMs": 5000, "pexelsQuery": "woman applying body lotion", "query": "", "tts": "Aplica crema.", "visualProof": "A woman applies lotion.", "mediaNeedKind": "human_action", "requiresReadableData": False, "temporalAction": "single", "continuityGroup": ""}
            output = public / "assets" / "S0001_pexels.mp4"
            output.write_bytes(b"provider-video")
            signature = hashlib.sha256(("woman applying body lotion|5000|candidate:0").encode("utf-8")).hexdigest()
            pathlib.Path(str(output) + ".request.json").write_text(json.dumps({"signature": signature}), encoding="utf-8")
            provider = mock.Mock()
            provider.mode = "real"
            rel, actual, media_type = create_asset(provider, {"run_id": "test"}, {"public": public}, shot, "pexels")
            self.assertEqual(output, actual)
            self.assertEqual("video", media_type)
            self.assertEqual("runs/test/assets/S0001_pexels.mp4", rel)
            provider.pexels_clip.assert_not_called()

    def test_media_fit_cache_is_invalidated_by_semantic_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            asset = pathlib.Path(directory) / "asset.png"
            asset.write_bytes(b"stable-asset")
            shot = {"shotId": "S0001", "tts": "Texto", "visualProof": "Crema", "screenCopy": "CREMA", "subcopy": "", "hookRequirement": ""}
            with mock.patch("engine.longform_pipeline.media_fit", return_value=(True, "first")) as first:
                self.assertEqual((True, "first"), cached_media_fit(asset, "asset.png", shot, "image"))
                first.assert_called_once()
            with mock.patch("engine.longform_pipeline.media_fit", return_value=(False, "should not run")) as cached:
                self.assertEqual((True, "first"), cached_media_fit(asset, "asset.png", shot, "image"))
                cached.assert_not_called()
            shot["requiredEvidence"] = "La misma mujer y zona deben aparecer antes y después."
            with mock.patch("engine.longform_pipeline.media_fit", return_value=(True, "new evidence")) as evidence_changed:
                self.assertEqual((True, "new evidence"), cached_media_fit(asset, "asset.png", shot, "image"))
                evidence_changed.assert_called_once()
            shot["screenCopy"] = "OTRA PROMESA"
            with mock.patch("engine.longform_pipeline.media_fit", return_value=(False, "changed")) as changed:
                self.assertEqual((False, "changed"), cached_media_fit(asset, "asset.png", shot, "image"))
                changed.assert_called_once()

    def test_generated_pair_cache_requires_current_compiled_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            asset = pathlib.Path(directory) / "pair.png"
            asset.write_bytes(b"pair")
            old_pair = {"left": "old left", "right": "old right"}
            new_pair = {"left": "new left", "right": "new right"}
            signature = hashlib.sha256(json.dumps(old_pair, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            pathlib.Path(str(asset) + ".image_pair.json").write_text(json.dumps({"signature": signature}), encoding="utf-8")
            self.assertTrue(cached_generated_request_matches(asset, {"queryVariants": {"image_pair": [json.dumps(old_pair)]}}, "image_pair"))
            self.assertFalse(cached_generated_request_matches(asset, {"queryVariants": {"image_pair": [json.dumps(new_pair)]}}, "image_pair"))

    def test_draft_repair_keeps_hook_clean_and_does_not_misroute_purchase_decision_as_lighting(self):
        plan = {"shots": [
            {"shotId": "S0001", "proofKind": "product_inspection", "tts": "Antes de comprarla, mira el envase.", "temporalEvidenceMode": "initial_final", "requiresReadableData": True},
            {"shotId": "S0009", "proofKind": "exact_ui_state", "uiTemplate": "comparison", "tts": "No pagues una promesa sin evidencia.", "requiredEvidence": "A purchase decision contrasts claim and evidence."},
        ]}
        report = {"viewer": {"blockers": [
            {"label": "HOOK-3S", "reason": "El envase no ofrece una etiqueta grande y el overlay adicional tapa más el frente del tarro."},
            {"label": "S0009", "reason": "La visual de decisión de compra con claim exagerado no muestra el contraste narrado más allá del texto."},
        ]}}
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            build_draft_repair_plan({"thumbnail_promise": "ANTES DE COMPRARLA"}, plan, report, {"work": work})
            repair = json.loads((work / "07c_draft_repair_plan.json").read_text(encoding="utf-8"))
        hook = repair["patches"]["S0001"]
        decision = repair["patches"]["S0009"]
        self.assertEqual("image", hook["route"])
        self.assertFalse(hook["requiresReadableData"])
        self.assertEqual("ANTES DE COMPRARLA", hook["screenCopy"])
        self.assertTrue(hook["suppressScreenCopy"])
        self.assertEqual("", hook["hybridTemplate"])
        self.assertEqual("ui", decision["route"])
        self.assertEqual("claim-evidence", decision["uiVariant"])

    def test_pexels_query_is_broad_and_specific_to_object(self):
        shot = {"visualProof": "The exact ingredient label is visibly examined", "prompt": "", "tts": "Mira la etiqueta de la crema"}
        self.assertEqual("body lotion label", compact_pexels_query("a long narrated sentence that is not a stock query at all", shot))

    def test_pexels_query_preserves_specific_seven_word_action(self):
        query = "woman applying body lotion arm close up"
        shot = {"visualProof": "topical application", "prompt": "camera comparison", "tts": "una crema"}
        self.assertEqual(query, compact_pexels_query(query, shot))

    def test_image_pair_compiler_emits_one_state_per_provider_call(self):
        shot = {
            "continuityGroup": "same-woman",
            "peoplePolicy": "contextual",
            "requiresVisibleFace": True,
            "requiredEvidence": "The same woman evaluates the same forearm before and after.",
            "prompt": "Landscape 16:9 controlled two-panel documentary comparison of the SAME woman. Her face is visible in EACH panel. A jar labeled LUMERA is visible in both panels. Left: neutral baseline. Right: subtle relief.",
        }
        pair = json.loads(compile_image_pair(shot)[0])
        for prompt in pair.values():
            self.assertIn("exactly ONE full-frame photographic state", prompt)
            self.assertIn("face and the relevant body area", prompt)
            self.assertNotRegex(prompt.lower(), r"two[- ]panel|split[- ]screen|each panel|both panels|diptych")
            self.assertIn("fictional packaging label", prompt)
        self.assertIn("State A only: neutral baseline", pair["left"])
        self.assertIn("State B only: subtle relief", pair["right"])
        compiled = compile_image_pair(shot)
        self.assertEqual(3, len(set(compiled)))
        self.assertIn("Continuity retry", json.loads(compiled[1])["left"])
        self.assertIn("minor lettering is not salient", json.loads(compiled[2])["right"])

    def test_perceptual_duplicate_catches_reencoded_same_scene(self):
        with tempfile.TemporaryDirectory() as directory:
            first = pathlib.Path(directory) / "first.mp4"
            second = pathlib.Path(directory) / "second.mp4"
            MockProviders(1920, 1080, 30).pexels_clip("same", 1.0, str(first))
            normalize_user_clip(first, second, 900)
            known = visual_fingerprints(first, "video")
            candidate = visual_fingerprints(second, "video")
            self.assertEqual("S0001", perceptual_duplicate(candidate, [("S0001", known)]))

    def test_generated_images_also_run_media_fit(self):
        class ImageOnlyProvider:
            mode = "mock"
            def clip_extractor_clip(self, *args, **kwargs): raise RuntimeError("no clip")
            def pexels_clip(self, *args, **kwargs): raise RuntimeError("no pexels")
            def image_clip(self, prompt, output): MockProviders(1920, 1080, 30).image_clip(prompt, output)
            def omni_clip(self, *args, **kwargs): raise RuntimeError("no omni")
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            paths = {"public": root / "public"}
            (paths["public"] / "assets").mkdir(parents=True)
            data = {"run_id": "test", "_input_dir": directory, "user_clips": []}
            shot = {"shotId": "S0001", "startMs": 0, "endMs": 800, "tts": "Una crema tópica", "visualProof": "cream jar", "query": "cream", "clipQuery": "cream jar", "pexelsQuery": "body cream", "prompt": "cream jar", "route": "image", "screenCopy": "CREMA", "subcopy": ""}
            with mock.patch("engine.longform_pipeline.asset_library.search", return_value=[]), mock.patch("engine.longform_pipeline.media_fit", return_value=(True, "ok")) as fit:
                result = resolve_support_asset(ImageOnlyProvider(), data, paths, shot, set(), set(), [])
            self.assertEqual("image", result[3])
            fit.assert_called_once()

    def test_omni_uri_delivery_enables_store(self):
        old_delivery = os.environ.get("OMNI_VIDEO_DELIVERY")
        old_store = os.environ.get("OMNI_VIDEO_STORE")
        try:
            os.environ["OMNI_VIDEO_DELIVERY"] = "uri"
            os.environ.pop("OMNI_VIDEO_STORE", None)
            body = RealProviders(1920, 1080, 30)._omni_request_body("test", "gemini-omni-flash-preview")
            self.assertIs(True, body["store"])
        finally:
            if old_delivery is None: os.environ.pop("OMNI_VIDEO_DELIVERY", None)
            else: os.environ["OMNI_VIDEO_DELIVERY"] = old_delivery
            if old_store is None: os.environ.pop("OMNI_VIDEO_STORE", None)
            else: os.environ["OMNI_VIDEO_STORE"] = old_store

    def test_qa_resolves_longform_run_assets_from_public_root(self):
        expected = ROOT / "remotion" / "public" / "runs" / "sample" / "assets" / "clip.mp4"
        self.assertEqual(str(expected), public_path("runs/sample/assets/clip.mp4"))

    def test_explicit_user_clip_has_priority_and_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "source.mp4"
            source.write_bytes(b"fixture")
            data = {"_input_dir": directory, "user_clips": [{"path": str(source), "description": "otra cosa", "shot_ids": ["S0001"]}]}
            shot = {"shotId": "S0001", "tts": "Aplicamos crema", "visualProof": "Aplicación de crema", "query": "body cream"}
            matches = matching_user_clips(data, shot, set())
            self.assertEqual(source.resolve(), matches[0]["_source"])
            self.assertEqual([], matching_user_clips(data, shot, {str(source.resolve()).lower()}))

    def test_user_clip_is_not_looped_to_fill_a_longer_shot(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "short.mp4"
            output = pathlib.Path(directory) / "normalized.mp4"
            MockProviders(1920, 1080, 30).clip_extractor_clip("test", 1.0, str(source))
            normalize_user_clip(source, output, 2500)
            self.assertLess(ffprobe(output)["duration_ms"], 1400)

    def test_mock_omni_respects_longform_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "omni.mp4"
            MockProviders(1920, 1080, 30).omni_clip("test", 0.5, str(output))
            meta = ffprobe(output)
            self.assertEqual((1920, 1080), (meta["width"], meta["height"]))
            self.assertAlmostEqual(30, meta["fps"], places=1)

    def test_provider_mode_invalidates_per_shot_asset_cache(self):
        shot = {"shotId": "S0001", "tts": "Prueba", "route": "pexels"}
        mock_plan = {"scriptHash": "same", "providerMode": "mock"}
        real_plan = {"scriptHash": "same", "providerMode": "real"}
        self.assertNotEqual(shot_input_signature(mock_plan, shot), shot_input_signature(real_plan, shot))

    def test_resumed_plan_cannot_mix_provider_modes(self):
        with mock.patch.dict(os.environ, {"PROVIDER_MODE": "real"}):
            with self.assertRaisesRegex(RuntimeError, "providerMode=mock"):
                assert_provider_mode({"providerMode": "mock"}, "props")
        with mock.patch.dict(os.environ, {"PROVIDER_MODE": "mock"}):
            assert_provider_mode({"providerMode": "mock"}, "props")

    def test_generated_packaging_allows_only_fictional_label_text(self):
        source = pathlib.Path(RealProviders.image_clip.__code__.co_filename).read_text(encoding="utf-8")
        self.assertIn("Packaging must use a readable fictional label", source)
        self.assertIn("must not imitate a real trademark", source)

    def test_media_fit_distinguishes_declared_fictional_label_from_third_party_brand(self):
        qa_source = pathlib.Path(__file__).parents[1].joinpath("engine", "qa.py").read_text(encoding="utf-8")
        pipeline_source = pathlib.Path(__file__).parents[1].joinpath("engine", "longform_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("MARCA FICTICIA DECLARADA POR EL MOTOR", qa_source)
        self.assertIn('"fictional_label": shot.get("fictionalLabel")', pipeline_source)


class FeasibilityRouterTests(unittest.TestCase):
    def test_cutout_disabled_does_not_change_existing_routes(self):
        shot = {"shotId": "S0001", "chapterId": "C01", "tts": "El calendario muestra cómo cambia el proceso", "screenCopy": "CAMBIO GRADUAL", "visualProof": "timeline"}
        with mock.patch.dict(os.environ, {"CUTOUT_PROVIDER_ENABLED": "0"}):
            normalize_media_contract(shot, {"media_need_kind": "timeline_or_progression", "evidence_mode": "illustrative"})
        self.assertNotIn("cutout_motion", shot["routePlan"])

    def test_cutout_can_be_preferred_only_for_illustrative_beats(self):
        shot = {"shotId": "S0001", "chapterId": "C01", "tts": "El calendario avanza y el medidor sube", "screenCopy": "CAMBIO GRADUAL", "visualProof": "timeline"}
        with mock.patch.dict(os.environ, {"CUTOUT_PROVIDER_ENABLED": "1"}):
            normalize_media_contract(shot, {
                "media_need_kind": "abstract_concept", "evidence_mode": "illustrative",
                "route": "cutout_motion", "temporal_action": "multi_step",
                "stop_motion_intent": "visual_anchor",
                "why_stop_motion": "El calendario cobra vida y convierte el paso del tiempo en un ancla memorable.",
            })
            assign_evidence_beats([shot])
            compile_all(shot)
        self.assertEqual("cutout_motion", shot["route"])
        self.assertTrue(shot["stopMotion"]["eligible"])
        self.assertEqual([], validate_media_contract(shot))

    def test_cutout_is_removed_from_data_exact_routes(self):
        shot = {"shotId": "S0001", "chapterId": "C01", "tts": "Muestra exactamente 15 miligramos", "screenCopy": "15 MG", "visualProof": "exact value"}
        with mock.patch.dict(os.environ, {"CUTOUT_PROVIDER_ENABLED": "1"}):
            normalize_media_contract(shot, {"media_need_kind": "exact_ui_state", "evidence_mode": "data_exact", "route": "cutout_motion", "requires_readable_data": True})
        self.assertNotIn("cutout_motion", shot["routePlan"])
        self.assertEqual("ui", shot["route"])

    def test_cutout_compiler_keeps_locked_narration_and_concrete_cues(self):
        narration = "El calendario avanza mientras la cinta mide siempre desde la misma distancia."
        shot = {"tts": narration, "visualProof": "seguimiento con calendario y cinta", "mediaNeedKind": "abstract_concept", "cutoutProps": ["calendario de seguimiento", "cinta métrica"], "cutoutRelation": "secuencia", "stopMotion": {"eligible": True, "intent": "technical_choreography", "why": "La coreografía ordena la medición y hace visible la progresión temporal."}, "motionSpec": {"visualPrimitive": "timeline"}}
        script = compile_cutout(shot)[0]
        self.assertIn("Background:", script)
        self.assertIn("Props: calendario de seguimiento, cinta métrica", script)
        self.assertIn("Intent: technical_choreography", script)
        self.assertIn("Choreography:", script)
        self.assertNotIn(narration, script)

    def test_cutout_cache_namespace_separates_preview_from_final_without_rewriting_narration(self):
        script = "Background: mesa. Props: reloj, calendario. Relacion: secuencia.\nEl reloj gira y el calendario avanza."
        preview = namespace_script_assets(script, "procedural", "Adrian Yepez editorial v1")
        final = namespace_script_assets(script, "codex-oauth", "Adrian Yepez editorial v1")
        self.assertNotEqual(preview, final)
        self.assertIn("preview procedural", preview)
        self.assertIn("recorte premium", final)
        self.assertTrue(preview.endswith("El reloj gira y el calendario avanza."))
        self.assertTrue(final.endswith("El reloj gira y el calendario avanza."))

    def test_cutout_client_ref_matches_real_api_contract(self):
        value = safe_client_ref("run:01/shot 2", "codex-oauth", "script")
        self.assertRegex(value, r"^[A-Za-z0-9._-]{1,120}$")
        self.assertNotIn(":", value)
        long_value = safe_client_ref("x" * 200, "codex-oauth", "different script")
        self.assertLessEqual(len(long_value), 120)
        self.assertRegex(long_value, r"-codex-oauth-[a-f0-9]{12}$")

    def test_cutout_analysis_rejects_motionless_multistep(self):
        analysis = {
            "scenes": [{"motion": {"prop_calendario": "settle"}}],
            "asset_specs": [
                {"type": "background", "label": "tablero"},
                {"type": "prop", "label": "calendario de seguimiento"},
            ],
            "estimated_duration_seconds": 5.0,
        }
        errors = validate_cutout_analysis(analysis, {"temporal_action": "multi_step", "expected_props": ["calendario de seguimiento"], "evidence_mode": "illustrative"}, 5.0)
        self.assertTrue(any("settle" in error for error in errors))

    def test_mock_cutout_clip_is_horizontal_and_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "cutout.mp4"
            MockProviders(1920, 1080, 30).cutout_clip("Background: mesa. Props: reloj.\nEl reloj gira.", 2.0, str(output), {"evidence_mode": "illustrative"})
            meta = ffprobe(output)
            self.assertEqual((1920, 1080), (meta["width"], meta["height"]))
            self.assertFalse(meta["has_audio"])

    def test_cutout_route_materializes_through_longform_asset_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            paths = {"public": root / "public", "work": root / "work"}
            (paths["public"] / "assets").mkdir(parents=True)
            shot = {
                "shotId": "S0001", "startMs": 0, "endMs": 2000, "tts": "El reloj gira.",
                "visualProof": "reloj girando", "mediaNeedKind": "abstract_concept", "evidenceMode": "illustrative",
                "requiresReadableData": False, "temporalAction": "single", "continuityGroup": "", "evidenceBeatId": "B001",
                "cutoutProps": ["reloj analógico"], "cutoutPrompt": "Background: mesa. Props: reloj analógico. Relacion: separado.\nEl reloj gira.",
                "stopMotion": {"eligible": True, "intent": "playful_surreal", "why": "El reloj cobra vida para convertir el paso del tiempo en un cambio visual memorable."},
                "stopMotionIntent": "playful_surreal", "whyStopMotion": "El reloj cobra vida para convertir el paso del tiempo en un cambio visual memorable.",
            }
            rel, output, media_type = create_asset(MockProviders(1920, 1080, 30), {"run_id": "cutout-contract"}, paths, shot, "cutout_motion")
            self.assertEqual("video", media_type)
            self.assertIn("_cutout.mp4", rel)
            self.assertTrue(output.is_file())
            self.assertTrue(pathlib.Path(str(output) + ".request.json").is_file())
            self.assertTrue(pathlib.Path(str(output) + ".cutout.json").is_file())

    def test_provider_ladder_honors_deterministic_boundary_after_cutout(self):
        shot = {"mediaNeedKind": "timeline_or_progression", "routePlan": ["cutout_motion", "ui", "motion-card", "omni"]}
        self.assertEqual(["cutout_motion"], provider_routes_before_deterministic(shot))

    def test_real_footage_pair_runs_before_deterministic_fallback(self):
        shot = {"mediaNeedKind": "human_action", "routePlan": ["clip_extractor", "pexels", "image", "omni"]}
        self.assertEqual(["pexels", "image", "omni"], provider_routes_before_deterministic(shot))
        self.assertEqual("", deterministic_fallback_route(shot))
        human = {"mediaNeedKind": "human_action", "routePlan": ["clip_extractor", "motion-card", "omni"]}
        self.assertEqual("", deterministic_fallback_route(human))
        packaging = {"mediaNeedKind": "product_inspection", "routePlan": ["image", "ui"], "hybridTemplate": "product-inspection", "beatRole": "proof"}
        self.assertEqual("", deterministic_fallback_route(packaging))

    def test_cutout_normalizer_retimes_without_audio_or_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "source.mp4"
            output = pathlib.Path(directory) / "normalized.mp4"
            MockProviders(1920, 1080, 24).cutout_clip("test", 6.0, str(source))
            timing = CutoutVideoClient(1920, 1080, 30)._normalize(source, output, 5.0)
            meta = ffprobe(output)
            self.assertAlmostEqual(5.0, meta["duration_ms"] / 1000, places=1)
            self.assertFalse(meta["has_audio"])
            self.assertAlmostEqual(5 / timing["source_duration_seconds"], timing["pts_factor"], places=3)

    def test_readable_label_routes_to_product_image_with_deterministic_overlay(self):
        shot = {"shotId": "S0001", "chapterId": "C01", "tts": "Revisa cuánto retinol dice la etiqueta", "screenCopy": "MIRA LA ETIQUETA", "visualProof": "label"}
        normalize_media_contract(shot, {"route": "image"})
        assign_evidence_beats([shot])
        compile_all(shot)
        self.assertEqual("product_inspection", shot["mediaNeedKind"])
        self.assertTrue(shot["requiresReadableData"])
        self.assertEqual("image", shot["route"])
        self.assertEqual("product-inspection", shot["hybridTemplate"])
        self.assertIn("ui", shot["routePlan"])
        self.assertEqual([], validate_media_contract(shot))

    def test_multistep_action_never_routes_to_still(self):
        shot = {"shotId": "S0001", "chapterId": "C01", "tts": "Primero aplica la crema, luego toma una foto y después compara", "screenCopy": "COMPARA CON MÉTODO", "visualProof": "protocol"}
        normalize_media_contract(shot, {"route": "image"})
        self.assertEqual("multi_step", shot["temporalAction"])
        self.assertNotIn("image", shot["routePlan"])

    def test_concrete_angle_comparison_overrides_wrong_product_label(self):
        shot = {
            "shotId": "S0001",
            "chapterId": "C01",
            "tts": "Una foto tomada desde otro ángulo puede fabricar una diferencia.",
            "screenCopy": "EL ÁNGULO ENGAÑA",
            "visualProof": "split-screen comparison of the same person from two different angles",
        }
        normalize_media_contract(shot, {"media_need_kind": "product_inspection", "route": "clip_extractor"})
        self.assertEqual("comparison", shot["mediaNeedKind"])
        self.assertIn("ui", shot["routePlan"])

    def test_package_claim_routes_to_product_image_with_readable_overlay(self):
        shot = {
            "shotId": "S0001",
            "chapterId": "C01",
            "tts": "Si el envase promete eliminar grasa y está lleno de absolutos, guarda tu dinero.",
            "screenCopy": "REVISA LA PROMESA",
            "visualProof": "contrast the claim printed on the package",
        }
        normalize_media_contract(shot, {"media_need_kind": "product_inspection", "route": "clip_extractor"})
        self.assertEqual("product_inspection", shot["mediaNeedKind"])
        self.assertTrue(shot["requiresReadableData"])
        self.assertEqual("image", shot["route"])
        self.assertEqual("product-inspection", shot["hybridTemplate"])

    def test_image_query_compiler_is_idempotent(self):
        shot = {
            "shotId": "S0001",
            "tts": "Compara la misma persona desde dos ángulos",
            "prompt": "Landscape 16:9 editorial split-screen of the same subject.",
            "visualProof": "same subject, different angles",
            "mediaNeedKind": "comparison",
            "continuityGroup": "comparison-test",
        }
        first = compile_all(shot)["image"][0]
        second = compile_all(shot)["image"][0]
        self.assertEqual(first, second)
        self.assertEqual(1, second.count("Continuity lock"))

    def test_clip_query_compiler_is_idempotent(self):
        shot = {
            "shotId": "S0001",
            "tts": "Un dermatologo comenta el estudio en una entrevista publica.",
            "clipQuery": "Dermatologist explains topical cream study interview",
            "visualProof": "the quoted dermatologist explains the study",
            "mediaNeedKind": "third_party_commentary",
            "sourceTitle": "Dermatologist explains topical cream study",
            "sourceChannel": "Health Interview",
        }
        first = compile_all(shot)["clip_extractor"][0]
        second = compile_all(shot)["clip_extractor"][0]
        self.assertEqual(first, second)
        self.assertIn("commentary", second)

    def test_filmable_override_updates_route_query_and_acceptance_proof_together(self):
        shot = {"tts": "La superficie se vea más lisa durante un tiempo.", "visualProof": "abstract distinction", "route": "motion-card", "routePlan": ["motion-card"], "hookRequirement": "La etiqueta debe decir LUMERA"}
        apply_filmable_overrides([shot])
        self.assertEqual("human_action", shot["mediaNeedKind"])
        self.assertEqual("pexels", shot["route"])
        self.assertEqual("", shot["clipQuery"])
        self.assertIn("woman", shot["pexelsQuery"])
        self.assertIn("woman", shot["visualProof"].lower())
        self.assertFalse(shot["movingVisualRequired"])
        self.assertNotIn("LUMERA", shot["hookRequirement"])

    def test_patch_test_proof_is_atomic_for_a_short_beat(self):
        shot = {"tts": "Antes de usarla, prueba una pequeña zona. Espera y revisa.", "visualProof": "", "route": "motion-card", "routePlan": ["motion-card"]}
        apply_filmable_overrides([shot])
        self.assertTrue(shot["movingVisualRequired"])
        self.assertEqual("human_action", shot["mediaNeedKind"])
        self.assertEqual("pexels", shot["route"])
        self.assertEqual(["pexels", "omni", "ui"], shot["routePlan"])
        self.assertNotIn("cutout_motion", shot["routePlan"])
        self.assertEqual("procedure", shot["uiTemplate"])
        self.assertIn("one clearly defined test area", shot["visualProof"])
        self.assertNotIn("wait", shot["visualProof"].lower())
        self.assertNotIn("check", shot["clipBaseQuery"].lower())

    def test_buying_rule_routes_to_readable_deterministic_ui(self):
        shot = {"tts": "La regla de compra es sencilla: revisa ingredientes, tiempo y tolerancia.", "visualProof": "", "route": "motion-card", "routePlan": ["motion-card"], "hookRequirement": "La etiqueta debe decir LUMERA", "hybridTemplate": "product-inspection"}
        apply_purchase_evidence_routes([shot])
        self.assertEqual("ui", shot["route"])
        self.assertEqual(["ui"], shot["routePlan"])
        self.assertTrue(shot["requiresReadableData"])
        self.assertEqual("REGLA DE COMPRA", shot["screenCopy"])
        self.assertEqual(["PROMESA", "INGREDIENTES", "TIEMPO", "TOLERANCIA"], shot["uiItems"])
        self.assertNotIn("evidenceOverlayItems", shot)
        self.assertNotIn("hybridTemplate", shot)

    def test_surface_sensations_use_an_explanatory_motion_diagram(self):
        shot = {"tts": "El calor, cosquilleo o sudor no demuestran que cambió la grasa.", "visualProof": "skin sensation", "proofKind": "human_action", "mediaNeedKind": "human_action"}
        align_observable_evidence_contracts([shot])
        self.assertEqual("physiological_mechanism", shot["proofKind"])
        self.assertEqual("ui", shot["route"])
        self.assertEqual("mechanism", shot["uiTemplate"])
        self.assertFalse(shot["requiresObservedTransition"])
        stale = {**shot, "uiTemplate": "surface-vs-composition"}
        align_observable_evidence_contracts([stale])
        self.assertEqual("mechanism", stale["uiTemplate"])

    def test_second_hook_beat_gets_specific_topical_action(self):
        shots = [{"tts": "La pregunta.", "requiresReadableData": True}, {"tts": "No demuestra que eliminó grasa.", "route": "motion-card", "routePlan": ["motion-card"]}]
        apply_early_context_broll({"title": "Cremas reductoras"}, shots)
        self.assertEqual("pexels", shots[1]["route"])
        self.assertNotIn("clip_extractor", shots[1]["routePlan"])
        self.assertEqual("woman applying body lotion leg", shots[1]["pexelsQuery"])
        self.assertIn("without implying fat loss", shots[1]["visualProof"])

    def test_closing_body_distinction_clears_stale_product_route(self):
        shot = {"tts": "Necesitas distinguir piel, hinchazón y grasa antes de elegir.", "route": "clip_extractor", "routePlan": ["clip_extractor", "pexels"], "visualProof": "reads a product label", "hookRequirement": "LUMERA"}
        apply_closing_distinction_route([shot])
        self.assertIn(shot["route"], {"image", "ui", "omni"})
        self.assertNotIn("clip_extractor", shot["routePlan"])
        self.assertNotIn("cutout_motion", shot["routePlan"])
        self.assertEqual("anatomy-explainer", shot["uiTemplate"])
        self.assertIn("three-part", shot["visualProof"])

    def test_cta_repeating_distinction_words_stays_deterministic(self):
        shot = {"tts": "Ahora mira Cómo distinguir grasa, hinchazón y piel flácida.", "route": "image", "routePlan": ["image"]}
        data = {"cta": {"target_video_title": "Cómo distinguir grasa, hinchazón y piel flácida", "target_video_id": "abc123DEF45", "target_channel_id": "channel-1", "target_url": "https://youtu.be/abc123DEF45", "visibility": "public", "verified_at": "2026-07-17T00:00:00Z", "verified": True, "screen_copy": "MIRA ESTE VIDEO"}}
        apply_closing_distinction_route([shot])
        route_before_cta = shot["route"]
        apply_cta_end_screen_route(data, [shot])
        self.assertEqual(route_before_cta, shot["route"])
        self.assertTrue(shot["ctaAnchor"])
        self.assertNotIn("verifiedCtaEndScreen", shot)
        self.assertNotEqual("verified-next-video", shot.get("uiTemplate"))
        self.assertNotIn("uiValues", shot)

    def test_angle_comparison_ui_uses_complete_phrases(self):
        shot = {"tts": "Una foto tomada desde otro ángulo puede fabricar una diferencia.", "screenCopy": "EL ÁNGULO ENGAÑA", "subcopy": "Puede fabricar diferencias", "mediaNeedKind": "comparison", "continuityGroup": "comparison"}
        spec = compile_all(shot)["ui"][0]
        self.assertEqual(["MISMA PERSONA", "OTRO ÁNGULO"], spec["items"])

    def test_third_graphic_route_is_alternated_when_feasible(self):
        shots = [
            {"route": "motion-card", "routePlan": ["motion-card", "image"], "temporalAction": "single", "requiresReadableData": False},
            {"route": "ui", "routePlan": ["ui", "clip_extractor"], "temporalAction": "single", "requiresReadableData": False},
            {"route": "ui", "routePlan": ["ui", "clip_extractor", "pexels"], "temporalAction": "multi_step", "requiresReadableData": False},
        ]
        balance_graphic_routes(shots)
        self.assertEqual("pexels", shots[2]["route"])
        self.assertEqual("alternate_after_2_graphics", shots[2]["routingAdjustment"])
        self.assertEqual(["pexels", "ui"], shots[2]["routePlan"])

    def test_query_compilers_are_provider_specific(self):
        shot = {"shotId": "S0001", "chapterId": "C01", "tts": "Una mujer aplica crema en el brazo", "visualProof": "hand applying body cream", "screenCopy": "APLICA POCO", "subcopy": "", "mediaNeedKind": "human_action", "continuityGroup": "cream-demo"}
        result = compile_all(shot)
        self.assertNotIn("clip_extractor", result)
        self.assertLessEqual(len(result["pexels"][0].split()), 9)
        self.assertIn("Continuity lock", result["image"][0])
        self.assertIn("Start state", result["omni"][0])
        self.assertNotEqual(result["image"][0], result["pexels"][0])

    def test_abstract_queries_are_rejected(self):
        self.assertTrue(abstract_query("combine task fragments one thread"))

    def test_rejection_generates_directed_constraints(self):
        feedback = rejection_feedback("MICROSTOCK watermark and wrong software Blender")
        self.assertIn("third_party_watermark", feedback["rejected_because"])
        self.assertIn("wrong_software", feedback["rejected_because"])

    def test_ui_materialization_is_reproducible(self):
        shot = {"uiSpec": {"template": "comparison", "state": "resolved", "headline": "ANTES Y DESPUÉS", "subcopy": "", "items": ["ANTES", "DESPUÉS"], "values": [], "continuityGroup": "test", "dataSource": "locked_narration"}}
        materialize_shot(shot)
        self.assertEqual("ui-card", shot["visualKind"])
        self.assertEqual("deterministic-ui", shot["provider"])

    def test_ui_copy_never_leaks_provider_query_translation(self):
        shot = {"tts": "Lee la etiqueta con una regla clara", "screenCopy": "", "subcopy": "", "mediaNeedKind": "label_or_ingredient", "continuityGroup": "label"}
        result = compile_all(shot)["ui"][0]
        serialized = json.dumps(result, ensure_ascii=False).lower()
        self.assertNotIn("product label", serialized)
        self.assertIn("etiqueta", serialized)
        self.assertTrue(all(len(item) <= 32 for item in [result["headline"], *result["items"]]))

    def test_ui_copy_never_cuts_a_word_at_character_limit(self):
        shot = {"tts": "La próxima vez que veas una transformación sorprendente", "screenCopy": "", "subcopy": "", "mediaNeedKind": "abstract_concept", "continuityGroup": ""}
        headline = compile_all(shot)["ui"][0]["headline"]
        self.assertNotIn("SORP", headline)
        self.assertLessEqual(len(headline), 32)

    def test_ui_copy_keeps_a_complete_five_word_phrase_when_it_fits(self):
        shot = {"tts": "Te gusta cómo se siente", "screenCopy": "", "subcopy": "", "mediaNeedKind": "abstract_concept", "continuityGroup": ""}
        result = compile_all(shot)["ui"][0]
        self.assertEqual("TE GUSTA CÓMO SE SIENTE", result["headline"])
        self.assertIn("TE GUSTA CÓMO SE SIENTE", result["items"])

    def test_global_set_qa_blocks_still_only_when_transition_must_be_observed(self):
        plan = {"shots": [{"shotId": "S0001", "visualKind": "image", "source": "x.png", "provider": "image", "mediaType": "image", "temporalAction": "multi_step", "temporalEvidenceMode": "continuous", "requiresObservedTransition": True, "requiresReadableData": False, "continuityGroup": ""}]}
        self.assertEqual("FAIL", validate_set(plan)["status"])

    def test_global_set_qa_classifies_cutout_as_generated_video(self):
        plan = {"shots": [{"shotId": "S0001", "visualKind": "broll", "source": "x.mp4", "provider": "cutout_motion", "mediaType": "video", "temporalAction": "multi_step", "requiresReadableData": False, "continuityGroup": ""}]}
        result = validate_set(plan)
        self.assertEqual("PASS", result["status"])
        self.assertEqual(1, result["metrics"]["media_classes"]["generated"])

    def test_global_set_qa_allows_illustrative_broll_inside_state_group(self):
        plan = {"shots": [
            {"shotId": "S0001", "visualKind": "ui-card", "source": "", "provider": "deterministic-ui", "mediaType": "card", "requiresReadableData": False, "requiresStateContinuity": True, "continuityGroup": "comparison"},
            {"shotId": "S0002", "visualKind": "broll", "source": "woman.mp4", "provider": "pexels", "mediaType": "video", "requiresReadableData": False, "requiresStateContinuity": False, "continuityGroup": "comparison"},
            {"shotId": "S0003", "visualKind": "ui-card", "source": "", "provider": "deterministic-ui", "mediaType": "card", "requiresReadableData": False, "requiresStateContinuity": True, "continuityGroup": "comparison"},
        ]}
        self.assertEqual("PASS", validate_set(plan)["status"])

    def test_prefilter_rejects_watermark_filename_before_vision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "MICROSTOCK_sample.png"
            MockProviders(1920, 1080, 30).image_clip("test", str(path))
            result = prefilter(path, "image", {"mediaNeedKind": "human_action", "requiresReadableData": False}, "image")
            self.assertEqual("REJECT", result["status"])

    def test_people_prefilter_requires_face_only_when_explicit_evidence(self):
        with mock.patch.object(media_prefilter_module, "_face_metrics", return_value=(0, 0.0)):
            contextual_errors, contextual_metrics = media_prefilter_module._people_errors([object()], {"peoplePolicy": "contextual"})
            required_errors, required_metrics = media_prefilter_module._people_errors([object()], {"peoplePolicy": "contextual", "requiresVisibleFace": True})
        self.assertEqual([], contextual_errors)
        self.assertFalse(contextual_metrics["requires_visible_face"])
        self.assertIn("rostro esperado como evidencia pero no visible", required_errors)
        self.assertTrue(required_metrics["requires_visible_face"])

    def test_provider_telemetry_summarizes_cost_and_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            telemetry = ProviderTelemetry(pathlib.Path(directory) / "events.jsonl")
            telemetry.emit(provider="image", scene="S1", query_or_prompt="x", result="produced", estimated_cost_usd=0.04)
            telemetry.emit(provider="image", scene="S1", query_or_prompt="x", result="selected", asset_after="image.png", estimated_cost_usd=0)
            telemetry.emit(provider="image", scene="S2", query_or_prompt="y", result="rejected", rejection_reason="logo", estimated_cost_usd=0)
            summary = telemetry.summary()
            self.assertEqual(3, summary["events"])
            self.assertEqual(1, summary["providers"]["image"]["calls"])
            self.assertEqual(1, summary["providers"]["image"]["rejected"])
            self.assertEqual("image.png", summary["surviving_sources"]["S1"]["asset"])

    def test_contract_rejects_provider_contradictions_before_calls(self):
        shot = {"shotId": "S1", "mediaNeedKind": "exact_ui_state", "route": "image", "routePlan": ["image"], "requiresReadableData": True, "requiresStateContinuity": False, "temporalAction": "multi_step", "temporalEvidenceMode": "continuous", "requiresObservedTransition": True, "movingVisualRequired": True, "prompt": "before and after without text", "screenCopy": "CAMBIO", "motionSpec": {"purpose": "explain", "visualPrimitive": "diagram", "timeline": [{"at": 0, "action": "stage", "target": "primary"}]}}
        errors = validate_media_contract(shot)
        self.assertTrue(any("datos legibles" in error for error in errors))
        self.assertTrue(any("transicion completa" in error for error in errors))

    def test_thumbnail_prefilter_does_not_reject_resolution_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "candidate.jpg"
            MockProviders(640, 360, 30).image_clip("test", str(path))
            result = prefilter_search_thumbnail(path, {"media_need_kind": "human_action"})
            self.assertEqual("PASS", result["status"])

    def test_pexels_audits_three_thumbnails_before_bounded_download(self):
        videos = [{
            "id": index,
            "url": "https://pexels.test/body-cream-%d" % index,
            "image": "https://thumb.test/%d.jpg" % index,
            "user": {"name": "creator"},
            "video_files": [{"width": 1920, "height": 1080, "link": "https://video.test/%d.mp4" % index}],
        } for index in range(1, 6)]
        downloaded_videos = []
        def fake_download(url, path):
            if url.endswith(".jpg"):
                MockProviders(640, 360, 30).image_clip("thumbnail", path)
            else:
                downloaded_videos.append(url)
                pathlib.Path(path).write_bytes(b"video")
        def fake_normalize(_self, _source, output, _duration):
            pathlib.Path(output).write_bytes(b"normalized")
            return output
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"PEXELS_API_KEY": "test"}), mock.patch.object(provider_core, "_http", return_value=(200, json.dumps({"videos": videos}))), mock.patch.object(provider_core, "_download", side_effect=fake_download), mock.patch.object(RealProviders, "_normalize_video", fake_normalize):
            output = pathlib.Path(directory) / "clip.mp4"
            RealProviders(1920, 1080, 30).pexels_clip("body cream home", 2, str(output), {"media_need_kind": "product_inspection"})
            audit = json.loads(pathlib.Path(str(output) + ".pexels_candidates.json").read_text(encoding="utf-8"))
            self.assertEqual(3, len(audit["candidates"]))
            self.assertEqual(1, len(downloaded_videos))
            self.assertTrue(output.is_file())

    def test_pexels_ranks_body_lotion_action_above_serum_mismatch(self):
        videos = [
            {
                "id": 1,
                "url": "https://pexels.test/woman-holding-serum-1",
                "image": "https://thumb.test/serum.jpg",
                "user": {"name": "creator"},
                "video_files": [{"width": 1920, "height": 1080, "link": "https://video.test/serum.mp4"}],
            },
            {
                "id": 2,
                "url": "https://pexels.test/woman-applying-body-lotion-arm-2",
                "image": "https://thumb.test/lotion.jpg",
                "user": {"name": "creator"},
                "video_files": [{"width": 1920, "height": 1080, "link": "https://video.test/lotion.mp4"}],
            },
        ]
        downloaded_videos = []
        def fake_download(url, path):
            if url.endswith(".jpg"):
                MockProviders(640, 360, 30).image_clip("thumbnail", path)
            else:
                downloaded_videos.append(url)
                pathlib.Path(path).write_bytes(b"video")
        def fake_normalize(_self, _source, output, _duration):
            pathlib.Path(output).write_bytes(b"normalized")
            return output
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"PEXELS_API_KEY": "test"}), mock.patch.object(provider_core, "_http", return_value=(200, json.dumps({"videos": videos}))), mock.patch.object(provider_core, "_download", side_effect=fake_download), mock.patch.object(RealProviders, "_normalize_video", fake_normalize):
            output = pathlib.Path(directory) / "clip.mp4"
            RealProviders(1920, 1080, 30).pexels_clip("woman applying body lotion arm", 2, str(output), {"media_need_kind": "human_action"})
            self.assertEqual(["https://video.test/lotion.mp4"], downloaded_videos)


class ScriptHandoffTests(unittest.TestCase):
    def test_suno_request_separates_audible_style_from_editorial_context(self):
        request = build_suno_request(mood="warm, credible", bpm=92, duration_seconds=180, chapter_titles=["La prueba"])
        self.assertTrue(request["instrumental"])
        self.assertIn("piano", request["description"])
        self.assertIn("vocals", request["exclude"])
        self.assertNotIn("45+", request["description"])
        self.assertNotIn("health explainer", request["description"].lower())
        self.assertIn("audience", request["editorial_context"])

    def test_extracts_only_narration_column(self):
        markdown = """| AUDIO / NARRACION | ESTIMULO VISUAL / RITMO |\n|---|---|\n| ¿Reduce grasa? | Envase |\n| Mira la etiqueta. | Macro |\n\nSTATUS FINAL: SCRIPT_COMPLETO\n"""
        self.assertEqual(["¿Reduce grasa?", "Mira la etiqueta."], table_audio(markdown))

    def test_balanced_chapters_preserve_row_order(self):
        rows = ["fila %d con varias palabras" % index for index in range(12)]
        groups = balanced_chapters(rows, 4)
        self.assertEqual(rows, [row for group in groups for row in group])
        self.assertEqual(4, len(groups))

    def test_tts_speed_never_slows_voice_to_fill_runtime(self):
        self.assertEqual(0.98, effective_tts_speed(402, 3))
        self.assertAlmostEqual(0.98, effective_tts_speed(585, 3), places=2)

    def test_short_script_is_rejected_before_tts(self):
        error = natural_voice_density_error(277, 2)
        self.assertIn("SCRIPT_DURATION_MISMATCH", error)
        self.assertIn("360-400 palabras", error)
        self.assertEqual("", natural_voice_density_error(380, 2))

    def test_voice_profile_signature_changes_with_speed(self):
        with mock.patch.dict(os.environ, {"ELEVENLABS_SPEED": "0.98", "LONGFORM_TTS_LOCK_SPEED": "1"}, clear=False):
            natural = tts_voice_profile(0.98)
            slowed = tts_voice_profile(0.70)
        self.assertNotEqual(natural["signature"], slowed["signature"])
        self.assertTrue(natural["speed_locked"])

    def test_chunker_assigns_long_pause_without_exceeding_shot_limit(self):
        voice = {
            "duration_ms": 15000,
            "chapters": [{"id": "C01", "title": "Prueba", "start_ms": 0, "end_ms": 15000}],
            "words": [
                {"chapter_id": "C01", "word": "Primera.", "start_ms": 0, "end_ms": 1000},
                {"chapter_id": "C01", "word": "Segunda", "start_ms": 9000, "end_ms": 10000},
                {"chapter_id": "C01", "word": "frase.", "start_ms": 14000, "end_ms": 15000},
            ],
        }
        shots = chunk_words(voice)
        self.assertTrue(all(0 < shot["endMs"] - shot["startMs"] <= MAX_SHOT_MS for shot in shots))
        self.assertEqual(15000, shots[-1]["endMs"])

    def test_chunker_accounts_for_final_chapter_padding_before_split(self):
        voice = {
            "duration_ms": 8067,
            "chapters": [{"id": "C01", "title": "Prueba", "start_ms": 0, "end_ms": 8067}],
            "words": [
                {"chapter_id": "C01", "word": "Inicio", "start_ms": 0, "end_ms": 7400},
                {"chapter_id": "C01", "word": "final.", "start_ms": 7400, "end_ms": 7511},
            ],
        }
        shots = chunk_words(voice)
        self.assertEqual(2, len(shots))
        self.assertTrue(all(shot["endMs"] - shot["startMs"] <= MAX_SHOT_MS for shot in shots))
        self.assertEqual(8067, shots[-1]["endMs"])


if __name__ == "__main__":
    unittest.main()
