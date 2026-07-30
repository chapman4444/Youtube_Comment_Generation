"""Responsive window sizing without creating Tk."""

from llm_youtube_comment_generation.interfaces.gui.layout import (
    initial_size,
    valid_saved_geometry,
)


def test_large_screen_gets_a_larger_working_window():
    width, height = initial_size(1920, 1080)

    assert width >= 1400
    assert height >= 800
    assert width < 1920
    assert height < 1080


def test_small_screen_is_never_forced_far_beyond_available_space():
    width, height = initial_size(1024, 768)

    assert width <= 1024
    assert height <= 768


def test_only_real_tk_geometry_is_restored():
    assert valid_saved_geometry("1440x850+100+40")
    assert valid_saved_geometry("1280x800")
    assert not valid_saved_geometry("maximize")
    assert not valid_saved_geometry("1440 by 850")
