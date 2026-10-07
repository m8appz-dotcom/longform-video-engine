import pathlib
import tempfile
import unittest
from unittest import mock

from tools.finalize_suno_download import candidate_files


class SunoDownloadTests(unittest.TestCase):
    def test_candidate_files_only_returns_recent_supported_extensions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            recent = root / "recent.tmp"
            recent.write_bytes(b"mp3")
            ignored = root / "notes.txt"
            ignored.write_text("not audio", encoding="utf-8")
            with mock.patch("tools.finalize_suno_download.time.time", return_value=recent.stat().st_mtime + 10):
                result = candidate_files(root, max_age_seconds=60)
            self.assertEqual([recent], result)


if __name__ == "__main__":
    unittest.main()
