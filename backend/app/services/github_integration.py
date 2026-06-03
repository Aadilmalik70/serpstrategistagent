"""GitHub integration — create PRs with SEO fixes."""
import logging
import base64
import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubIntegration:
    """Creates pull requests with SEO fixes on a GitHub repo."""

    def __init__(self, repo: str, token: str):
        """
        Args:
            repo: "owner/repo" format
            token: GitHub personal access token with repo scope
        """
        self.repo = repo
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get_file_content(self, file_path: str, ref: str = None) -> str | None:
        """Fetch a file's content from the repo. Returns None if file doesn't exist."""
        async with httpx.AsyncClient(timeout=30) as client:
            params = {"ref": ref} if ref else {}
            resp = await client.get(
                f"{GITHUB_API}/repos/{self.repo}/contents/{file_path}",
                headers=self.headers,
                params=params,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            content_b64 = data.get("content", "")
            return base64.b64decode(content_b64).decode("utf-8")

    async def get_repo_tree(self, path: str = "") -> list[str]:
        """Get the file tree of the repo recursively."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Use Git Trees API for full recursive listing
            # First get default branch
            repo_resp = await client.get(
                f"{GITHUB_API}/repos/{self.repo}",
                headers=self.headers,
            )
            if repo_resp.status_code != 200:
                return []
            default_branch = repo_resp.json().get("default_branch", "main")

            # Get tree recursively
            tree_resp = await client.get(
                f"{GITHUB_API}/repos/{self.repo}/git/trees/{default_branch}",
                headers=self.headers,
                params={"recursive": "1"},
            )
            if tree_resp.status_code != 200:
                return []

            tree = tree_resp.json().get("tree", [])
            return [
                item["path"] for item in tree
                if item["type"] == "blob"  # files only
            ]

    async def verify_connection(self) -> dict:
        """Verify the GitHub connection works."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{self.repo}",
                headers=self.headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "connected": True,
                    "repo": self.repo,
                    "default_branch": data.get("default_branch"),
                    "private": data.get("private"),
                }
            return {"connected": False, "error": resp.text}

    async def create_fix_pr(
        self,
        file_path: str,
        new_content: str,
        branch_name: str,
        title: str,
        description: str,
        base_branch: str = None,
    ) -> dict:
        """Create a PR with a single file fix.

        Returns:
            {"pr_url": "...", "pr_number": int, "branch": "..."}
        """
        async with httpx.AsyncClient(timeout=30) as client:
            # 0. Auto-detect default branch if not specified
            if not base_branch:
                repo_resp = await client.get(
                    f"{GITHUB_API}/repos/{self.repo}",
                    headers=self.headers,
                )
                if repo_resp.status_code == 200:
                    base_branch = repo_resp.json().get("default_branch", "main")
                else:
                    base_branch = "main"

            # 1. Get the SHA of the base branch
            ref_resp = await client.get(
                f"{GITHUB_API}/repos/{self.repo}/git/ref/heads/{base_branch}",
                headers=self.headers,
            )
            if ref_resp.status_code != 200:
                return {"error": f"Failed to get base branch: {ref_resp.text}"}
            base_sha = ref_resp.json()["object"]["sha"]

            # 2. Create a new branch
            create_ref_resp = await client.post(
                f"{GITHUB_API}/repos/{self.repo}/git/refs",
                headers=self.headers,
                json={
                    "ref": f"refs/heads/{branch_name}",
                    "sha": base_sha,
                },
            )
            if create_ref_resp.status_code not in (200, 201):
                # Branch might already exist
                if "already exists" not in create_ref_resp.text:
                    return {"error": f"Failed to create branch: {create_ref_resp.text}"}

            # 3. Get current file (if exists) for its SHA
            file_resp = await client.get(
                f"{GITHUB_API}/repos/{self.repo}/contents/{file_path}",
                headers=self.headers,
                params={"ref": branch_name},
            )
            file_sha = file_resp.json().get("sha") if file_resp.status_code == 200 else None

            # 4. Create/update the file
            content_b64 = base64.b64encode(new_content.encode()).decode()
            update_body = {
                "message": f"fix(seo): {title}",
                "content": content_b64,
                "branch": branch_name,
            }
            if file_sha:
                update_body["sha"] = file_sha

            update_resp = await client.put(
                f"{GITHUB_API}/repos/{self.repo}/contents/{file_path}",
                headers=self.headers,
                json=update_body,
            )
            if update_resp.status_code not in (200, 201):
                return {"error": f"Failed to update file: {update_resp.text}"}

            # 5. Create the PR
            pr_resp = await client.post(
                f"{GITHUB_API}/repos/{self.repo}/pulls",
                headers=self.headers,
                json={
                    "title": f"[SEO Fix] {title}",
                    "body": description,
                    "head": branch_name,
                    "base": base_branch,
                },
            )
            if pr_resp.status_code not in (200, 201):
                return {"error": f"Failed to create PR: {pr_resp.text}"}

            pr_data = pr_resp.json()
            logger.info(f"Created PR #{pr_data['number']}: {pr_data['html_url']}")

            return {
                "pr_url": pr_data["html_url"],
                "pr_number": pr_data["number"],
                "branch": branch_name,
            }

    async def create_multi_file_pr(
        self,
        files: dict[str, str],  # path -> content
        branch_name: str,
        title: str,
        description: str,
        base_branch: str = "main",
    ) -> dict:
        """Create a PR with multiple file changes using the Git tree API.

        Args:
            files: Dict of file_path -> new_content
        """
        async with httpx.AsyncClient(timeout=30) as client:
            # 1. Get base branch SHA
            ref_resp = await client.get(
                f"{GITHUB_API}/repos/{self.repo}/git/ref/heads/{base_branch}",
                headers=self.headers,
            )
            if ref_resp.status_code != 200:
                return {"error": f"Failed to get base branch: {ref_resp.text}"}
            base_sha = ref_resp.json()["object"]["sha"]

            # 2. Get the base tree
            commit_resp = await client.get(
                f"{GITHUB_API}/repos/{self.repo}/git/commits/{base_sha}",
                headers=self.headers,
            )
            base_tree_sha = commit_resp.json()["tree"]["sha"]

            # 3. Create blobs for each file
            tree_items = []
            for path, content in files.items():
                blob_resp = await client.post(
                    f"{GITHUB_API}/repos/{self.repo}/git/blobs",
                    headers=self.headers,
                    json={"content": content, "encoding": "utf-8"},
                )
                if blob_resp.status_code != 201:
                    return {"error": f"Failed to create blob for {path}: {blob_resp.text}"}
                tree_items.append({
                    "path": path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_resp.json()["sha"],
                })

            # 4. Create new tree
            tree_resp = await client.post(
                f"{GITHUB_API}/repos/{self.repo}/git/trees",
                headers=self.headers,
                json={"base_tree": base_tree_sha, "tree": tree_items},
            )
            if tree_resp.status_code != 201:
                return {"error": f"Failed to create tree: {tree_resp.text}"}
            new_tree_sha = tree_resp.json()["sha"]

            # 5. Create commit
            commit_resp = await client.post(
                f"{GITHUB_API}/repos/{self.repo}/git/commits",
                headers=self.headers,
                json={
                    "message": f"fix(seo): {title}",
                    "tree": new_tree_sha,
                    "parents": [base_sha],
                },
            )
            if commit_resp.status_code != 201:
                return {"error": f"Failed to create commit: {commit_resp.text}"}
            new_commit_sha = commit_resp.json()["sha"]

            # 6. Create branch ref
            create_ref_resp = await client.post(
                f"{GITHUB_API}/repos/{self.repo}/git/refs",
                headers=self.headers,
                json={"ref": f"refs/heads/{branch_name}", "sha": new_commit_sha},
            )
            if create_ref_resp.status_code not in (200, 201):
                if "already exists" not in create_ref_resp.text:
                    return {"error": f"Failed to create branch: {create_ref_resp.text}"}

            # 7. Create PR
            pr_resp = await client.post(
                f"{GITHUB_API}/repos/{self.repo}/pulls",
                headers=self.headers,
                json={
                    "title": f"[SEO Fix] {title}",
                    "body": description,
                    "head": branch_name,
                    "base": base_branch,
                },
            )
            if pr_resp.status_code not in (200, 201):
                return {"error": f"Failed to create PR: {pr_resp.text}"}

            pr_data = pr_resp.json()
            logger.info(f"Created multi-file PR #{pr_data['number']}: {pr_data['html_url']}")

            return {
                "pr_url": pr_data["html_url"],
                "pr_number": pr_data["number"],
                "branch": branch_name,
                "files_changed": len(files),
            }

    async def verify_connection(self) -> dict:
        """Verify token has access to the repo."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{self.repo}",
                headers=self.headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "connected": True,
                    "repo": data["full_name"],
                    "default_branch": data["default_branch"],
                    "private": data["private"],
                }
            return {"connected": False, "error": resp.text}
