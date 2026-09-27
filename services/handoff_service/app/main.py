from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Response,
)

from services.handoff_service.app.db import (
    close_db,
    connect_db,
    get_pool,
)
from services.handoff_service.app.idempotency import (
    build_fingerprints,
)
from services.handoff_service.app.queue_client import (
    QueueNoCapacityError,
    QueueRejectedError,
    QueueUnavailableError,
    request_assignment,
)
from services.handoff_service.app.repository import (
    HandoffRepository,
    IdempotencyConflictError,
)
from services.handoff_service.app.routing import (
    required_skill_for_reason,
)
from services.handoff_service.app.schemas import (
    HandoffCreateRequest,
    HandoffResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()

    yield

    await close_db()


app = FastAPI(
    title="RelayOps Handoff Service",
    version="0.2.0",
    lifespan=lifespan,
)


def to_response(
    row,
) -> HandoffResponse:
    return HandoffResponse(
        handoff_id=row["handoff_id"],
        conversation_id=row["conversation_id"],
        customer_id=row["customer_id"],
        status=row["status"],
        required_skill=row["required_skill"],
        agent_id=row["agent_id"],
        agent_name=row["agent_name"],
        queue_name=row["queue_name"],
        last_error=row["last_error"],
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "handoff-service",
    }


@app.get(
    "/api/v1/handoffs/{handoff_id}",
    response_model=HandoffResponse,
)
async def get_handoff(
    handoff_id: str,
):
    repository = HandoffRepository(get_pool())

    row = await repository.get(handoff_id)

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Handoff not found.",
        )

    return to_response(row)


@app.post(
    "/api/v1/handoffs",
    response_model=HandoffResponse,
)
async def create_handoff(
    request: HandoffCreateRequest,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=16,
            max_length=128,
        ),
    ],
):
    required_skill = required_skill_for_reason(request.reason)

    key_hash, request_hash = build_fingerprints(
        request,
        idempotency_key,
    )

    repository = HandoffRepository(get_pool())

    try:
        row, created = await repository.create_or_get(
            request=request,
            required_skill=required_skill,
            key_hash=key_hash,
            request_hash=request_hash,
        )

    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    response.status_code = 201 if created else 200

    if row["status"] == "ASSIGNED":
        return to_response(row)

    await repository.mark_assigning(row["handoff_id"])

    assignment_request = {
        "handoff_id": row["handoff_id"],
        "conversation_id": (row["conversation_id"]),
        "required_skill": (row["required_skill"]),
        "priority": row["priority"],
    }

    try:
        assignment = await request_assignment(assignment_request)

    except QueueNoCapacityError:
        await repository.mark_waiting(row["handoff_id"])

    except QueueUnavailableError as exc:
        await repository.mark_retry_pending(
            row["handoff_id"],
            str(exc),
        )

    except QueueRejectedError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    else:
        await repository.mark_assigned(
            handoff_id=row["handoff_id"],
            agent_id=assignment["agent_id"],
            agent_name=assignment["agent_name"],
            queue_name=assignment["queue_name"],
        )

    updated = await repository.get(row["handoff_id"])

    if updated is None:
        raise RuntimeError("Handoff disappeared after creation.")

    return to_response(updated)
