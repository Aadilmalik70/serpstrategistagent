from types import SimpleNamespace

from app.services.content_creation_service import _serialize_internal_link_targets


def test_internal_link_targets_use_the_joined_page_path():
    recommendation = SimpleNamespace(
        anchor_text="technical SEO guide",
        reason="The target page covers a closely related topic.",
    )
    target_page = SimpleNamespace(path="/guides/technical-seo")

    result = _serialize_internal_link_targets([(recommendation, target_page)])

    assert result == [
        {
            "path": "/guides/technical-seo",
            "anchor_text": "technical SEO guide",
            "reason": "The target page covers a closely related topic.",
        }
    ]
