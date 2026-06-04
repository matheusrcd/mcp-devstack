"""AWS service modules.

One file per AWS service. Each file:
  - defines Pydantic input models for its tools
  - implements the tool functions
  - exposes a `register(mcp)` function that the server calls at startup

Keeping registration explicit (rather than module-import side effects) means
you can see every tool the server exposes by reading server.py.
"""
