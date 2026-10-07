from engine import gemma_audio


def test_sample_windows_cover_hook_middle_and_cta():
    windows = gemma_audio.sample_windows(600_000)
    assert [item[0] for item in windows] == ["hook", "middle", "cta"]
    assert windows[0] == ("hook", 0, 25_000)
    assert windows[1] == ("middle", 287_500, 25_000)
    assert windows[2] == ("cta", 575_000, 25_000)


def test_sample_windows_deduplicate_short_video():
    windows = gemma_audio.sample_windows(8_000)
    assert windows == [("hook", 0, 8_000)]


def test_expected_for_window_uses_word_midpoints():
    words = [
        {"word": "uno", "start_ms": 0, "end_ms": 200},
        {"word": "dos", "start_ms": 900, "end_ms": 1100},
        {"word": "tres", "start_ms": 1900, "end_ms": 2100},
    ]
    assert gemma_audio.expected_for_window(words, 0, 1500) == "uno dos"
    assert gemma_audio.expected_for_window(words, 1500, 2500) == "tres"
