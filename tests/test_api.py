"""API tests for the expense tracker demo app."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EXPENSES_DB", str(tmp_path / "test.db"))
    return TestClient(app)


def test_create_and_fetch_expense(client: TestClient) -> None:
    created = client.post(
        "/expenses",
        json={"description": "coffee", "amount_cents": 450, "category": "food"},
    )
    assert created.status_code == 201
    expense_id = created.json()["id"]

    fetched = client.get(f"/expenses/{expense_id}")
    assert fetched.status_code == 200
    assert fetched.json()["description"] == "coffee"


def test_rejects_non_positive_amount(client: TestClient) -> None:
    response = client.post(
        "/expenses",
        json={"description": "freebie", "amount_cents": 0, "category": "food"},
    )
    assert response.status_code == 422


def test_list_filters_by_category(client: TestClient) -> None:
    client.post(
        "/expenses", json={"description": "coffee", "amount_cents": 450, "category": "food"}
    )
    client.post("/expenses", json={"description": "bus", "amount_cents": 250, "category": "travel"})

    food_only = client.get("/expenses", params={"category": "food"})
    assert food_only.status_code == 200
    assert [e["category"] for e in food_only.json()] == ["food"]


def test_empty_category_filter_returns_empty_list(client: TestClient) -> None:
    client.post(
        "/expenses",
        json={"description": "coffee", "amount_cents": 450, "category": "food"},
    )
    response = client.get("/expenses", params={"category": ""})
    assert response.status_code == 200
    assert response.json() == []


def test_get_missing_expense_returns_404(client: TestClient) -> None:
    response = client.get("/expenses/999")
    assert response.status_code == 404


def test_summary_totals_by_category(client: TestClient) -> None:
    client.post(
        "/expenses", json={"description": "coffee", "amount_cents": 450, "category": "food"}
    )
    client.post(
        "/expenses", json={"description": "lunch", "amount_cents": 1200, "category": "food"}
    )

    response = client.get("/summary")
    assert response.status_code == 200
    assert response.json() == {"food": 1650}
