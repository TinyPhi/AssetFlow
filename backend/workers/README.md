# `backend/workers`

Asynchronous background worker processes (§B4.2, §B9.3). Run with `python -m workers.main`; see
[docs/operations/worker.md](../../docs/operations/worker.md).

| Module | Role |
| --- | --- |
| `main.py` | Process: config, providers, worker database pool, LISTEN wake-up, heartbeat, clean SIGTERM |
| `outbox_dispatcher.py` | Claims outbox rows (`FOR UPDATE SKIP LOCKED`), runs subscribers, records result, dead letter |
| `subscribers.py` | Subscriber registry: event type to named consumers (idempotent through `processed_events`) |

Later plans add the job runner, housekeeping and the notification sender here.
