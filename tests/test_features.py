"""Tests for budgets, recurring expenses, CSV import/export, and reports."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EXPENSES_DB", str(tmp_path / "test.db"))
    return TestClient(app)


def _add_expense(client: TestClient, description: str, cents: int, category: str, spent_on: str):
    resp = client.post(
        "/expenses",
        json={
            "description": description,
            "amount_cents": cents,
            "category": category,
            "spent_on": spent_on,
        },
    )
    assert resp.status_code == 201
    return resp.json()


# --- budgets ---------------------------------------------------------------


def test_budget_upsert_and_list(client: TestClient) -> None:
    first = client.put(
        "/budgets", json={"category": "food", "month": "2026-07", "amount_cents": 50000}
    )
    assert first.status_code == 200
    updated = client.put(
        "/budgets", json={"category": "food", "month": "2026-07", "amount_cents": 60000}
    )
    assert updated.status_code == 200
    assert updated.json()["amount_cents"] == 60000

    listed = client.get("/budgets", params={"month": "2026-07"})
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_budget_rejects_bad_month(client: TestClient) -> None:
    resp = client.put(
        "/budgets", json={"category": "food", "month": "2026-13", "amount_cents": 100}
    )
    assert resp.status_code == 422


def test_budget_status_compares_budget_vs_spend(client: TestClient) -> None:
    client.put("/budgets", json={"category": "food", "month": "2026-07", "amount_cents": 1000})
    _add_expense(client, "lunch", 700, "food", "2026-07-10")
    _add_expense(client, "dinner", 600, "food", "2026-07-11")
    _add_expense(client, "taxi", 300, "travel", "2026-07-12")  # unbudgeted
    _add_expense(client, "old lunch", 999, "food", "2026-06-10")  # other month

    resp = client.get("/budgets/status", params={"month": "2026-07"})
    assert resp.status_code == 200
    by_cat = {s["category"]: s for s in resp.json()}
    assert by_cat["food"]["spent_cents"] == 1300
    assert by_cat["food"]["remaining_cents"] == -300
    assert by_cat["food"]["over_budget"] is True
    assert by_cat["travel"]["budget_cents"] == 0


# --- recurring ---------------------------------------------------------------


def test_recurring_crud(client: TestClient) -> None:
    created = client.post(
        "/recurring",
        json={"description": "rent", "amount_cents": 120000, "category": "housing", "day_of_month": 1},
    )
    assert created.status_code == 201
    rid = created.json()["id"]

    updated = client.put(
        f"/recurring/{rid}",
        json={"description": "rent", "amount_cents": 125000, "category": "housing", "day_of_month": 2},
    )
    assert updated.status_code == 200
    assert updated.json()["amount_cents"] == 125000

    assert client.get(f"/recurring/{rid}").status_code == 200
    assert client.delete(f"/recurring/{rid}").status_code == 204
    assert client.get(f"/recurring/{rid}").status_code == 404


def test_recurring_rejects_bad_day(client: TestClient) -> None:
    resp = client.post(
        "/recurring",
        json={"description": "x", "amount_cents": 100, "category": "misc", "day_of_month": 32},
    )
    assert resp.status_code == 422


def test_materialize_is_idempotent_and_clamps_day(client: TestClient) -> None:
    client.post(
        "/recurring",
        json={"description": "rent", "amount_cents": 120000, "category": "housing", "day_of_month": 31},
    )
    first = client.post("/recurring/materialize", params={"month": "2026-02"})
    assert first.status_code == 201
    body = first.json()
    assert len(body["created"]) == 1
    assert body["created"][0]["spent_on"] == "2026-02-28"

    second = client.post("/recurring/materialize", params={"month": "2026-02"})
    assert second.json()["created"] == []
    assert second.json()["skipped"] == 1

    expenses = client.get("/expenses").json()
    assert len(expenses) == 1


# --- CSV ---------------------------------------------------------------------


def test_csv_export_with_filters(client: TestClient) -> None:
    _add_expense(client, "coffee", 450, "food", "2026-07-01")
    _add_expense(client, "bus", 250, "travel", "2026-07-02")
    _add_expense(client, "old", 100, "food", "2026-05-01")

    resp = client.get(
        "/expenses/export",
        params={"start": "2026-07-01", "end": "2026-07-31", "category": "food"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert lines[0] == "id,description,amount_cents,category,spent_on"
    assert len(lines) == 2
    assert "coffee" in lines[1]


def test_csv_import_roundtrip(client: TestClient) -> None:
    csv_body = (
        "description,amount_cents,category,spent_on\n"
        "coffee,450,food,2026-07-01\n"
        "bus,250,travel,2026-07-02\n"
    )
    resp = client.post(
        "/expenses/import", files={"file": ("expenses.csv", csv_body, "text/csv")}
    )
    assert resp.status_code == 201
    assert resp.json() == {"imported": 2}
    assert len(client.get("/expenses").json()) == 2


def test_csv_import_rejects_bad_row(client: TestClient) -> None:
    csv_body = (
        "description,amount_cents,category,spent_on\n"
        "coffee,not-a-number,food,2026-07-01\n"
    )
    resp = client.post(
        "/expenses/import", files={"file": ("expenses.csv", csv_body, "text/csv")}
    )
    assert resp.status_code == 400
    assert client.get("/expenses").json() == []


def test_csv_import_rejects_missing_columns(client: TestClient) -> None:
    resp = client.post(
        "/expenses/import", files={"file": ("x.csv", "description,amount_cents\na,1\n", "text/csv")}
    )
    assert resp.status_code == 400


# --- reports -----------------------------------------------------------------


def test_spending_report_aggregates_and_filters(client: TestClient) -> None:
    _add_expense(client, "coffee", 450, "food", "2026-06-15")
    _add_expense(client, "lunch", 1200, "food", "2026-07-01")
    _add_expense(client, "bus", 250, "travel", "2026-07-02")

    all_report = client.get("/reports/spending")
    assert all_report.status_code == 200
    body = all_report.json()
    assert body["by_category"] == {"food": 1650, "travel": 250}
    assert body["by_month"] == {"2026-06": 450, "2026-07": 1450}
    assert body["total_cents"] == 1900

    filtered = client.get(
        "/reports/spending",
        params={"start": "2026-07-01", "end": "2026-07-31", "category": "food"},
    )
    fbody = filtered.json()
    assert fbody["by_category"] == {"food": 1200}
    assert fbody["by_month"] == {"2026-07": 1200}
    assert fbody["total_cents"] == 1200
