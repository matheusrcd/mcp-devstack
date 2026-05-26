"""FastMCP server assembly.

This is the single source of truth for what the server exposes:
  - which tools (via the aws/*.register(mcp) calls)
  - which resources (the runbook markdown files)

To add a new service (e.g. SQS, Athena, Datadog):
  1. Create src/devstack_mcp/aws/<service>.py with a `register(mcp)` function.
  2. Import and call it below.
That's the entire change — no decorator magic, no discovery layer.
"""

from __future__ import annotations

import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from devstack_mcp.aws import dynamodb
from devstack_mcp.config import configure_logging, load_settings

logger = logging.getLogger(__name__)

# The server name follows the MCP best-practice format `{service}_mcp`.
# `devstack_mcp` reflects that this server is a developer toolkit, not tied
# to one AWS service — Athena/SQS/Datadog will live alongside DynamoDB here.
mcp = FastMCP("devstack_mcp")

# Register every service's tools. Order doesn't matter functionally, but
# grouping by service keeps this file readable as it grows.
dynamodb.register(mcp)


# ---------------------------------------------------------------------------
# Runbook resources
# ---------------------------------------------------------------------------
# Runbooks are markdown files in ./runbooks. We expose them as MCP *resources*
# (not tools) because:
#   - Resources are the right primitive for "here is some text the agent can
#     read and reason over". Tools are for "do something / fetch live data".
#   - Clients can list resources and let the user pick one to load into context.
#
# URI template: runbook://<filename-without-extension>
# Example:      runbook://dynamodb-hot-partition

RUNBOOKS_DIR = Path(__file__).resolve().parent.parent.parent / "runbooks"


@mcp.resource("runbook://{name}")
async def get_runbook(name: str) -> str:
    """Return the contents of runbooks/<name>.md.

    Agents call this when the user asks to "run the X runbook" or to "show
    me the incident playbook for Y". The runbook itself contains the steps;
    the agent executes them by calling the appropriate tools.
    """
    # Defence-in-depth against path traversal: only allow simple filenames.
    # An attacker who controls `name` could otherwise try `../../etc/passwd`.
    if "/" in name or ".." in name or name.startswith("."):
        return f"Error: Invalid runbook name '{name}'. Use the slug only, no path separators."

    path = RUNBOOKS_DIR / f"{name}.md"
    if not path.is_file():
        # List available runbooks in the error so the agent can self-correct.
        available = sorted(p.stem for p in RUNBOOKS_DIR.glob("*.md")) if RUNBOOKS_DIR.is_dir() else []
        return (
            f"Error: Runbook '{name}' not found.\n"
            f"Available runbooks: {', '.join(available) if available else '(none)'}"
        )
    return path.read_text(encoding="utf-8")


def run() -> None:
    """Boot the server on stdio transport.

    stdio is the right transport for a developer-machine MCP server:
      - One client (your editor or Claude Desktop) launches it as a subprocess.
      - No network exposure, no auth to configure.
    Swap to `mcp.run(transport="streamable_http", port=8000)` if you later
    want to host the server remotely for a team.
    """
    settings = load_settings()
    configure_logging(settings.log_level)
    logger.info(
        "devstack_mcp starting (aws_profile=%s region=%s)",
        settings.aws_profile,
        settings.aws_region,
    )
    mcp.run()
