# 02 — AWS authentication

## TL;DR

This server uses **whatever credentials `boto3` finds**. On your laptop that
means your `~/.aws/credentials` profile. You can verify it works in 5 seconds:

```bash
AWS_PROFILE=your-profile aws sts get-caller-identity
```

If that prints your account + user ARN, the MCP server will see exactly the
same identity.

## The boto3 credential chain (in order)

`boto3.Session(profile_name=...)` walks this chain until something works:

1. **Hard-coded credentials** passed to `Session(aws_access_key_id=..., aws_secret_access_key=...)`. We don't do this.
2. **Environment variables**: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`.
3. **Shared credential file**: `~/.aws/credentials`, profile selected by `AWS_PROFILE` (or `default`).
4. **Shared config file**: `~/.aws/config`. Supports `[profile foo]` blocks that reference SSO, role-assumption, MFA, etc.
5. **EC2/ECS/EKS/Lambda instance metadata service (IMDS)**: when you deploy this on AWS, the role of the instance is used automatically.

That ordering means you can override the configured profile by exporting env
vars in a particular shell, without touching `.env`. Useful when you have a
"read-only-prod" profile and want to use it for one investigation:

```bash
AWS_PROFILE=ro-prod devstack-mcp
```

## Why we picked named profiles for v1

| Option                        | Pros                                | Cons                                                                                  |
|-------------------------------|-------------------------------------|---------------------------------------------------------------------------------------|
| **Named profile (chosen)**    | Already how most engineers auth     | Local-only; doesn't work for a team server                                            |
| Static env vars (`AWS_ACCESS_KEY_ID`) | Trivially obvious                   | Worst-in-class security — long-lived keys, often end up in `.env` and then in git    |
| SSO via `aws sso login`       | Short-lived creds, audit trail      | Slightly more setup; boto3 handles it transparently once configured                   |
| Instance role / IAM role      | Right answer for production         | Requires a deployment story; not useful on a laptop                                   |

You can move to SSO without changing this code at all — boto3 reads SSO
profiles from `~/.aws/config` just like static ones.

## Where we set up the session

[`src/devstack_mcp/aws/session.py`](../src/devstack_mcp/aws/session.py)

```python
@lru_cache(maxsize=1)
def _session() -> boto3.Session:
    settings = load_settings()
    return boto3.Session(profile_name=settings.aws_profile,
                         region_name=settings.aws_region)
```

The `@lru_cache(maxsize=1)` makes this a process-wide singleton — built once,
reused for every tool call. Building a fresh `Session` on every call would
add ~50–100ms of credential resolution per request.

## Minimum IAM policy for v1

The DynamoDB tools need exactly this much. Attach to the IAM user/role your
profile points at:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:ListTables",
        "dynamodb:DescribeTable",
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:Scan"
      ],
      "Resource": "*"
    }
  ]
}
```

When you add Athena / SQS / Datadog later, extend this policy in the same
file alongside your application's IaC.

## Troubleshooting

| Symptom                                                         | Likely cause                                                       |
|-----------------------------------------------------------------|--------------------------------------------------------------------|
| `NoCredentialsError: Unable to locate credentials`              | `AWS_PROFILE` points at a profile that doesn't exist in `~/.aws/credentials`. |
| `ExpiredTokenException`                                          | SSO session expired — run `aws sso login --profile <p>` again.    |
| `AccessDeniedException` on every DynamoDB call                  | IAM policy missing — see "Minimum IAM policy" above.              |
| Works in shell, fails in Claude Desktop                         | Claude Desktop launches the server with a minimal env; either set `AWS_PROFILE` in the client's MCP server config, or use `default` profile. |
