# Recommended Skills & Plugins for SERP Strategists Agent

## Installation Priority

---

## TIER 1: Essential for Planning & PRD (Install First)

### 1. Superpowers (obra/superpowers) ⭐ 216K stars
**Purpose**: Complete software development methodology — brainstorming, planning, TDD, subagent-driven development.

**Why it's #1 for this project:**
- `brainstorming` — Socratic design refinement (perfect for refining your PRD)
- `writing-plans` — Breaks work into detailed implementation plans with exact file paths
- `executing-plans` — Batch execution with human checkpoints
- `subagent-driven-development` — Parallel agent-driven development with two-stage review
- `test-driven-development` — RED-GREEN-REFACTOR enforcement
- `using-git-worktrees` — Isolated branch workspace per feature

**Install (GitHub Copilot CLI):**
```
copilot plugin marketplace add obra/superpowers-marketplace
copilot plugin install superpowers@superpowers-marketplace
```

**Or via Agent Skills Ninja:**
Search "superpowers" → Install

---

### 2. Compound Engineering (EveryInc/compound-engineering-plugin) ⭐ 19.3K stars
**Purpose**: 37 skills + 51 agents. Makes each unit of work compound into the next. 80% planning/review, 20% execution.

**Why it's critical for PRD work:**
- `/ce-strategy` — Creates STRATEGY.md with target problem, approach, persona, metrics, tracks
- `/ce-ideate` — Big-picture ideation & critical evaluation before committing
- `/ce-brainstorm` — Interactive Q&A → writes right-sized requirements doc
- `/ce-plan` — Turns feature ideas into detailed implementation plans
- `/ce-work` — Execute plans with worktrees and task tracking
- `/ce-code-review` — Multi-agent code review
- `/ce-product-pulse` — Time-windowed usage/performance reports
- `/ce-compound` — Document learnings for compounding knowledge

**Install (GitHub Copilot):**
1. VS Code Command Palette → `Chat: Install Plugin from Source`
2. Enter `EveryInc/compound-engineering-plugin`
3. Select `compound-engineering`

---

## TIER 2: Agent Architecture & Context Engineering

### 3. Context Engineering Skills (muratcankoylan/Agent-Skills-for-Context-Engineering) ⭐ 16.3K stars
**Purpose**: 15 skills for building production-grade AI agent systems. Directly relevant to your LangGraph agent.

**Critical skills for your agent architecture:**
- `multi-agent-patterns` — Orchestrator, peer-to-peer, hierarchical architectures
- `memory-systems` — Short-term, long-term, graph-based memory (your Memory Layer)
- `tool-design` — Agent-tool contracts, tool surfaces (your Tool Layer)
- `harness-engineering` — Autonomous loops with locked evaluators, approval boundaries
- `project-development` — LLM project lifecycle from ideation to deployment
- `evaluation` — Build evaluation frameworks (your Evaluation Layer)
- `context-optimization` — Token efficiency, retrieval precision

**Install (copy individual skills):**
```bash
mkdir -p .github/skills
# Download key skills:
curl -o .github/skills/multi-agent-patterns.md https://raw.githubusercontent.com/muratcankoylan/Agent-Skills-for-Context-Engineering/main/skills/multi-agent-patterns/SKILL.md
curl -o .github/skills/memory-systems.md https://raw.githubusercontent.com/muratcankoylan/Agent-Skills-for-Context-Engineering/main/skills/memory-systems/SKILL.md
curl -o .github/skills/tool-design.md https://raw.githubusercontent.com/muratcankoylan/Agent-Skills-for-Context-Engineering/main/skills/tool-design/SKILL.md
curl -o .github/skills/harness-engineering.md https://raw.githubusercontent.com/muratcankoylan/Agent-Skills-for-Context-Engineering/main/skills/harness-engineering/SKILL.md
curl -o .github/skills/project-development.md https://raw.githubusercontent.com/muratcankoylan/Agent-Skills-for-Context-Engineering/main/skills/project-development/SKILL.md
```

---

## TIER 3: VS Code Extension (Already Installed)

### 4. Agent Skills Ninja (yamapan.agent-skill-ninja) ✅ Installed
**Purpose**: Search, install, manage all skills from one place. MCP tools integration.

**Use it to:**
- `@skill /search` — Search for skills by keyword
- `@skill /recommend` — Get project-based recommendations
- `@skill /install` — Install directly from Copilot Chat
- Sidebar spiral icon → Browse/install from all sources

---

## TIER 4: Supporting Skills (Install as needed)

### 5. Anthropic Official Skills (anthropics/skills) ⭐ 146K stars
- `mcp-builder` — Build MCP servers (useful for your tool integrations)
- `claude-api` — Claude API patterns (for your content generation layer)
- `frontend-design` — Frontend design (for your Next.js dashboard)

### 6. Additional Relevant Sources
- `danielmiessler/Personal_AI_Infrastructure` — PAI Packs for personal AI infrastructure
- `Wirasm/PRPs-agentic-eng` — Prompt Recipe Patterns for agentic engineering

---

## Mapping Skills to Your Project Phases

| Phase | Best Skill/Plugin | Command |
|-------|------------------|---------|
| Product Strategy | Compound Engineering | `/ce-strategy` |
| Feature Ideation | Compound Engineering | `/ce-ideate` |
| PRD Refinement | Superpowers | `brainstorming` |
| Requirements Docs | Compound Engineering | `/ce-brainstorm` |
| Architecture Design | Context Engineering | `multi-agent-patterns`, `tool-design` |
| Sprint Planning | Superpowers | `writing-plans` |
| Implementation | Superpowers | `subagent-driven-development` |
| Agent Design | Context Engineering | `harness-engineering`, `memory-systems` |
| Code Review | Compound Engineering | `/ce-code-review` |
| Knowledge Capture | Compound Engineering | `/ce-compound` |

---

## Quick Start Sequence

1. Install **Agent Skills Ninja** extension ✅ Done
2. Install **Superpowers** plugin (for planning methodology)
3. Install **Compound Engineering** plugin (for strategy + brainstorming)
4. Download **Context Engineering** skills (for agent architecture patterns)
5. Start with `/ce-strategy` to create your STRATEGY.md
6. Then use `brainstorming` to refine PRD requirements
7. Use `writing-plans` for Sprint 1 implementation planning
