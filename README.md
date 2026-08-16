# BPMCamundaTry01 — ProcureFlow

A complete, runnable Camunda 8 purchase-request example written in Python.

## What it demonstrates

- A complete FastAPI purchase-request UI, including dashboard, request form, detail view, status, and audit trail.
- Demo login/identity switching at every approval step: requester, manager, finance, and procurement director.
- Role-enforced sign-off: an identity cannot approve a task it does not own.
- `processes/purchase-approval.bpmn` — a deployable BPMN process that calls a DMN business rule task and assigns a user task.
- `processes/approval-routing.dmn` — approval routing rules:
  - ≤ 10,000 TWD: manager
  - > 10,000 TWD or regulated category: manager + finance
  - > 50,000 TWD: manager + finance + procurement director
- Camunda 8 REST integration: each submission attempts to deploy the BPMN + DMN assets and starts a process instance. The UI retains a local audit view so it is also usable during Camunda downtime.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# Terminal 1: local Camunda 8
# The project was tested with Docker Desktop.
docker compose up -d
# Terminal 2: app
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000. Camunda REST runs on http://127.0.0.1:8080.

## Tests

```bash
.venv/bin/pytest -q
```

The tests cover DMN-equivalent route evaluation, sequential approvals, final status, and an unauthorized approval attempt.

## Note about Camunda tasks

The BPMN and DMN are deployed to a local Camunda 8 endpoint through `/v2/deployments`; a process instance is started through `/v2/process-instances`. For a lightweight, immediately inspectable training sample, web approvals are stored in SQLite and mirror the DMN task route, rather than relying on the Tasklist UI.
