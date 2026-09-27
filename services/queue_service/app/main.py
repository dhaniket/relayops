from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from services.queue_service.app.db import (
    close_db,
    connect_db,
    get_pool,
)
from services.queue_service.app.repository import (
    AssignmentConflictError,
    NoCapacityError,
    QueueRepository,
)
from services.queue_service.app.schemas import (
    AssignmentRequest,
    AssignmentResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()

    yield

    await close_db()


app = FastAPI(
    title="RelayOps Agent Queue Service",
    version="0.2.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "queue-service",
    }


@app.get("/internal/v1/agents")
async def list_agents():
    repository = QueueRepository(get_pool())

    rows = await repository.list_agents()

    return [dict(row) for row in rows]


@app.post(
    "/internal/v1/assignments",
    response_model=AssignmentResponse,
)
async def assign_agent(
    request: AssignmentRequest,
):
    repository = QueueRepository(get_pool())

    try:
        assignment = await repository.assign(request)

    except NoCapacityError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "NO_CAPACITY",
                "message": str(exc),
            },
        ) from exc

    except AssignmentConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ASSIGNMENT_CONFLICT",
                "message": str(exc),
            },
        ) from exc

    return AssignmentResponse(
        handoff_id=assignment["handoff_id"],
        agent_id=assignment["agent_id"],
        agent_name=assignment["agent_name"],
        required_skill=(assignment["required_skill"]),
        queue_name=(f"{assignment['required_skill']}" "-queue"),
        status="ASSIGNED",
    )
