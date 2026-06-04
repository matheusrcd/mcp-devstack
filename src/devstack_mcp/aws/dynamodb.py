"""DynamoDB read-only tools.

Design notes (read these before adding a new tool here):

1. EVERY tool here is read-only. We never expose put_item, delete_item, update_item,
   or batch_write. The MCP `destructiveHint` annotation reflects this — but it's a
   hint, not a guard. The real guard is that we simply don't implement write APIs.

2. We expose four primitives that compose into most read use cases:
       list_tables       -> "what's in this account/region?"
       describe_table    -> "what's the schema/indexes of this table?"
       get_item          -> "give me exactly one item by primary key"
       query             -> "give me items by partition key (+ optional sort condition)"
       scan              -> "I have no PK; cap it and filter server-side"

3. Why expose raw KeyConditionExpression / FilterExpression strings instead of
   building a typed query DSL? Because LLM agents are good at writing the AWS
   expression syntax (it's well-documented and shows up in their training data),
   and a custom DSL would just be a leaky wrapper around it. We stay close to
   the AWS API surface so the agent can use AWS docs directly.

4. Scan is intentionally capped (default 50, max 500). Unbounded scans in
   production tables can be a real outage. The docstring says so loudly so
   an agent knows when NOT to reach for it.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from devstack_mcp.aws.session import get_client, get_resource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------
# DynamoDB returns numbers as `Decimal` because JSON's float can't safely
# represent every AWS-supported number. Standard json.dumps doesn't know how
# to serialise Decimal, so we provide a default= hook.
class _DynamoJSONEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            # If the value has no fractional part, return int; otherwise float.
            # This is "good enough" for human-readable output — agents reading
            # the JSON don't need full Decimal precision.
            return int(o) if o == o.to_integral_value() else float(o)
        if isinstance(o, (bytes, bytearray)):
            return o.decode("utf-8", errors="replace")
        return super().default(o)


def _dump(obj: Any) -> str:
    """Pretty-print dicts/lists as JSON, handling Decimals."""
    return json.dumps(obj, indent=2, cls=_DynamoJSONEncoder, default=str)


def _format_aws_error(e: Exception) -> str:
    """Turn boto exceptions into actionable, agent-friendly messages.

    Why this matters: a raw `ClientError` stack trace tells the agent nothing.
    A message like "Table 'orders' not found in region us-east-1. Use
    dynamodb_list_tables to see available tables." gives it a next step.
    """
    if isinstance(e, ClientError):
        code = e.response.get("Error", {}).get("Code", "Unknown")
        msg = e.response.get("Error", {}).get("Message", str(e))
        hints = {
            "ResourceNotFoundException": (
                "The table doesn't exist in this region. "
                "Call dynamodb_list_tables to see what's available, "
                "or pass a different `region`."
            ),
            "AccessDeniedException": (
                "Your AWS profile lacks permission for this DynamoDB action. "
                "Check the IAM policy attached to the profile in ~/.aws/credentials."
            ),
            "ValidationException": (
                "AWS rejected the request as malformed. "
                "Most often this means the Key dict's attribute names/types don't match the table's primary key. "
                "Use dynamodb_describe_table to inspect the schema."
            ),
            "ProvisionedThroughputExceededException": (
                "The table is being throttled. Retry with a smaller `limit`, "
                "or wait a few seconds before trying again."
            ),
        }
        hint = hints.get(code, "")
        return f"Error [{code}]: {msg}" + (f"\nHint: {hint}" if hint else "")

    if isinstance(e, BotoCoreError):
        return (
            f"Error: AWS client failure ({type(e).__name__}: {e}). "
            "This usually means credentials or network — check `aws sts get-caller-identity` works."
        )

    return f"Error: Unexpected {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Input models — one per tool, each with strict validation.
# ---------------------------------------------------------------------------
# Why a model per tool (instead of one giant model with optional fields)?
# Because FastMCP generates the tool's JSON schema from the model. Separate
# models = each tool has a minimal, precise schema the LLM can reason about.

_STRICT = ConfigDict(str_strip_whitespace=True, extra="forbid")


class ListTablesInput(BaseModel):
    model_config = _STRICT
    region: str | None = Field(
        default=None,
        description="AWS region override, e.g. 'us-east-1'. Defaults to the server's configured region.",
    )
    limit: int = Field(
        default=100,
        ge=1,
        le=100,
        description="Max table names to return (AWS hard-caps this page at 100).",
    )
    start_table_name: str | None = Field(
        default=None,
        description="Pagination cursor. Pass the `next_start_table_name` from the previous response.",
    )


class DescribeTableInput(BaseModel):
    model_config = _STRICT
    table_name: str = Field(..., min_length=3, max_length=255, description="DynamoDB table name.")
    region: str | None = Field(default=None, description="AWS region override.")


class GetItemInput(BaseModel):
    model_config = _STRICT
    table_name: str = Field(..., min_length=3, max_length=255)
    key: dict[str, Any] = Field(
        ...,
        description=(
            "Primary key as a plain dict, e.g. {'user_id': 'u_123'} for a hash-only key, "
            "or {'user_id': 'u_123', 'created_at': 1700000000} for hash+range. "
            "Attribute names and types MUST match the table's key schema exactly — "
            "use dynamodb_describe_table to check."
        ),
    )
    region: str | None = Field(default=None)


class QueryInput(BaseModel):
    model_config = _STRICT
    table_name: str = Field(..., min_length=3, max_length=255)
    partition_key_name: str = Field(
        ...,
        description="The table's partition (HASH) key attribute name, e.g. 'user_id'.",
    )
    partition_key_value: Any = Field(
        ...,
        description="The value to match for the partition key (string, number, or bytes).",
    )
    sort_key_name: str | None = Field(
        default=None,
        description="Optional sort (RANGE) key attribute name, if you want to filter on it.",
    )
    sort_key_condition: str | None = Field(
        default=None,
        description=(
            "One of: 'eq', 'lt', 'lte', 'gt', 'gte', 'begins_with', 'between'. "
            "Used together with sort_key_value(s)."
        ),
    )
    sort_key_value: Any = Field(default=None, description="Value for sort key conditions other than 'between'.")
    sort_key_value_2: Any = Field(default=None, description="Upper bound for 'between' condition.")
    index_name: str | None = Field(
        default=None,
        description="Optional GSI/LSI name to query instead of the base table.",
    )
    limit: int = Field(default=50, ge=1, le=500, description="Max items to return.")
    scan_index_forward: bool = Field(
        default=True,
        description="True = ascending sort key order; False = descending (newest-first if sort key is a timestamp).",
    )
    region: str | None = Field(default=None)


class ScanInput(BaseModel):
    model_config = _STRICT
    table_name: str = Field(..., min_length=3, max_length=255)
    filter_expression: str | None = Field(
        default=None,
        description=(
            "Optional DynamoDB FilterExpression string, e.g. '#s = :status'. "
            "Filtering is applied AFTER the scan — it does not reduce read cost, only response size."
        ),
    )
    expression_attribute_names: dict[str, str] | None = Field(
        default=None,
        description="Maps placeholders like '#s' to real attribute names, e.g. {'#s': 'status'}.",
    )
    expression_attribute_values: dict[str, Any] | None = Field(
        default=None,
        description="Maps placeholders like ':status' to values, e.g. {':status': 'FAILED'}.",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=500,
        description="HARD CAP on items returned. Scans are expensive — prefer dynamodb_query when you have a partition key.",
    )
    region: str | None = Field(default=None)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
# Each tool is a small async wrapper around boto3. The Pydantic model has
# already validated input by the time we get here, so the body focuses on
# the AWS call + response shaping.


def register(mcp: FastMCP) -> None:
    """Attach DynamoDB tools to the given FastMCP instance.

    Called once from server.py. Keeping registration in a function (rather
    than module-level decorators) lets server.py be the single source of
    truth for which tools the server exposes.
    """

    @mcp.tool(
        name="dynamodb_list_tables",
        annotations={
            "title": "List DynamoDB tables",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def dynamodb_list_tables(params: ListTablesInput) -> str:
        """List DynamoDB table names in a region.

        Use this first when you don't know what tables exist, or to confirm
        you're targeting the right region. Returns up to 100 names per page
        and a `next_start_table_name` cursor when more pages exist.
        """
        try:
            client = get_client("dynamodb", region=params.region)
            kwargs: dict[str, Any] = {"Limit": params.limit}
            if params.start_table_name:
                kwargs["ExclusiveStartTableName"] = params.start_table_name
            resp = client.list_tables(**kwargs)
            return _dump(
                {
                    "table_names": resp.get("TableNames", []),
                    "next_start_table_name": resp.get("LastEvaluatedTableName"),
                    "has_more": "LastEvaluatedTableName" in resp,
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("dynamodb_list_tables failed")
            return _format_aws_error(e)

    @mcp.tool(
        name="dynamodb_describe_table",
        annotations={
            "title": "Describe DynamoDB table schema",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def dynamodb_describe_table(params: DescribeTableInput) -> str:
        """Return key schema, GSIs/LSIs, item count, and size for a table.

        Always call this before dynamodb_get_item or dynamodb_query when you're
        not 100% sure of the table's partition/sort key attribute names — the
        wrong attribute name causes a ValidationException with no useful detail.
        """
        try:
            client = get_client("dynamodb", region=params.region)
            resp = client.describe_table(TableName=params.table_name)
            t = resp["Table"]
            # We deliberately project to a compact shape rather than dumping the
            # full DescribeTable response, which is noisy (provisioned-throughput
            # history, ARN, replicas, etc.). Agents do better with focused data.
            summary = {
                "table_name": t["TableName"],
                "status": t.get("TableStatus"),
                "item_count": t.get("ItemCount"),
                "size_bytes": t.get("TableSizeBytes"),
                "key_schema": t.get("KeySchema"),
                "attribute_definitions": t.get("AttributeDefinitions"),
                "global_secondary_indexes": [
                    {"name": gsi["IndexName"], "key_schema": gsi["KeySchema"]}
                    for gsi in t.get("GlobalSecondaryIndexes", [])
                ],
                "local_secondary_indexes": [
                    {"name": lsi["IndexName"], "key_schema": lsi["KeySchema"]}
                    for lsi in t.get("LocalSecondaryIndexes", [])
                ],
                "billing_mode": t.get("BillingModeSummary", {}).get("BillingMode")
                or ("PROVISIONED" if t.get("ProvisionedThroughput", {}).get("ReadCapacityUnits") else None),
            }
            return _dump(summary)
        except Exception as e:  # noqa: BLE001
            logger.exception("dynamodb_describe_table failed")
            return _format_aws_error(e)

    @mcp.tool(
        name="dynamodb_get_item",
        annotations={
            "title": "Get a single DynamoDB item by primary key",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def dynamodb_get_item(params: GetItemInput) -> str:
        """Fetch exactly one item by its primary key.

        This is the cheapest DynamoDB operation — always prefer it when you
        already know the partition key (and sort key if the table has one).
        Returns the item as a JSON object, or `{"found": false}` when no item
        matches the given key.
        """
        try:
            table = get_resource("dynamodb", region=params.region).Table(params.table_name)
            resp = table.get_item(Key=params.key)
            item = resp.get("Item")
            if item is None:
                return _dump({"found": False, "key": params.key})
            return _dump({"found": True, "item": item})
        except Exception as e:  # noqa: BLE001
            logger.exception("dynamodb_get_item failed")
            return _format_aws_error(e)

    @mcp.tool(
        name="dynamodb_query",
        annotations={
            "title": "Query DynamoDB by partition key",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def dynamodb_query(params: QueryInput) -> str:
        """Query items sharing a partition key, optionally narrowed by sort key.

        Examples of when to use this:
          - "All orders for user u_123"  -> partition_key=user_id, value='u_123'
          - "Orders for u_123 created after Jan 1"
              -> add sort_key_name='created_at', sort_key_condition='gt',
                 sort_key_value=1704067200

        Set `scan_index_forward=False` to get newest-first when the sort key
        is a timestamp.
        """
        try:
            table = get_resource("dynamodb", region=params.region).Table(params.table_name)

            # Build the KeyConditionExpression with boto3's typed Condition builder.
            # Using the builder (rather than a raw string) means we don't have to
            # manage ExpressionAttributeNames/Values ourselves for the key.
            kce = Key(params.partition_key_name).eq(params.partition_key_value)

            if params.sort_key_name and params.sort_key_condition:
                sk = Key(params.sort_key_name)
                cond = params.sort_key_condition.lower()
                if cond == "eq":
                    kce = kce & sk.eq(params.sort_key_value)
                elif cond == "lt":
                    kce = kce & sk.lt(params.sort_key_value)
                elif cond == "lte":
                    kce = kce & sk.lte(params.sort_key_value)
                elif cond == "gt":
                    kce = kce & sk.gt(params.sort_key_value)
                elif cond == "gte":
                    kce = kce & sk.gte(params.sort_key_value)
                elif cond == "begins_with":
                    kce = kce & sk.begins_with(params.sort_key_value)
                elif cond == "between":
                    if params.sort_key_value is None or params.sort_key_value_2 is None:
                        return (
                            "Error: 'between' condition requires both sort_key_value "
                            "(lower bound) and sort_key_value_2 (upper bound)."
                        )
                    kce = kce & sk.between(params.sort_key_value, params.sort_key_value_2)
                else:
                    return (
                        f"Error: Unknown sort_key_condition '{params.sort_key_condition}'. "
                        "Allowed: eq, lt, lte, gt, gte, begins_with, between."
                    )

            kwargs: dict[str, Any] = {
                "KeyConditionExpression": kce,
                "Limit": params.limit,
                "ScanIndexForward": params.scan_index_forward,
            }
            if params.index_name:
                kwargs["IndexName"] = params.index_name

            resp = table.query(**kwargs)
            return _dump(
                {
                    "count": resp.get("Count", 0),
                    "scanned_count": resp.get("ScannedCount", 0),
                    "items": resp.get("Items", []),
                    "has_more": "LastEvaluatedKey" in resp,
                    "last_evaluated_key": resp.get("LastEvaluatedKey"),
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("dynamodb_query failed")
            return _format_aws_error(e)

    @mcp.tool(
        name="dynamodb_scan",
        annotations={
            "title": "Scan a DynamoDB table (capped)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def dynamodb_scan(params: ScanInput) -> str:
        """Scan a table with an optional server-side filter. CAPPED AT 500 ITEMS.

        Important caveats:
          - Scan reads every item in the page, even if your filter drops them.
            That means scan COSTS the same whether you filter or not.
          - Prefer dynamodb_query whenever you know the partition key.
          - This tool will never return more than `limit` items (max 500) and
            does NOT auto-paginate. Use `last_evaluated_key` to continue if
            needed (not yet exposed as a tool input — add it when required).
        """
        try:
            table = get_resource("dynamodb", region=params.region).Table(params.table_name)
            kwargs: dict[str, Any] = {"Limit": params.limit}
            if params.filter_expression:
                kwargs["FilterExpression"] = params.filter_expression
            if params.expression_attribute_names:
                kwargs["ExpressionAttributeNames"] = params.expression_attribute_names
            if params.expression_attribute_values:
                kwargs["ExpressionAttributeValues"] = params.expression_attribute_values

            resp = table.scan(**kwargs)
            return _dump(
                {
                    "count": resp.get("Count", 0),
                    "scanned_count": resp.get("ScannedCount", 0),
                    "items": resp.get("Items", []),
                    "has_more": "LastEvaluatedKey" in resp,
                    "last_evaluated_key": resp.get("LastEvaluatedKey"),
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("dynamodb_scan failed")
            return _format_aws_error(e)
