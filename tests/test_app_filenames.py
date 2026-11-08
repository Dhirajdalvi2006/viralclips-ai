"""Regression tests for the uploaded-filename sanitiser.

The uploaded filename is untrusted input. ``_safe_filename`` must turn
it into a single path component that cannot escape its directory, be
interpreted by a shell, or collide with a reserved device name.
"""
from __future__ import annotations

import pytest

from viralclips_app.main import _safe_filename


def _assert_safe(result: str) -> None:
    """Every invariant the sanitiser must guarantee."""
    assert result, "the result must never be empty"
    assert "\x00" not in result
    assert "/" not in result
    assert "\\" not in result
    assert ".." not in result
    for ch in result:
        assert ord(ch) >= 32, f"control character {ord(ch)} survived"
        assert ch not in '&|;<>()$`"\'*?[]{}~^#%', (
            f"shell metacharacter {ch!r} survived")
    # A Windows path component cannot end in a dot or a space.
    assert not result.endswith(".")
    assert not result.endswith(" ")


# --- traversal ------------------------------------------------------------

@pytest.mark.parametrize("name,expected_final", [
    ("../../evil.mp4", "evil"),
    ("..\\..\\evil.mp4", "evil"),
    ("........evil.mp4", "evil"),
    ("../../../../Windows/System32/config/SAM.mp4", "sam"),
    ("..\\..\\..\\..\\Windows\\System32\\config\\SAM.mp4", "sam"),
    ("....//....//evil.mp4", "evil"),
    ("..%2f..%2fevil.mp4", "evil"),
])
def test_traversal_sequences_never_survive(name, expected_final):
    result = _safe_filename(name)
    _assert_safe(result)
    # The final path component is what survives; everything before the
    # last separator is discarded.
    assert expected_final in result.lower()


def test_traversal_keeps_the_extension():
    assert _safe_filename("../../evil.mp4").endswith(".mp4")


def test_a_deeply_nested_name_becomes_the_final_component():
    result = _safe_filename("a/b/c/d/evil.mp4")
    _assert_safe(result)
    assert result == "evil.mp4"


def test_a_backslash_path_becomes_the_final_component():
    result = _safe_filename("a\\b\\c\\evil.mp4")
    _assert_safe(result)
    assert result == "evil.mp4"


# --- shell metacharacters -------------------------------------------------

@pytest.mark.parametrize("name", [
    "evil; command.mp4",
    "evil && rm -rf /.mp4",
    "evil | cat.mp4",
    "evil$(whoami).mp4",
    "evil`whoami`.mp4",
    "evil & calc.mp4",
    "evil>out.mp4",
    "evil<in.mp4",
    "evil*.mp4",
    "evil?.mp4",
])
def test_shell_metacharacters_are_removed(name):
    result = _safe_filename(name)
    _assert_safe(result)
    assert result.endswith(".mp4")


def test_a_shell_fragment_cannot_survive_as_a_whole_word():
    result = _safe_filename("evil; rm -rf /.mp4")
    assert "rm" not in result.replace("upload", "")
    assert ";" not in result


# --- shell command words ---------------------------------------------------

@pytest.mark.parametrize("name", [
    "rm -rf home.mp4",
    "evil name; rm -rf .mp4",
    "shutdown now.mp4",
    "curl http://example.com.mp4",
    "whoami.mp4",
    "powershell -enc SQBFAFgA.mp4",
    "netstat -an.mp4",
    "chmod 777 file.mp4",
    "sudo rm everything.mp4",
])
def test_a_shell_command_word_never_survives(name):
    """A word that names a shell command must not survive.

    Removing the metacharacters is not sufficient on its own: a name
    such as ``rm -rf home`` contains none of them and still reads as a
    command.
    """
    result = _safe_filename(name)
    _assert_safe(result)
    words = {w.strip("._-").lower() for w in result.replace(".mp4", "").split()}
    assert not words & {
        "rm", "shutdown", "curl", "whoami", "powershell", "netstat",
        "chmod", "sudo",
    }, f"a command word survived in {result!r}"


def test_a_flag_after_a_command_word_is_dropped_with_it():
    result = _safe_filename("rm -rf home.mp4")
    assert "-rf" not in result
    assert "rm" not in result


@pytest.mark.parametrize("name", [
    "charm.mp4",
    "Terminal.mp4",
    "networking.mp4",
    "formatting.mp4",
    "cat video.mp4",
    "find out.mp4",
    "my holiday video.mp4",
    "settings.mp4",
])
def test_ordinary_words_are_not_mistaken_for_commands(name):
    """The command-word filter must not eat ordinary video names."""
    result = _safe_filename(name)
    _assert_safe(result)
    stem = result.rsplit(".", 1)[0]
    assert stem.lower() == name.rsplit(".", 1)[0].lower(), (
        f"{name!r} was altered into {result!r}")


# --- null bytes and control characters ------------------------------------

def test_a_null_byte_is_removed():
    result = _safe_filename("evil\x00name.mp4")
    _assert_safe(result)
    assert "\x00" not in result


def test_a_null_byte_before_the_extension_is_removed():
    result = _safe_filename("evil.mp4\x00")
    _assert_safe(result)
    assert "\x00" not in result


def test_control_characters_are_removed():
    result = _safe_filename("evil\r\nname\t\x1b.mp4")
    _assert_safe(result)
    assert "\r" not in result
    assert "\n" not in result
    assert "\t" not in result
    assert "\x1b" not in result


# --- unicode ---------------------------------------------------------------

def test_a_unicode_filename_survives_intact():
    result = _safe_filename("vidéo-de-mariage.mp4")
    _assert_safe(result)
    assert "vidéo" in result
    assert result.endswith(".mp4")


def test_a_unicode_filename_with_cjk_characters_survives():
    result = _safe_filename("测试视频.mp4")
    _assert_safe(result)
    assert result.endswith(".mp4")
    assert "测试" in result


def test_a_unicode_filename_with_an_emoji_survives():
    result = _safe_filename("clip-🎬-final.mp4")
    _assert_safe(result)
    assert result.endswith(".mp4")


# --- empty and missing names ----------------------------------------------

def test_an_empty_filename_gets_the_default():
    result = _safe_filename("")
    _assert_safe(result)
    assert result == "upload.mp4"


def test_a_none_filename_gets_the_default():
    result = _safe_filename(None)
    _assert_safe(result)
    assert result == "upload.mp4"


def test_a_whitespace_filename_gets_the_default():
    result = _safe_filename("   ")
    _assert_safe(result)
    assert result.startswith("upload")


def test_a_filename_that_is_only_dots_gets_the_default():
    result = _safe_filename("....")
    _assert_safe(result)
    assert result.startswith("upload")


def test_a_filename_that_is_only_a_separator_gets_the_default():
    result = _safe_filename("///")
    _assert_safe(result)
    assert result.startswith("upload")


# --- Windows reserved names -----------------------------------------------

@pytest.mark.parametrize("name", [
    "CON.mp4", "con.mp4", "PRN.mp4", "AUX.mp4", "NUL.mp4",
    "COM1.mp4", "com9.mp4", "LPT1.mp4", "lpt9.mp4",
])
def test_windows_reserved_names_are_renamed(name):
    result = _safe_filename(name)
    _assert_safe(result)
    stem = result.rsplit(".", 1)[0].lower()
    assert stem not in {
        "con", "prn", "aux", "nul",
        "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8",
        "com9", "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7",
        "lpt8", "lpt9",
    }
    assert result.endswith(".mp4")


def test_a_reserved_name_keeps_its_extension():
    assert _safe_filename("CON.mp4").endswith(".mp4")


# --- length ----------------------------------------------------------------

def test_a_very_long_filename_is_truncated():
    result = _safe_filename("a" * 5000 + ".mp4")
    _assert_safe(result)
    assert len(result) <= 140


def test_a_very_long_name_still_keeps_its_extension():
    result = _safe_filename("a" * 5000 + ".mp4")
    assert result.endswith(".mp4")


def test_a_very_long_traversal_name_is_truncated_and_safe():
    result = _safe_filename("../" * 500 + "evil.mp4")
    _assert_safe(result)
    assert len(result) <= 140


# --- ordinary names --------------------------------------------------------

def test_an_ordinary_name_is_left_alone():
    assert _safe_filename("holiday-video.mp4") == "holiday-video.mp4"


def test_spaces_in_a_name_are_kept():
    result = _safe_filename("my holiday video.mp4")
    _assert_safe(result)
    assert "my holiday video" in result


def test_the_extension_is_lower_cased():
    assert _safe_filename("Video.MP4").endswith(".mp4")


def test_a_name_with_no_extension_has_none_added():
    result = _safe_filename("videofile")
    _assert_safe(result)
    assert "." not in result


def test_a_leading_dot_is_not_treated_as_a_hidden_file():
    result = _safe_filename(".hidden.mp4")
    _assert_safe(result)
    assert not result.startswith(".")
