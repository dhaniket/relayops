import asyncio
import os

import httpx2

QUEUE_SERVICE_BASE_URL = os.getenv(
    "QUEUE_SERVICE_BASE_URL",
    "http://127.0.0.1:8201",
)


class QueueNoCapacityError(Exception):
    pass


class QueueUnavailableError(Exception):
    pass


class QueueRejectedError(Exception):
    pass


async def request_assignment(
    assignment_request: dict,
) -> dict:

    max_attempts = 3

    async with httpx2.AsyncClient(
        timeout=httpx2.Timeout(2.0),
    ) as client:

        for attempt in range(
            1,
            max_attempts + 1,
        ):

            try:
                response = await client.post(
                    (f"{QUEUE_SERVICE_BASE_URL}" "/internal/v1/assignments"),
                    json=assignment_request,
                )

            except (
                httpx2.TimeoutException,
                httpx2.ConnectError,
            ) as exc:

                if attempt == max_attempts:
                    raise QueueUnavailableError(
                        "Queue Service remained " "unavailable after retries."
                    ) from exc

                await asyncio.sleep(0.25 * (2 ** (attempt - 1)))

                continue

            if response.status_code == 409:

                body = response.json()
                detail = body.get("detail", {})

                code = detail.get("code")

                if code == "NO_CAPACITY":
                    raise QueueNoCapacityError(
                        detail.get(
                            "message",
                            "No agent capacity.",
                        )
                    )

                raise QueueRejectedError(
                    detail.get(
                        "message",
                        "Queue rejected assignment.",
                    )
                )

            if response.status_code in {
                500,
                502,
                503,
                504,
            }:

                if attempt == max_attempts:
                    raise QueueUnavailableError(
                        "Queue Service repeatedly " "returned a server error."
                    )

                await asyncio.sleep(0.25 * (2 ** (attempt - 1)))

                continue

            try:
                response.raise_for_status()

            except httpx2.HTTPStatusError as exc:
                raise QueueRejectedError(
                    "Queue Service rejected " "the assignment."
                ) from exc

            return response.json()

    raise QueueUnavailableError("Assignment attempts exhausted.")
