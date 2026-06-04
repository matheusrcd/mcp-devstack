# devstack-mcp

An MCP (Model Context Protocol) server that gives an LLM agent — Claude
Desktop, Cursor, Claude Code, your own agent built on the Anthropic SDK —
direct access to your AWS account for **incident analysis and runbook
execution**.

> **v1 scope (today):** DynamoDB read-only tools + markdown runbooks.
> **Planned:** Athena, SQS, Datadog logs/metrics. See [the roadmap](#roadmap).

---

## Why this exists

When something breaks in production, the dance is always the same:

1. Open the AWS console, switch region, find the right service.
2. Run a query or describe a table to confirm the schema.
3. Copy an ID, paste it into a DynamoDB console search.
4. Open Datadog, search logs for that ID in the right time window.
5. Correlate, repeat.

Each step is 30 seconds of clicking and 0 seconds of thinking. An LLM with
the right tools can do all of that mechanical work, leaving you to make the
actual decisions.

This server gives the LLM those tools — through a single, standard protocol
(MCP) that works across every modern AI client.

---

## Quickstart

### 1. Install

Requires Python ≥ 3.10 and AWS credentials configured in `~/.aws/credentials`.

```bash
git clone <this-repo> mcp-devstack && cd mcp-devstack
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Sanity-check AWS access

```bash
AWS_PROFILE=default aws sts get-caller-identity
```

If that prints your account/user ARN, the MCP server will see the same
credentials. (Why? See [docs/02-aws-auth.md](docs/02-aws-auth.md).)

### 3. Test the server starts

```bash
devstack-mcp
```

It will sit there silently — that's correct, it's waiting for JSON-RPC frames
on stdin. Hit `Ctrl+C` to exit. To inspect tools interactively, use:

```bash
npx @modelcontextprotocol/inspector devstack-mcp
```

This opens a UI where you can list tools and call them with sample inputs.

### 4. Connect a client

See [docs/05-connecting-clients.md](docs/05-connecting-clients.md) for
Claude Desktop, Cursor, and Claude Code configs.

The short version (Claude Desktop) — edit
`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "devstack": {
      "command": "/absolute/path/to/.venv/bin/devstack-mcp",
      "env": { "AWS_PROFILE": "default", "AWS_REGION": "us-east-1" }
    }
  }
}
```

Restart Claude Desktop. Ask it: *"List my DynamoDB tables in us-east-1."*

---

## What's in v1

### Tools

| Tool                       | What it does                                                          |
|----------------------------|-----------------------------------------------------------------------|
| `dynamodb_list_tables`     | Paginated list of table names in a region                             |
| `dynamodb_describe_table`  | Key schema, indexes, item count, size                                 |
| `dynamodb_get_item`        | Fetch one item by primary key (cheapest op)                           |
| `dynamodb_query`           | Items by partition key, optional sort key condition, supports GSIs    |
| `dynamodb_scan`            | Capped scan (max 500) with optional FilterExpression                  |

All tools are **read-only**. There is no `put_item`, `delete_item`, or
`update_item` in this server — by design, not by configuration.

### Resources (runbooks)

| URI                                    | What it is                                             |
|----------------------------------------|--------------------------------------------------------|
| `runbook://dynamodb-hot-partition`     | Step-by-step DynamoDB hot-partition investigation      |

Each runbook is a markdown file in [`runbooks/`](runbooks/). Add a new file,
restart, get a new runbook. See [docs/04-runbooks.md](docs/04-runbooks.md).

---

## Documentation

Start with [`docs/`](docs/) — read in order:

1. [What is MCP, and why are we building one?](docs/00-what-is-mcp.md)
2. [Architecture of this server](docs/01-architecture.md)
3. [AWS authentication](docs/02-aws-auth.md)
4. [Adding a new tool](docs/03-adding-tools.md)
5. [Runbooks as resources](docs/04-runbooks.md)
6. [Connecting a client](docs/05-connecting-clients.md)

Every source file also has a header comment explaining **why it exists**, not
just what it does. If something looks like framework magic, the comment
breaks it down.

---

## Project layout

```
mcp-devstack/
├── README.md                   ← you are here
├── pyproject.toml              ← deps, entrypoint script
├── .env.example                ← copy to .env, edit
├── docs/                       ← read in order
├── runbooks/                   ← markdown, exposed as MCP resources
└── src/devstack_mcp/
    ├── __main__.py             ← entrypoint
    ├── config.py               ← env-var loading
    ├── server.py               ← FastMCP assembly + resource handler
    └── aws/
        ├── session.py          ← cached boto3 Session
        └── dynamodb.py         ← v1 tools live here
```

See [docs/01-architecture.md](docs/01-architecture.md) for the full diagram
of how a tool call flows through these files.

---

## Roadmap

Tracked here so contributors know what's coming and what's already covered.

- [x] DynamoDB read-only (list / describe / get / query / scan)
- [x] Markdown runbooks as MCP resources
- [ ] SQS read-only (list queues, get attributes, peek messages)
- [ ] Athena (start query, get results, list databases)
- [ ] Datadog logs (search by query + time window)
- [ ] Datadog metrics (point query, monitor status)
- [ ] CloudWatch logs (filter pattern, log insights)
- [ ] Per-tool dry-run / explain mode (show what would be called)

When you add a new service, follow [docs/03-adding-tools.md](docs/03-adding-tools.md).

---

## Safety stance

- **Read-only by construction.** Write APIs are not implemented, not just disabled by a flag.
- **Your credentials, your blast radius.** The server uses whatever IAM your `AWS_PROFILE` has. Give it least-privilege — see [docs/02-aws-auth.md](docs/02-aws-auth.md) for the minimum policy.
- **No outbound calls except to AWS / Datadog.** No telemetry. No update checks.
- **Errors include hints, not secrets.** Error formatting redacts internals and points at the next likely step. See `_format_aws_error` in [aws/dynamodb.py](src/devstack_mcp/aws/dynamodb.py).

---

## License

MIT.
