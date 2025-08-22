# app/workflows.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

ACT_START_TO_CLOSE = timedelta(seconds=2)
ACT_SCHEDULE_TO_CLOSE = timedelta(seconds=8)
ACT_RETRY = RetryPolicy(
    initial_interval=timedelta(milliseconds=500),
    backoff_coefficient=1.5,
    maximum_attempts=2,
)
MANUAL_REVIEW_WINDOW = timedelta(seconds=3)
SHIPPING_TASK_QUEUE = "shipping-tq"


@workflow.defn
class ShippingWorkflow:
    @workflow.run
    async def run(self, payload: Dict[str, Any]) -> str:
        """
        Expects: {
          "order": {...},               # dict with order_id, items, address
          "parent_workflow_id": "..."   # string
        }
        """
        order = payload["order"]
        parent_workflow_id = payload["parent_workflow_id"]

        # Prepare package
        await workflow.execute_activity(
            "prepare_package",
            order,  # single argument (dict)
            start_to_close_timeout=ACT_START_TO_CLOSE,
            schedule_to_close_timeout=ACT_SCHEDULE_TO_CLOSE,
            retry_policy=ACT_RETRY,
        )

        # Dispatch carrier; on failure, notify parent then re-raise
        try:
            await workflow.execute_activity(
                "dispatch_carrier",
                order,  # single argument (dict)
                start_to_close_timeout=ACT_START_TO_CLOSE,
                schedule_to_close_timeout=ACT_SCHEDULE_TO_CLOSE,
                retry_policy=ACT_RETRY,
            )
        except Exception as e:
            await workflow.signal_external_workflow(
                parent_workflow_id, "dispatch_failed", str(e)
            )
            raise

        return "dispatched"


@dataclass
class _OrderState:
    order_id: str
    payment_id: str
    address: Optional[Dict[str, Any]] = None
    items: Optional[List[Dict[str, Any]]] = None

    approved: bool = False
    canceled: bool = False
    cancel_reason: Optional[str] = None

    current_step: str = "init"
    child_attempts: int = 0
    last_error: Optional[str] = None
    dispatch_failed_reason: Optional[str] = None


@workflow.defn
class OrderWorkflow:
    def __init__(self) -> None:
        # Initialize state so signals arriving before run() don't crash
        self.s: _OrderState = _OrderState(order_id="", payment_id="")

    # --------- Signals ---------
    @workflow.signal
    def cancel_order(self, reason: str = "user_request") -> None:
        self.s.canceled = True
        self.s.cancel_reason = reason

    @workflow.signal
    def update_address(self, address: Dict[str, Any]) -> None:
        self.s.address = address

    @workflow.signal
    def approve(self) -> None:
        self.s.approved = True

    # Child will call this on failure
    @workflow.signal
    def dispatch_failed(self, reason: str) -> None:
        self.s.dispatch_failed_reason = reason

    # ---------- Query ----------
    @workflow.query
    def status(self) -> Dict[str, Any]:
        return {
            "order_id": self.s.order_id,
            "step": self.s.current_step,
            "approved": self.s.approved,
            "canceled": self.s.canceled,
            "cancel_reason": self.s.cancel_reason,
            "child_attempts": self.s.child_attempts,
            "last_error": self.s.last_error,
            "dispatch_failed_reason": self.s.dispatch_failed_reason,
        }

    # ---------- Run ----------
    @workflow.run
    async def run(self, payload: Dict[str, Any]) -> str:
        """
        Expects: {
          "order_id": "...",
          "payment_id": "...",
          "address": {...} | None,
          "items": [ ... ] | None
        }
        """
        order_id: str = payload["order_id"]
        payment_id: str = payload["payment_id"]
        address: Optional[Dict[str, Any]] = payload.get("address")
        items: Optional[List[Dict[str, Any]]] = payload.get("items")

        self.s = _OrderState(order_id=order_id, payment_id=payment_id, address=address, items=items)

        # --- ReceiveOrder ---
        self._set_step("receive_order")
        order = await workflow.execute_activity(
            "receive_order",
            {  # SINGLE payload dict
                "order_id": order_id,
                "address": address,
                "items": items,
            },
            start_to_close_timeout=ACT_START_TO_CLOSE,
            schedule_to_close_timeout=ACT_SCHEDULE_TO_CLOSE,
            retry_policy=ACT_RETRY,
        )
        if self.s.canceled:
            return "canceled"

        # --- ValidateOrder ---
        self._set_step("validate_order")
        await workflow.execute_activity(
            "validate_order",
            order,  # single dict arg
            start_to_close_timeout=ACT_START_TO_CLOSE,
            schedule_to_close_timeout=ACT_SCHEDULE_TO_CLOSE,
            retry_policy=ACT_RETRY,
        )
        if self.s.canceled:
            return "canceled"

        # --- Persist latest address if a signal updated it during validation ---
        if self.s.address is not None:
            await workflow.execute_activity(
                "persist_address",
                {  # SINGLE payload dict
                    "order_id": self.s.order_id,
                    "address": self.s.address,
                },
                start_to_close_timeout=ACT_START_TO_CLOSE,
                schedule_to_close_timeout=ACT_SCHEDULE_TO_CLOSE,
                retry_policy=ACT_RETRY,
            )

        # --- Manual Review Gate (timer + approve signal) ---
        self._set_step("awaiting_approval")
        deadline = workflow.now() + MANUAL_REVIEW_WINDOW
        while not self.s.approved and not self.s.canceled and workflow.now() < deadline:
            await workflow.sleep(timedelta(milliseconds=100))

        if self.s.canceled:
            return "canceled"
        if not self.s.approved:
            self.s.last_error = "manual_review_timeout"
            return "failed"

        # --- ChargePayment (idempotent) ---
        self._set_step("charge_payment")
        await workflow.execute_activity(
            "charge_payment",
            {  # SINGLE payload dict
                "order": order,
                "payment_id": self.s.payment_id,
            },
            start_to_close_timeout=ACT_START_TO_CLOSE,
            schedule_to_close_timeout=ACT_SCHEDULE_TO_CLOSE,
            retry_policy=ACT_RETRY,
        )

        # --- Start child ShippingWorkflow on separate TQ ---
        self._set_step("shipping_child")
        attempts = 0
        while True:
            attempts += 1
            self.s.child_attempts = attempts
            try:
                await workflow.execute_child_workflow(
                    ShippingWorkflow.run,
                    {
                        "order": {
                            "order_id": self.s.order_id,
                            "items": order.get("items"),
                            "address": self.s.address,
                        },
                        "parent_workflow_id": self._workflow_id(),
                    },
                    id=f"ship-{self.s.order_id}-{attempts}",
                    task_queue=SHIPPING_TASK_QUEUE,
                    run_timeout=timedelta(seconds=10),
                )
                break  # child succeeded
            except Exception as e:
                self.s.last_error = f"shipping_failed: {e!s}"
                if attempts >= 2:
                    return "failed"
                # else retry once

        # --- Mark order shipped in DB ---
        self._set_step("mark_shipped")
        await workflow.execute_activity(
            "mark_shipped",
            {"order_id": self.s.order_id},  # SINGLE payload dict
            start_to_close_timeout=ACT_START_TO_CLOSE,
            schedule_to_close_timeout=ACT_SCHEDULE_TO_CLOSE,
            retry_policy=ACT_RETRY,
        )

        self._set_step("done")
        return "shipped"

    # ---------- Helpers ----------
    def _set_step(self, step: str) -> None:
        self.s.current_step = step

    def _workflow_id(self) -> str:
        return workflow.info().workflow_id
