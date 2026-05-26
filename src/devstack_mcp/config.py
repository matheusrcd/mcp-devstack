"""Server-wide configuration.

Centralising env-var access in one module means:
  1. Tools never reach into os.environ directly — easier to test and mock.
  2. We can validate required vars at startup and fail fast with a clear error.
  3. There's a single place to document what knobs exist (see .env.example).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load .env into os.environ once, at import time.
# In production (where you set env vars directly), this is a no-op.
load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Immutable bag of settings, built once at startup.

    Using a frozen dataclass (instead of reading os.environ each call) makes it
    obvious to readers that these values don't change while the server is running.
    """

    aws_profile: str
    aws_region: str
    log_level: str


def load_settings() -> Settings:
    """Read environment and return a Settings instance.

    We give every field a sensible default so the server can boot with zero
    configuration on a developer machine that already has `aws configure` done.
    """
    return Settings(
        aws_profile=os.environ.get("AWS_PROFILE", "default"),
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        log_level=os.environ.get("DEVSTACK_MCP_LOG_LEVEL", "INFO").upper(),
    )


def configure_logging(level: str) -> None:
    """Set up logging to STDERR.

    Critical: MCP stdio servers communicate over STDOUT with JSON-RPC frames.
    Any print/log to stdout corrupts that stream and breaks the client.
    Python's logging module defaults to stderr, which is exactly what we want.
    """
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
