# Runbooks

Each `.md` file in this folder is exposed as an MCP **resource** at the URI
`runbook://<filename-without-extension>`.

## How a runbook is used

1. The user (in Claude / Cursor / etc.) says: *"Run the dynamodb-hot-partition runbook on the `orders` table."*
2. The agent calls the MCP resource `runbook://dynamodb-hot-partition` and reads the markdown.
3. The markdown contains step-by-step instructions that tell the agent **which tools to call** and **in what order**.
4. The agent executes those steps using the actual MCP tools (`dynamodb_describe_table`, `dynamodb_query`, etc.) and presents the findings.

So a runbook is just a recipe written for an LLM, not Python code. That means
non-engineers on your team can write and edit them too.

## Writing a good runbook

- **Be explicit about which tools to call.** Don't say "check the table" — say "call `dynamodb_describe_table` with `table_name=<X>`".
- **State the goal first.** The agent uses it to decide when to stop or escalate.
- **Include an escalation step.** "If item count > 1B, stop and ask the human."
- **Keep it short.** 10–20 numbered steps is plenty; longer runbooks get summarised and lose detail.

See [`dynamodb-hot-partition.md`](dynamodb-hot-partition.md) for a worked example.
