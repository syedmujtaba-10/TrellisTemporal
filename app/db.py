# app/db.py
from __future__ import annotations

import json
from typing import Any, Dict, Optional
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
from sqlalchemy.pool import NullPool   # <-- add this
import os

# pull your DSN the same way you already do (aiomysql driver on Windows)
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3307"))
MYSQL_DB   = os.getenv("MYSQL_DB", "trellis")
MYSQL_USER = os.getenv("MYSQL_USER", "trellis")
MYSQL_PWD  = os.getenv("MYSQL_PASSWORD", "trellisPW")

# If you stayed on asyncmy, change aiomysql -> asyncmy here:
ASYNC_MYSQL_URI = f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PWD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"

# 🔧 IMPORTANT: disable pooling to avoid cross-event-loop reuse in Temporal workers
engine = create_async_engine(
    ASYNC_MYSQL_URI,
    pool_pre_ping=True,
    poolclass=NullPool,   # <-- this is the key change
    future=True,
)

Session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)

# --- your existing helpers (unchanged) ---
async def insert_event(order_id: str, type_: str, payload: Optional[Dict[str, Any]] = None) -> None:
    async with Session.begin() as session:
        await session.execute(
            text("INSERT INTO events (order_id, type, payload_json) VALUES (:oid, :t, :payload)"),
            {"oid": order_id, "t": type_, "payload": json.dumps(payload) if payload else None},
        )

async def upsert_order_state(order_id: str, state: str, address: Optional[Dict[str, Any]] = None) -> None:
    async with Session.begin() as session:
        await session.execute(
            text("""
                INSERT INTO orders (id, state, address_json)
                VALUES (:oid, :st, :addr)
                ON DUPLICATE KEY UPDATE state = VALUES(state),
                                        address_json = COALESCE(VALUES(address_json), address_json)
            """),
            {"oid": order_id, "st": state, "addr": json.dumps(address) if address else None},
        )
