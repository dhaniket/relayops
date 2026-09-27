# RelayOps

RelayOps is a fault-tolerant human-handoff routing backend for conversational AI platforms.

The project was built as a focused distributed-systems exercise around a realistic conversational-AI use case: transferring a conversation from an automated assistant to a human support agent while preserving context, preventing duplicate work, surviving service failures, and coordinating concurrent agent assignments safely.

## What RelayOps Demonstrates

RelayOps focuses on:

- microservice boundaries
- synchronous service-to-service HTTP communication
- durable state with Neon PostgreSQL
- state-machine design
- client-facing idempotency
- internal service idempotency
- bounded retries and backoff
- partial-failure recovery
- PostgreSQL transactions
- concurrency control with `FOR UPDATE SKIP LOCKED`
- crash recovery
- horizontal-scaling reasoning
- system-design trade-offs

It intentionally does **not** add Kafka, RabbitMQ, Redis, or LLM functionality because those are not required for the core Day 10 learning goals.

## Architecture

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

RelayOps uses one Neon database for development convenience, but each service owns a separate schema.

```text
handoff.* -> Handoff Service
queue.*   -> Queue Service
```

Services do not directly query each other's private tables.

## Services

### Handoff Service

Port:

```text
8200
```

Swagger:

```text
http://127.0.0.1:8200/docs
```

Responsibilities:
- receive human-handoff requests
- preserve conversation/customer context
- map escalation reasons to required skills
- create durable handoffs
- enforce `Idempotency-Key`
- track handoff state
- request agent assignment
- record assignment success or retryable failure

### Queue Service

Port:

```text
8201
```

Swagger:

```text
http://127.0.0.1:8201/docs
```

Responsibilities:
- store support agents
- store skills
- track active load and capacity
- select eligible agents
- enforce assignment idempotency
- coordinate concurrent assignment requests safely

## Project Structure

```text
relayops/
|
|-- services/
|   |
|   |-- handoff_service/
|   |   |-- app/
|   |       |-- db.py
|   |       |-- idempotency.py
|   |       |-- main.py
|   |       |-- queue_client.py
|   |       |-- repository.py
|   |       |-- routing.py
|   |       `-- schemas.py
|   |
|   `-- queue_service/
|       |-- app/
|           |-- db.py
|           |-- main.py
|           |-- repository.py
|           `-- schemas.py
|
|-- tests/
|   `-- integration/
|       `-- test_queue_concurrency.py
|
|-- docs/
|   `-- system-design.md
|
|-- .env
|-- .env.example
|-- .gitignore
|-- requirements.txt
`-- README.md
```

## Technology Stack

- Python 3
- FastAPI
- HTTPX
- Pydantic
- Neon PostgreSQL
- asyncpg
- pytest
- pytest-asyncio

## Setup

### 1. Create and activate a virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure Neon

Create:

```text
.env
```

Add your Neon PostgreSQL connection string:

```env
DATABASE_URL=postgresql://USER:PASSWORD@YOUR_NEON_ENDPOINT/neondb?sslmode=require
```

Keep `sslmode=require`.

Do not commit `.env`.

A safe example can be stored in `.env.example`.

## Run the Services

Open two terminals from the repository root.

### Queue Service

```powershell
python -m uvicorn `
    services.queue_service.app.main:app `
    --reload `
    --port 8201
```

### Handoff Service

```powershell
python -m uvicorn `
    services.handoff_service.app.main:app `
    --reload `
    --port 8200
```

## API Testing

Use FastAPI Swagger instead of manually constructing long request bodies in PowerShell.

### Handoff Service

Open:

```text
http://127.0.0.1:8200/docs
```

Use:

```text
POST /api/v1/handoffs
```

Example `Idempotency-Key`:

```text
relayops-test-key-0001
```

Example request body:

```json
{
  "conversation_id": "conv-1007",
  "customer_id": "cust-42",
  "channel": "whatsapp",
  "reason": "PAYMENT_FAILURE",
  "priority": "HIGH",
  "conversation_summary": "Customer reports being charged twice and requires human assistance."
}
```

### Queue Service

Open:

```text
http://127.0.0.1:8201/docs
```

Use:

```text
POST /internal/v1/assignments
```

Example:

```json
{
  "handoff_id": "handoff-test-001",
  "conversation_id": "conv-test-001",
  "required_skill": "billing",
  "priority": "HIGH"
}
```

## Escalation Routing

Example mappings:

```text
PAYMENT_FAILURE -> billing
CLAIM_DISPUTE   -> claims
POLICY_CHANGE   -> policy_servicing
```

The Handoff Service interprets escalation reasons. The Queue Service only receives the required skill.

## Handoff State Machine

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

## Client Idempotency

The Handoff Service requires:

```http
Idempotency-Key: <operation-key>
```

Behavior:

| Request | Result |
|---|---|
| New key + payload A | New handoff |
| Same key + same payload A | Original handoff |
| Same key + different payload B | `409 Conflict` |
| Different key + same payload | Separate handoff |

## Queue Assignment Idempotency

The Queue Service uses `handoff_id` as the primary key for assignments.

If the Handoff Service retries the same assignment after a timeout, the Queue Service returns the original logical assignment instead of selecting a second agent.

## Retries

The Handoff Service retries transient-looking failures such as:
- connection failure
- timeout
- HTTP 500
- HTTP 502
- HTTP 503
- HTTP 504

Retries are bounded and use exponential backoff.

RelayOps does not blindly retry `NO_CAPACITY`.

## Concurrency Control

Agent selection runs inside a PostgreSQL transaction and uses:

```sql
FOR UPDATE SKIP LOCKED
```

Important invariant:

```text
active_load <= max_load
```

for every agent.

## Neon Schema Layout

```text
handoff.handoffs
queue.agents
queue.assignments
```

Example Neon query:

```sql
SELECT
    handoff_id,
    conversation_id,
    status,
    agent_id
FROM handoff.handoffs
ORDER BY created_at DESC;
```

Agent load:

```sql
SELECT
    agent_id,
    name,
    active_load,
    max_load
FROM queue.agents
ORDER BY agent_id;
```

Capacity safety check:

```sql
SELECT
    agent_id,
    active_load,
    max_load
FROM queue.agents
WHERE active_load > max_load;
```

Expected:

```text
0 rows
```

## Failure Behavior

### Queue Service unavailable

The handoff remains durable and becomes `RETRY_PENDING`.

### No available agent

The handoff becomes `WAITING_FOR_AGENT`.

### Handoff Service restart

Existing handoffs remain available because state is stored in Neon.

### Queue Service restart

Agent load and assignment state remain available because they are stored in Neon.

### Neon unavailable

RelayOps must fail rather than pretend a durable operation succeeded.

## Testing

Run:

```powershell
pytest -v
```

Stage 3 includes a concurrency integration test that sends multiple assignment requests concurrently.

The important verification is not only that the HTTP calls succeed, but also that the database invariants remain correct.

## Security Notes

Never commit `.env`.

Check:

```powershell
git ls-files .env
```

The command should return nothing.

## System Design Documentation

See:

```text
docs/system-design.md
```

for the detailed architecture, failure model, concurrency reasoning, scaling discussion, and design trade-offs.

## Current Limitations

RelayOps currently does not include:
- automatic background retry processing
- automatic wake-up for waiting handoffs
- authentication
- authorization
- tenant isolation
- rate limiting
- load balancing
- production observability
- distributed tracing
- event publishing
- advanced agent-routing strategies
- separate physical databases per service

## Future Improvements

Possible future additions:
- automatic retry worker
- agent availability events
- multi-tenant routing
- authentication and authorization
- rate limiting
- load balancing
- metrics, logs, and tracing
- audit event publishing
- SLA-aware routing
- language-aware agent matching

## Day 10 Learning Outcomes

RelayOps demonstrates:
- real microservice ownership boundaries
- synchronous service-to-service communication
- partial failures
- durable distributed state
- state-machine modeling
- idempotent public APIs
- idempotent internal APIs
- safe bounded retries
- crash recovery
- PostgreSQL transactions
- concurrency control
- horizontal-scaling reasoning
- distributed-system trade-offs
