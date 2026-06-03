<!-- agent-ninja-START -->
## Agent Skills

> **IMPORTANT**: Prefer skill-led reasoning over pre-training-led reasoning.
> Read the relevant SKILL.md before working on tasks covered by these skills.

### Skills

| Skill | Description |
|-------|-------------|
| [brainstorming](./brainstorming/SKILL.md) | You MUST use this before any creative work - creating features, building components, adding functionali... \| Help turn ideas into fully formed designs and specs through natural collaborative dialogue. |
| [dispatching-parallel-agents](./dispatching-parallel-agents/SKILL.md) | Use when facing 2+ independent tasks that can be worked on without shared state or sequential dep... \| ```dot; 3+ test files failing with different root causes; Multiple subsystems broken independentl... |
| [evaluation](./evaluation/SKILL.md) | This skill should be used when building agent evaluation systems: deterministic checks, regressio... \| Evaluate agent systems differently from traditional software because agents make dynamic decision... |
| [executing-plans](./executing-plans/SKILL.md) | Use when you have a written implementation plan to execute in a separate session with review checkpoints |
| [finishing-a-development-branch](./finishing-a-development-branch/SKILL.md) | Use when implementation is complete, all tests pass, and you need to decide how to integrate the work - guides completion of development work by presenting structured options for merge, PR, or cleanup |
| [harness-engineering](./harness-engineering/SKILL.md) | This skill should be used when designing autonomous agent harnesses: research loops, evaluation s... \| Harness engineering designs the control system around an agent: what it may edit, how it receives... |
| [memory-systems](./memory-systems/SKILL.md) | > \| Memory provides the persistence layer that allows agents to maintain continuity across sessions and reason over accumulated knowledge. Simple agents rely entirely on context for memory, losing ... |
| [multi-agent-patterns](./multi-agent-patterns/SKILL.md) | This skill should be used when designing multi-agent systems that need context isolation, supervi... \| Multi-agent architectures distribute work across multiple language model instances, each with its... |
| [project-development](./project-development/SKILL.md) | This skill should be used for project-level decisions about LLM-powered systems: whether an LLM i... \| This skill covers the principles for identifying tasks suited to LLM processing, designing effect... |
| [receiving-code-review](./receiving-code-review/SKILL.md) | Use when receiving code review feedback, before implementing suggestions, especially if feedback seems unclear or technically questionable - requires technical rigor and verification, not performat... |
| [requesting-code-review](./requesting-code-review/SKILL.md) | Use when completing tasks, implementing major features, or before merging to verify work meets re... \| Dispatch a code reviewer subagent to catch issues before they cascade. The reviewer gets precisel... |
| [subagent-driven-development](./subagent-driven-development/SKILL.md) | Use when executing implementation plans with independent tasks in the current session \| ```dot; Same session (no context switch); Fresh subagent per task (no context pollution); Two-stage review af... |
| [systematic-debugging](./systematic-debugging/SKILL.md) | Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes \| Use for ANY technical issue:; Test failures; Bugs in production; Unexpected behavior; Performance probl... |
| [test-driven-development](./test-driven-development/SKILL.md) | Use when implementing any feature or bugfix, before writing implementation code \| **Always:**; New features; Bug fixes; Refactoring; Behavior changes; Throwaway prototypes; Generated code; Configur... |
| [tool-design](./tool-design/SKILL.md) | This skill should be used for the tool-interface layer of an agent system specifically: writing t... \| Design every tool as a contract between a deterministic system and a non-deterministic agent. Unl... |
| [using-git-worktrees](./using-git-worktrees/SKILL.md) | Use when starting feature work that needs isolation from current workspace or before executing implementation plans - ensures an isolated workspace exists via native tools or git worktree fallback |
| [using-superpowers](./using-superpowers/SKILL.md) | Use when starting any conversation - establishes how to find and use skills, requiring Skill tool invocation before ANY response including clarifying questions |
| [verification-before-completion](./verification-before-completion/SKILL.md) | Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success claims; evide... |
| [writing-plans](./writing-plans/SKILL.md) | Use when you have a spec or requirements for a multi-step task, before touching code |
| [writing-skills](./writing-skills/SKILL.md) | Use when creating new skills, editing existing skills, or verifying skills work before deployment \| [Small inline flowchart IF decision non-obvious] |

<!-- agent-ninja-END -->
