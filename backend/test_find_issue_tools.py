"""Get full issues from LibreCrawl via generate_report or export_results."""
import asyncio
import httpx
import json

MCP_URL = "http://127.0.0.1:5081/mcp"
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def parse_sse(text):
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    return json.loads(text)


async def main():
    client = httpx.AsyncClient(timeout=120)
    init = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "1.0"}}
    }
    r = await client.post(MCP_URL, headers=HEADERS, json=init)
    sid = r.headers.get("mcp-session-id", "")
    sh = {**HEADERS, "Mcp-Session-Id": sid}
    await client.post(MCP_URL, headers=sh, json={"jsonrpc": "2.0", "method": "notifications/initialized"})

    # First: check export_results structure (keys of first page)
    print("=== export_results for crawl 7 ===")
    r2 = await client.post(MCP_URL, headers=sh, json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "librecrawl_export_results", "arguments": {"crawl_id": "7"}}
    })
    data = parse_sse(r2.text)
    content = data.get("result", {}).get("content", [])
    for c in content:
        if "text" in c:
            parsed = json.loads(c["text"])
            # Show top-level keys
            print(f"Top-level keys: {list(parsed.keys())}")
            pages = parsed.get("pages", [])
            if pages:
                print(f"First page keys: {list(pages[0].keys())}")
                print(f"First page sample: {json.dumps(pages[0], indent=2)[:500]}")
            # Check if there's an issues key
            issues = parsed.get("issues", [])
            if issues:
                print(f"\nIssues count: {len(issues)}")
                print(f"First issue: {json.dumps(issues[0], indent=2)}")
            break

    # Second: try generate_report for crawl 7
    print("\n=== generate_report for crawl 7 ===")
    r3 = await client.post(MCP_URL, headers=sh, json={
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "librecrawl_generate_report", "arguments": {"crawl_id": "7"}}
    })
    data3 = parse_sse(r3.text)
    content3 = data3.get("result", {}).get("content", [])
    for c in content3:
        if "text" in c:
            text = c["text"]
            print(f"Report length: {len(text)} chars")
            # Show first 2000 chars of the report
            print(text[:2000])
            break


asyncio.run(main())
