# Architecture Decision Records

Switchyard records significant architecture decisions as ADRs in the
[MADR](https://adr.github.io/madr/) format: status, context, decision drivers, considered
options with pros and cons, decision and consequences, linked to requirement IDs.

Each ADR is written in the milestone that introduces its decision (FR-109). The task that writes
an ADR changes only its own row in this table from `planned` to `accepted`.

| # | Title | Status | Milestone | Task |
|---|---|---|---|---|
| [001](0001-openai-compatible-api-and-canonical-schema.md) | OpenAI-compatible API and canonical schema | accepted | M0 | T04 |
| [002](0002-runtime-ecs-fargate.md) | Run the gateway on AWS ECS Fargate | accepted | M0 | T04 |
| 003 | Request lifecycle state machine and idempotent settlement | planned | M1 | T06 |
| 004 | Error taxonomy, retry classification and retry budget | planned | M4 | T17 |
| 005 | Streaming semantics, layered timeouts and cancellation | planned | M4 | T19 |
| 006 | Postgres-only budget reservation | planned | M6 | T25 |
| 007 | Capability registry and capability-aware fallback | planned | M2 | T10 |
| 008 | Tenant isolation and HMAC-SHA-256 API keys | planned | M5 | T21 |
| 009 | Exact cache eligibility; semantic cache deferred | planned | M7 | T28 |
| 010 | Policy versioning and last-known-good config | planned | M3 | T16 |

## Status values

- `planned` — the decision is recorded in `.claude/project_memory/decisions.md`; the ADR file is not written yet.
- `accepted` — the ADR file exists and the decision is in force.
- `superseded by NNN` — replaced by a later ADR; the old file is kept for history.

## Writing a new ADR

1. Copy the structure of [ADR-001](0001-openai-compatible-api-and-canonical-schema.md).
2. Name the file `NNNN-short-kebab-title.md` with the next free number.
3. Link the requirement IDs it covers and update its row here in the same commit.
