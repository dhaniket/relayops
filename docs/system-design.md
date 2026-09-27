# RelayOps System Design

## 1. Overview

RelayOps is a fault-tolerant human-handoff routing backend for conversational AI systems.

Its purpose is to take a conversation that requires human assistance, preserve the handoff context, determine the required support skill, and route the handoff to an available human agent without losing state or creating duplicate assignments during retries.

RelayOps focuses on microservice boundaries, durable distributed state, idempotency, concurrency control, retries, partial-failure recovery, and system-design reasoning.

## 2. Core Services

### Handoff Service

Responsibilities:
- Receive handoff requests from an upstream bot or conversational AI system.
- Store conversation and customer context.
- Map escalation reasons to required agent skills.
- Create and persist handoff state.
- Enforce client-facing idempotency using `Idempotency-Key`.
- Call the Queue Service to request an assignment.
- Persist assignment success, business-capacity waits, or retryable technical failures.

Database ownership:

```text
handoff.*
```

Primary table:

```text
handoff.handoffs
```

Default local port:

```text
8200
```

Swagger:

```text
http://127.0.0.1:8200/docs
```

### Queue Service

Responsibilities:
- Store agent identities, skills, load, and capacity.
- Accept internal assignment requests from the Handoff Service.
- Select an eligible agent.
- Prevent duplicate logical assignments.
- Coordinate concurrent assignment requests safely.
- Return the existing assignment when the same handoff is retried.

Database ownership:

```text
queue.*
```

Primary tables:

```text
queue.agents
queue.assignments
```

Default local port:

```text
8201
```

Swagger:

```text
http://127.0.0.1:8201/docs
```

## 3. High-Level Architecture

```text
                   Conversational AI / Bot / Client
                               |
                               | POST /api/v1/handoffs
                               | Idempotency-Key
                               v
                    +-----------------------+
                    |    Handoff Service    |
                    |        :8200          |
                    +-----------+-----------+
                                |
                                | owns
                                v
                     Neon PostgreSQL
                     handoff.handoffs
                                |
                                | synchronous HTTP
                                v
                    +-----------------------+
                    |     Queue Service     |
                    |        :8201          |
                    +-----------+-----------+
                                |
                                | owns
                                v
                     Neon PostgreSQL
                     queue.agents
                     queue.assignments
```

RelayOps uses one Neon PostgreSQL database for development convenience, but keeps separate service-owned schemas.

The Handoff Service must not query `queue.*` directly.

The Queue Service must not query `handoff.*` directly.

Service-to-service interaction happens through HTTP contracts.

## 4. Why Two Services?

The two services represent different business responsibilities.

### Handoff domain

The Handoff Service answers:
- Why does this conversation need a human?
- What customer/conversation context must be preserved?
- Which support skill is required?
- What is the lifecycle state of the handoff?
- Has this client operation already been processed?

### Queue domain

The Queue Service answers:
- Which agents exist?
- What skills does each agent have?
- Which agents currently have capacity?
- Which eligible agent should receive this handoff?
- Has this handoff already been assigned?

The Handoff Service asks:

> "I need an agent with the `billing` skill."

The Queue Service decides:

> "Meera is the correct available agent."

## 5. Handoff State Machine

```text
                     REQUESTED
                         |
                         v
                     ASSIGNING
                   /     |      \
                  /      |       \
                 v       v        v
           ASSIGNED   WAITING   RETRY_PENDING
                        |             |
                        |             |
                   capacity       dependency
                    returns        recovers
                        |             |
                        +------v------+
                           ASSIGNING
```

### REQUESTED

The handoff has been durably created but assignment has not yet completed.

### ASSIGNING

The Handoff Service is attempting to obtain an assignment from the Queue Service.

### ASSIGNED

A human agent has been assigned. For the current project scope, `ASSIGNED` is terminal.

### WAITING_FOR_AGENT

The Queue Service is healthy, but no eligible agent currently has capacity. This is a business-capacity condition.

### RETRY_PENDING

The assignment could not complete because of a technical dependency problem such as a timeout, connection failure, or retryable server error.

## 6. Durable State

Stage 1 stored important state in Python memory. That caused two problems:

1. Restarting a service lost its local state.
2. Multiple replicas would maintain different copies of the same state.

Stage 2 moved authoritative state into Neon PostgreSQL.

The Handoff Service stores:
- handoff ID
- idempotency key fingerprint
- request fingerprint
- conversation ID
- customer ID
- channel
- escalation reason
- priority
- conversation summary
- required skill
- handoff status
- assigned agent information
- last technical error
- timestamps

The Queue Service stores:
- agents
- skills
- active load
- maximum load
- assignments

FastAPI processes are therefore not the source of truth.

## 7. Client-Facing Idempotency

The client sends:

```http
Idempotency-Key: <unique-operation-key>
```

The Handoff Service stores two fingerprints:

```text
idempotency_key_hash
request_hash
```

Expected behavior:

| Request | Result |
|---|---|
| New key + payload A | Create handoff |
| Same key + same payload A | Return original handoff |
| Same key + different payload B | `409 Conflict` |
| Different key + same payload A | New handoff allowed |

The database enforces uniqueness with:

```text
UNIQUE(idempotency_key_hash)
```

## 8. Internal Assignment Idempotency

The Queue Service uses:

```text
handoff_id PRIMARY KEY
```

in `queue.assignments`.

If the Handoff Service retries the same assignment after a timeout, the Queue Service returns the original logical assignment instead of selecting another agent.

If the same `handoff_id` is reused with conflicting assignment data, the Queue Service returns a conflict.

## 9. Safe Retry Strategy

Retries are only safe after the downstream assignment operation is idempotent.

The Handoff Service retries transient failures such as:
- connection failure
- timeout
- HTTP 500
- HTTP 502
- HTTP 503
- HTTP 504

Retries are bounded and use exponential backoff.

The service does not blindly retry a business-capacity response such as `NO_CAPACITY`.

## 10. Concurrency Control

Agent selection runs inside a PostgreSQL transaction.

The core query uses:

```sql
FOR UPDATE SKIP LOCKED
```

Conceptually:

```text
Transaction A
    |
    | locks eligible agent row
    v

Transaction B
    |
    | skips currently locked row
    v
checks another eligible agent
```

This coordination happens in PostgreSQL, so it works across multiple Queue Service processes.

The primary safety invariant is:

```text
active_load <= max_load
```

for every agent.

## 11. Why Assignment Creation and Load Update Share a Transaction

The Queue Service:
1. Claims the logical assignment.
2. Selects and locks an eligible agent.
3. Increments that agent's load.
4. Stores the selected agent in the assignment.

These changes happen inside one PostgreSQL transaction.

If the transaction fails before commit, all of those changes roll back together.

## 12. Partial Failure Behavior

### Queue Service unavailable

The handoff is still durably created. After bounded retries fail:

```text
status = RETRY_PENDING
```

### No agent capacity

The Queue Service is healthy, but no eligible agent can accept more work.

```text
status = WAITING_FOR_AGENT
```

### Handoff Service crashes

Handoff state remains in Neon.

### Queue Service crashes

Agent and assignment state remains in Neon.

### Neon unavailable

RelayOps cannot safely create authoritative handoff state or coordinate assignments. The system should fail rather than falsely report success.

## 13. Crash Recovery

```text
Create handoff
      |
      v
Persist REQUESTED
      |
      v
Queue unavailable
      |
      v
RETRY_PENDING
      |
      v
Handoff Service crashes
      |
      v
Services restart
      |
      v
Client replays same Idempotency-Key
      |
      v
Same handoff recovered
      |
      v
Queue now succeeds
      |
      v
ASSIGNED
```

## 14. Service Ownership and Shared Neon

RelayOps currently uses one physical Neon PostgreSQL database.

Logical ownership remains:

```text
handoff.*  -> Handoff Service only
queue.*    -> Queue Service only
```

A stricter production deployment could use separate databases or clusters.

The key rule is that a service should not depend directly on another service's private persistence model.

## 15. Synchronous Communication Trade-Off

Current flow:

```text
POST /handoffs
      |
      v
Handoff Service
      |
      v
Queue Service
      |
      v
assignment result
      |
      v
client response
```

Advantages:
- Simple to reason about.
- Immediate assignment result.
- No additional broker.
- Easy API-level debugging.

Trade-offs:
- Client latency includes Queue Service latency.
- Queue availability affects the request flow.
- Retry semantics are required.
- Network ambiguity must be handled.

An alternative architecture could store the handoff and perform assignment asynchronously through a background worker or broker.

## 16. Why RelayOps Does Not Use Kafka or RabbitMQ

RelayOps is still a distributed system without a message broker.

Kafka or RabbitMQ could later support events such as:

```text
handoff.created
handoff.assigned
handoff.failed
```

They are not required for the Day 10 learning goals.

## 17. Why RelayOps Does Not Use Redis

PostgreSQL already owns the authoritative handoff and assignment state.

Using Redis only to store idempotency keys would create another consistency boundary.

Redis is better suited to later concerns such as rate limiting, presence, caching, or short-lived coordination.

## 18. Scaling Analysis

### Handoff Service

Can be horizontally replicated because important handoff state lives in Neon instead of process memory.

Potential bottlenecks:
- database connection pool limits
- Neon query latency
- Queue Service latency
- request volume

### Queue Service

Multiple replicas can coordinate through PostgreSQL transactions and row locks.

Potential bottlenecks:
- contention on agent rows
- assignment transaction rate
- database connection count
- routing algorithm complexity

### Neon PostgreSQL

Possible bottlenecks:
- connection saturation
- transaction contention
- query latency
- lock contention

### Human capacity

Even perfect infrastructure cannot route more simultaneous conversations than available support capacity allows.

## 19. Current Failure Matrix

| Failure | Behavior |
|---|---|
| Handoff Service crashes | State remains in Neon |
| Queue Service crashes | Handoff may become `RETRY_PENDING` |
| Queue Service times out | Bounded retry; then `RETRY_PENDING` |
| No eligible agent | `WAITING_FOR_AGENT` |
| Duplicate client POST | Original handoff returned |
| Duplicate assignment call | Original assignment returned |
| Conflicting idempotency key | `409 Conflict` |
| Concurrent assignment requests | PostgreSQL transaction + row locking coordinates capacity |
| Neon unavailable | Operation must fail rather than claim success |

## 20. Current Limitations

RelayOps intentionally does not yet include:
- automatic background processing of `RETRY_PENDING`
- automatic wake-up of `WAITING_FOR_AGENT`
- authentication
- authorization
- tenant isolation
- rate limiting
- load balancer configuration
- production observability
- distributed tracing
- advanced routing algorithms
- agent presence events
- a broker-based event system
- separate physical databases per service
- production migrations tooling

## 21. Future Evolution

Possible future additions:
- automatic retry worker
- capacity-change triggered reassignment
- multi-tenant routing
- authenticated internal APIs
- rate limiting
- load balancing
- metrics and tracing
- audit/event publishing
- smarter routing policy
- agent language and proficiency matching
- channel-aware routing
- SLA-aware priority handling

## 22. Key Design Principles

1. Persist business state before depending on downstream services.
2. Make retries idempotent before adding retry loops.
3. Use database constraints for correctness across multiple processes.
4. Use transactions for related state changes.
5. Treat business-capacity failures differently from technical failures.
6. Keep service ownership explicit.
7. Do not introduce infrastructure without a clear requirement.
8. Design distributed systems around partial failure, not only the happy path.
