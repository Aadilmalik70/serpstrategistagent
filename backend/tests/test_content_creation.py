from types import SimpleNamespace

from app.services.content_creation_service import _opportunity_dicts, _serialize_internal_link_targets


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


def test_opportunity_payload_is_materialized_from_orm_values():
    opportunity = SimpleNamespace(
        id="opportunity-id",
        site_id="site-id",
        page_id=None,
        opportunity_type="refresh",
        status="open",
        title="Refresh the technical SEO guide",
        summary="Search decay requires a refresh.",
        target_query="technical SEO guide",
        target_path="/guides/technical-seo",
        priority_score=80,
        confidence_score=75,
        effort_score=45,
        evidence=[{"signal": "content_intelligence"}],
        created_at="2026-07-29T00:00:00+00:00",
        updated_at="2026-07-29T00:00:00+00:00",
    )

    result = _opportunity_dicts([opportunity])

    assert result[0]["updated_at"] == "2026-07-29T00:00:00+00:00"
    assert result[0]["target_path"] == "/guides/technical-seo"
