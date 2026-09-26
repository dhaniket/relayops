from typing import Literal

from pydantic import BaseModel, Field

Skill = Literal[
    "billing",
    "claims",
    "policy_servicing",
]


Priority = Literal[
    "LOW",
    "NORMAL",
    "HIGH",
    "URGENT",
]


class AssignmentRequest(BaseModel):
    handoff_id: str = Field(
        min_length=5,
        max_length=100,
    )

    conversation_id: str = Field(
        min_length=3,
        max_length=100,
    )

    required_skill: Skill

    priority: Priority


class AssignmentResponse(BaseModel):
    handoff_id: str

    agent_id: str

    agent_name: str

    required_skill: Skill

    queue_name: str

    status: Literal["ASSIGNED"]
