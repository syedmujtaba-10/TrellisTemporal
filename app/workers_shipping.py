# app/workers_shipping.py
from __future__ import annotations

import os
import asyncio
import structlog

from temporalio.client import Client
from temporalio.worker import Worker



# Load env via config import side effect (not directly used here)
from .config import ASYNC_MYSQL_URI  # noqa: F401

# Shipping activities
from .activities import prepare_package, dispatch_carrier

# Shipping workflow (we'll implement it in app/workflows.py)
from .workflows import ShippingWorkflow  # noqa: F401

TEMPORAL_TARGET = os.getenv("TEMPORAL_TARGET", "localhost:7233")
SHIPPING_TQ = os.getenv("SHIPPING_TQ", "shipping-tq")

log = structlog.get_logger("worker.shipping")


async def main() -> None:
    client = await Client.connect(TEMPORAL_TARGET)
    log.info("connected_to_temporal", target=TEMPORAL_TARGET)

    worker = Worker(
        client=client,
        task_queue=SHIPPING_TQ,
        workflows=[ShippingWorkflow],
        activities=[
            prepare_package,
            dispatch_carrier,
        ],
        max_concurrent_activities=50,
        max_concurrent_workflow_tasks=20,
    )

    log.info("shipping_worker_started", task_queue=SHIPPING_TQ)
    await worker.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("shipping_worker_stopped")
