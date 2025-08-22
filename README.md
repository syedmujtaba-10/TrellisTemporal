# Trellis Temporal Take-Home (Python) - Order -> Payment -> Shipping

This repo implements the take-home using Temporal’s Python SDK with a **single-payload Order workflow**, a **Shipping child workflow**, and a **local MySQL** database for persistence (orders, payments, shipments, events). It includes:

* Temporal workflows/activities with retries, a manual-review timer, signals, and a child workflow on a separate task queue.
* A small FastAPI **API** to start workflows, send signals (approve/cancel/update address), and inspect status.
* **Tests** (unit + Temporal time-skipping test).
* **Docker** (Temporal dev server, API, workers, MySQL, Adminer) + **Manual run instructions**.

> ✅ We follow the assignment’s single-payload contract: the workflow `run()` takes **one dict**:
> `{"order_id", "payment_id", "address", "items"}`

---

## Contents

* [Architecture](#architecture)
* [Data Model](#data-model)
* [Requirements](#requirements)
* [Project Layout](#project-layout)
* [Quick Start (Manual — recommended first)](#quick-start-manual--recommended-first)
* [Happy-Path One-Liner (PowerShell)](#happy-path-one-liner-powershell)
* [All-in-Docker](#all-in-docker)
* [API Reference](#api-reference)
* [Observability & Logs](#observability--logs)
* [Tests](#tests)
* [Configuration](#configuration)
* [Troubleshooting](#troubleshooting)

---

## Architecture

**OrderWorkflow** (parent, task queue `orders-tq`)

1. `receive_order` -> DB insert + event.
2. `validate_order` -> DB state update.
3. Manual Review window (timer \~3s) -> waits for `approve` **signal**.
4. `charge_payment` -> idempotent by `payment_id` (DB upsert).
5. Starts **child** `ShippingWorkflow` on **`shipping-tq`**.
6. `mark_shipped` -> DB state update to `shipped`.

**Signals**

* `approve()` - pass manual review.
* `cancel_order(reason)` - cancel before shipment.
* `update_address(address)` - update prior to dispatch.
* From child: `dispatch_failed(reason)` -> parent may retry child.

**ShippingWorkflow** (child, task queue `shipping-tq`)

* `prepare_package` and `dispatch_carrier`.
* On failure, signals parent `dispatch_failed`.

**Activity timeouts/retries** are tight (to exercise `flaky_call()` behavior in services).

---

## Data Model

Tables (created by `db/init.sql`):

* `orders(id, state, address_json, created_at, updated_at)`
* `payments(payment_id PK, order_id, status, amount, created_at, updated_at)`
* `shipments(id, order_id, status, payload_json, ts)`
* `events(id, order_id, type, payload_json, ts)` ← **audit trail**

**Idempotency:** `payment_id` is the PK; `INSERT … ON DUPLICATE KEY UPDATE` ensures safe retries.

---

## Requirements

* **Python** 3.11+
* **Docker** (for Temporal dev server / optional stack)
* **Windows (PowerShell)** steps included; macOS/Linux commands are similar.

Python deps (see `requirements.txt`):

```
temporalio==1.8.*
fastapi==0.115.*
uvicorn[standard]==0.30.*
SQLAlchemy==2.0.*
aiomysql==0.2.*
cryptography
python-dotenv
pydantic==2.*
structlog==24.*
pytest==8.*
pytest-asyncio==0.23.*
```

Install:

```powershell
python -m venv trellisvenv
.\trellisvenv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## Project Layout

```
app/
  api.py                # FastAPI (start workflow, signals, status)
  activities.py         # Thin wrappers calling services
  services.py           # Business stubs + DB writes + flaky_call()
  workflows.py          # OrderWorkflow + ShippingWorkflow (single payload)
  workers_orders.py     # Worker for orders-tq
  workers_shipping.py   # Worker for shipping-tq
  db.py                 # Async SQLAlchemy engine + helpers
db/
  init.sql              # Creates tables
tests/
  test_payment_idempotency.py
  test_workflow_happy.py
docker-compose.yaml     # Temporal + API + workers + MySQL + Adminer (optional)
README.md
```

---

## Quick Start (Manual — recommended first)

Run each in **its own terminal**. Close Docker Compose if running:

```powershell
docker compose down -v
```

### 1) Run Docker

```powershell
docker compose up
```

### 2) Orders worker

```powershell
.\trellisvenv\Scripts\Activate.ps1

python -m app.workers_orders
```

### 3) Shipping worker

```powershell
.\trellisvenv\Scripts\Activate.ps1

python -m app.workers_shipping
```

### 4) API (FastAPI)

```powershell
.\trellisvenv\Scripts\Activate.ps1

uvicorn app.api:app --host 0.0.0.0 --port 8000
```

Health:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

---

## Happy-Path One-Liner (PowerShell)

```powershell
$oid="o-$([int](Get-Random -Minimum 1000 -Maximum 9999))"; $payload=@{payment_id="pay-$oid"; address=@{line1="123 Main"; city="Chicago"}; items=@(@{sku="ABC"; qty=1})} | ConvertTo-Json -Depth 6; irm -Method Post -Uri "http://localhost:8000/orders/$oid/start" -Body $payload -ContentType 'application/json'; Start-Sleep -Milliseconds 800; irm -Method Post -Uri "http://localhost:8000/orders/$oid/signals/approve"; irm -Method Get -Uri "http://localhost:8000/orders/$oid/status"
```

> If `/status` errors with *“WorkflowTaskStarted”*, wait \~300ms after start, then retry status (race during first task).

---

## All-in-Docker

Once manual works, you can run the full stack:

```powershell
docker compose up -d --build
docker compose ps
```



## API Reference

Base URL: `http://localhost:8000`

### Health

`GET /health` → `{"ok": true}`

### Start Order

`POST /orders/{order_id}/start`
Body (single payload dict):

```json
{
  "payment_id": "pay-o-1234",
  "address": { "line1": "123 Main", "city": "Chicago" },
  "items": [ { "sku": "ABC", "qty": 1 } ]
}
```

Response:

```json
{ "workflow_id": "order-o-1234", "run_id": "..." }
```

### Signals

* `POST /orders/{order_id}/signals/approve`
* `POST /orders/{order_id}/signals/cancel`
  Body: `{ "reason": "user_request" }`
* `POST /orders/{order_id}/signals/address`
  Body: `{ "address": { "line1": "...", "city": "..." } }`

### Status

* `GET /orders/{order_id}/status`
  Returns workflow query result or a fallback **lifecycle** via Describe if query isn’t ready (maps NOT\_FOUND → 404).

---

## Observability & Logs

* **Temporal UI** ([http://localhost:8233](http://localhost:8233)): full event history, retries, failure reasons, child workflow.
* **DB events**:

  ```sql
  SELECT type, JSON_PRETTY(payload_json) AS payload, ts
  FROM events
  WHERE order_id = 'o-1234'
  ORDER BY ts;
  ```
* **Worker logs** show structured entries (`receive_order.start`, `charge_payment.start`, etc.) including retry attempt numbers.

---

## Tests

Run:

```powershell
.\trellisvenv\Scripts\Activate.ps1
python -m pytest -q
```

What they cover:

* **`test_payment_idempotency.py`** — ensures duplicate `payment_id` charges are idempotent (single row).
* **`test_workflow_happy.py`** — Temporal **time-skipping** test runs both workers in-process, sends `approve`, and asserts the workflow completes within the 15s runtime budget.

> Tests patch `services.flaky_call` to deterministic no-failures for predictable outcomes.

---

## Configuration

These env vars are read by API and workers:

```
TEMPORAL_TARGET=localhost:7233
ORDERS_TQ=orders-tq
SHIPPING_TQ=shipping-tq

MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_DB=trellis
MYSQL_USER=trellis
MYSQL_PASSWORD=trellisPW
```

You can also place them in a `.env` and load via `python-dotenv` (already included).

---


