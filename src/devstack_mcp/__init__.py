"""devstack_mcp — an MCP server exposing AWS tooling for incident analysis.

The package is intentionally tiny at the top level. Real code lives in:
  - server.py   — builds the FastMCP instance and registers tools/resources
  - config.py   — reads environment variables
  - aws/        — one module per AWS service (dynamodb today, athena/sqs later)

The MCP runtime imports `server.mcp` (the FastMCP instance) when it starts.
"""

__version__ = "0.1.0"
