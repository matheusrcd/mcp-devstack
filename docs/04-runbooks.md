# 04 — Runbooks as resources

## What a runbook is, in this project

A **runbook** is a single markdown file in [`runbooks/`](../runbooks/) that
describes how an LLM agent should investigate or remediate a specific
situation, **using the tools this MCP server exposes**.

Example: [`dynamodb-hot-partition.md`](../runbooks/dynamodb-hot-partition.md)
walks the agent through "you suspect a DynamoDB hot partition — here are the
specific tool calls to make, in order, to confirm or rule it out."

## Why markdown and not Python

The original instinct is "make each runbook a Python function and expose it
as one big tool". We deliberately did not do that. Here's why.

| Approach                  | Pros                                            | Cons                                                                                                                              |
|---------------------------|-------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| **Markdown resource** (chosen) | Anyone can author/edit. Version-controlled as docs. Agent decides which steps apply. Easy to audit (it's just text). | The agent has to follow the steps — quality depends on the model. |
| Python function           | Deterministic execution.                        | Every runbook = code change + deploy. Non-engineers can't contribute. The function ends up being one giant tool that does many things, which is exactly what MCP tells you NOT to do. |

The killer argument is contribution: SREs and support engineers can write
markdown but most won't touch the Python repo. Lower the barrier and the
runbook library grows.

## How the resource is exposed

[`src/devstack_mcp/server.py`](../src/devstack_mcp/server.py) registers one
templated resource:

```python
@mcp.resource("runbook://{name}")
async def get_runbook(name: str) -> str:
    ...
```

The `{name}` placeholder means a single handler covers every file in
`runbooks/`. The agent (or user) loads one by URI:

```
runbook://dynamodb-hot-partition
runbook://sqs-backlog-triage
runbook://athena-query-failed
```

The handler:
1. Rejects names containing `/` or `..` (path traversal defence).
2. Reads `runbooks/<name>.md` from disk.
3. Returns the contents as plain text, which the client puts into the agent's context window.

## How a runbook gets used end-to-end

1. **User** says to Claude: *"Run the dynamodb-hot-partition runbook on the `orders` table."*
2. **Claude** calls `resources/read` with URI `runbook://dynamodb-hot-partition`.
3. **This server** returns the markdown content.
4. **Claude** now has the steps in context. It starts executing them by calling
   the actual MCP tools (`dynamodb_describe_table`, `dynamodb_query`, …).
5. Between tool calls, Claude reasons about the results — applying the runbook's
   stop conditions, deciding whether to escalate.
6. Claude summarises findings in the format the runbook asked for.

The runbook never executes by itself. It's an instruction sheet the LLM follows.

## Authoring guidelines (cheat sheet)

- Lead with **Goal** and **When to use** so the agent (and humans skimming) know if it applies.
- Use **numbered steps**. Each step should map to at most 1–2 tool calls.
- Name the tool explicitly: ``call `dynamodb_describe_table` with `{table_name, region}` ``.
- End with **Stop conditions** — when to bail out and ask a human.
- Keep it **under ~300 lines**. Past that, agents start summarising and losing detail.

See the [`runbooks/README.md`](../runbooks/README.md) for a shorter authoring summary.

## When to graduate a runbook into a tool

If a runbook is purely mechanical (no judgement calls, no branching), and you
run it 50+ times a month, it's probably worth turning the whole thing into a
single tool that executes the sequence deterministically. Until then, leave
it as markdown.
