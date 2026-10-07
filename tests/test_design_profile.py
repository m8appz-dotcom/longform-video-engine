from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from engine.design_profile import (
    NEUTRAL_PROFILE,
    extract_design_profile,
    remotion_theme,
    resolve_design_profile,
    validate_design_profile,
)


class DesignProfileTests(unittest.TestCase):
    def test_builtin_profile_is_frontier_dark_default(self):
        colors = NEUTRAL_PROFILE["tokens"]["colors"]
        self.assertEqual("frontier-dark-v1", NEUTRAL_PROFILE["id"])
        self.assertEqual("#0A0A0A", colors["background"])
        self.assertEqual("#FFFFFF", colors["accent"])
        self.assertEqual("#FF7A17", colors["highlight"])
        self.assertIn("sans-serif", remotion_theme(NEUTRAL_PROFILE)["fontDisplay"])
        self.assertEqual(400, NEUTRAL_PROFILE["typography"]["displayWeight"])
        self.assertFalse(NEUTRAL_PROFILE["effects"]["useShadows"])
        self.assertEqual([], validate_design_profile(NEUTRAL_PROFILE))

    def test_explicit_project_profile_reaches_remotion(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = resolve_design_profile({
                "design_profile": {
                    "tokens": {
                        "colors": {"background": "#101820", "accent": "#00AEEF", "highlight": "#F5D547"},
                        "semanticColors": {"fluid": "#4CB5AE", "fat": "#E2B13C"},
                    },
                    "composition": {"splitRatio": 0.58, "edgePadding": 104, "cardRadius": 8},
                    "motion": {"entrance": "scale", "intensity": 0.82},
                    "rendering": {"spatialMode": "three", "allowThree": True},
                },
            }, pathlib.Path(directory))
        theme = remotion_theme(profile)
        self.assertTrue(profile["id"].startswith("project-"))
        self.assertEqual("#00AEEF", theme["accent"])
        self.assertEqual("#4CB5AE", theme["semanticColors"]["fluid"])
        self.assertEqual(0.58, theme["composition"]["splitRatio"])
        self.assertEqual("scale", theme["motion"]["entrance"])
        self.assertTrue(theme["rendering"]["allowThree"])

    def test_url_source_compiles_layout_motion_and_advanced_visuals(self):
        html = """
        <html><head><style>
        :root { color:#15212A; background:#F7F8FA; }
        .panel { color:#1B7F72; border-radius:6px; padding:12px; transition-duration:300ms; }
        @keyframes slideIn { from { transform:translateX(10px); } }
        </style></head><body><canvas></canvas><script>/* three.js WebGL */</script></body></html>
        """
        with tempfile.TemporaryDirectory() as directory, mock.patch("engine.design_profile._fetch", return_value=html):
            profile = extract_design_profile("https://example.test", pathlib.Path(directory))
        self.assertEqual("compact", profile["composition"]["density"])
        self.assertEqual(6, profile["composition"]["cardRadius"])
        self.assertEqual("slide", profile["motion"]["entrance"])
        self.assertEqual("three", profile["rendering"]["spatialMode"])
        self.assertTrue(profile["rendering"]["allowThree"])
        self.assertTrue(profile["rendering"]["allowWebgl"])
        self.assertTrue(profile["rendering"]["allowCanvas"])

    def test_invalid_profile_is_rejected_before_render(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "DesignProfile invalido"):
                resolve_design_profile({
                    "design_profile": {
                        "tokens": {"colors": {"accent": "teal"}},
                        "composition": {"splitRatio": 0.9},
                        "typography": {"displayLetterSpacing": -2.4},
                    },
                }, pathlib.Path(directory))

    def test_natural_language_instructions_compile_to_runtime_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = resolve_design_profile({
                "design_source": {"type": "instructions", "value": "Estilo compacto y dinamico. Acento: #6B46C1. Use Three.js y WebGL. Entrada scale. Split 58."},
            }, pathlib.Path(directory))
        self.assertEqual("#6B46C1", profile["tokens"]["colors"]["accent"])
        self.assertEqual("compact", profile["composition"]["density"])
        self.assertEqual(0.58, profile["composition"]["splitRatio"])
        self.assertEqual("scale", profile["motion"]["entrance"])
        self.assertEqual(0.82, profile["motion"]["intensity"])
        self.assertTrue(profile["rendering"]["allowThree"])
        self.assertTrue(profile["rendering"]["allowWebgl"])

    def test_explicit_tokens_override_natural_language(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = resolve_design_profile({
                "design_instructions": "Acento: #6B46C1. Estilo compacto.",
                "design_profile": {"tokens": {"colors": {"accent": "#147D64"}}},
            }, pathlib.Path(directory))
        self.assertEqual("#147D64", profile["tokens"]["colors"]["accent"])


if __name__ == "__main__":
    unittest.main()
