import pytest

from elvis_setup.views import (
    build_game_channel_names,
    parse_game_names,
    stylize_game_name,
)


def test_stylizes_game_name_with_shared_font() -> None:
    assert stylize_game_name("Minecraft") == "𝐌𝐈𝐍𝐄𝐂𝐑𝐀𝐅𝐓"
    assert stylize_game_name("GTA V") == "𝐆𝐓𝐀-𝐕"


def test_builds_category_text_and_voice_names() -> None:
    assert build_game_channel_names("Minecraft") == (
        "🎮┊『𝐌𝐈𝐍𝐄𝐂𝐑𝐀𝐅𝐓』",
        "💬┊『𝐂𝐇𝐀𝐓-𝐌𝐈𝐍𝐄𝐂𝐑𝐀𝐅𝐓』",
        "🔊┊『𝐕𝐎𝐈𝐂𝐄-𝐌𝐈𝐍𝐄𝐂𝐑𝐀𝐅𝐓』",
    )


def test_parses_game_names_and_removes_duplicates() -> None:
    assert parse_game_names("Minecraft, AOV, minecraft, GTA V") == [
        "Minecraft",
        "AOV",
        "GTA V",
    ]


@pytest.mark.parametrize("raw_value", ["", "   ", ", ,"])
def test_rejects_empty_game_list(raw_value: str) -> None:
    with pytest.raises(ValueError, match="ít nhất một"):
        parse_game_names(raw_value)


def test_zero_is_a_valid_game_name() -> None:
    assert parse_game_names("0") == ["0"]


def test_rejects_more_than_twenty_five_games() -> None:
    with pytest.raises(ValueError, match="tối đa 25"):
        parse_game_names(",".join(f"Game {index}" for index in range(26)))


def test_rejects_names_that_exceed_discord_channel_limit() -> None:
    with pytest.raises(ValueError, match="quá dài"):
        parse_game_names("a" * 100)
