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
            CREATE SCHEMA IF NOT EXISTS handoff;
            """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS handoff.handoffs (
                handoff_id TEXT PRIMARY KEY,

                idempotency_key_hash TEXT
                    NOT NULL UNIQUE,

                request_hash TEXT NOT NULL,

                conversation_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                reason TEXT NOT NULL,
                priority TEXT NOT NULL,

                conversation_summary TEXT NOT NULL,
                required_skill TEXT NOT NULL,

                status TEXT NOT NULL
                    CHECK (
                        status IN (
                            'REQUESTED',
                            'ASSIGNING',
                            'ASSIGNED',
                            'WAITING_FOR_AGENT',
                            'RETRY_PENDING'
                        )
                    ),

                agent_id TEXT,
                agent_name TEXT,
                queue_name TEXT,

                last_error TEXT,

                created_at TIMESTAMPTZ
                    NOT NULL DEFAULT NOW(),

                updated_at TIMESTAMPTZ
                    NOT NULL DEFAULT NOW()
            );
            """)


async def close_db() -> None:
    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Handoff database is not initialized.")

    return _pool
