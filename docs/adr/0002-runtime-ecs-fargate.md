# ADR-002: Run the gateway on AWS ECS Fargate

- **Status:** accepted
- **Date:** 2026-11-04
- **Milestone:** M0 (decision), implemented in M9 (T30 graceful shutdown, T31 Terraform, T32 CD pipeline)
- **Deciders:** Switchyard maintainers
- **Requirements:** FR-03, FR-105, FR-106, FR-107, NFR-01, NFR-02, NFR-12, NFR-13
- **Related:** [ADR-001](0001-openai-compatible-api-and-canonical-schema.md) · ADR-005 (streaming and timeouts) · ADR-006 (Postgres budgets)

## Context

Switchyard is a single, stateless HTTP service with stateful dependencies: Postgres for money and
tenancy (ADR-006), Redis for rate limits, breakers and cache, and Secrets Manager for provider keys
and the API-key pepper (ADR-008). Its traffic profile drives the runtime choice:

- **Long-lived SSE responses.** A streamed completion stays open for up to `deadline_ms`
  (60 s by default) across all attempts (ADR-005).
- **Tight latency budget.** Gateway overhead must stay under p95 15 ms non-streaming and
  10 ms added TTFT for streams (NFR-01, NFR-02).
- **Warm connection pools.** Each request does at least two short Postgres writes
  (reserve, settle) and several Redis calls; per-request connection setup would consume
  most of the latency budget.
- **Zero truncated streams on deploy** (NFR-12): a rolling deploy must drain in-flight
  streams, not cut them.

The project is built and operated by one person, so operational load counts as a real cost.

## Decision drivers

1. Native support for long-lived streaming HTTP responses.
2. Predictable latency: no cold starts on the request path.
3. Persistent connection pools to RDS Postgres and ElastiCache Redis.
4. Graceful SIGTERM drain that the load balancer respects (FR-107).
5. Low operational overhead and fixed cost for a single service.
6. Fully reproducible from Terraform, with one-step rollback (FR-105, FR-106).

## Considered options

### Option A — ECS Fargate behind an ALB (chosen)

Long-running container tasks in private subnets, an Application Load Balancer in front,
RDS Postgres, ElastiCache Redis and Secrets Manager, all in Terraform.

- Good: long-lived HTTP/SSE connections are normal; the only limit is the ALB idle timeout (configurable, default 60 s, raised above the stream idle timeout).
- Good: tasks stay warm, so async SQLAlchemy and redis-py pools are reused across requests.
- Good: ECS sends SIGTERM and waits `stopTimeout` (up to 120 s on Fargate) before SIGKILL, enough to drain a 60 s stream.
- Good: no nodes, AMIs or cluster upgrades to manage; rollback is "redeploy the previous task definition".
- Bad: you pay for idle tasks (a minimum of 2 tasks for availability) even at zero traffic.
- Bad: AWS-specific; task definitions, ALB and IAM wiring do not port to other clouds.

### Option B — AWS Lambda (with response streaming)

- Good: scale to zero; pay per request; no servers.
- Bad: hard **15-minute** maximum duration per invocation, and response streaming is capped (200 MB per streamed response since July 2025, previously 20 MB; buffered responses 6 MB), with native streaming support aimed at Node.js; Python needs a custom runtime or web adapter.
- Bad: when fronted by API Gateway REST APIs, the default 29 s integration timeout cuts long streams (raisable for Regional/private REST APIs since June 2024 via a quota request, at the cost of a lower account throttle), and the API Gateway proxy path caps responses at 10 MB.
- Bad: cold starts (hundreds of ms for a Python + FastAPI + pydantic package) break the p95 < 15 ms overhead target.
- Bad: each concurrent invocation opens its own DB connections; at 200 concurrent requests this needs RDS Proxy just to protect Postgres.
- Bad: no SIGTERM drain model for in-flight streams.

### Option C — Amazon EKS

- Good: maximum flexibility (service mesh, custom autoscalers, multi-service growth); portable Kubernetes manifests.
- Bad: control-plane fee of about **$0.10/hour (~$73/month)** per cluster before any workload runs.
- Bad: cluster upgrades, add-ons (ingress controller, CNI, autoscaler) and RBAC are ongoing work that a single service does not justify.
- Bad: more moving parts to secure and explain, without improving any acceptance target.

### Option D — EC2 Auto Scaling group

- Good: lowest unit compute cost; full control of the host.
- Bad: AMI patching, instance hardening and capacity management are on us.
- Bad: slower, less atomic rollbacks than swapping a task definition.

## Decision

Option A. The gateway runs as an ECS Fargate service (minimum 2 tasks across 2 AZs) behind an ALB,
with RDS Postgres, ElastiCache Redis and Secrets Manager, all provisioned by Terraform from zero
(`us-east-1` by default, parameterized). `/healthz` is the container and target-group health check
(FR-03). Drain settings are tied to the stream deadline:

| Setting | Rule | Default |
|---|---|---|
| `deadline_ms` (max stream life) | ADR-005 | 60 s |
| ALB deregistration delay | > `deadline_ms` | 90 s |
| ECS `stopTimeout` | > `deadline_ms`, ≤ 120 s (Fargate max) | 90 s |
| ALB idle timeout | > `idle_stream_ms` | 120 s |

## Consequences

**Positive**
- Long SSE streams, warm pools and graceful drain work without workarounds, which directly supports NFR-01, NFR-02 and NFR-12.
- Rollback is one action: redeploy the previous task definition, plus re-activate the last-known-good policy (ADR-010).
- Autoscaling on CPU and ALB active-connection count matches the connection-bound workload.
- The whole stack is reproducible from Terraform for the M9 "apply from zero" exit gate.

**Negative**
- Baseline cost is always on (2 tasks, RDS, ElastiCache, ALB), even with no traffic; acceptable for a demo environment that can be destroyed with Terraform.
- `deadline_ms` cannot exceed about 110 s without changing the drain strategy, because Fargate caps `stopTimeout` at 120 s.
- The stack is AWS-specific; portability is explicitly not a v1 goal.
- Graceful shutdown (T30) must be implemented correctly in the app: stop accepting new requests on SIGTERM, finish open streams, then exit.
