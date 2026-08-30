import pytest

from elvis_setup.models import ChannelSpec


def test_rejects_unknown_channel_type() -> None:
    with pytest.raises(ValueError, match="Loại kênh"):
        ChannelSpec.from_dict({"name": "invalid", "type": "stage"})


def test_rejects_unknown_access_rule() -> None:
    with pytest.raises(ValueError, match="Quyền truy cập"):
        ChannelSpec.from_dict({"name": "invalid", "access": "everyone"})


def test_defaults_to_member_text_channel() -> None:
    channel = ChannelSpec.from_dict({"name": "chat"})
    assert channel.kind == "text"
    assert channel.access == "member"
