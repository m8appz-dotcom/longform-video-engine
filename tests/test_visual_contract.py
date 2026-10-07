from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np

from engine.composition_qa import validate_composed_frames
from engine.art_direction_qa import review_art_direction
from engine.motion_choreography import apply_motion_choreography, validate_motion_choreography
from engine.visual_contract import (
    internal_id_visible,
    normalize_plan_visual_composition,
    repair_payload_matches,
    repair_plan_hash,
    repair_shot_hash,
    validate_plan_visual_composition,
)


class VisualCompositionContractTests(unittest.TestCase):
    def test_hybrid_without_local_ocr_is_deferred_to_composed_frame_qa(self):
        plan = {"shots": [{
            "shotId": "S0001", "route": "ui", "visualKind": "ui-card",
            "uiTemplate": "comparison", "backgroundSource": "evidence.png",
            "assetOcrAvailable": False,
        }]}
        normalize_plan_visual_composition(plan)
        self.assertEqual([], validate_plan_visual_composition(plan, resolved=True))
        self.assertEqual("hybrid", plan["shots"][0]["visualStrategy"])
        self.assertEqual("remotion", plan["shots"][0]["textOwner"])

    def test_unknown_ui_without_semantic_template_is_blocked(self):
        plan = {"shots": [{"shotId": "S0001", "route": "ui", "visualKind": "ui-card"}]}
        normalize_plan_visual_composition(plan)
        errors = validate_plan_visual_composition(plan)
        self.assertTrue(any("fallback Diagram prohibido" in error for error in errors))

    def test_high_ui_share_passes_when_semantic_grammar_varies(self):
        plan = {"shots": [
            {"shotId": "S0001", "route": "ui", "uiTemplate": "comparison"},
            {"shotId": "S0002", "route": "ui", "uiTemplate": "mechanism"},
            {"shotId": "S0003", "route": "ui", "uiTemplate": "process-steps"},
            {"shotId": "S0004", "route": "ui", "uiTemplate": "product-inspection"},
        ]}
        normalize_plan_visual_composition(plan)
        self.assertEqual([], validate_plan_visual_composition(plan))

    def test_three_identical_semantic_grammars_are_blocked(self):
        plan = {"shots": [
            {"shotId": "S0001", "route": "ui", "uiTemplate": "comparison"},
            {"shotId": "S0002", "route": "ui", "uiTemplate": "comparison"},
            {"shotId": "S0003", "route": "ui", "uiTemplate": "comparison"},
        ]}
        normalize_plan_visual_composition(plan)
        self.assertTrue(any("misma gramatica" in error for error in validate_plan_visual_composition(plan)))

    def test_filmable_plan_requires_real_video_only_after_resolution(self):
        plan = {"shots": [{"shotId": "S0001", "route": "pexels", "proofKind": "human_action", "mediaType": "image"}]}
        normalize_plan_visual_composition(plan)
        self.assertEqual([], validate_plan_visual_composition(plan, resolved=False))
        self.assertTrue(any("ningun video real" in error for error in validate_plan_visual_composition(plan, resolved=True)))

    def test_repair_payload_is_bound_to_exact_plan_and_shot(self):
        plan = {"scriptHash": "script", "designProfileId": "design", "durationMs": 5000, "shots": [{"shotId": "S0001", "route": "ui"}]}
        payload = {
            "policy": "policy", "attempt": 1, "expiresAfterAttempt": 1,
            "scriptHash": "script", "designProfileId": "design",
            "sourcePlanHash": repair_plan_hash(plan),
            "patches": {"S0001": {"sourceShotHash": repair_shot_hash(plan["shots"][0]), "route": "image"}},
        }
        self.assertTrue(repair_payload_matches(payload, plan, "policy"))
        plan["shots"][0]["route"] = "pexels"
        self.assertFalse(repair_payload_matches(payload, plan, "policy"))

    def test_catalog_id_detection_ignores_whitespace_only(self):
        self.assertTrue(internal_id_visible("VIDEO nZ5K G52rfH8", "nZ5KG52rfH8"))
        self.assertFalse(internal_id_visible("SIGUIENTE VIDEO", "nZ5KG52rfH8"))

    def test_composed_frame_blocks_visible_catalog_id(self):
        with tempfile.TemporaryDirectory() as directory:
            frame = pathlib.Path(directory) / "frame.png"
            cv2.imwrite(str(frame), np.full((360, 640, 3), 245, dtype=np.uint8))
            samples = [{"path": frame, "label": "CTA", "shot": {}}]
            plan = {"cta": {"target_video_id": "nZ5KG52rfH8"}}
            with mock.patch("engine.composition_qa._ocr", return_value=("VIDEO nZ5KG52rfH8", True)):
                report = validate_composed_frames(samples, plan)
            self.assertEqual("FAIL", report["status"])

    def test_end_screen_source_never_renders_catalog_id(self):
        source = pathlib.Path(__file__).resolve().parents[1] / "remotion" / "src" / "longform" / "VerifiedEndScreen.tsx"
        text = source.read_text(encoding="utf-8")
        self.assertNotIn("{endScreen.targetVideoId}", text)

    def test_supported_semantic_scene_uses_v2_with_v1_fallback(self):
        plan = {"shots": [{
            "shotId": "S0001", "route": "image", "uiTemplate": "body-distinction",
            "hybridTemplate": "body-distinction", "backgroundSource": "runs/test/anatomy.png",
            "visualKind": "ui-card",
        }]}
        normalize_plan_visual_composition(plan)
        shot = plan["shots"][0]
        self.assertEqual("semantic-v2", shot["rendererVersion"])
        self.assertEqual("semantic-v1", shot["fallbackRenderer"])
        self.assertEqual([], validate_plan_visual_composition(plan))

    def test_literal_anatomy_cannot_fall_back_to_ui_wireframe(self):
        plan = {"shots": [{"shotId": "S0001", "route": "ui", "uiTemplate": "anatomy-explainer"}]}
        normalize_plan_visual_composition(plan)
        errors = validate_plan_visual_composition(plan)
        self.assertTrue(any("no admite UI como medio primario" in error for error in errors))

    def test_resolved_protocol_requires_literal_background(self):
        plan = {"shots": [{
            "shotId": "S0001", "route": "image", "uiTemplate": "process-steps",
            "uiVariant": "protocol-diagram", "hybridTemplate": "process-steps",
        }]}
        normalize_plan_visual_composition(plan)
        errors = validate_plan_visual_composition(plan, resolved=True)
        self.assertTrue(any("sin asset literal" in error for error in errors))

    def test_unsupported_scene_cannot_force_v2(self):
        plan = {"shots": [{"shotId": "S0001", "route": "ui", "uiTemplate": "timeline", "rendererVersion": "semantic-v2"}]}
        normalize_plan_visual_composition(plan)
        self.assertEqual("semantic-v1", plan["shots"][0]["rendererVersion"])

    def test_motion_choreography_varies_repeated_patterns(self):
        plan = {"shots": [
            {"shotId": "S0001", "visualStrategy": "motion"},
            {"shotId": "S0002", "visualStrategy": "motion"},
            {"shotId": "S0003", "visualStrategy": "motion"},
            {"shotId": "S0004", "visualStrategy": "motion"},
        ]}
        apply_motion_choreography(plan)
        self.assertEqual([], validate_motion_choreography(plan))
        self.assertGreater(len({shot["motionPattern"] for shot in plan["shots"]}), 1)

    def test_project_three_grammar_only_applies_to_explicit_abstract_3d(self):
        plan = {
            "designProfile": {"rendering": {"spatialMode": "three", "allowThree": True, "allowWebgl": True}},
            "shots": [
                {"shotId": "S0001", "proofKind": "abstract_concept", "representation": "3d", "motionSpec": {"visualPrimitive": "editorial"}},
                {"shotId": "S0002", "proofKind": "physiological_mechanism", "representation": "3d", "motionSpec": {"visualPrimitive": "anatomy"}},
            ],
        }
        apply_motion_choreography(plan)
        self.assertEqual("three_scene", plan["shots"][0]["motionSpec"]["visualPrimitive"])
        self.assertEqual("anatomy", plan["shots"][1]["motionSpec"]["visualPrimitive"])
        self.assertTrue(plan["shots"][0]["designGrammar"]["threeAllowed"])

    def test_disallowed_advanced_primitive_falls_back_to_editorial(self):
        plan = {
            "designProfile": {"rendering": {"spatialMode": "flat", "allowThree": False, "allowParticles": False}},
            "shots": [
                {"shotId": "S0001", "proofKind": "abstract_concept", "representation": "3d", "motionSpec": {"visualPrimitive": "three_scene"}},
                {"shotId": "S0002", "proofKind": "abstract_concept", "motionSpec": {"visualPrimitive": "particles"}},
            ],
        }
        apply_motion_choreography(plan)
        self.assertEqual("editorial", plan["shots"][0]["motionSpec"]["visualPrimitive"])
        self.assertEqual("editorial", plan["shots"][1]["motionSpec"]["visualPrimitive"])

    def test_art_direction_is_advisory_only(self):
        report = review_art_direction({"shots": [{"shotId": "S0001", "rendererVersion": "semantic-v1"}]}, {"improvements": ["Más contraste"]})
        self.assertEqual("ADVISORY", report["status"])
        self.assertFalse(report["blocking"])
        self.assertFalse(report["current_run_asset_rejection_allowed"])


if __name__ == "__main__":
    unittest.main()
