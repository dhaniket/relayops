from uuid import uuid4

import asyncpg

from services.handoff_service.app.schemas import (
    HandoffCreateRequest,
)


class IdempotencyConflictError(Exception):
    pass


class HandoffRepository:
    def __init__(
        self,
        pool: asyncpg.Pool,
    ) -> None:
        self.pool = pool

    async def create_or_get(
        self,
        request: HandoffCreateRequest,
        required_skill: str,
        key_hash: str,
        request_hash: str,
    ) -> tuple[asyncpg.Record, bool]:

        handoff_id = f"handoff-{uuid4()}"

        async with self.pool.acquire() as conn:

            row = await conn.fetchrow(
                """
                INSERT INTO handoff.handoffs (
                    handoff_id,
                    idempotency_key_hash,
                    request_hash,

                    conversation_id,
                    customer_id,
                    channel,
                    reason,
                    priority,
                    conversation_summary,
                    required_skill,

                    status
                )

                VALUES (
                    $1,
                    $2,
                    $3,

                    $4,
                    $5,
                    $6,
                    $7,
                    $8,
                    $9,
                    $10,

                    'REQUESTED'
                )

                ON CONFLICT (
                    idempotency_key_hash
                )
                DO NOTHING

                RETURNING *;
                """,
                handoff_id,
                key_hash,
                request_hash,
                request.conversation_id,
                request.customer_id,
                request.channel,
                request.reason,
                request.priority,
                request.conversation_summary,
                required_skill,
            )

            if row is not None:
                return row, True

            existing = await conn.fetchrow(
                """
                SELECT *

                FROM handoff.handoffs

                WHERE idempotency_key_hash = $1;
                """,
                key_hash,
            )

            if existing is None:
                raise RuntimeError("Idempotent handoff " "could not be recovered.")

            if existing["request_hash"] != request_hash:
                raise IdempotencyConflictError(
                    "Idempotency key was reused " "with different request data."
                )

            return existing, False

    async def get(
        self,
        handoff_id: str,
    ) -> asyncpg.Record | None:

        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                """
                SELECT *

                FROM handoff.handoffs

                WHERE handoff_id = $1;
                """,
                handoff_id,
            )

    async def mark_assigning(
        self,
        handoff_id: str,
    ) -> None:

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE handoff.handoffs

                SET
                    status = 'ASSIGNING',
                    updated_at = NOW()

                WHERE
                    handoff_id = $1
                    AND status <> 'ASSIGNED';
                """,
                handoff_id,
            )

    async def mark_assigned(
        self,
        handoff_id: str,
        agent_id: str,
        agent_name: str,
        queue_name: str,
    ) -> None:

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE handoff.handoffs

                SET
                    status = 'ASSIGNED',

                    agent_id = $2,
                    agent_name = $3,
                    queue_name = $4,

                    last_error = NULL,
                    updated_at = NOW()

                WHERE handoff_id = $1;
                """,
                handoff_id,
                agent_id,
                agent_name,
                queue_name,
            )

    async def mark_waiting(
        self,
        handoff_id: str,
    ) -> None:

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE handoff.handoffs

                SET
                    status = 'WAITING_FOR_AGENT',
                    last_error = (
                        'No eligible agent currently '
                        'has capacity.'
                    ),
                    updated_at = NOW()

                WHERE
                    handoff_id = $1
                    AND status <> 'ASSIGNED';
                """,
                handoff_id,
            )

    async def mark_retry_pending(
        self,
        handoff_id: str,
        error: str,
    ) -> None:

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE handoff.handoffs

                SET
                    status = 'RETRY_PENDING',
                    last_error = $2,
                    updated_at = NOW()

                WHERE
                    handoff_id = $1
                    AND status <> 'ASSIGNED';
                """,
                handoff_id,
                error,
            )
