# Runbook: Investigate a suspected DynamoDB hot partition

## Goal

Determine whether a DynamoDB table is experiencing a **hot partition** —
a single partition key receiving disproportionate read/write traffic and
causing throttling (`ProvisionedThroughputExceededException`) even though
the table's overall capacity looks under-utilised.

## When to use

- Users report intermittent DynamoDB errors on one table.
- CloudWatch shows `ThrottledRequests` > 0 but `ConsumedCapacity` is well below provisioned.
- A single tenant / user / shard is suspected of generating most traffic.

## Inputs you need

- `table_name` — the DynamoDB table being investigated.
- `region` — optional, defaults to the server's configured region.
- A hypothesis for which partition key value(s) might be hot (optional, but speeds things up).

## Steps

1. **Confirm the table exists and inspect its key schema.**
   Call `dynamodb_describe_table` with `{table_name, region}`. Note:
   - the partition key attribute name (this is what gets hashed across partitions)
   - whether a sort key exists
   - the item count and size (gives you a rough sense of scale)
   - whether there are GSIs — GSIs have their own partitions and can hot-spot independently

2. **If a hypothesis was provided, query the suspected hot partition.**
   Call `dynamodb_query` with the suspected `partition_key_name` and `partition_key_value`,
   `limit=10`, `scan_index_forward=false` (newest first if sort key is a timestamp).
   - A `count` close to `limit` with very recent sort-key values suggests heavy concurrent writes/reads on this partition.

3. **If no hypothesis, sample the table to look for skew.**
   Call `dynamodb_scan` with `limit=200`. Group the returned items by partition key value (do this in your head / in the response).
   - If one PK value appears in > 30% of the sample, that's a strong hot-partition signal.
   - If the sample looks uniform, the issue may be elsewhere (GSI throttling, capacity misconfig).

4. **Cross-check with the application.**
   Ask the user: "Does partition key value `X` correspond to a single high-traffic tenant / user / device?"
   - If yes → the fix is in the application's data model (add a shard suffix, split the entity).
   - If no → escalate to a human; this runbook can't go further without app context.

5. **Summarise findings.**
   Report back, in this order:
   - Table schema (PK/SK, GSIs, scale)
   - Evidence collected (which queries/scans, what was observed)
   - Hot partition? Yes / No / Inconclusive
   - Recommended next action (re-shard, add GSI, raise capacity, or escalate)

## Stop conditions

- **Stop and ask the human** if the table has > 1 billion items (the sample in step 3 won't be representative).
- **Stop and ask the human** if any tool returns `AccessDeniedException` — the runbook can't proceed without the missing permission, and a human needs to decide whether to grant it.
- **Never call any write tool.** This server doesn't expose any, but the runbook reiterates the rule for clarity.
