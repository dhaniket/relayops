import asyncpg

from services.queue_service.app.schemas import (
    AssignmentRequest,
)


class NoCapacityError(Exception):
    pass


class AssignmentConflictError(Exception):
    pass


class QueueRepository:
    def __init__(
        self,
        pool: asyncpg.Pool,
    ) -> None:
        self.pool = pool

    async def assign(
        self,
        request: AssignmentRequest,
    ) -> asyncpg.Record:

        async with self.pool.acquire() as conn:

            async with conn.transaction():

                claimed = await conn.fetchrow(
                    """
                    INSERT INTO queue.assignments (
                        handoff_id,
                        conversation_id,
                        required_skill,
                        priority,
                        status
                    )
                    VALUES (
                        $1,
                        $2,
                        $3,
                        $4,
                        'PENDING'
                    )

                    ON CONFLICT (handoff_id)
                    DO NOTHING

                    RETURNING handoff_id;
                    """,
                    request.handoff_id,
                    request.conversation_id,
                    request.required_skill,
                    request.priority,
                )

                if claimed is None:

                    existing = await conn.fetchrow(
                        """
                        SELECT
                            a.handoff_id,
                            a.conversation_id,
                            a.required_skill,
                            a.priority,
                            a.status,
                            a.agent_id,
                            ag.name AS agent_name

                        FROM queue.assignments AS a

                        JOIN queue.agents AS ag
                            ON ag.agent_id = a.agent_id

                        WHERE a.handoff_id = $1;
                        """,
                        request.handoff_id,
                    )

                    if existing is None:
                        raise RuntimeError(
                            "Existing assignment " "could not be recovered."
                        )

                    same_request = (
                        existing["conversation_id"] == request.conversation_id
                        and existing["required_skill"] == request.required_skill
                    )

                    if not same_request:
                        raise AssignmentConflictError(
                            "Handoff ID was reused " "with different assignment data."
                        )

                    return existing

                agent = await conn.fetchrow(
                    """
                    SELECT
                        agent_id,
                        name,
                        active_load,
                        max_load

                    FROM queue.agents

                    WHERE
                        $1 = ANY(skills)
                        AND active_load < max_load

                    ORDER BY
                        active_load ASC,
                        agent_id ASC

                    FOR UPDATE SKIP LOCKED

                    LIMIT 1;
                    """,
                    request.required_skill,
                )

                if agent is None:
                    raise NoCapacityError("No eligible agent has capacity.")

                await conn.execute(
                    """
                    UPDATE queue.agents

                    SET active_load = active_load + 1

                    WHERE agent_id = $1;
                    """,
                    agent["agent_id"],
                )

                await conn.execute(
                    """
                    UPDATE queue.assignments

                    SET
                        status = 'ASSIGNED',
                        agent_id = $2

                    WHERE handoff_id = $1;
                    """,
                    request.handoff_id,
                    agent["agent_id"],
                )

                return await conn.fetchrow(
                    """
                    SELECT
                        a.handoff_id,
                        a.conversation_id,
                        a.required_skill,
                        a.priority,
                        a.status,
                        a.agent_id,
                        ag.name AS agent_name

                    FROM queue.assignments AS a

                    JOIN queue.agents AS ag
                        ON ag.agent_id = a.agent_id

                    WHERE a.handoff_id = $1;
                    """,
                    request.handoff_id,
                )

    async def list_agents(
        self,
    ) -> list[asyncpg.Record]:

        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT
                    agent_id,
                    name,
                    skills,
                    active_load,
                    max_load

                FROM queue.agents

                ORDER BY agent_id;
                """)
