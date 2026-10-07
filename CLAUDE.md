# TaxResearch

## Cost-aware delegation

When delegating to subagents, prefer cheaper models:

- **Implementation** → `implementer` agent (Haiku). Hand it concrete, well-specified tasks.
- **Code exploration / search** → `explorer` agent (Sonnet), read-only.
- Keep planning, design decisions, and final review of agent output in the main session.
