import asyncio
import httpx


async def main():
    async with httpx.AsyncClient(timeout=60) as c:
        print("Sending: 'What are my top SEO issues?'")
        r = await c.post(
            "http://localhost:8000/chat/b689d83e-ac0f-47aa-b786-716c2837788f",
            json={"message": "What are my top SEO issues?"},
        )
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"\nAgent response:\n{data['response'][:1000]}")
        else:
            print(f"Error: {r.text}")


asyncio.run(main())
