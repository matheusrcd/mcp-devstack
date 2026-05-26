"""Process entrypoint.

Two equivalent ways to start the server, both arrive here:
  - `python -m devstack_mcp`
  - `devstack-mcp`            (the script defined in pyproject.toml)
"""

from devstack_mcp.server import run


def main() -> None:
    run()


if __name__ == "__main__":
    main()
