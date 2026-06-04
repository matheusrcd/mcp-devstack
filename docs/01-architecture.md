# 01 — Architecture of this server

## File-by-file map

```
mcp-devstack/
├── pyproject.toml              # deps + entrypoint script
├── .env.example                # copy to .env, edit
├── runbooks/                   # exposed as MCP resources at runbook://<name>
│   ├── README.md               # how to write a runbook
│   └── dynamodb-hot-partition.md
├── docs/                       # the docs you're reading
└── src/devstack_mcp/
    ├── __init__.py             # package marker
    ├── __main__.py             # entrypoint — `python -m devstack_mcp`
    ├── config.py               # reads env vars; central Settings dataclass
    ├── server.py               # builds FastMCP, registers tools + resources
    └── aws/
        ├── __init__.py
        ├── session.py          # cached boto3 Session / clients / resources
        └── dynamodb.py         # Pydantic inputs + tool functions for DynamoDB
```

## How a single tool call gets executed

This diagram traces what happens when Claude calls `dynamodb_query`:

```
                                                  ┌──────────────────────────┐
   1. Client sends JSON-RPC                       │ src/devstack_mcp/        │
      tools/call {                                │   server.py              │
        name: "dynamodb_query",                   │                          │
        arguments: { table_name: "orders",        │  FastMCP("devstack_mcp") │
                     partition_key_name: "uid",   │      ├─ register(dynamodb)
                     partition_key_value: "u_1" } │      └─ @resource runbook│
      }                                           │                          │
                                                  └─────────────┬────────────┘
                                                                │
                                                                ▼
   2. FastMCP looks up the tool by name           ┌──────────────────────────┐
      and validates the args against the          │ aws/dynamodb.py          │
      Pydantic model (QueryInput).                │                          │
                                                  │  QueryInput  (Pydantic)  │
                                                  │     ↓ validated          │
                                                  │  dynamodb_query(params)  │
                                                  └─────────────┬────────────┘
                                                                │
   3. The tool calls boto3.                                     ▼
      First time: build a cached Session         ┌──────────────────────────┐
      from ~/.aws/credentials.                    │ aws/session.py           │
                                                  │   _session()  ← lru_cache│
                                                  │   get_resource("dynamodb")│
                                                  └─────────────┬────────────┘
                                                                │
                                                                ▼
                                                  ┌──────────────────────────┐
                                                  │  AWS DynamoDB API        │
                                                  │  (over the network)      │
                                                  └─────────────┬────────────┘
                                                                │
   4. boto3 deserialises AttributeValue                         ▼
      back to Python types. We wrap the                ┌─────────────────┐
      response with count / items / has_more           │  JSON response  │
      and json.dumps it.                                │  (with Decimal  │
                                                       │   encoder)      │
                                                       └────────┬────────┘
                                                                │
                                                                ▼
   5. FastMCP wraps the string in an MCP                ┌──────────────────┐
      "content" envelope and sends it back              │ → back to client │
      over stdout.                                      └──────────────────┘
```

## Why this layering

1. **`config.py` knows about env vars, nobody else does.** Tools take their
   region from a Pydantic field that defaults to `None`; when `None`, the
   `session` helper falls back to `Settings.aws_region`. Means tools are
   easy to unit-test — pass a region explicitly, no env needed.

2. **`aws/session.py` owns boto3.** No tool imports `boto3` directly. If we
   ever need to swap to async boto (aioboto3) or mock the AWS layer for
   tests, there's exactly one file to change.

3. **One file per AWS service in `aws/`.** Each file has a `register(mcp)`
   function. `server.py` calls them all. Adding SQS later = add
   `aws/sqs.py`, call `sqs.register(mcp)` in `server.py`. No dynamic discovery.

4. **Runbooks are not code.** They're markdown files. The `@mcp.resource`
   handler in `server.py` reads them. A new runbook = a new `.md` file.
   No deploy, no restart needed for the *content* (the resource list does
   currently get registered at startup, so for new *files* you do need a
   restart — but editing an existing runbook is live).

## Swapping transports (when you outgrow stdio)

Today, [`server.py`](../src/devstack_mcp/server.py) ends with:

```python
mcp.run()                              # stdio (default)
```

To run as a long-lived HTTP service that multiple teammates can hit:

```python
mcp.run(transport="streamable_http", port=8000)
```

That's literally the only code change. You then also have to:
- put it behind auth (the MCP spec supports OAuth 2.1 bearer tokens)
- decide whose AWS credentials it uses (no longer "yours" — probably an IAM role)
- run it somewhere (Fargate / Lambda / a VM)

Don't do this yet. Get value from the stdio version first.
