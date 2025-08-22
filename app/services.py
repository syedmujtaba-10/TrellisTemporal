# app/services.py
from __future__ import annotations

import asyncio, random
from typing import Dict, Any, Optional

from sqlalchemy import text
import structlog

from .db import Session, insert_event, upsert_order_state

log = structlog.get_logger("services")


# ----- DO NOT CHANGE BEHAVIOR (must be called by all functions below) -----
async def flaky_call() -> None:
    """Either raise an error or sleep long enough to trigger an activity timeout."""
    rand_num = random.random()
    if rand_num < 0.33:
        raise RuntimeError("Forced failure for testing")
    if rand_num < 0.67:
        await asyncio.sleep(300)  # Expect the activity layer to time out before this completes


# ----- Helpers -----
def _order_id_from(order: Dict[str, Any]) -> str:
    return order.get("order_id") or order.get("id")  # support either key


# ----- Function stubs with DB reads/writes -----
async def order_received(
    order_id: str,
    address: Optional[Dict[str, Any]] = None,
    items: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    await flaky_call()

    if items is None:
        items = [{"sku": "ABC", "qty": 1}]

    # Persist order row + event
    await upsert_order_state(order_id, "received", address)
    await insert_event(order_id, "order_received", {"address": address, "items": items})
    log.info("order_received", order_id=order_id)

    return {"order_id": order_id, "items": items, "address": address}


async def order_validated(order: Dict[str, Any]) -> bool:
    await flaky_call()

    if not order.get("items"):
        raise ValueError("No items to validate")

    oid = _order_id_from(order)
    await upsert_order_state(oid, "validated")
    await insert_event(oid, "order_validated", {"items": order.get("items")})
    log.info("order_validated", order_id=oid)

    return True


async def payment_charged(order: Dict[str, Any], payment_id: str) -> Dict[str, Any]:
    """
    Charge payment after simulating an error/timeout first.
    Implements idempotency: the same payment_id can be safely retried.
    """
    await flaky_call()

    oid = _order_id_from(order)
    # Simple demo "amount": sum of quantities
    amount = float(sum(int(i.get("qty", 1)) for i in order.get("items", [])))

    # Use a transaction + SELECT ... FOR UPDATE to make idempotency concurrency-safe
    async with Session.begin() as session:
        res = await session.execute(
            text("SELECT status, amount FROM payments WHERE payment_id = :pid FOR UPDATE"),
            {"pid": payment_id},
        )
        row = res.first()

        if row and row[0] == "charged":
            # Already charged → idempotent success
            await insert_event(oid, "payment_idempotent", {"payment_id": payment_id, "amount": float(row[1])})
            await upsert_order_state(oid, "payment_charged")
            log.info("payment_already_charged", order_id=oid, payment_id=payment_id)
            return {"status": "charged", "amount": float(row[1])}

        # Upsert to 'charged' so retries don't double-charge
        await session.execute(
            text(
                """
                INSERT INTO payments (payment_id, order_id, status, amount)
                VALUES (:pid, :oid, 'charged', :amt)
                ON DUPLICATE KEY UPDATE
                  order_id = VALUES(order_id),
                  status   = 'charged',
                  amount   = VALUES(amount)
                """
            ),
            {"pid": payment_id, "oid": oid, "amt": amount},
        )

    await upsert_order_state(oid, "payment_charged")
    await insert_event(oid, "payment_charged", {"payment_id": payment_id, "amount": amount})
    log.info("payment_charged", order_id=oid, payment_id=payment_id, amount=amount)

    return {"status": "charged", "amount": amount}


async def package_prepared(order: Dict[str, Any]) -> str:
    await flaky_call()

    oid = _order_id_from(order)
    async with Session.begin() as session:
        await session.execute(
            text("INSERT INTO shipments (order_id, status, payload_json) VALUES (:oid, 'prepared', NULL)"),
            {"oid": oid},
        )

    await insert_event(oid, "package_prepared", None)
    log.info("package_prepared", order_id=oid)
    return "Package ready"


async def carrier_dispatched(order: Dict[str, Any]) -> str:
    await flaky_call()

    oid = _order_id_from(order)
    async with Session.begin() as session:
        await session.execute(
            text("INSERT INTO shipments (order_id, status, payload_json) VALUES (:oid, 'dispatched', NULL)"),
            {"oid": oid},
        )

    # Mark order as in shipping (final 'shipped' happens in order_shipped)
    await upsert_order_state(oid, "shipping")
    await insert_event(oid, "carrier_dispatched", None)
    log.info("carrier_dispatched", order_id=oid)
    return "Dispatched"


async def order_shipped(order: Dict[str, Any]) -> str:
    await flaky_call()

    oid = _order_id_from(order)
    await upsert_order_state(oid, "shipped")
    await insert_event(oid, "order_shipped", None)
    log.info("order_shipped", order_id=oid)
    return "Shipped"
