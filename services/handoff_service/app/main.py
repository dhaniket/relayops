import os
from uuid import uuid4

import httpx2
from fastapi import FastAPI, HTTPException

from services.handoff_service.app.routing import (
    required_skill_for_reason,
)
from services.handoff_service.app.schemas import (
    HandoffCreateRequest,
    HandoffResponse,
)

app = FastAPI(
    title="RelayOps Handoff Service",
    version="0.1.0",
)


QUEUE_SERVICE_BASE_URL = os.getenv(
    "QUEUE_SERVICE_BASE_URL",
    "http://127.0.0.1:8201",
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "handoff-service",
    }


@app.post(
    "/api/v1/handoffs",
    response_model=HandoffResponse,
    status_code=201,
)
async def create_handoff(
    request: HandoffCreateRequest,
):
    handoff_id = f"handoff-{uuid4()}"

    required_skill = required_skill_for_reason(request.reason)

    assignment_request = {
        "handoff_id": handoff_id,
        "conversation_id": (request.conversation_id),
        "required_skill": required_skill,
        "priority": request.priority,
    }

    try:
        async with httpx2.AsyncClient(
            timeout=httpx2.Timeout(3.0),
        ) as client:
            response = await client.post(
                (f"{QUEUE_SERVICE_BASE_URL}" "/internal/v1/assignments"),
                json=assignment_request,
            )

            if response.status_code == 409:
                return HandoffResponse(
                    handoff_id=handoff_id,
                    conversation_id=(request.conversation_id),
                    customer_id=request.customer_id,
                    status="WAITING_FOR_AGENT",
                    required_skill=required_skill,
                )

            response.raise_for_status()

            assignment = response.json()

    except httpx2.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Agent Queue Service timed out.",
        ) from exc

    except httpx2.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail=("Agent Queue Service unavailable."),
        ) from exc

    except httpx2.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=("Agent Queue Service returned " "an unexpected error."),
        ) from exc

    return HandoffResponse(
        handoff_id=handoff_id,
        conversation_id=request.conversation_id,
        customer_id=request.customer_id,
        status="ASSIGNED",
        required_skill=required_skill,
        agent_id=assignment["agent_id"],
        agent_name=assignment["agent_name"],
        queue_name=assignment["queue_name"],
    )
