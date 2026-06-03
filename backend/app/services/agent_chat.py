"""Chat-based SEO Agent — conversational interface to the agent's capabilities.

The agent can:
- Analyze SEO issues and explain them
- Browse the connected GitHub repo (file tree, read files)
- Generate code fixes with full context and show diffs before applying
- Generate content (meta descriptions, blog posts, etc.)
- Create reports on SEO health
- Execute approved changes via GitHub PRs
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.site import Site
from app.models.issue import Issue
from app.models.fix_action import FixAction
from app.services.github_integration import GitHubIntegration
from app.services.llm_analyzer import _get_llm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the SERP Strategist Agent — an autonomous SEO expert that helps website owners improve their search rankings.

You have access to:
- The site's SEO issues (from crawl + analysis)
- The connected GitHub repository (you can browse files, understand the codebase)
- The ability to generate code fixes and create PRs

Your approach:
1. When asked to fix something, FIRST browse the repo to understand the actual code structure
2. Show the user WHAT you plan to change and WHY before doing it
3. Present diffs in a readable format
4. Only execute (create PR) when the user approves

Current site context:
- Domain: {domain}
- Tech Stack: {tech_stack}
- CMS: {cms}
- GitHub Repo: {github_repo}
- Total Issues: {issue_count}

Be conversational, explain your reasoning, and always show your work before taking action.
When showing code changes, use this format:

📁 **File**: `path/to/file.ext`
🔍 **Why**: Brief explanation of why this change helps SEO
```diff
- old line
+ new line
```

After showing proposed changes, ask: "Should I create a PR with these changes?"
"""


class AgentChat:
    """Manages a conversational session with the SEO agent."""

    def __init__(self, site_id: uuid.UUID):
        self.site_id = site_id
        self.messages: list[dict] = []
        self.site: Site | None = None
        self.github: GitHubIntegration | None = None
        self._repo_tree: list[str] | None = None

    async def initialize(self, db: AsyncSession):
        """Load site context."""
        self.site = await db.get(Site, self.site_id)
        if not self.site:
            raise ValueError(f"Site {self.site_id} not found")

        if self.site.github_repo and self.site.github_token:
            self.github = GitHubIntegration(
                repo=self.site.github_repo, token=self.site.github_token
            )

    async def get_repo_tree(self) -> list[str]:
        """Get the file tree of the connected repo."""
        if self._repo_tree:
            return self._repo_tree

        if not self.github:
            return ["No GitHub repo connected"]

        self._repo_tree = await self.github.get_repo_tree()
        return self._repo_tree

    async def get_file(self, path: str) -> str | None:
        """Read a file from the repo."""
        if not self.github:
            return None
        return await self.github.get_file_content(path)

    async def get_issues_summary(self, db: AsyncSession) -> str:
        """Get a summary of current SEO issues."""
        result = await db.execute(
            select(Issue).where(Issue.site_id == self.site_id)
        )
        issues = result.scalars().all()

        if not issues:
            return "No issues found. Run an analysis first."

        by_severity = {}
        for issue in issues:
            by_severity.setdefault(issue.severity, []).append(issue)

        summary = f"**{len(issues)} SEO issues found:**\n\n"
        for severity in ["critical", "high", "medium", "low"]:
            if severity in by_severity:
                summary += f"**{severity.upper()}** ({len(by_severity[severity])}):\n"
                for issue in by_severity[severity][:5]:
                    summary += f"  • {issue.title} — `{issue.affected_url or 'N/A'}`\n"
                if len(by_severity[severity]) > 5:
                    summary += f"  ... and {len(by_severity[severity]) - 5} more\n"
                summary += "\n"

        return summary

    async def chat(self, user_message: str, db: AsyncSession) -> str:
        """Process a user message and return the agent's response."""
        if not self.site:
            await self.initialize(db)

        # Check if this is an approval to execute a previously proposed fix
        action_result = await self._check_and_execute_action(user_message, db)
        if action_result:
            return action_result

        llm = _get_llm()
        if not llm:
            return "Error: No LLM configured. Check GROQ_API_KEY."

        # Build context
        issue_count = (await db.execute(
            select(Issue).where(Issue.site_id == self.site_id)
        )).scalars().all()

        system = SYSTEM_PROMPT.format(
            domain=self.site.domain,
            tech_stack=self.site.tech_stack or "unknown",
            cms=self.site.cms or "none",
            github_repo=self.site.github_repo or "not connected",
            issue_count=len(issue_count),
        )

        # Build tool context based on the message intent
        tool_context = await self._gather_context(user_message, db)

        # Build messages
        messages = [SystemMessage(content=system)]

        # Add conversation history (last 10 messages)
        for msg in self.messages[-10:]:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            else:
                messages.append(AIMessage(content=msg["content"]))

        # Current message with tool context
        full_message = user_message
        if tool_context:
            full_message += f"\n\n---\n[CONTEXT gathered by agent tools]:\n{tool_context}"

        messages.append(HumanMessage(content=full_message))

        # Get response
        response = await llm.ainvoke(messages)
        agent_response = response.content

        # Store in history
        self.messages.append({"role": "user", "content": user_message, "timestamp": datetime.now(timezone.utc).isoformat()})
        self.messages.append({"role": "assistant", "content": agent_response, "timestamp": datetime.now(timezone.utc).isoformat()})

        return agent_response

    async def _check_and_execute_action(self, user_message: str, db: AsyncSession) -> str | None:
        """Detect if user is approving a previously proposed fix and execute it."""
        import re
        msg_lower = user_message.lower().strip()

        # Check if this is an approval
        approval_phrases = ["yes", "do it", "go ahead", "create the pr", "approve", "make it", "ship it", "yes please", "y", "ok", "sure", "let's do it", "create pr", "option 1", "option 2"]
        is_approval = any(phrase in msg_lower for phrase in approval_phrases)

        if not is_approval:
            return None

        # Find the last assistant message that proposed a fix (has a diff)
        last_proposal = None
        for msg in reversed(self.messages):
            if msg["role"] == "assistant" and "```diff" in msg["content"]:
                last_proposal = msg["content"]
                break

        if not last_proposal:
            return None

        if not self.github:
            return "❌ Cannot create PR — no GitHub repo connected. Connect one in the Integrations tab."

        # Extract file path and diff from the proposal
        file_pattern = r'📁\s*\*\*File\*\*:\s*`([^`]+)`'
        file_matches = re.findall(file_pattern, last_proposal)

        diff_pattern = r'```diff\s*\n(.*?)```'
        diff_matches = re.findall(diff_pattern, last_proposal, re.DOTALL)

        if not file_matches or not diff_matches:
            return None

        # Determine which option user chose (if multiple were offered)
        target_idx = 0
        if "option 2" in msg_lower or "second" in msg_lower:
            target_idx = min(1, len(file_matches) - 1)

        file_path = file_matches[target_idx]
        diff_content = diff_matches[target_idx]

        # Extract the new lines from the diff
        new_lines = []
        for line in diff_content.strip().split("\n"):
            if line.startswith("+ ") or line.startswith("+\t"):
                new_lines.append(line[2:])
            elif line.startswith("+") and not line.startswith("+++"):
                new_lines.append(line[1:])

        if not new_lines:
            return None

        code_snippet = "\n".join(new_lines)

        # Fetch the actual file from repo and merge using LLM
        existing_content = await self.github.get_file_content(file_path)

        llm = _get_llm()
        if not llm:
            return "❌ Error: No LLM available to merge code."

        if existing_content:
            merge_prompt = f"""You are a code editor. Merge this change into the existing file.

EXISTING FILE ({file_path}):
```
{existing_content}
```

CHANGE TO APPLY (from diff):
```
{code_snippet}
```

Return ONLY the complete updated file content. No explanation, no code fences."""
        else:
            merge_prompt = f"""Generate a complete {self.site.tech_stack or 'Next.js'} file at path `{file_path}` that implements:
```
{code_snippet}
```

Return ONLY the file content. No explanation, no code fences."""

        merge_response = await llm.ainvoke(merge_prompt)
        final_content = merge_response.content.strip()

        # Strip code fences if LLM added them
        if final_content.startswith("```"):
            lines = final_content.split("\n")
            if lines[-1].strip() == "```":
                final_content = "\n".join(lines[1:-1])
            else:
                final_content = "\n".join(lines[1:])

        # Create the PR
        branch_name = f"seo-fix/{uuid.uuid4().hex[:8]}"
        title = f"SEO: Update {file_path}"

        # Try to extract a better title from the proposal
        title_match = re.search(r'🔍\s*\*\*Why\*\*:\s*(.+?)(?:\n|$)', last_proposal)
        description = title_match.group(1) if title_match else f"Automated SEO fix for {self.site.domain}"

        result = await self.github.create_fix_pr(
            file_path=file_path,
            new_content=final_content,
            branch_name=branch_name,
            title=title,
            description=description,
        )

        if "error" in result:
            error_msg = f"❌ Failed to create PR: {result['error']}"
            self.messages.append({"role": "user", "content": user_message, "timestamp": datetime.now(timezone.utc).isoformat()})
            self.messages.append({"role": "assistant", "content": error_msg, "timestamp": datetime.now(timezone.utc).isoformat()})
            return error_msg

        # Save as fix action in DB
        fix = FixAction(
            id=uuid.uuid4(),
            site_id=self.site_id,
            action_type="github_pr",
            status="completed",
            title=title,
            description=description,
            fix_content={"file_path": file_path, "branch": branch_name, "code_snippet": code_snippet},
            target_path=file_path,
            execution_result=result,
            executed_at=datetime.now(timezone.utc),
        )
        db.add(fix)
        await db.commit()

        pr_url = result.get("pr_url", "")
        pr_number = result.get("pr_number", "")

        success_msg = f"""✅ **PR #{pr_number} created successfully!**

🔗 [{pr_url}]({pr_url})

**Branch**: `{branch_name}`
**File changed**: `{file_path}`

The PR is ready for review. You can merge it directly on GitHub or I can help with more fixes. What else would you like me to work on?"""

        self.messages.append({"role": "user", "content": user_message, "timestamp": datetime.now(timezone.utc).isoformat()})
        self.messages.append({"role": "assistant", "content": success_msg, "timestamp": datetime.now(timezone.utc).isoformat()})
        return success_msg

    async def _gather_context(self, message: str, db: AsyncSession) -> str:
        """Intelligently gather context based on what the user is asking about."""
        context_parts = []
        msg_lower = message.lower()

        # If asking about issues/problems/analysis
        if any(w in msg_lower for w in ["issue", "problem", "fix", "error", "seo", "analyze", "what's wrong", "improve"]):
            issues_summary = await self.get_issues_summary(db)
            context_parts.append(f"## Current Issues\n{issues_summary}")

        # If asking about code/files/repo
        if any(w in msg_lower for w in ["file", "code", "repo", "layout", "config", "component", "fix", "change", "pr"]):
            if self.github:
                tree = await self.get_repo_tree()
                # Show relevant parts of the tree
                relevant = [f for f in tree if any(ext in f for ext in [".tsx", ".ts", ".js", ".mjs", ".json", ".css", ".config"])]
                if len(relevant) > 50:
                    relevant = relevant[:50]
                context_parts.append(f"## Repo File Tree (key files)\n```\n" + "\n".join(relevant) + "\n```")

        # If referencing specific files, fetch them
        if self.github:
            import re
            file_refs = re.findall(r'[`"\']([a-zA-Z0-9_/.-]+\.[a-zA-Z]+)[`"\']', message)
            for ref in file_refs[:3]:  # Max 3 files
                content = await self.get_file(ref)
                if content:
                    context_parts.append(f"## File: {ref}\n```\n{content[:3000]}\n```")

        return "\n\n".join(context_parts) if context_parts else ""

    async def execute_fix(self, file_path: str, new_content: str, title: str, description: str, db: AsyncSession) -> dict:
        """Execute an approved fix by creating a PR."""
        if not self.github:
            return {"error": "No GitHub repo connected"}

        branch_name = f"seo-fix/{uuid.uuid4().hex[:8]}"

        result = await self.github.create_fix_pr(
            file_path=file_path,
            new_content=new_content,
            branch_name=branch_name,
            title=title,
            description=description,
        )

        if "error" not in result:
            # Save as fix action
            fix = FixAction(
                id=uuid.uuid4(),
                site_id=self.site_id,
                action_type="github_pr",
                status="completed",
                title=title,
                description=description,
                fix_content={"file_path": file_path, "branch": branch_name},
                target_path=file_path,
                execution_result=result,
                executed_at=datetime.now(timezone.utc),
            )
            db.add(fix)
            await db.commit()

        return result


# Session store — in-memory for now, could be Redis later
_chat_sessions: dict[str, AgentChat] = {}


def get_or_create_session(site_id: uuid.UUID) -> AgentChat:
    """Get or create a chat session for a site."""
    key = str(site_id)
    if key not in _chat_sessions:
        _chat_sessions[key] = AgentChat(site_id)
    return _chat_sessions[key]
