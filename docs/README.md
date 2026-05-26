# Documentation

Read these in order if you're new to the project (or to MCP itself):

1. [**00 — What is MCP, and why are we building one?**](00-what-is-mcp.md)
   The 10-minute mental model. Read this first.

2. [**01 — Architecture of this server**](01-architecture.md)
   How the pieces fit together, with a diagram. What lives where.

3. [**02 — AWS authentication**](02-aws-auth.md)
   How `boto3` picks credentials, why we chose profiles, how to verify it works.

4. [**03 — Adding a new tool**](03-adding-tools.md)
   The pattern, step by step. Copy-paste-able template at the bottom.

5. [**04 — Runbooks as resources**](04-runbooks.md)
   Why runbooks live in markdown, not Python. How an agent uses them.

6. [**05 — Connecting a client (Claude / Cursor)**](05-connecting-clients.md)
   The JSON snippet you paste into your client config to make this server appear.

## Conventions used in these docs

- **WHY before WHAT.** Every doc opens with the reason the thing exists. The how-to comes after.
- **File:line references** use the form `path/to/file.py:42` so you can jump to the exact location.
- **No magic.** If something looks like framework magic, the doc explains what's really happening underneath.
