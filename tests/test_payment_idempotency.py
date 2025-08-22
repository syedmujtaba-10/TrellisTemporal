# tests/test_payment_idempotency.py
import uuid
import json

import pytest
from sqlalchemy import text

import app.services as services
from app.db import Session


@pytest.mark.asyncio
async def test_payment_idempotency(monkeypatch, db_ready):
    # Avoid random failures/timeouts for this unit test
    async def _no_flaky():
        return None
    monkeypatch.setattr(services, "flaky_call", _no_flaky)

    order_id = f"o-{uuid.uuid4().hex[:8]}"
    payment_id = f"pay-{order_id}"

    # 1) Create the order (uses DB insert + event)
    order = await services.order_received(order_id, address={"line1": "X"}, items=[{"sku": "ABC", "qty": 2}])

    # 2) Charge twice with the same payment_id
    first = await services.payment_charged(order, payment_id)
    second = await services.payment_charged(order, payment_id)  # should be idempotent

    assert first["status"] == "charged"
    assert second["status"] == "charged"
    assert float(first["amount"]) == float(second["amount"]) == 2.0

    # 3) Verify only one row exists and is 'charged'
    async with Session.begin() as session:
        row = (await session.execute(
            text("SELECT COUNT(*), MIN(status), MIN(amount) FROM payments WHERE payment_id = :pid"),
            {"pid": payment_id},
        )).first()
        assert row[0] == 1
        assert row[1] == "charged"
        assert float(row[2]) == 2.0
