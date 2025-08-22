# app/workers_orders.py
from __future__ import annotations

import os
import asyncio
import structlog

from temporalio.client import Client
from temporalio.worker import Worker


# Loads .env on import (see your existing config.py)
from .config import ASYNC_MYSQL_URI  # not used here, but keeps DB env loaded

# Activities for the orders side
from .activities import (
    receive_order,
    validate_order,
    charge_payment,
    persist_address,
    mark_shipped,
)

# Order workflow (we'll add this in app/workflows.py next)
from .workflows import OrderWorkflow  # noqa: F401

# ----- envs with safe defaults -----
TEMPORAL_TARGET = os.getenv("TEMPORAL_TARGET", "localhost:7233")
ORDERS_TQ = os.getenv("ORDERS_TQ", "orders-tq")

log = structlog.get_logger("worker.orders")


async def main() -> None:
    # Connect to Temporal dev server
    client = await Client.connect(TEMPORAL_TARGET)
    log.info("connected_to_temporal", target=TEMPORAL_TARGET)

    # Register workflows + activities on the orders task queue
    worker = Worker(
        client=client,
        task_queue=ORDERS_TQ,
        workflows=[OrderWorkflow],
        activities=[
            receive_order,
            validate_order,
            charge_payment,
            persist_address,   # used by UpdateAddress signal handler
            mark_shipped,
        ],
        # Tweak concurrency as you like; defaults are fine for the take-home
        max_concurrent_activities=50,
        max_concurrent_workflow_tasks=20,
    )

    log.info("orders_worker_started", task_queue=ORDERS_TQ)
    await worker.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("orders_worker_stopped")
