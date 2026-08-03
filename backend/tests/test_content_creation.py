import asyncio
from types import SimpleNamespace

from app.services.content_creation_service import (
    _classify_search_opportunity,
    _next_draft_version,
    _opportunity_payload,
    _serialize_internal_link_targets,
)


def _search_opportunity(**overrides):
    values = {
        "opportunity_type": "low_ctr",
        "page_url": "https://example.com/blog/seo-guide?utm_source=gsc",
        "metrics": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_search_opportunity_with_existing_url_is_refresh_not_new_page():
    page = SimpleNamespace(id="page-id", path="/blog/seo-guide")

    result = _classify_search_opportunity(
        _search_opportunity(),
        site_domain="example.com",
        pages_by_path={"/blog/seo-guide": page},
    )

    assert result["type"] == "refresh_existing_page"
    assert result["page_id"] == "page-id"
    assert result["path"] == "/blog/seo-guide"


def test_search_url_is_refresh_even_before_the_page_is_crawled():
    result = _classify_search_opportunity(
        _search_opportunity(),
        site_domain="example.com",
        pages_by_path={},
    )

    assert result["type"] == "refresh_existing_page"
    assert result["page_id"] is None


def test_indexing_diagnostic_is_technical_and_not_content_creation():
    result = _classify_search_opportunity(
        _search_opportunity(
            opportunity_type="not_indexed",
            page_url="https://example.com/blog/seo-guide",
        ),
        site_domain="example.com",
        pages_by_path={},
    )

    assert result["type"] == "technical_fix"
    assert result["path"] == "/blog/seo-guide"


def test_legal_and_admin_paths_are_excluded_from_content_opportunities():
    for path in ("/privacy", "/terms-of-service", "/cookies", "/admin/blog"):
        result = _classify_search_opportunity(
            _search_opportunity(page_url=f"https://example.com{path}"),
            site_domain="example.com",
            pages_by_path={path: SimpleNamespace(id="system-page", path=path)},
        )

        assert result["type"] == "excluded"


def test_search_opportunity_without_target_url_can_be_a_new_page():
    result = _classify_search_opportunity(
        _search_opportunity(page_url=None, metrics={}),
        site_domain="example.com",
        pages_by_path={},
    )

    assert result["type"] == "new_page"


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
