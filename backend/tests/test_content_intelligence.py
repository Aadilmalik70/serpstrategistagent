from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

from app.services.content_intelligence_service import build_semantic_graph, score_content_page


def _page(path: str, title: str, *, linked_from=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        path=path,
        title=title,
        h1=title,
        meta_description=f"Learn about {title}",
        word_count=500,
        content_hash=None,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        meta={
            "h2": [f"{title} guide", "Implementation details"],
            "h3": [],
            "linked_from": linked_from or [],
            "internal_links": [],
        },
    )


def test_information_gain_and_decay_scoring_is_evidence_backed():
    page = _page("/guides/semantic-seo", "Semantic SEO")
    terms = {
        page.id: ["semantic", "seo", "knowledge", "graph", "entities"],
    }
    scored = score_content_page(
        page,
        all_terms=terms,
        query_terms_by_page={page.id: ["semantic", "knowledge", "graph"]},
        query_term_pages={"semantic": {page.id}, "knowledge": {page.id}, "graph": {page.id}},
        current_metrics={"clicks": 5, "impressions": 40, "ctr": 0.125, "position": 8},
        previous_metrics={"clicks": 12, "impressions": 60, "ctr": 0.2, "position": 6},
        today=datetime(2026, 7, 28, tzinfo=timezone.utc).date(),
    )
    assert scored["decay_score"] >= 50
    assert scored["information_gain_score"] > 0
    assert scored["metrics"]["information_gain_method"] == "deterministic_lexical_proxy"
    assert any(item["signal"] == "search_decay" for item in scored["evidence"])


def test_semantic_graph_contains_page_topic_and_related_edges():
    first = _page("/guides/semantic-seo", "Semantic SEO")
    second = _page("/guides/topic-clusters", "Topic Clusters")
    scored = {
        first.id: {"topics": ["semantic", "seo", "entities"]},
        second.id: {"topics": ["seo", "entities", "clusters"]},
    }
    graph = build_semantic_graph([first, second], scored)
    assert any(node["type"] == "topic" for node in graph["nodes"])
    assert any(edge["type"] == "related" for edge in graph["edges"])
    assert graph["topic_clusters"]


def test_orphan_candidate_inputs_are_safe_for_missing_link_metadata():
    from app.services.content_intelligence_service import _recommendation_candidates

    source = _page("/guides/source", "SEO Source", linked_from=["/"])
    target = _page("/guides/target", "SEO Target")
    target.meta["internal_links"] = []
    scored = {
        source.id: {"topics": ["seo", "source"]},
        target.id: {"topics": ["seo", "target"]},
    }
    recommendations = _recommendation_candidates([source, target], scored)
    assert recommendations
    assert recommendations[0]["target_page_id"] == target.id
