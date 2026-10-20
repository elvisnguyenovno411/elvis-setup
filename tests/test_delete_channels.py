from types import SimpleNamespace

import pytest

from elvis_setup.views import expand_preserved_channel_ids, parse_preserved_channel_ids


def test_zero_means_preserve_nothing() -> None:
    assert parse_preserved_channel_ids("0") == set()


def test_parses_comma_separated_ids_and_channel_mentions() -> None:
    assert parse_preserved_channel_ids("123, 456, <#789>, 123") == {123, 456, 789}


@pytest.mark.parametrize("raw_value", ["", "abc", "123, nope", "-1", "0, 123"])
def test_rejects_invalid_channel_ids(raw_value: str) -> None:
    with pytest.raises(ValueError):
        parse_preserved_channel_ids(raw_value)


def test_preserving_channel_also_preserves_parent_category() -> None:
    child = SimpleNamespace(id=11, category_id=10)
    category = SimpleNamespace(id=10, category_id=None, channels=[child])
    other = SimpleNamespace(id=12, category_id=None)
    guild = SimpleNamespace(categories=[category], channels=[category, child, other])

    assert expand_preserved_channel_ids(guild, {11}) == {10, 11}


def test_preserving_category_also_preserves_its_children() -> None:
    child = SimpleNamespace(id=11, category_id=10)
    category = SimpleNamespace(id=10, category_id=None, channels=[child])
    guild = SimpleNamespace(categories=[category], channels=[category, child])

    assert expand_preserved_channel_ids(guild, {10}) == {10, 11}
