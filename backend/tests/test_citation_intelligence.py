from app.services.citation_intelligence_service import aggregate_scan_results, analyze_answer, gap_priority


def test_answer_analysis_is_provider_neutral_and_evidence_backed():
    result = analyze_answer(
        answer="SERP Strategists is a useful option. Ahrefs is also mentioned.",
        brand_terms=["SERP Strategists"],
        competitor_terms=["Ahrefs", "Semrush"],
        cited_urls=["https://SERPStrategists.com/guide", "not-a-url"],
    )

    assert result["brand_mentioned"] is True
    assert result["cited_urls"] == ["https://serpstrategists.com/guide"]
    assert result["competitor_mentions"] == ["Ahrefs"]
    assert result["gap_type"] is None
    assert {item["signal"] for item in result["evidence"]} == {
        "brand_mention",
        "citations",
        "competitor_mentions",
    }


def test_missing_brand_and_missing_citation_are_distinct_gaps():
    no_brand = analyze_answer(
        answer="Use Ahrefs for this workflow.",
        brand_terms=["SERP Strategists"],
        competitor_terms=["Ahrefs"],
        cited_urls=[],
    )
    no_citation = analyze_answer(
        answer="SERP Strategists can help with this workflow.",
        brand_terms=["SERP Strategists"],
        competitor_terms=[],
        cited_urls=[],
    )
    brand_gap = analyze_answer(
        answer="Use this workflow for technical SEO.",
        brand_terms=["SERP Strategists"],
        competitor_terms=[],
        cited_urls=[],
    )

    assert no_brand["gap_type"] == "competitor_gap"
    assert no_citation["gap_type"] == "citation_gap"
    assert brand_gap["gap_type"] == "brand_mention_gap"
    assert gap_priority("brand_mention_gap")[0] > gap_priority("citation_gap")[0]


def test_scan_aggregation_calculates_visibility_and_competitor_metrics():
    summary = aggregate_scan_results(
        [
            {"brand_mentioned": True, "cited_urls": ["https://example.com"], "competitor_mentions": ["Ahrefs"]},
            {"brand_mentioned": False, "cited_urls": [], "competitor_mentions": ["Ahrefs"]},
        ],
        ["Ahrefs", "Semrush"],
    )

    assert summary["mention_rate"] == 0.5
    assert summary["citation_rate"] == 0.5
    assert summary["visibility_score"] == 50
    assert summary["competitor_metrics"] == {"Ahrefs": 2, "Semrush": 0}
