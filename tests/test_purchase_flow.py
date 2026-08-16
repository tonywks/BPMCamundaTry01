from fastapi.testclient import TestClient

from app.main import create_app


def client(tmp_path):
    return TestClient(create_app(database_path=str(tmp_path / "purchases.db")))


def test_request_above_manager_limit_requires_manager_and_finance(tmp_path):
    app = client(tmp_path)
    response = app.post(
        "/purchase-requests",
        data={
            "requester": "alice",
            "supplier": "Acme Supplies",
            "category": "IT",
            "amount": "25000",
            "currency": "TWD",
            "justification": "Replace development laptops",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    request_id = int(response.headers["location"].rsplit("/", 1)[-1])
    detail = app.get(f"/purchase-requests/{request_id}")
    assert "Manager approval" in detail.text
    assert "Finance approval" in detail.text


def test_approvals_complete_in_sequence_and_mark_request_approved(tmp_path):
    app = client(tmp_path)
    created = app.post(
        "/purchase-requests",
        data={
            "requester": "alice", "supplier": "Acme", "category": "IT",
            "amount": "25000", "currency": "TWD", "justification": "Laptop",
        },
        follow_redirects=False,
    )
    request_id = int(created.headers["location"].rsplit("/", 1)[-1])
    manager = app.post(f"/purchase-requests/{request_id}/approve", data={"actor": "manager", "decision": "approve", "comment": "Budget approved"})
    assert manager.status_code == 200
    assert "Finance approval" in manager.text
    finance = app.post(f"/purchase-requests/{request_id}/approve", data={"actor": "finance", "decision": "approve", "comment": "Funds confirmed"})
    assert finance.status_code == 200
    assert "Approved" in finance.text


def test_unauthorised_role_cannot_approve_current_task(tmp_path):
    app = client(tmp_path)
    created = app.post(
        "/purchase-requests",
        data={
            "requester": "alice", "supplier": "Acme", "category": "IT",
            "amount": "1000", "currency": "TWD", "justification": "Keyboard",
        },
        follow_redirects=False,
    )
    request_id = int(created.headers["location"].rsplit("/", 1)[-1])
    response = app.post(f"/purchase-requests/{request_id}/approve", data={"actor": "finance", "decision": "approve", "comment": ""})
    assert response.status_code == 403


def test_dmn_decision_table_returns_expected_routing():
    from app.workflow import evaluate_approval
    assert evaluate_approval(1000, "IT") == ["manager"]
    assert evaluate_approval(25000, "IT") == ["manager", "finance"]
    assert evaluate_approval(60000, "IT") == ["manager", "finance", "procurement_director"]
    assert evaluate_approval(1000, "Regulated") == ["manager", "finance"]
