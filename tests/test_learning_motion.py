import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
os.sys.path.insert(0, str(ROOT))

from engine import channel_learning
from engine.longform_pipeline import build_sfx_events, prepare_remotion_public


class HumanLearningTests(unittest.TestCase):
    def test_machine_qa_alone_never_promotes_provider_bias(self):
        state = {
            "observations": [
                {"run_id": f"run-{index}", "proof_kind": "human_action", "provider": "pexels", "run_pass": True, "quality_score": 90}
                for index in range(3)
            ]
        }
        rules = channel_learning._rebuild_rules(state, [])
        self.assertEqual("pending", rules[0]["status"])
        self.assertEqual(0.0, rules[0]["bias"])

    def test_repeated_human_approval_promotes_good_provider_fit(self):
        state = {
            "observations": [
                {"run_id": run_id, "proof_kind": "human_action", "provider": "pexels", "run_pass": True, "quality_score": 90}
                for run_id in ("run-a", "run-a", "run-b")
            ]
        }
        feedback = [
            {"run_id": "run-a", "status": "APPROVED", "note": ""},
            {"run_id": "run-b", "status": "APPROVED", "note": ""},
        ]
        rules = channel_learning._rebuild_rules(state, feedback)
        self.assertEqual("promoted", rules[0]["status"])
        self.assertEqual(5.0, rules[0]["bias"])

    def test_generic_rejection_does_not_penalize_a_provider(self):
        state = {
            "observations": [
                {"run_id": run_id, "proof_kind": "human_action", "provider": "pexels", "run_pass": False, "quality_score": 40}
                for run_id in ("run-a", "run-a", "run-b")
            ]
        }
        feedback = [
            {"run_id": "run-a", "status": "REJECTED", "note": "El ritmo general se siente lento"},
            {"run_id": "run-b", "status": "REJECTED", "note": "El cierre no cumple la promesa"},
        ]
        rules = channel_learning._rebuild_rules(state, feedback)
        self.assertEqual("pending", rules[0]["status"])
        self.assertEqual(0.0, rules[0]["bias"])


class MotionRuntimeTests(unittest.TestCase):
    def test_semantic_sfx_cues_are_bounded_and_resolved(self):
        plan = {"shots": [{
            "shotId": "S0001",
            "startMs": 1000,
            "endMs": 6000,
            "motionSpec": {"sfxCues": [
                {"at": 0.20, "kind": "line-draw"},
                {"at": 0.55, "kind": "reveal"},
                {"at": 0.90, "kind": "impact"},
            ]},
        }]}
        events = build_sfx_events(plan)
        shot_cues = [event for event in events if event.get("semantic") != "chapter-transition"]
        self.assertEqual(2, len(shot_cues))
        self.assertTrue(all(event.get("src") for event in events))
        self.assertGreaterEqual(shot_cues[1]["startMs"] - shot_cues[0]["startMs"], 650)

    def test_remotion_public_contains_only_current_run_and_shared_sfx(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            public = root / "public"
            current = public / "runs" / "run-current"
            stale = public / "runs" / "run-stale"
            shared = public / "sfx"
            current.mkdir(parents=True)
            stale.mkdir(parents=True)
            shared.mkdir(parents=True)
            (current / "asset.mp4").write_bytes(b"video")
            (stale / "old.mp4").write_bytes(b"old")
            (shared / "cue.wav").write_bytes(b"sfx")
            paths = {"work": root / "work"}
            with mock.patch("engine.longform_pipeline.REMOTION_DIR", root):
                staged = prepare_remotion_public("run-current", paths)
            self.assertTrue((staged / "runs" / "run-current" / "asset.mp4").is_file())
            self.assertTrue((staged / "sfx" / "cue.wav").is_file())
            self.assertFalse((staged / "runs" / "run-stale").exists())
            manifest = json.loads((paths["work"] / "render_public_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("run-current", manifest["run_id"])


if __name__ == "__main__":
    unittest.main()
