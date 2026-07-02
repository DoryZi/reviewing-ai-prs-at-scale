"""Expense tracker API — the deliberately boring demo app for self-healing-reviews.

The app is small on purpose: every scene in the review-stack demo plants a bug
here and shows a different layer of the stack catching it.
"""

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from app import db

app = FastAPI(title="Expense Tracker", version="0.1.0")


class ExpenseIn(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    amount_cents: int = Field(gt=0)
    category: str = Field(min_length=1, max_length=50)


class Expense(ExpenseIn):
    id: int


def get_db() -> Iterator[sqlite3.Connection]:
    conn = db.get_connection(Path(os.getenv("EXPENSES_DB", "expenses.db")))
    try:
        yield conn
    finally:
        conn.close()


@app.post("/expenses", response_model=Expense, status_code=201)
def create_expense(expense: ExpenseIn, conn: sqlite3.Connection = Depends(get_db)) -> Expense:
    cur = conn.execute(
        "INSERT INTO expenses (description, amount_cents, category) VALUES (?, ?, ?)",
        (expense.description, expense.amount_cents, expense.category),
    )
    conn.commit()
    return Expense(id=cur.lastrowid or 0, **expense.model_dump())


@app.get("/expenses", response_model=list[Expense])
def list_expenses(
    category: str | None = None, conn: sqlite3.Connection = Depends(get_db)
) -> list[Expense]:
    if category is not None:
        rows = conn.execute("SELECT * FROM expenses WHERE category = ?", (category,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM expenses").fetchall()
    return [Expense(**dict(row)) for row in rows]


@app.get("/expenses/{expense_id}", response_model=Expense)
def get_expense(expense_id: int, conn: sqlite3.Connection = Depends(get_db)) -> Expense:
    row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="expense not found")
    return Expense(**dict(row))


@app.get("/summary")
def summary(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, int]:
    rows = conn.execute(
        "SELECT category, SUM(amount_cents) AS total_cents FROM expenses GROUP BY category"
    ).fetchall()
    return {row["category"]: row["total_cents"] for row in rows}
