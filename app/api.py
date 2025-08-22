# app/api.py
import os
import asyncio
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from temporalio.client import Client

from .workflows import OrderWorkflow

TEMPORAL_TARGET = os.getenv("TEMPORAL_TARGET", "localhost:7233")
ORDERS_TQ = os.getenv("ORDERS_TQ", "orders-tq")

app = FastAPI(title="Trellis Temporal API")

# --------- Models ---------
class StartOrder(BaseModel):
    payment_id: str
    address: Optional[Dict[str, Any]] = None
    items: Optional[List[Dict[str, Any]]] = None

class CancelBody(BaseModel):
    reason: Optional[str] = "user_request"

class AddressBody(BaseModel):
    address: Dict[str, Any]

# --------- Startup / Shutdown ---------
@app.on_event("startup")
async def _startup():
    # Retry until Temporal is ready
    last_err: Optional[Exception] = None
    for _ in range(60):  # ~30s
        try:
            app.state.temporal = await Client.connect(TEMPORAL_TARGET)
            break
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.5)
    else:
        raise RuntimeError(f"Could not connect to Temporal at {TEMPORAL_TARGET}: {last_err}")

@app.on_event("shutdown")
async def _shutdown():
    # Nothing to close for temporal client
    pass

# --------- Routes ---------
@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/orders/{order_id}/start")
async def start_order(order_id: str, payload: StartOrder):
    """
    Start OrderWorkflow with a SINGLE payload dict (matches workflows.py contract).
    """
    client: Client = app.state.temporal
    handle = await client.start_workflow(
        OrderWorkflow.run,
        {
            "order_id": order_id,
            "payment_id": payload.payment_id,
            "address": payload.address,
            "items": payload.items,
        },
        id=f"order-{order_id}",
        task_queue=ORDERS_TQ,
        run_timeout=timedelta(seconds=15),
    )
    return {"workflow_id": handle.id, "run_id": handle.result_run_id}

@app.post("/orders/{order_id}/signals/approve")
async def signal_approve(order_id: str):
    client: Client = app.state.temporal
    handle = client.get_workflow_handle(f"order-{order_id}")
    await handle.signal(OrderWorkflow.approve)
    return {"ok": True}

@app.post("/orders/{order_id}/signals/cancel")
async def signal_cancel(order_id: str, body: CancelBody):
    client: Client = app.state.temporal
    handle = client.get_workflow_handle(f"order-{order_id}")
    await handle.signal(OrderWorkflow.cancel_order, body.reason)
    return {"ok": True}

@app.post("/orders/{order_id}/signals/address")
async def signal_address(order_id: str, body: AddressBody):
    client: Client = app.state.temporal
    handle = client.get_workflow_handle(f"order-{order_id}")
    await handle.signal(OrderWorkflow.update_address, body.address)
    return {"ok": True}

@app.get("/orders/{order_id}/status")
async def status(order_id: str):
    client: Client = app.state.temporal
    handle = client.get_workflow_handle(f"order-{order_id}")
    try:
        st = await handle.query(OrderWorkflow.status)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return st
