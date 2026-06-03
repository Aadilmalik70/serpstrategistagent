"""WordPress REST API integration — update posts/pages with SEO fixes."""
import logging
import httpx

logger = logging.getLogger(__name__)


class WordPressIntegration:
    """Updates WordPress posts/pages via REST API with SEO-optimized content."""

    def __init__(self, site_url: str, username: str, app_password: str):
        """
        Args:
            site_url: WordPress site URL (e.g., https://example.com)
            username: WordPress username
            app_password: WordPress application password
        """
        self.base_url = site_url.rstrip("/")
        self.api_url = f"{self.base_url}/wp-json/wp/v2"
        self.auth = (username, app_password)

    async def update_post(
        self,
        post_id: int,
        updates: dict,
    ) -> dict:
        """Update a WordPress post/page.

        Args:
            post_id: WordPress post ID
            updates: Dict with fields to update:
                - title: New title
                - content: New content (HTML)
                - excerpt: New excerpt/meta description
                - slug: New URL slug
                - meta: Dict of meta fields (yoast_wpseo_title, yoast_wpseo_metadesc, etc.)
        """
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.api_url}/posts/{post_id}",
                auth=self.auth,
                json=updates,
            )
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"Updated WP post {post_id}: {data.get('title', {}).get('rendered', '')}")
                return {
                    "success": True,
                    "post_id": post_id,
                    "url": data.get("link"),
                    "title": data.get("title", {}).get("rendered", ""),
                }
            return {
                "success": False,
                "error": resp.text,
                "status_code": resp.status_code,
            }

    async def update_page(self, page_id: int, updates: dict) -> dict:
        """Update a WordPress page."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.api_url}/pages/{page_id}",
                auth=self.auth,
                json=updates,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "success": True,
                    "page_id": page_id,
                    "url": data.get("link"),
                    "title": data.get("title", {}).get("rendered", ""),
                }
            return {
                "success": False,
                "error": resp.text,
                "status_code": resp.status_code,
            }

    async def get_post_by_slug(self, slug: str) -> dict | None:
        """Find a post by its URL slug."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.api_url}/posts",
                auth=self.auth,
                params={"slug": slug},
            )
            if resp.status_code == 200:
                posts = resp.json()
                if posts:
                    return posts[0]
        return None

    async def get_page_by_slug(self, slug: str) -> dict | None:
        """Find a page by its URL slug."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.api_url}/pages",
                auth=self.auth,
                params={"slug": slug},
            )
            if resp.status_code == 200:
                pages = resp.json()
                if pages:
                    return pages[0]
        return None

    async def update_yoast_meta(
        self,
        post_id: int,
        title: str | None = None,
        description: str | None = None,
        is_page: bool = False,
    ) -> dict:
        """Update Yoast SEO meta fields specifically.

        This targets the Yoast SEO plugin's custom fields.
        """
        meta = {}
        if title:
            meta["yoast_wpseo_title"] = title
        if description:
            meta["yoast_wpseo_metadesc"] = description

        endpoint = "pages" if is_page else "posts"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.api_url}/{endpoint}/{post_id}",
                auth=self.auth,
                json={"meta": meta},
            )
            if resp.status_code == 200:
                return {"success": True, "post_id": post_id, "meta_updated": meta}
            return {"success": False, "error": resp.text}

    async def verify_connection(self) -> dict:
        """Verify WordPress credentials work."""
        async with httpx.AsyncClient(timeout=10) as client:
            # Try to get current user info
            resp = await client.get(
                f"{self.base_url}/wp-json/wp/v2/users/me",
                auth=self.auth,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "connected": True,
                    "username": data.get("name"),
                    "roles": data.get("roles", []),
                    "url": self.base_url,
                }
            return {"connected": False, "error": resp.text}
