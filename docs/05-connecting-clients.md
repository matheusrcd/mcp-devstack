# 05 — Connecting a client

You have a working MCP server. Now you need a client (Claude Desktop, Cursor,
your own agent, etc.) to launch it and talk to it.

## Prerequisite

Install the package into a virtualenv so the `devstack-mcp` script is on a
known path:

```bash
cd /Users/matheus/Code/mcp-devstack
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
which devstack-mcp     # note this path — clients need the absolute path
```

The `-e .` (editable install) means code changes take effect without
reinstalling. Restart the client to pick up changes though, because each
client caches the tool list at startup.

## Claude Desktop (macOS)

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "devstack": {
      "command": "/Users/matheus/Code/mcp-devstack/.venv/bin/devstack-mcp",
      "env": {
        "AWS_PROFILE": "default",
        "AWS_REGION": "us-east-1"
      }
    }
  }
}
```

Why we pass env vars in the client config (instead of relying on `.env`):
Claude Desktop launches the server with a stripped environment, so `AWS_PROFILE`
in your shell does NOT propagate to the subprocess. Setting it here is the
reliable path.

After editing, **fully quit and restart Claude Desktop** (Cmd+Q — not just
close the window). When it relaunches, you should see "devstack" listed in
the MCP indicator (the little plug icon at the bottom of the input box).

## Cursor

`Settings → MCP → Add new MCP server`:

- **Name**: `devstack`
- **Type**: `command`
- **Command**: `/Users/matheus/Code/mcp-devstack/.venv/bin/devstack-mcp`
- **Env**: `AWS_PROFILE=default`, `AWS_REGION=us-east-1`

## Claude Code (this CLI)

Edit `~/.claude.json` or run:

```bash
claude mcp add devstack /Users/matheus/Code/mcp-devstack/.venv/bin/devstack-mcp \
  --env AWS_PROFILE=default --env AWS_REGION=us-east-1
```

## Sanity check

Once connected, in your client try:

> List my DynamoDB tables in us-east-1.

The agent should call `dynamodb_list_tables` and show you the result. If
that works, the server is wired up correctly.

## Debugging

stdio MCP servers log to **stderr**. The client usually captures it:

- **Claude Desktop**: `~/Library/Logs/Claude/mcp*.log`
- **Cursor**: `Help → Show Logs → MCP`
- **Claude Code**: pass `--mcp-debug` when starting

If the server fails to start, you'll see the Python traceback in one of those
logs. Most common cause: virtualenv path wrong in `command`.
