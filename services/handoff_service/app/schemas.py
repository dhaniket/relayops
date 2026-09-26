from typing import Literal

from pydantic import BaseModel, Field


class HandoffCreateRequest(BaseModel):
    conversation_id: str = Field(
        min_length=3,
        max_length=100,
    )

    customer_id: str = Field(
        min_length=2,
        max_length=100,
    )

    channel: Literal[
        "web",
        "whatsapp",
        "voice",
    ]

    reason: Literal[
        "PAYMENT_FAILURE",
        "CLAIM_DISPUTE",
        "POLICY_CHANGE",
    ]

    priority: Literal[
        "LOW",
        "NORMAL",
        "HIGH",
        "URGENT",
    ]

    conversation_summary: str = Field(
        min_length=10,
        max_length=2000,
    )


class HandoffResponse(BaseModel):
    handoff_id: str

    conversation_id: str

    customer_id: str

    status: Literal[
        "ASSIGNED",
        "WAITING_FOR_AGENT",
    ]

    required_skill: str

    agent_id: str | None = None

    agent_name: str | None = None

    queue_name: str | None = None
