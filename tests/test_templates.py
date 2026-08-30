from pathlib import Path

import pytest

from elvis_setup.template_loader import TemplateLoader

ROOT = Path(__file__).resolve().parents[1]


def test_loads_all_public_templates() -> None:
    templates = TemplateLoader(ROOT / "templates").load_all()

    assert len(templates) == 13
    assert "beauty" in templates
    assert templates["beauty"].name == "Làm đẹp & Makeup"


@pytest.mark.parametrize("template_key", ["gaming", "study", "beauty", "support"])
def test_every_template_inherits_required_core(template_key: str) -> None:
    template = TemplateLoader(ROOT / "templates").load_all()[template_key]
    keys = {category.key for category in template.categories}

    assert {"thong-tin", "quan-tri"}.issubset(keys)
    assert len(template.categories) >= 5


def test_each_topic_adds_one_category_with_text_and_voice_rooms() -> None:
    loader = TemplateLoader(ROOT / "templates")
    base = loader.load_base()
    base_keys = {category.key for category in base.categories}

    for template in loader.load_all().values():
        topic_categories = [
            category for category in template.categories if category.key not in base_keys
        ]
        assert len(topic_categories) == 1
        assert len(topic_categories[0].channels) == 2
        assert {channel.kind for channel in topic_categories[0].channels} == {"text", "voice"}


def test_channel_access_values_are_valid() -> None:
    templates = TemplateLoader(ROOT / "templates").load_all()
    valid = {"member", "member_read_only", "member_role_picker", "admin"}

    for template in templates.values():
        for category in template.categories:
            for channel in category.channels:
                assert channel.access in valid


def test_base_contains_role_picker_channel() -> None:
    base = TemplateLoader(ROOT / "templates").load_base()
    channels = [channel for category in base.categories for channel in category.channels]
    role_picker = next(channel for channel in channels if channel.name == "🎭・chon-role")

    assert role_picker.access == "member_role_picker"
    assert role_picker.kind == "text"


def test_template_colors_are_rgb_values() -> None:
    templates = TemplateLoader(ROOT / "templates").load_all()
    assert all(0 <= template.color <= 0xFFFFFF for template in templates.values())
