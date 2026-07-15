from __future__ import annotations

import asyncio
import multiprocessing
import os
import re
import resource
import signal
import time
from dataclasses import asdict, dataclass
from typing import Awaitable, Callable
from urllib.parse import urlsplit


WAF_BODY_SIGNATURES = (
    "attention required! | cloudflare",
    "cf-chl-",
    "checking your browser",
    "cloudflare ray id",
    "incapsula incident id",
    "access denied | akamai",
    "request unsuccessful. incapsula",
    "datadome",
    "perimeterx",
    "px-captcha",
)
WAF_HEADER_NAMES = {
    "cf-ray": "cloudflare",
    "x-sucuri-id": "sucuri",
    "x-iinfo": "imperva",
    "x-akamai-transformed": "akamai",
}
JS_ROOT_MARKERS = (
    'id="__next"',
    "id='__next'",
    'id="root"',
    "id='root'",
    'id="app"',
    "id='app'",
    "data-reactroot",
    "ng-version=",
)


async def verify_renderer_runtime() -> None:
    """Fail startup when the sandboxed, resource-limited renderer cannot run."""
    payload = {
        "url": "https://renderer.invalid/",
        "user_agent": "SERPStrategistsRendererCheck/1.0",
        "timeout_seconds": 5.0,
        "mobile": False,
        "max_html_bytes": 100_000,
        "source_html": "<!doctype html><html><body>renderer check</body></html>",
        "max_requests": 1,
        "pinned_address": "192.0.2.1",
    }
    await asyncio.to_thread(_run_renderer_process, payload, 10.0)


@dataclass(frozen=True)
class BotBlock:
    detected: bool
    provider: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RenderedPage:
    url: str
    status_code: int
    headers: dict[str, str]
    html: str
    response_time_ms: int
    device: str


def detect_bot_block(status_code: int, headers: dict[str, str], body: bytes | str) -> BotBlock:
    normalized_headers = {key.lower(): value for key, value in headers.items()}
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    lowered = text[:250_000].lower()
    provider = next(
        (name for header, name in WAF_HEADER_NAMES.items() if header in normalized_headers),
        None,
    )
    signature = next((value for value in WAF_BODY_SIGNATURES if value in lowered), None)
    challenge_status = status_code in {401, 403, 409, 429, 503}
    strong_success_signature = any(
        value in lowered
        for value in ("cf-chl-", "checking your browser", "px-captcha", "request unsuccessful. incapsula")
    )
    if (challenge_status and bool(signature or provider)) or (status_code == 200 and strong_success_signature):
        return BotBlock(
            detected=True,
            provider=provider or "unknown",
            reason=f"HTTP {status_code}: automated-request challenge detected",
        )
    return BotBlock(detected=False)


def needs_javascript_render(html: str, *, word_count: int) -> bool:
    lowered = html[:500_000].lower()
    has_root = any(marker in lowered for marker in JS_ROOT_MARKERS)
    script_count = len(re.findall(r"<script\b", lowered))
    noscript_warning = "enable javascript" in lowered or "requires javascript" in lowered
    return bool(noscript_warning or (has_root and script_count >= 1 and word_count < 80))


class AdaptivePacer:
    def __init__(self, *, base_delay_seconds: float, max_delay_seconds: float) -> None:
        self.base_delay_seconds = max(0.0, base_delay_seconds)
        self.max_delay_seconds = max(self.base_delay_seconds, max_delay_seconds)
        self.delay_seconds = self.base_delay_seconds
        self.concurrency_scale = 1.0
        self.throttle_events = 0

    def record(self, *, status_code: int, bot_blocked: bool) -> None:
        if bot_blocked or status_code in {429, 503}:
            self.throttle_events += 1
            seed = max(self.delay_seconds, self.base_delay_seconds, 0.25)
            self.delay_seconds = min(self.max_delay_seconds, seed * 2)
            self.concurrency_scale = max(0.25, self.concurrency_scale / 2)
            return
        if status_code < 400:
            self.delay_seconds = max(self.base_delay_seconds, self.delay_seconds * 0.8)
            self.concurrency_scale = min(1.0, self.concurrency_scale + 0.1)

    def concurrency(self, configured: int) -> int:
        return max(1, int(configured * self.concurrency_scale))

    def respect_retry_after(self, value: str | None) -> None:
        if not value:
            return
        try:
            delay = float(value.strip())
        except ValueError:
            return
        self.delay_seconds = min(self.max_delay_seconds, max(self.delay_seconds, max(0.0, delay)))


async def _render_in_process(
    url: str,
    *,
    user_agent: str,
    timeout_seconds: float,
    mobile: bool,
    max_html_bytes: int,
    source_html: str,
    pinned_address: str,
    max_requests: int = 30,
) -> RenderedPage:
    """Render already-bounded HTML with a sandboxed, same-origin browser boundary."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - production image installs Playwright.
        raise RuntimeError("JavaScript rendering is unavailable") from exc

    target = urlsplit(url)
    target_host = (target.hostname or "").lower().rstrip(".")
    target_port = target.port or (443 if target.scheme == "https" else 80)
    if not target_host:
        raise RuntimeError("Rendered crawler target is invalid")
    source_bytes = source_html.encode("utf-8")
    if len(source_bytes) > max_html_bytes:
        raise RuntimeError("Rendered crawler source exceeds the configured byte limit")
    resolver_address = f"[{pinned_address}]" if ":" in pinned_address else pinned_address

    started = time.perf_counter()
    timeout_ms = max(1_000, int(timeout_seconds * 1_000))
    viewport = {"width": 390, "height": 844} if mobile else {"width": 1440, "height": 1000}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            chromium_sandbox=True,
            args=[
                "--disable-dev-shm-usage",
                "--renderer-process-limit=1",
                "--js-flags=--max-old-space-size=128",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                f"--host-resolver-rules=MAP {target_host} {resolver_address},EXCLUDE localhost",
            ],
        )
        try:
            context = await browser.new_context(
                user_agent=user_agent,
                viewport=viewport,
                is_mobile=mobile,
                has_touch=mobile,
                service_workers="block",
                accept_downloads=False,
            )
            request_count = 0
            served_document = False
            subresource_bytes = 0

            async def guard_request(route) -> None:
                nonlocal request_count, served_document, subresource_bytes
                request_count += 1
                if request_count > max_requests:
                    await route.abort()
                    return
                request_url = route.request.url
                parsed = urlsplit(request_url)
                if parsed.scheme not in {"http", "https"}:
                    await route.abort()
                    return
                request_host = (parsed.hostname or "").lower().rstrip(".")
                if request_host != target_host:
                    await route.abort()
                    return
                request_port = parsed.port or (443 if parsed.scheme == "https" else 80)
                if request_port != target_port:
                    await route.abort()
                    return
                if route.request.resource_type == "document":
                    if served_document:
                        await route.abort()
                        return
                    served_document = True
                    await route.fulfill(
                        status=200,
                        headers={
                            "content-type": "text/html; charset=utf-8",
                            "content-security-policy": (
                                "default-src 'none'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                                "style-src 'self' 'unsafe-inline'; connect-src 'none'; img-src 'none'; "
                                "font-src 'none'; media-src 'none'; frame-src 'none'; object-src 'none'; "
                                "base-uri 'none'; form-action 'none'"
                            ),
                        },
                        body=source_html,
                    )
                    return
                if route.request.resource_type not in {"script", "stylesheet"}:
                    await route.abort()
                    return
                fetched = await route.fetch(timeout=timeout_ms, max_redirects=0)
                response_url = urlsplit(fetched.url)
                response_host = (response_url.hostname or "").lower().rstrip(".")
                response_port = response_url.port or (443 if response_url.scheme == "https" else 80)
                content_length = fetched.headers.get("content-length")
                if (
                    response_host != target_host
                    or response_port != target_port
                    or not content_length
                    or not content_length.isdigit()
                    or int(content_length) > max_html_bytes
                    or subresource_bytes + int(content_length) > max_html_bytes * 3
                ):
                    await route.abort()
                    return
                subresource_bytes += int(content_length)
                await route.fulfill(response=fetched)

            async def block_websocket(websocket_route) -> None:
                await websocket_route.close(code=1008, reason="WebSockets are disabled for crawling")

            await context.route_web_socket("**/*", block_websocket)
            await context.route("**/*", guard_request)
            page = await context.new_page()
            response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 5_000))
            except Exception:
                pass
            final_url = page.url
            final_host = (urlsplit(final_url).hostname or "").lower().rstrip(".")
            if final_host != target_host:
                raise RuntimeError("Rendered page redirected outside the configured site")
            dom_nodes = await page.evaluate("document.getElementsByTagName('*').length")
            if int(dom_nodes) > 50_000:
                raise RuntimeError("Rendered DOM exceeds the configured node limit")
            dom_character_count = await page.evaluate(
                """(limit) => {
                    let total = 0;
                    const walker = document.createTreeWalker(document, NodeFilter.SHOW_TEXT);
                    while (walker.nextNode()) {
                        total += (walker.currentNode.nodeValue || '').length;
                        if (total > limit) return total;
                    }
                    const nodes = document.getElementsByTagName('*');
                    for (const node of nodes) {
                        for (const attr of node.attributes || []) total += attr.value.length;
                        if (total > limit) return total;
                    }
                    return total;
                }""",
                max_html_bytes * 2,
            )
            if int(dom_character_count) > max_html_bytes * 2:
                raise RuntimeError("Rendered DOM exceeds the configured content limit")
            html = await page.content()
            encoded = html.encode("utf-8")
            if len(encoded) > max_html_bytes:
                html = encoded[:max_html_bytes].decode("utf-8", errors="ignore")
            headers = await response.all_headers() if response else {}
            status_code = response.status if response else 0
            await context.close()
        finally:
            await browser.close()
    return RenderedPage(
        url=final_url,
        status_code=status_code,
        headers={key.lower(): value for key, value in headers.items()},
        html=html,
        response_time_ms=int((time.perf_counter() - started) * 1_000),
        device="mobile" if mobile else "desktop",
    )


def _renderer_worker(payload: dict, send_connection) -> None:
    try:
        os.setsid()
        memory_limit = max(2 * 1024 * 1024 * 1024, int(payload["max_html_bytes"]) * 128)
        cpu_limit = max(5, int(float(payload["timeout_seconds"])) + 5)
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit + 1))
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        allowed_environment = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "HOME",
                "LANG",
                "LC_ALL",
                "LD_LIBRARY_PATH",
                "PATH",
                "PLAYWRIGHT_BROWSERS_PATH",
                "TMPDIR",
                "TZ",
            }
        }
        os.environ.clear()
        os.environ.update(allowed_environment)
        rendered = asyncio.run(_render_in_process(**payload))
        send_connection.send(("ok", asdict(rendered)))
    except BaseException as exc:
        send_connection.send(("error", f"{type(exc).__name__}: {str(exc)[:1000]}"))
    finally:
        send_connection.close()


def _process_tree_usage(root_pid: int) -> tuple[int, int]:
    processes: dict[int, tuple[int, int]] = {}
    try:
        entries = [entry for entry in os.listdir("/proc") if entry.isdigit()]
    except OSError:
        return 0, 0
    for entry in entries:
        try:
            status: dict[str, str] = {}
            with open(f"/proc/{entry}/status", encoding="utf-8") as handle:
                for line in handle:
                    key, _, value = line.partition(":")
                    if key in {"PPid", "VmRSS"}:
                        status[key] = value.strip()
            parent_pid = int(status.get("PPid", "0").split()[0])
            resident_kib = int(status.get("VmRSS", "0 kB").split()[0])
            processes[int(entry)] = (parent_pid, resident_kib * 1024)
        except (OSError, ValueError):
            continue
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, (parent_pid, _) in processes.items():
            if parent_pid in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    return sum(processes.get(pid, (0, 0))[1] for pid in descendants), len(descendants)


def _kill_renderer_process(process) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        if process.is_alive():
            process.kill()
    process.join(timeout=2)


def _run_renderer_process(payload: dict, timeout_seconds: float) -> dict:
    context = multiprocessing.get_context("spawn")
    receive_connection, send_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_renderer_worker,
        args=(payload, send_connection),
        daemon=True,
    )
    process.start()
    send_connection.close()
    try:
        deadline = time.monotonic() + timeout_seconds
        while not receive_connection.poll(0.1):
            if not process.is_alive():
                process.join(timeout=1)
                raise RuntimeError("Isolated renderer exited without a result")
            resident_bytes, process_count = _process_tree_usage(process.pid)
            if resident_bytes > 768 * 1024 * 1024 or process_count > 32:
                _kill_renderer_process(process)
                raise RuntimeError("Rendered crawler exceeded its process-group resource limit")
            if time.monotonic() >= deadline:
                _kill_renderer_process(process)
                raise RuntimeError("Rendered crawler exceeded its isolated wall-clock limit")
        status, value = receive_connection.recv()
        process.join(timeout=2)
        if process.is_alive():
            _kill_renderer_process(process)
        if status != "ok":
            raise RuntimeError(str(value))
        return value
    finally:
        receive_connection.close()
        if process.is_alive():
            _kill_renderer_process(process)


async def render_url(
    url: str,
    *,
    user_agent: str,
    timeout_seconds: float,
    mobile: bool,
    validate_url: Callable[[str], Awaitable[object]],
    max_html_bytes: int,
    source_html: str,
    max_requests: int = 30,
) -> RenderedPage:
    """Render untrusted HTML in a secret-scrubbed, resource-limited process group."""
    target = urlsplit(url)
    if not target.hostname:
        raise RuntimeError("Rendered crawler target is invalid")
    source_bytes = source_html.encode("utf-8")
    if len(source_bytes) > max_html_bytes:
        raise RuntimeError("Rendered crawler source exceeds the configured byte limit")
    pinned_address = str(await validate_url(url))
    payload = {
        "url": url,
        "user_agent": user_agent,
        "timeout_seconds": timeout_seconds,
        "mobile": mobile,
        "max_html_bytes": max_html_bytes,
        "source_html": source_html,
        "max_requests": max_requests,
        "pinned_address": pinned_address,
    }
    value = await asyncio.to_thread(
        _run_renderer_process,
        payload,
        max(5.0, timeout_seconds + 5.0),
    )
    final_url = str(value["url"])
    await validate_url(final_url)
    return RenderedPage(**value)
