import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()


DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured.")


_pool: asyncpg.Pool | None = None


async def connect_db() -> None:
    global _pool

    _pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=5,
        command_timeout=10,
    )

    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE SCHEMA IF NOT EXISTS queue;
            """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS queue.agents (
                agent_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                skills TEXT[] NOT NULL,

                active_load INTEGER NOT NULL
                    CHECK (active_load >= 0),

                max_load INTEGER NOT NULL
                    CHECK (max_load > 0)
            );
            """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS queue.assignments (
                handoff_id TEXT PRIMARY KEY,

                conversation_id TEXT NOT NULL,
                required_skill TEXT NOT NULL,
                priority TEXT NOT NULL,

                status TEXT NOT NULL
                    CHECK (
                        status IN (
                            'PENDING',
                            'ASSIGNED'
                        )
                    ),

                agent_id TEXT
                    REFERENCES queue.agents(agent_id),

                created_at TIMESTAMPTZ
                    NOT NULL DEFAULT NOW()
            );
            """)

        agents = [
            (
                "agent-101",
                "Asha",
                ["billing", "policy_servicing"],
                1,
                3,
            ),
            (
                "agent-102",
                "Rohan",
                ["claims"],
                2,
                3,
            ),
            (
                "agent-103",
                "Meera",
                ["billing", "claims"],
                0,
                2,
            ),
        ]

        await conn.executemany(
            """
            INSERT INTO queue.agents (
                agent_id,
                name,
                skills,
                active_load,
                max_load
            )
            VALUES ($1, $2, $3, $4, $5)

            ON CONFLICT (agent_id)
            DO NOTHING;
            """,
            agents,
        )


async def close_db() -> None:
    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Queue database is not initialized.")

    return _pool
