"""LLM-powered code fix agent — clones repo, reads code, generates fix, pushes PR."""
import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def execute_fix_with_codex(
    repo_url: str,
    github_token: str,
    task_prompt: str,
    branch_name: str,
) -> dict:
    """Execute a fix using LLM to generate code changes.

    Flow:
    1. Clone the repo to a temp directory
    2. Create a fix branch
    3. Read relevant files, ask LLM to generate changes
    4. Apply changes, push branch and create PR

    Returns:
        {"status": "success", "pr_url": "...", "files_changed": [...]}
        or {"error": "..."}
    """
    work_dir = None
    try:
        # 1. Clone repo into a temp directory
        base_dir = tempfile.mkdtemp(prefix="codex_fix_")
        work_dir = os.path.join(base_dir, "repo")
        clone_url = f"https://x-access-token:{github_token}@github.com/{repo_url}.git"

        print(f"[AGENT] Cloning {repo_url}...", flush=True)

        clone_result = await _run_cmd(
            [
                "git",
                "-c", "credential.helper=",
                "clone", "--depth", "1",
                clone_url, work_dir,
            ],
            cwd=None,
            timeout=120,
            env={
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "never",
                "GIT_ASKPASS": "",
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        if clone_result["returncode"] != 0:
            stderr = clone_result["stderr"].replace(github_token, "***")
            return {"error": f"Failed to clone repo: {stderr}"}

        print("[AGENT] Clone successful. Analyzing code...", flush=True)

        # 2. Create fix branch
        await _run_cmd(["git", "checkout", "-b", branch_name], cwd=work_dir)

        # 3. Use LLM to generate code changes
        fix_result = await _generate_fix_with_llm(task_prompt, work_dir)
        if fix_result.get("error"):
            return fix_result

        # 4. Check for changes
        diff_result = await _run_cmd(["git", "diff", "--name-only"], cwd=work_dir)
        untracked = await _run_cmd(
            ["git", "ls-files", "--others", "--exclude-standard"], cwd=work_dir
        )

        changed_files = [f for f in diff_result["stdout"].strip().split("\n") if f]
        new_files = [f for f in untracked["stdout"].strip().split("\n") if f]
        all_files = changed_files + new_files

        if not all_files:
            return {"status": "no_changes", "message": "LLM generated no file changes"}

        # 5. Commit and push
        if new_files:
            await _run_cmd(["git", "add"] + new_files, cwd=work_dir)
        await _run_cmd(["git", "add", "-u"], cwd=work_dir)
        await _run_cmd(
            ["git", "commit", "-m", f"fix(seo): {branch_name}"],
            cwd=work_dir,
            env={
                "GIT_AUTHOR_NAME": "SERP Strategist",
                "GIT_AUTHOR_EMAIL": "agent@serpstrategist.local",
                "GIT_COMMITTER_NAME": "SERP Strategist",
                "GIT_COMMITTER_EMAIL": "agent@serpstrategist.local",
            },
        )

        push_result = await _run_cmd(
            ["git", "-c", "credential.helper=", "push", "origin", branch_name],
            cwd=work_dir,
            timeout=60,
            env={
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "never",
                "GIT_ASKPASS": "",
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        if push_result["returncode"] != 0:
            stderr = push_result["stderr"].replace(github_token, "***")
            return {"error": f"Failed to push: {stderr}"}

        # 6. Create PR via GitHub API
        pr_result = await _create_pr(
            repo=repo_url,
            token=github_token,
            branch=branch_name,
            title=f"SEO Fix: {branch_name}",
            body=f"**Automated fix by SERP Strategist Agent**\n\n**Task:**\n{task_prompt}\n\n**Files changed:** {', '.join(all_files)}",
        )

        print(f"[AGENT] PR created: {pr_result.get('pr_url', 'unknown')}", flush=True)

        return {
            "status": "success",
            "files_changed": all_files,
            "pr_url": pr_result.get("pr_url"),
            "pr_number": pr_result.get("pr_number"),
            "branch": branch_name,
        }

    except Exception as e:
        logger.error(f"Fix execution failed: {e}")
        return {"error": str(e)}
    finally:
        if work_dir:
            base = os.path.dirname(work_dir)
            if base and os.path.exists(base):
                shutil.rmtree(base, ignore_errors=True)


async def run_codex_chat(task_prompt: str, repo_path: str) -> dict:
    """Run LLM fix on an already-cloned local repo. Returns changes made."""
    fix_result = await _generate_fix_with_llm(task_prompt, repo_path)
    if fix_result.get("error"):
        return fix_result

    diff_result = await _run_cmd(["git", "diff", "--stat"], cwd=repo_path)
    return {
        "status": "success",
        "diff_summary": diff_result["stdout"],
    }


# === LLM Code Generation ===

async def _generate_fix_with_llm(task_prompt: str, repo_dir: str) -> dict:
    """Use the configured LLM to analyze code and generate a fix."""
    from app.services.llm_analyzer import _get_llm

    llm = _get_llm()
    if not llm:
        return {"error": "No LLM configured (need GROQ_API_KEY or GOOGLE_API_KEY)"}

    # Find relevant files in the repo
    relevant_files = _find_relevant_files(task_prompt, repo_dir)
    if not relevant_files:
        return {"error": "Could not identify relevant files to fix"}

    # Read file contents
    file_contents = {}
    for fpath in relevant_files[:5]:  # Limit to 5 files to stay within context
        full_path = os.path.join(repo_dir, fpath)
        if os.path.isfile(full_path):
            try:
                content = Path(full_path).read_text(encoding="utf-8", errors="replace")
                if len(content) > 10000:
                    content = content[:10000] + "\n... [truncated]"
                file_contents[fpath] = content
            except Exception:
                pass

    if not file_contents:
        return {"error": "Could not read any relevant files"}

    # Build LLM prompt
    files_section = ""
    for fpath, content in file_contents.items():
        files_section += f"\n--- FILE: {fpath} ---\n{content}\n"

    prompt = f"""You are an expert web developer fixing an SEO issue.

TASK:
{task_prompt}

REPOSITORY FILES:
{files_section}

INSTRUCTIONS:
- Identify which file(s) need changes to fix the SEO issue described above.
- For EACH file you need to change, output the COMPLETE updated file content.
- Use this EXACT format for each file change:

===FILE: path/to/file.ext===
(complete file content here)
===END_FILE===

- Only output files that need changes. Do not output unchanged files.
- Make minimal, focused changes. Don't refactor unrelated code.
- If you need to create a new file, use the same format with the new path.
- Output ONLY the file blocks, no explanation before or after.
"""

    print(f"[AGENT] Asking LLM to generate fix ({len(file_contents)} files in context)...", flush=True)

    try:
        response = await asyncio.to_thread(lambda: llm.invoke(prompt).content)
    except Exception as e:
        return {"error": f"LLM call failed: {str(e)[:200]}"}

    if not response:
        return {"error": "LLM returned empty response"}

    # Parse response and apply changes
    changes = _parse_file_changes(response)
    if not changes:
        return {"error": "LLM did not produce any file changes in expected format"}

    # Apply changes
    applied = []
    for fpath, content in changes.items():
        full_path = os.path.join(repo_dir, fpath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        Path(full_path).write_text(content, encoding="utf-8")
        applied.append(fpath)
        print(f"[AGENT] Applied change to: {fpath}", flush=True)

    return {"status": "ok", "files_changed": applied}


def _find_relevant_files(task_prompt: str, repo_dir: str) -> list[str]:
    """Find files in the repo relevant to the fix task."""
    task_lower = task_prompt.lower()
    candidate_files = []

    # Walk the repo (skip irrelevant dirs)
    skip_dirs = {".git", "node_modules", ".next", "__pycache__", "dist", "build", ".cache", "backup"}
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            rel_path = os.path.relpath(os.path.join(root, fname), repo_dir).replace("\\", "/")
            candidate_files.append(rel_path)

    # Score files by relevance to the task
    scored = []
    for fpath in candidate_files:
        score = 0
        fpath_lower = fpath.lower()

        # Skip binary/asset files
        ext = os.path.splitext(fpath)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".lock", ".map"):
            continue

        # Boost if path parts appear in task
        parts = re.split(r"[/\-_.]", fpath_lower)
        for part in parts:
            if len(part) > 3 and part in task_lower:
                score += 10

        # Boost SEO-relevant files
        if "layout" in fpath_lower or "head" in fpath_lower:
            score += 5
        if "metadata" in fpath_lower or "seo" in fpath_lower:
            score += 8
        if "page" in fpath_lower:
            score += 3
        if ext in (".tsx", ".jsx", ".html", ".astro", ".svelte", ".vue"):
            score += 2
        if ext in (".ts", ".js"):
            score += 1

        # Boost if URL paths from task match file structure
        url_paths = re.findall(r"/[\w-]+(?:/[\w-]+)*", task_prompt)
        for url_path in url_paths:
            url_parts = url_path.strip("/").split("/")
            for part in url_parts:
                if len(part) > 2 and part in fpath_lower:
                    score += 5

        if score > 0:
            scored.append((score, fpath))

    scored.sort(key=lambda x: x[0], reverse=True)
    result = [fpath for _, fpath in scored[:10]]

    # Fallback: key files
    if not result:
        for fpath in candidate_files:
            if any(name in fpath.lower() for name in ("layout", "page", "index", "app", "head")):
                result.append(fpath)
                if len(result) >= 5:
                    break

    print(f"[AGENT] Found {len(result)} relevant files: {result[:5]}", flush=True)
    return result


def _parse_file_changes(response: str) -> dict[str, str]:
    """Parse LLM response to extract file changes."""
    changes = {}

    # Match ===FILE: path=== ... ===END_FILE===
    pattern = r"===FILE:\s*(.+?)===\s*\n(.*?)===END_FILE==="
    matches = re.findall(pattern, response, re.DOTALL)

    for fpath, content in matches:
        fpath = fpath.strip()
        content = content.strip("\n")
        if fpath and content:
            changes[fpath] = content

    return changes


# === Subprocess Helpers ===

async def _run_cmd(
    cmd: list[str],
    cwd: str | None,
    timeout: int = 30,
    env: dict | None = None,
) -> dict:
    """Run a subprocess command using thread pool (Windows compatible)."""
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)

    def _sync_run():
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=proc_env,
                timeout=timeout,
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout.decode(errors="replace"),
                "stderr": result.stderr.decode(errors="replace"),
            }
        except subprocess.TimeoutExpired:
            return {"returncode": -1, "stdout": "", "stderr": "Command timed out"}
        except Exception as e:
            return {"returncode": -1, "stdout": "", "stderr": str(e)}

    return await asyncio.to_thread(_sync_run)


async def _create_pr(repo: str, token: str, branch: str, title: str, body: str) -> dict:
    """Create a pull request via GitHub API."""
    async with httpx.AsyncClient(timeout=15) as client:
        # Get default branch
        repo_resp = await client.get(
            f"https://api.github.com/repos/{repo}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        base_branch = "main"
        if repo_resp.status_code == 200:
            base_branch = repo_resp.json().get("default_branch", "main")

        # Create PR
        pr_resp = await client.post(
            f"https://api.github.com/repos/{repo}/pulls",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            json={
                "title": title,
                "body": body,
                "head": branch,
                "base": base_branch,
            },
        )

        if pr_resp.status_code in (200, 201):
            data = pr_resp.json()
            return {"pr_url": data["html_url"], "pr_number": data["number"]}
        else:
            return {"error": f"PR creation failed: {pr_resp.text[:200]}"}
