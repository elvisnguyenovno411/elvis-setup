import pytest

from elvis_setup.config import Settings


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("OWNER_USER_ID", "111111111111111111")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    settings = Settings.from_env()

    assert settings.token == "test-token"
    assert settings.owner_user_id == 111111111111111111
    assert settings.log_level == "DEBUG"


def test_settings_reject_invalid_owner_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("OWNER_USER_ID", "not-a-number")

    with pytest.raises(RuntimeError, match="dãy số Discord"):
        Settings.from_env()
