# app/activities.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from temporalio import activity
import structlog, json
from sqlalchemy import text

log = structlog.get_logger("activities")


@activity.defn
async def receive_order(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create/record an order row. Payload: {order_id, address?, items?}"""
    from . import services  # lazy import
    info = activity.info()
    order_id = payload["order_id"]
    address = payload.get("address")
    items: Optional[List[Dict[str, Any]]] = payload.get("items")
    log.info("receive_order.start", order_id=order_id, attempt=info.attempt)
    result = await services.order_received(order_id=order_id, address=address, items=items)
    log.info("receive_order.done", order_id=order_id)
    return result


@activity.defn
async def validate_order(order: Dict[str, Any]) -> bool:
    """Validate order contents (raises on invalid)."""
    from . import services  # lazy import
    info = activity.info()
    log.info("validate_order.start", order_id=order.get("order_id"), attempt=info.attempt)
    ok = await services.order_validated(order)
    log.info("validate_order.done", order_id=order.get("order_id"))
    return ok


@activity.defn
async def charge_payment(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Payload: { order: {...}, payment_id: str }"""
    from . import services  # lazy import
    info = activity.info()
    order = payload["order"]
    payment_id = payload["payment_id"]
    log.info(
        "charge_payment.start",
        order_id=order.get("order_id"),
        payment_id=payment_id,
        attempt=info.attempt,
    )
    res = await services.payment_charged(order, payment_id)
    log.info(
        "charge_payment.done",
        order_id=order.get("order_id"),
        payment_id=payment_id,
        status=res.get("status"),
        amount=res.get("amount"),
    )
    return res


@activity.defn
async def prepare_package(order: Dict[str, Any]) -> str:
    from . import services  # lazy import
    info = activity.info()
    log.info("prepare_package.start", order_id=order.get("order_id"), attempt=info.attempt)
    s = await services.package_prepared(order)
    log.info("prepare_package.done", order_id=order.get("order_id"))
    return s


@activity.defn
async def dispatch_carrier(order: Dict[str, Any]) -> str:
    from . import services  # lazy import
    info = activity.info()
    log.info("dispatch_carrier.start", order_id=order.get("order_id"), attempt=info.attempt)
    s = await services.carrier_dispatched(order)
    log.info("dispatch_carrier.done", order_id=order.get("order_id"))
    return s


@activity.defn
async def mark_shipped(payload: Dict[str, Any]) -> str:
    """Payload: { order_id: str }"""
    from . import services  # lazy import
    info = activity.info()
    order_id = payload["order_id"]
    log.info("mark_shipped.start", order_id=order_id, attempt=info.attempt)
    s = await services.order_shipped({"order_id": order_id})
    log.info("mark_shipped.done", order_id=order_id)
    return s


@activity.defn
async def persist_address(payload: Dict[str, Any]) -> str:
    """
    Update only the address_json for an order (do NOT touch state).
    Payload: { order_id: str, address: {...} }
    """
    from .db import Session, insert_event  # lazy import
    info = activity.info()
    order_id = payload["order_id"]
    address = payload["address"]
    log.info("persist_address.start", order_id=order_id, attempt=info.attempt)
    async with Session.begin() as session:
        await session.execute(
            text("UPDATE orders SET address_json = :addr WHERE id = :oid"),
            {"addr": json.dumps(address), "oid": order_id},
        )
    await insert_event(order_id, "address_updated", address)
    log.info("persist_address.done", order_id=order_id)
    return "address_updated"
