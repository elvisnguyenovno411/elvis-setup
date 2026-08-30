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


def test_channel_access_values_are_valid() -> None:
    templates = TemplateLoader(ROOT / "templates").load_all()
    valid = {"member", "member_read_only", "admin"}

    for template in templates.values():
        for category in template.categories:
            for channel in category.channels:
                assert channel.access in valid


def test_template_colors_are_rgb_values() -> None:
    templates = TemplateLoader(ROOT / "templates").load_all()
    assert all(0 <= template.color <= 0xFFFFFF for template in templates.values())
