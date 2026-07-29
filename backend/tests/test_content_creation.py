import asyncio
from types import SimpleNamespace

from app.services.content_creation_service import (
    _next_draft_version,
    _opportunity_payload,
    _serialize_internal_link_targets,
)


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


class _ExpiredOpportunity:
    id = "opportunity-id"

    @property
    def updated_at(self):
        raise AssertionError("the expired ORM timestamp must not be accessed")


class _ProjectionResult:
    def mappings(self):
        return self

    def all(self):
        return [{
            "id": "opportunity-id",
            "site_id": "site-id",
            "page_id": None,
            "opportunity_type": "refresh",
            "status": "open",
            "title": "Refresh the technical SEO guide",
            "summary": "Search decay requires a refresh.",
            "target_query": "technical SEO guide",
            "target_path": "/guides/technical-seo",
            "priority_score": 80,
            "confidence_score": 75,
            "effort_score": 45,
            "evidence": [{"signal": "content_intelligence"}],
            "created_at": "2026-07-29T00:00:00+00:00",
            "updated_at": "2026-07-29T00:00:00+00:00",
        }]


class _ProjectionDB:
    async def execute(self, statement):
        del statement
        return _ProjectionResult()


def test_opportunity_payload_uses_explicit_columns_for_expired_orm_rows():
    result = asyncio.run(
        _opportunity_payload(_ProjectionDB(), [_ExpiredOpportunity()])
    )

    assert result[0]["updated_at"] == "2026-07-29T00:00:00+00:00"
    assert result[0]["target_path"] == "/guides/technical-seo"


def test_null_draft_version_is_normalized_before_incrementing():
    assert _next_draft_version(None, is_new_version=True, has_persisted_id=False) == 1
    assert _next_draft_version(None, is_new_version=True, has_persisted_id=True) == 1
    assert _next_draft_version(1, is_new_version=True, has_persisted_id=True) == 2
    assert _next_draft_version(None, is_new_version=False, has_persisted_id=True) == 1
