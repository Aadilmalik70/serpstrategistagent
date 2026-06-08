"""List LibreCrawl MCP tools and test crawl export."""
import asyncio
import httpx
import json

MCP_URL = "http://127.0.0.1:5081/mcp"
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


async def mcp_session():
    """Create MCP session, return (client, session_headers)."""
    client = httpx.AsyncClient(timeout=60)
    init = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}
    }
    r = await client.post(MCP_URL, headers=HEADERS, json=init)
    session_id = r.headers.get("mcp-session-id", "")
    sh = {**HEADERS, "Mcp-Session-Id": session_id}
    await client.post(MCP_URL, headers=sh, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    return client, sh


def parse_sse(text):
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    return json.loads(text)


async def main():
    client, sh = await mcp_session()

    # List tools
    r = await client.post(MCP_URL, headers=sh, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    data = parse_sse(r.text)
    tools = data.get("result", {}).get("tools", [])
    print(f"Total MCP tools: {len(tools)}")
    print("\nCrawl/export related tools:")
    for t in tools:
        n = t["name"].lower()
        if any(k in n for k in ["crawl", "list", "export", "load", "sync", "page", "url", "audit"]):
            print(f"  {t['name']}: {t.get('description', '')[:120]}")

    # Try to call list_crawls or export
    print("\n--- Calling librecrawl_list_crawls ---")
    r2 = await client.post(MCP_URL, headers=sh, json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "librecrawl_list_crawls", "arguments": {}}
    })
    result = parse_sse(r2.text)
    content = result.get("result", {}).get("content", [])
    for c in content:
        if "text" in c:
            parsed = json.loads(c["text"])
            print(f"Saved crawls: {json.dumps(parsed, indent=2)[:1000]}")

    # Try export_results for crawl 4 (latest from MCP server logs)
    print("\n--- Calling librecrawl_export_results crawl_id=4 ---")
    r3 = await client.post(MCP_URL, headers=sh, json={
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "librecrawl_export_results", "arguments": {"crawl_id": "4"}}
    })
    result3 = parse_sse(r3.text)
    content3 = result3.get("result", {}).get("content", [])
    for c in content3:
        if "text" in c:
            parsed3 = json.loads(c["text"])
            if isinstance(parsed3, dict):
                print(f"URLs in export: {len(parsed3.get('urls', parsed3.get('results', [])))}")
                # Print keys
                print(f"Export keys: {list(parsed3.keys())}")
                # Print first URL if available
                urls = parsed3.get("urls", parsed3.get("results", []))
                if urls:
                    print(f"Sample URL: {json.dumps(urls[0], indent=2)[:300]}")
            elif isinstance(parsed3, list):
                print(f"URLs in export: {len(parsed3)}")
                if parsed3:
                    print(f"Sample: {json.dumps(parsed3[0], indent=2)[:300]}")

    await client.aclose()


asyncio.run(main())
