"""Get crawl #5 data from LibreCrawl to see page details."""
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
    
    # Initialize session
    init = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}
    }
    r = await client.post(MCP_URL, headers=HEADERS, json=init)
    session_id = r.headers.get("mcp-session-id", "")
    sh = {**HEADERS, "Mcp-Session-Id": session_id}
    await client.post(MCP_URL, headers=sh, json={"jsonrpc": "2.0", "method": "notifications/initialized"})

    # Export crawl 5
    print("--- Export crawl 5 ---")
    r2 = await client.post(MCP_URL, headers=sh, json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "librecrawl_export_results", "arguments": {"crawl_id": "5"}}
    })
    result = parse_sse(r2.text)
    content = result.get("result", {}).get("content", [])
    for c in content:
        if "text" in c:
            parsed = json.loads(c["text"])
            if isinstance(parsed, dict):
                print(f"Keys: {list(parsed.keys())}")
                pages = parsed.get("pages", parsed.get("results", parsed.get("urls", [])))
                print(f"Pages count: {len(pages)}")
                total = parsed.get("total", {})
                if total:
                    print(f"Total: {json.dumps(total, indent=2)[:300]}")
                if pages and len(pages) > 0:
                    print(f"\nSample page keys: {list(pages[0].keys())}")
                    print(f"Sample page: {json.dumps(pages[0], indent=2)[:500]}")
                    print(f"\n--- All URLs ---")
                    for p in pages[:20]:
                        url = p.get("url", p.get("path", "?"))
                        title = p.get("title", "")[:50]
                        status = p.get("status_code", p.get("status", "?"))
                        print(f"  [{status}] {url} - {title}")
                    if len(pages) > 20:
                        print(f"  ... and {len(pages) - 20} more")

    await client.aclose()


asyncio.run(main())
