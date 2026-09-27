import asyncio
from uuid import uuid4

import httpx2
import pytest

QUEUE_URL = "http://127.0.0.1:8201" "/internal/v1/assignments"


@pytest.mark.asyncio
async def test_concurrent_billing_assignments():
    first_handoff = f"concurrent-{uuid4()}"
    second_handoff = f"concurrent-{uuid4()}"

    first_request = {
        "handoff_id": first_handoff,
        "conversation_id": "conv-concurrent-1",
        "required_skill": "billing",
        "priority": "HIGH",
    }

    second_request = {
        "handoff_id": second_handoff,
        "conversation_id": "conv-concurrent-2",
        "required_skill": "billing",
        "priority": "HIGH",
    }

    async with httpx2.AsyncClient(timeout=5.0) as client:

        first_response, second_response = await asyncio.gather(
            client.post(
                QUEUE_URL,
                json=first_request,
            ),
            client.post(
                QUEUE_URL,
                json=second_request,
            ),
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    first = first_response.json()
    second = second_response.json()

    assert first["handoff_id"] != second["handoff_id"]

    assert first["status"] == "ASSIGNED"
    assert second["status"] == "ASSIGNED"
