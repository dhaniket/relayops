from fastapi import FastAPI, HTTPException

from services.queue_service.app.schemas import (
    AssignmentRequest,
    AssignmentResponse,
)

app = FastAPI(
    title="RelayOps Agent Queue Service",
    version="0.1.0",
)


AGENTS = [
    {
        "agent_id": "agent-101",
        "name": "Asha",
        "skills": {
            "billing",
            "policy_servicing",
        },
        "active_load": 1,
        "max_load": 3,
    },
    {
        "agent_id": "agent-102",
        "name": "Rohan",
        "skills": {
            "claims",
        },
        "active_load": 2,
        "max_load": 3,
    },
    {
        "agent_id": "agent-103",
        "name": "Meera",
        "skills": {
            "billing",
            "claims",
        },
        "active_load": 0,
        "max_load": 2,
    },
]


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "queue-service",
    }


@app.post(
    "/internal/v1/assignments",
    response_model=AssignmentResponse,
)
async def assign_agent(
    request: AssignmentRequest,
):
    eligible_agents = [
        agent
        for agent in AGENTS
        if (
            request.required_skill in agent["skills"]
            and agent["active_load"] < agent["max_load"]
        )
    ]

    if not eligible_agents:
        raise HTTPException(
            status_code=409,
            detail=("No agent with the required " "skill currently has capacity."),
        )

    selected_agent = min(
        eligible_agents,
        key=lambda agent: agent["active_load"],
    )

    selected_agent["active_load"] += 1

    return AssignmentResponse(
        handoff_id=request.handoff_id,
        agent_id=selected_agent["agent_id"],
        agent_name=selected_agent["name"],
        required_skill=request.required_skill,
        queue_name=(f"{request.required_skill}-queue"),
        status="ASSIGNED",
    )
