import pytest

from elvis_setup.views import parse_preserved_role_ids


def test_zero_means_preserve_no_extra_roles() -> None:
    assert parse_preserved_role_ids("0") == set()


def test_parses_comma_separated_ids_and_role_mentions() -> None:
    assert parse_preserved_role_ids("123, 456, <@&789>, 123") == {123, 456, 789}


@pytest.mark.parametrize("raw_value", ["", "abc", "123, nope", "-1", "0, 123", "<@123>"])
def test_rejects_invalid_role_ids(raw_value: str) -> None:
    with pytest.raises(ValueError):
        parse_preserved_role_ids(raw_value)
