import pytest

from elvis_setup.views import parse_role_names


def test_zero_is_a_valid_role_name() -> None:
    assert parse_role_names("0") == ["0"]


def test_parses_comma_separated_role_names() -> None:
    assert parse_role_names(" Thành viên, VIP, Khách ") == ["Thành viên", "VIP", "Khách"]


def test_ignores_empty_items_and_case_insensitive_duplicates() -> None:
    assert parse_role_names("VIP, , vip, Thành viên,") == ["VIP", "Thành viên"]


@pytest.mark.parametrize("raw_value", ["", "   ", ", ,"])
def test_rejects_empty_role_list(raw_value: str) -> None:
    with pytest.raises(ValueError, match="ít nhất một"):
        parse_role_names(raw_value)


def test_rejects_role_name_longer_than_discord_limit() -> None:
    with pytest.raises(ValueError, match="100 ký tự"):
        parse_role_names("a" * 101)


def test_rejects_more_than_fifty_roles() -> None:
    with pytest.raises(ValueError, match="tối đa 50"):
        parse_role_names(",".join(f"Role {index}" for index in range(51)))
