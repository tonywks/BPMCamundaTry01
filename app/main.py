import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.workflow import evaluate_approval, task_label

USERS = {
    "alice": {"name": "Alice Chen", "role": "requester"},
    "manager": {"name": "Michael Lin", "role": "manager"},
    "finance": {"name": "Fiona Wang", "role": "finance"},
    "procurement_director": {"name": "David Wu", "role": "procurement_director"},
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class Repository:
    def __init__(self, path: str):
        self.path = path
        with self.connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS purchase_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, requester TEXT NOT NULL, supplier TEXT NOT NULL,
                category TEXT NOT NULL, amount REAL NOT NULL, currency TEXT NOT NULL, justification TEXT NOT NULL,
                status TEXT NOT NULL, current_step INTEGER NOT NULL DEFAULT 0, route TEXT NOT NULL,
                created_at TEXT NOT NULL, camunda_instance_key TEXT
            );
            CREATE TABLE IF NOT EXISTS approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER NOT NULL, actor TEXT NOT NULL,
                decision TEXT NOT NULL, comment TEXT, decided_at TEXT NOT NULL
            );
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create(self, **data) -> int:
        route = ",".join(evaluate_approval(float(data["amount"]), data["category"]))
        with self.connect() as conn:
            cur = conn.execute("""INSERT INTO purchase_requests
              (requester,supplier,category,amount,currency,justification,status,current_step,route,created_at)
              VALUES (?,?,?,?,?,?,?,?,?,?)""", (data["requester"], data["supplier"], data["category"],
              float(data["amount"]), data["currency"], data["justification"], "Pending", 0, route, utcnow()))
            return cur.lastrowid

    def get(self, request_id: int):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM purchase_requests WHERE id=?", (request_id,)).fetchone()
            if not row:
                raise KeyError(request_id)
            return row

    def list(self):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM purchase_requests ORDER BY id DESC").fetchall()

    def set_camunda_instance(self, request_id: int, instance_key: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE purchase_requests SET camunda_instance_key=? WHERE id=?", (instance_key, request_id))

    def approvals(self, request_id: int):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM approvals WHERE request_id=? ORDER BY id", (request_id,)).fetchall()

    def decide(self, request_id: int, actor: str, decision: str, comment: str):
        request = self.get(request_id)
        route = request["route"].split(",")
        required = route[request["current_step"]] if request["status"] == "Pending" else None
        if USERS.get(actor, {}).get("role") != required:
            raise PermissionError("This identity cannot complete the current approval task.")
        with self.connect() as conn:
            conn.execute("INSERT INTO approvals (request_id,actor,decision,comment,decided_at) VALUES (?,?,?,?,?)",
                         (request_id, actor, decision, comment, utcnow()))
            if decision == "reject":
                conn.execute("UPDATE purchase_requests SET status='Rejected' WHERE id=?", (request_id,))
            elif request["current_step"] + 1 == len(route):
                conn.execute("UPDATE purchase_requests SET status='Approved', current_step=? WHERE id=?",
                             (request["current_step"] + 1, request_id))
            else:
                conn.execute("UPDATE purchase_requests SET current_step=current_step+1 WHERE id=?", (request_id,))


class CamundaClient:
    """Best-effort Camunda 8 REST deployment/start integration; UI stays usable offline."""
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or os.getenv("CAMUNDA_REST_URL", "http://localhost:8080")).rstrip("/")

    def deploy_and_start(self, request_id: int, amount: float, category: str) -> Optional[str]:
        process_dir = Path(__file__).parent.parent / "processes"
        try:
            with httpx.Client(timeout=5) as client:
                files = [
                    ("resources", ("purchase-approval.bpmn", (process_dir / "purchase-approval.bpmn").read_bytes(), "application/xml")),
                    ("resources", ("approval-routing.dmn", (process_dir / "approval-routing.dmn").read_bytes(), "application/xml")),
                ]
                deployed = client.post(f"{self.base_url}/v2/deployments", files=files)
                deployed.raise_for_status()
                payload = {"processDefinitionId": "purchase-approval", "variables": {"requestId": request_id, "amount": amount, "category": category}}
                started = client.post(f"{self.base_url}/v2/process-instances", json=payload)
                started.raise_for_status()
                return str(started.json().get("processInstanceKey", "deployed"))
        except (httpx.HTTPError, OSError):
            return None


STYLE = """<style>
*{box-sizing:border-box} body{margin:0;background:#f4f7fb;color:#172033;font:15px system-ui,-apple-system,sans-serif}nav{background:#172554;color:white;padding:16px 6%;display:flex;justify-content:space-between;align-items:center}nav a{color:white;text-decoration:none;font-weight:700}.shell{max-width:1080px;margin:32px auto;padding:0 20px}.card{background:white;border:1px solid #dbe3ef;border-radius:12px;padding:24px;margin:16px 0;box-shadow:0 2px 8px #1725540c}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}label{font-weight:650;display:block;margin-top:8px}input,select,textarea,button{font:inherit;padding:10px;border-radius:7px;border:1px solid #bdc9dc;width:100%;margin:6px 0 12px}textarea{min-height:90px}button{background:#2563eb;border:0;color:#fff;font-weight:700;cursor:pointer;width:auto;padding:10px 18px}.danger{background:#b91c1c}.badge{font-size:13px;padding:5px 9px;border-radius:999px;background:#e0e7ff;color:#3730a3;font-weight:700}.Approved{background:#dcfce7;color:#166534}.Rejected{background:#fee2e2;color:#991b1b}table{width:100%;border-collapse:collapse}td,th{padding:11px;border-bottom:1px solid #e5e7eb;text-align:left}.muted{color:#64748b}.timeline{border-left:3px solid #bfdbfe;padding-left:18px;margin-left:8px}.alert{background:#eff6ff;border-left:4px solid #2563eb;padding:12px}</style>"""


def layout(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>{STYLE}</head><body><nav><a href='/'>ProcureFlow · Camunda 8</a><span>Demo identities: Alice / Manager / Finance / Director</span></nav><main class='shell'>{body}</main></body></html>")


def request_detail(repo: Repository, request_id: int, notice: str = "") -> HTMLResponse:
    r = repo.get(request_id); route = r["route"].split(","); approvals = repo.approvals(request_id)
    current = task_label(route[r["current_step"]]) if r["status"] == "Pending" else "No open task"
    rows = "".join(f"<tr><td>{escape(a['actor'])}</td><td>{escape(a['decision'])}</td><td>{escape(a['comment'] or '')}</td><td>{a['decided_at']}</td></tr>" for a in approvals) or "<tr><td colspan=4 class=muted>No decisions yet.</td></tr>"
    route_html = " → ".join(task_label(x) for x in route)
    action = ""
    if r["status"] == "Pending":
        action = f"""<div class='card'><h2>Sign-off task: {current}</h2><p>Switch identity to submit a decision. Only the role owning the current task is authorized.</p><form method='post' action='/purchase-requests/{r['id']}/approve'><div class='grid'><label>Acting identity<select name='actor'>{''.join(f"<option value='{k}'>{v['name']} — {v['role']}</option>" for k,v in USERS.items())}</select></label><label>Decision<select name='decision'><option value='approve'>Approve</option><option value='reject'>Reject</option></select></label></div><label>Comment<textarea name='comment' placeholder='Reason / audit note'></textarea></label><button>Submit signed decision</button></form></div>"""
    notice_html = f"<p class='alert'>{escape(notice)}</p>" if notice else ""
    return layout(f"PR-{r['id']}", f"""{notice_html}<p><a href='/'>← Dashboard</a></p><div class='card'><div style='display:flex;justify-content:space-between'><div><h1>PR-{r['id']} · {escape(r['supplier'])}</h1><p class='muted'>Submitted by {escape(r['requester'])} · {r['created_at']}</p></div><span class='badge {r['status']}'>{r['status']}</span></div><div class='grid'><p><b>Amount</b><br>{r['amount']:,.0f} {r['currency']}</p><p><b>Category</b><br>{escape(r['category'])}</p><p><b>Current task</b><br>{current}</p></div><p><b>Business justification</b><br>{escape(r['justification'])}</p><p><b>DMN route</b><br>{route_html}</p><p><b>Camunda process instance</b><br>{escape(r['camunda_instance_key'] or 'Not connected')}</p></div>{action}<div class='card'><h2>Audit trail</h2><table><tr><th>Identity</th><th>Decision</th><th>Comment</th><th>When</th></tr>{rows}</table></div>""")


def create_app(database_path: str = "purchases.db") -> FastAPI:
    app = FastAPI(title="ProcureFlow Camunda Example")
    repo = Repository(database_path)
    camunda = CamundaClient()

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        rows = repo.list()
        table = "".join(f"<tr><td><a href='/purchase-requests/{r['id']}'>PR-{r['id']}</a></td><td>{escape(r['supplier'])}</td><td>{r['amount']:,.0f} {r['currency']}</td><td><span class='badge {r['status']}'>{r['status']}</span></td></tr>" for r in rows) or "<tr><td colspan=4 class='muted'>No requests yet.</td></tr>"
        return layout("ProcureFlow", f"""<div class='grid'><div class='card'><h1>Purchase request workflow</h1><p>Python + FastAPI UI, BPMN process and DMN routing for Camunda 8.</p><p><a href='/camunda'>View Camunda integration status →</a></p></div><div class='card'><h2>Approval identity switch</h2><p>Alice Chen (requester), Michael Lin (manager), Fiona Wang (finance), and David Wu (director).</p></div></div><div class='card'><h2>Submit a request</h2><form method='post' action='/purchase-requests'><div class='grid'><label>Requester<select name='requester'><option value='alice'>Alice Chen</option></select></label><label>Supplier<input name='supplier' required placeholder='Supplier name'></label><label>Category<select name='category'><option>IT</option><option>Office</option><option>Regulated</option></select></label><label>Amount (TWD)<input type='number' min='1' name='amount' required></label></div><input type='hidden' name='currency' value='TWD'><label>Business justification<textarea name='justification' required></textarea></label><button>Start purchase workflow</button></form></div><div class='card'><h2>Requests</h2><table><tr><th>ID</th><th>Supplier</th><th>Amount</th><th>Status</th></tr>{table}</table></div>""")

    @app.post("/purchase-requests")
    def create_request(requester: str = Form(...), supplier: str = Form(...), category: str = Form(...), amount: float = Form(...), currency: str = Form(...), justification: str = Form(...)):
        request_id = repo.create(requester=requester, supplier=supplier, category=category, amount=amount, currency=currency, justification=justification)
        instance_key = camunda.deploy_and_start(request_id, amount, category)
        if instance_key:
            repo.set_camunda_instance(request_id, instance_key)
        return RedirectResponse(f"/purchase-requests/{request_id}", status_code=303)

    @app.get("/purchase-requests/{request_id}", response_class=HTMLResponse)
    def show_request(request_id: int):
        try: return request_detail(repo, request_id)
        except KeyError: raise HTTPException(404)

    @app.post("/purchase-requests/{request_id}/approve", response_class=HTMLResponse)
    def approve(request_id: int, actor: str = Form(...), decision: str = Form(...), comment: str = Form("")):
        try:
            repo.decide(request_id, actor, decision, comment)
            return request_detail(repo, request_id, f"Decision recorded as {decision} by {USERS[actor]['name']}.")
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except KeyError:
            raise HTTPException(404)

    @app.get("/camunda", response_class=HTMLResponse)
    def camunda_page():
        try:
            response = httpx.get(f"{camunda.base_url}/v2/topology", timeout=2)
            state = "Connected" if response.is_success else f"HTTP {response.status_code}"
        except httpx.HTTPError:
            state = "Offline (UI runs independently; start Docker Camunda to deploy BPMN/DMN automatically)"
        return layout("Camunda integration", f"<div class='card'><h1>Camunda 8 integration</h1><p><b>REST endpoint:</b> {escape(camunda.base_url)}</p><p><b>Status:</b> {escape(state)}</p><p>The application deploys <code>processes/purchase-approval.bpmn</code> and <code>processes/approval-routing.dmn</code> when each request starts. The local UI keeps a synchronized audit-friendly approval task view.</p></div>")

    return app


app = create_app(os.getenv("PURCHASE_DB", "purchases.db"))
