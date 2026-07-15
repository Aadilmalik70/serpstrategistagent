from app.services.rendered_crawler import AdaptivePacer, detect_bot_block, needs_javascript_render


def test_javascript_shell_detection_is_bounded_to_likely_shells() -> None:
    shell = "<html><body><div id='__next'></div><script src='/app.js'></script></body></html>"
    content = "<html><body><main>" + " useful content" * 120 + "</main><script src='/app.js'></script></body></html>"

    assert needs_javascript_render(shell, word_count=0) is True
    assert needs_javascript_render(content, word_count=240) is False


def test_bot_block_detection_requires_challenge_evidence() -> None:
    cloudflare = detect_bot_block(
        403,
        {"CF-Ray": "abc"},
        "<title>Attention Required! | Cloudflare</title>",
    )
    ordinary_forbidden = detect_bot_block(403, {}, "This page is private")

    assert cloudflare.detected is True
    assert cloudflare.provider == "cloudflare"
    assert ordinary_forbidden.detected is False


def test_adaptive_pacer_slows_and_recovers_without_exceeding_limits() -> None:
    pacer = AdaptivePacer(base_delay_seconds=0.1, max_delay_seconds=2.0)
    pacer.record(status_code=429, bot_blocked=True)
    pacer.record(status_code=503, bot_blocked=False)

    assert pacer.throttle_events == 2
    assert pacer.delay_seconds <= 2.0
    assert pacer.concurrency(8) == 2

    for _ in range(10):
        pacer.record(status_code=200, bot_blocked=False)
    assert pacer.delay_seconds >= 0.1
    assert pacer.concurrency(8) > 2
