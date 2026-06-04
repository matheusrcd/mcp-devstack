# 00 — What is MCP, and why are we building one?

## The problem MCP solves

An LLM (Claude, GPT, etc.) is a text-in/text-out function. To make it useful for
real work it needs to do three things the model can't do by itself:

1. **Read fresh data** — "what's in the prod `orders` DynamoDB table right now?"
2. **Take actions** — "query Athena", "search Datadog logs", "list SQS queues"
3. **Reference documents** — "load the incident runbook"

Historically every product solved this by inventing its own "tool" plumbing:
OpenAI function-calling, LangChain tools, Anthropic's tool-use API, custom
plugin formats, etc. Each one with a different schema, different transport,
different auth story. If you wrote tools for Claude they didn't work in
Cursor; if you wrote them for Cursor they didn't work in Continue.

**MCP (Model Context Protocol)** is an open standard, introduced by Anthropic
in late 2024, that fixes this. It defines:

- a **wire protocol** (JSON-RPC 2.0) that any LLM client can speak to any tool server
- a small set of **primitives**: *tools*, *resources*, *prompts*
- two **transports**: `stdio` (subprocess) and `streamable HTTP` (remote)

So if you build an "MCP server", any MCP-aware client — Claude Desktop, Cursor,
Continue, Zed, your own agent built on the Anthropic SDK — can use it without
modification.

## The three primitives

| Primitive   | What it is                                | Analogy                              |
|-------------|-------------------------------------------|--------------------------------------|
| **Tool**    | A function the agent can call             | A REST API endpoint                  |
| **Resource**| A piece of content the agent can read     | A file the agent can `cat`           |
| **Prompt**  | A pre-written prompt template the user can pick from | A snippet in your editor             |

This server uses **tools** (one per AWS operation) and **resources** (one per
runbook). We don't use prompts yet.

## How a call actually flows

```
┌─────────────────────┐        JSON-RPC 2.0          ┌──────────────────────┐
│                     │ ───────────────────────────> │                      │
│  Client             │   "tools/call"                │  This MCP server     │
│  (Claude Desktop,   │   { name: "dynamodb_query",   │  (devstack_mcp)      │
│   Cursor, your      │     args: { ... } }           │                      │
│   own agent…)       │                               │   ├─ Pydantic        │
│                     │ <─────────────────────────── │   ├─ boto3 → AWS     │
│                     │   { content: [...text...] }   │   └─ json.dumps      │
└─────────────────────┘                               └──────────────────────┘
        ^                                                        │
        │                                                        │
        └────────────  agent reads response, decides ────────────┘
                       next step (call another tool,
                       answer user, run runbook step…)
```

The agent isn't magic — it's a loop. The client passes the user's message and
the list of available tools to the LLM. The LLM says "call tool X with args Y".
The client invokes the MCP server. The server returns text. The client appends
that text to the conversation and asks the LLM what to do next. Repeat until
the LLM produces a final answer.

## Why "stdio" transport for this server

We start the server as a subprocess of the client (Claude Desktop launches
`devstack-mcp`, and they talk over its stdin/stdout). Trade-offs:

| stdio                                       | streamable HTTP                    |
|---------------------------------------------|-------------------------------------|
| One client, one process — simple            | Many clients can share one server   |
| No network, no auth — secure by default     | Needs TLS, auth, deployment         |
| Right for "tools that read my AWS account"  | Right for "shared team service"     |

For a developer-laptop tool that uses *your* AWS credentials, stdio is the
right choice. We can swap transports later by changing one line in
[`src/devstack_mcp/server.py`](../src/devstack_mcp/server.py) — see [01-architecture.md](01-architecture.md).

## Further reading

- Official spec: https://modelcontextprotocol.io/specification
- Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Why MCP exists (Anthropic announcement): https://www.anthropic.com/news/model-context-protocol
