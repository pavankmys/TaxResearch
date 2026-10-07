# TaxResearch

## Cost-aware delegation

When delegating to subagents, prefer cheaper models:

- **Implementation** → `implementer` agent (Haiku). Hand it concrete, well-specified tasks.
- **Code exploration / search** → `explorer` agent (Sonnet), read-only.
- Keep planning, design decisions, and final review of agent output in the main session.

## Workflow: plan → freeze → code

Every change follows these three steps, in order:

1. **Plan** — explore (via `explorer`) and write a concrete plan: goal, files to change, approach, and how it will be verified.
2. **Freeze** — present the plan to the user and wait for explicit approval. Once approved, the plan is frozen: no scope changes during coding. If something forces a change, stop and re-plan with the user.
3. **Code** — implement exactly the frozen plan (via `implementer` where possible), verify, then review against the plan before committing.
