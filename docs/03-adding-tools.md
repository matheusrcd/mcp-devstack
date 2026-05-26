# 03 — Adding a new tool

This walks through adding a new tool **end-to-end**, using a hypothetical
`sqs_list_queues` tool as the example. Read it once, then use the template at
the bottom as your starting point.

## The pattern

Every tool in this server is built from four pieces:

1. **A Pydantic input model** — declares the args, their types, constraints, and descriptions.
2. **A tool function** — async, takes the model instance, returns a string.
3. **A `@mcp.tool` decorator** — registers it and supplies the annotations.
4. **A `register(mcp)` function** — called by `server.py` at startup.

Pieces 1–3 live in a service module like `aws/dynamodb.py`. Piece 4 wraps them.

## Step 1 — Create the service module

If the new tool belongs to a service we don't have yet, create
`src/devstack_mcp/aws/<service>.py`. For SQS:

```python
# src/devstack_mcp/aws/sqs.py
from __future__ import annotations
import json, logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from devstack_mcp.aws.session import get_client

logger = logging.getLogger(__name__)
```

## Step 2 — Define the Pydantic input model

```python
class ListQueuesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name_prefix: str | None = Field(
        default=None,
        description="Only return queues whose name starts with this prefix.",
        max_length=80,
    )
    limit: int = Field(default=100, ge=1, le=1000)
    region: str | None = Field(default=None)
```

**Why each field has a description:** FastMCP turns these into the tool's JSON
schema. The LLM reads those descriptions when deciding whether and how to
call the tool. **A field without a good description is a field the agent
will misuse.**

## Step 3 — Write the tool function

```python
def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="sqs_list_queues",
        annotations={
            "title": "List SQS queues",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def sqs_list_queues(params: ListQueuesInput) -> str:
        """List SQS queue URLs in a region, optionally filtered by name prefix.

        Use this to find queues during incident triage — for example,
        "show me all queues whose name starts with `orders-`".
        Returns queue URLs (not just names) so other SQS tools can use them.
        """
        try:
            client = get_client("sqs", region=params.region)
            kwargs: dict[str, Any] = {"MaxResults": params.limit}
            if params.name_prefix:
                kwargs["QueueNamePrefix"] = params.name_prefix
            resp = client.list_queues(**kwargs)
            return json.dumps(
                {
                    "queue_urls": resp.get("QueueUrls", []),
                    "next_token": resp.get("NextToken"),
                },
                indent=2,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("sqs_list_queues failed")
            return f"Error: {type(e).__name__}: {e}"
```

### What each annotation means

| Annotation        | Meaning                                                                         |
|-------------------|---------------------------------------------------------------------------------|
| `readOnlyHint`    | `True` if the tool never modifies state. Clients may auto-approve these.        |
| `destructiveHint` | `True` if the tool can delete or break things. Clients should warn loudly.      |
| `idempotentHint`  | `True` if calling twice with the same args has the same effect as calling once. |
| `openWorldHint`   | `True` if the tool talks to an external system whose state the agent doesn't control. |

These are *hints*, not security guarantees. The real safety comes from not
exposing destructive APIs at all.

## Step 4 — Wire it up in `server.py`

```python
# src/devstack_mcp/server.py
from devstack_mcp.aws import dynamodb, sqs   # <-- add the import

# ... mcp = FastMCP(...) ...

dynamodb.register(mcp)
sqs.register(mcp)                            # <-- and the call
```

That's it. Restart the server; the tool now appears in any connected client.

## Step 5 — Document the tool's purpose

The tool's **docstring is its product documentation** — it's literally the
text the LLM reads to decide whether to use it. A weak docstring leads to
the tool being ignored or misused.

A good tool docstring:
- says what it does in one sentence
- gives 1–2 example user requests that should trigger it
- mentions when *not* to use it (point to a better tool)
- documents the return shape if it's not obvious

Compare:

> "Lists queues."  ← will be ignored

> "List SQS queue URLs in a region, optionally filtered by name prefix. Use this to find queues during incident triage — for example, 'show me all queues whose name starts with `orders-`'. Returns queue URLs (not just names) so other SQS tools can use them."  ← will be used correctly

## Copy-paste template

```python
# src/devstack_mcp/aws/<service>.py
from __future__ import annotations
import json, logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from devstack_mcp.aws.session import get_client

logger = logging.getLogger(__name__)

class _MyToolInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    # add fields here, each with description=...
    region: str | None = Field(default=None)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="<service>_<action>_<resource>",
        annotations={
            "title": "<Human-readable title>",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def _my_tool(params: _MyToolInput) -> str:
        """<One-line description.>

        <Example user requests this tool should handle.>
        <When NOT to use this tool.>
        """
        try:
            client = get_client("<service>", region=params.region)
            resp = client.<api_call>(...)
            return json.dumps(resp, indent=2, default=str)
        except Exception as e:  # noqa: BLE001
            logger.exception("<service>_<action> failed")
            return f"Error: {type(e).__name__}: {e}"
```
