# tests/test_workflow_happy.py
import uuid
from datetime import timedelta

import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.client import Client
from temporalio.worker import Worker

from app.workflows import OrderWorkflow, ShippingWorkflow
from app.activities import (
    receive_order,
    validate_order,
    charge_payment,
    persist_address,
    mark_shipped,
    prepare_package,
    dispatch_carrier,
)
import app.services as services


@pytest.mark.asyncio
async def test_order_workflow_happy(monkeypatch, db_ready):
    # Make flaky_call deterministic for tests (no random failures / long sleeps)
    async def _no_flaky():
        return None
    monkeypatch.setattr(services, "flaky_call", _no_flaky)

    order_id = f"o-{uuid.uuid4().hex[:8]}"
    payment_id = f"pay-{order_id}"

    # Start Temporal test environment with time-skipping
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client: Client = env.client

        # Run both workers in-process on their task queues
        async with (
            Worker(
                client,
                task_queue="orders-tq",
                workflows=[OrderWorkflow],
                activities=[receive_order, validate_order, charge_payment, persist_address, mark_shipped],
            ),
            Worker(
                client,
                task_queue="shipping-tq",
                workflows=[ShippingWorkflow],
                activities=[prepare_package, dispatch_carrier],
            ),
        ):
            # Start workflow (single payload dict)
            handle = await client.start_workflow(
                OrderWorkflow.run,
                {
                    "order_id": order_id,
                    "payment_id": payment_id,
                    "address": {"line1": "123 Main", "city": "Chicago"},
                    "items": [{"sku": "ABC", "qty": 1}],
                },
                id=f"order-{order_id}",
                task_queue="orders-tq",
                run_timeout=timedelta(seconds=15),
            )

            # Approve immediately (manual review gate)
            await handle.signal(OrderWorkflow.approve)

            # Await completion
            result = await handle.result()
            assert result == "shipped"

            # Query status
            status = await handle.query(OrderWorkflow.status)
            assert status["step"] == "done"
            assert status["approved"] is True
            assert status["last_error"] is None
