"""Cached boto3 session and client factories.

Why a cache?
  - boto3 sessions are heavyweight (they load config files, resolve creds).
  - Creating a fresh client per tool call adds ~100ms of overhead.
  - The session itself is thread-safe; clients are also safe to share.

We key clients by (service_name, region) so a single server can talk to
multiple regions without re-authenticating.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import boto3

from devstack_mcp.config import load_settings


@lru_cache(maxsize=1)
def _session() -> boto3.Session:
    """Build the boto3 Session once per process.

    boto3 will resolve credentials in this order (the "default chain"):
      1. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY env vars
      2. The named profile in ~/.aws/credentials (AWS_PROFILE)
      3. EC2/ECS/Lambda instance role
    See docs/02-aws-auth.md for a deeper walk-through.
    """
    settings = load_settings()
    return boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)


@lru_cache(maxsize=32)
def get_client(service: str, region: str | None = None) -> Any:
    """Return a cached low-level boto3 client (e.g. dynamodb, sqs, athena).

    Low-level clients return raw AWS API responses — useful when you want
    full control. For DynamoDB items specifically we prefer the *resource*
    interface (see get_resource) because it auto-converts AttributeValue.
    """
    settings = load_settings()
    return _session().client(service, region_name=region or settings.aws_region)


@lru_cache(maxsize=32)
def get_resource(service: str, region: str | None = None) -> Any:
    """Return a cached high-level boto3 resource (currently only used for dynamodb).

    The resource interface deserialises DynamoDB's typed AttributeValue format
    ({"S": "foo"}, {"N": "42"}) into native Python types automatically.
    That saves us a lot of boilerplate in the tool layer.
    """
    settings = load_settings()
    return _session().resource(service, region_name=region or settings.aws_region)
