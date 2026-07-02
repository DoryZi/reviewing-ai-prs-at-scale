"""Expense tracker API — the deliberately boring demo app for self-healing-reviews.

The app is small on purpose: every scene in the review-stack demo plants a bug
here and shows a different layer of the stack catching it.
"""

import calendar
import csv
import io
import os
import sqlite3
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app import db

app = FastAPI(title="Expense Tracker", version="0.2.0")

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


class ExpenseIn(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    amount_cents: int = Field(gt=0)
    category: str = Field(min_length=1, max_length=50)
    spent_on: date | None = None


class Expense(BaseModel):
    id: int
    description: str
    amount_cents: int
    category: str
    spent_on: date


class BudgetIn(BaseModel):
    category: str = Field(min_length=1, max_length=50)
    month: str = Field(pattern=MONTH_PATTERN)
    amount_cents: int = Field(gt=0)


class Budget(BudgetIn):
    id: int


class BudgetStatus(BaseModel):
    category: str
    month: str
    budget_cents: int
    spent_cents: int
    remaining_cents: int
    over_budget: bool


class RecurringIn(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    amount_cents: int = Field(gt=0)
    category: str = Field(min_length=1, max_length=50)
    day_of_month: int = Field(ge=1, le=31)


class Recurring(RecurringIn):
    id: int


class MaterializeResult(BaseModel):
    month: str
    created: list[Expense]
    skipped: int


class ImportResult(BaseModel):
    imported: int


def get_db() -> Iterator[sqlite3.Connection]:
    conn = db.get_connection(Path(os.getenv("EXPENSES_DB", "expenses.db")))
    try:
        yield conn
    finally:
        conn.close()


def _row_to_expense(row: sqlite3.Row) -> Expense:
    return Expense(
        id=row["id"],
        description=row["description"],
        amount_cents=row["amount_cents"],
        category=row["category"],
        spent_on=date.fromisoformat(row["spent_on"]),
    )


def _insert_expense(conn: sqlite3.Connection, expense: ExpenseIn) -> Expense:
    spent_on = expense.spent_on or date.today()
    cur = conn.execute(
        "INSERT INTO expenses (description, amount_cents, category, spent_on)"
        " VALUES (?, ?, ?, ?)",
        (expense.description, expense.amount_cents, expense.category, spent_on.isoformat()),
    )
    return Expense(
        id=cur.lastrowid or 0,
        description=expense.description,
        amount_cents=expense.amount_cents,
        category=expense.category,
        spent_on=spent_on,
    )


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------


@app.post("/expenses", response_model=Expense, status_code=201)
def create_expense(expense: ExpenseIn, conn: sqlite3.Connection = Depends(get_db)) -> Expense:
    created = _insert_expense(conn, expense)
    conn.commit()
    return created


# NOTE: static /expenses/* routes must be declared before /expenses/{expense_id}
# so "export"/"import" are not swallowed by the int path converter.


@app.get("/expenses/export")
def export_expenses_csv(
    start: date | None = None,
    end: date | None = None,
    category: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> Response:
    """Export expenses as CSV, optionally filtered by date range and category."""
    query = "SELECT * FROM expenses WHERE 1=1"
    params: list[str] = []
    if start is not None:
        query += " AND spent_on >= ?"
        params.append(start.isoformat())
    if end is not None:
        query += " AND spent_on <= ?"
        params.append(end.isoformat())
    if category is not None:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY spent_on, id"
    rows = conn.execute(query, params).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "description", "amount_cents", "category", "spent_on"])
    for row in rows:
        writer.writerow(
            [row["id"], row["description"], row["amount_cents"], row["category"], row["spent_on"]]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="expenses.csv"'},
    )


@app.post("/expenses/import", response_model=ImportResult, status_code=201)
async def import_expenses_csv(
    file: UploadFile, conn: sqlite3.Connection = Depends(get_db)
) -> ImportResult:
    """Import expenses from an uploaded CSV file.

    Expected columns: description, amount_cents, category, and optionally
    spent_on (ISO date; defaults to today). The whole file imports atomically —
    any bad row rejects the entire upload with a 400 naming the row.
    """
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="file is not valid UTF-8") from exc

    reader = csv.DictReader(io.StringIO(text))
    required = {"description", "amount_cents", "category"}
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        raise HTTPException(
            status_code=400,
            detail=f"CSV must have columns: {', '.join(sorted(required))}",
        )

    imported = 0
    for line_no, row in enumerate(reader, start=2):
        try:
            spent_on_raw = (row.get("spent_on") or "").strip()
            expense = ExpenseIn(
                description=(row.get("description") or "").strip(),
                amount_cents=int((row.get("amount_cents") or "").strip()),
                category=(row.get("category") or "").strip(),
                spent_on=date.fromisoformat(spent_on_raw) if spent_on_raw else None,
            )
        except (ValueError, TypeError) as exc:
            conn.rollback()
            raise HTTPException(status_code=400, detail=f"invalid row at line {line_no}: {exc}") from exc
        _insert_expense(conn, expense)
        imported += 1
    conn.commit()
    return ImportResult(imported=imported)


@app.get("/expenses", response_model=list[Expense])
def list_expenses(
    category: str | None = None, conn: sqlite3.Connection = Depends(get_db)
) -> list[Expense]:
    if category is not None:
        rows = conn.execute("SELECT * FROM expenses WHERE category = ?", (category,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM expenses").fetchall()
    return [_row_to_expense(row) for row in rows]


@app.get("/expenses/{expense_id}", response_model=Expense)
def get_expense(expense_id: int, conn: sqlite3.Connection = Depends(get_db)) -> Expense:
    row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="expense not found")
    return _row_to_expense(row)


@app.get("/summary")
def summary(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, int]:
    rows = conn.execute(
        "SELECT category, SUM(amount_cents) AS total_cents FROM expenses GROUP BY category"
    ).fetchall()
    return {row["category"]: row["total_cents"] for row in rows}


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


@app.put("/budgets", response_model=Budget)
def set_budget(budget: BudgetIn, conn: sqlite3.Connection = Depends(get_db)) -> Budget:
    """Set or update the budget for a category+month (upsert)."""
    conn.execute(
        "INSERT INTO budgets (category, month, amount_cents) VALUES (?, ?, ?)"
        " ON CONFLICT (category, month) DO UPDATE SET amount_cents = excluded.amount_cents",
        (budget.category, budget.month, budget.amount_cents),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM budgets WHERE category = ? AND month = ?",
        (budget.category, budget.month),
    ).fetchone()
    return Budget(**dict(row))


@app.get("/budgets", response_model=list[Budget])
def list_budgets(
    month: str | None = Query(default=None, pattern=MONTH_PATTERN),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[Budget]:
    if month is not None:
        rows = conn.execute(
            "SELECT * FROM budgets WHERE month = ? ORDER BY category", (month,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM budgets ORDER BY month, category").fetchall()
    return [Budget(**dict(row)) for row in rows]


@app.get("/budgets/status", response_model=list[BudgetStatus])
def budget_status(
    month: str = Query(pattern=MONTH_PATTERN),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[BudgetStatus]:
    """Compare each category's budget vs actual spend for the given month.

    Categories with spend but no budget appear with budget_cents=0 so
    unbudgeted spending is visible rather than silently dropped.
    """
    budgets = {
        row["category"]: row["amount_cents"]
        for row in conn.execute("SELECT * FROM budgets WHERE month = ?", (month,))
    }
    spent = {
        row["category"]: row["total_cents"]
        for row in conn.execute(
            "SELECT category, SUM(amount_cents) AS total_cents FROM expenses"
            " WHERE substr(spent_on, 1, 7) = ? GROUP BY category",
            (month,),
        )
    }
    statuses = []
    for category in sorted(set(budgets) | set(spent)):
        budget_cents = budgets.get(category, 0)
        spent_cents = spent.get(category, 0)
        statuses.append(
            BudgetStatus(
                category=category,
                month=month,
                budget_cents=budget_cents,
                spent_cents=spent_cents,
                remaining_cents=budget_cents - spent_cents,
                over_budget=spent_cents > budget_cents,
            )
        )
    return statuses


# ---------------------------------------------------------------------------
# Recurring expenses
# ---------------------------------------------------------------------------


@app.post("/recurring", response_model=Recurring, status_code=201)
def create_recurring(
    template: RecurringIn, conn: sqlite3.Connection = Depends(get_db)
) -> Recurring:
    cur = conn.execute(
        "INSERT INTO recurring_expenses (description, amount_cents, category, day_of_month)"
        " VALUES (?, ?, ?, ?)",
        (template.description, template.amount_cents, template.category, template.day_of_month),
    )
    conn.commit()
    return Recurring(id=cur.lastrowid or 0, **template.model_dump())


@app.get("/recurring", response_model=list[Recurring])
def list_recurring(conn: sqlite3.Connection = Depends(get_db)) -> list[Recurring]:
    rows = conn.execute("SELECT * FROM recurring_expenses ORDER BY id").fetchall()
    return [Recurring(**dict(row)) for row in rows]


@app.post("/recurring/materialize", response_model=MaterializeResult, status_code=201)
def materialize_recurring(
    month: str = Query(pattern=MONTH_PATTERN),
    conn: sqlite3.Connection = Depends(get_db),
) -> MaterializeResult:
    """Materialize all due recurring templates into real expenses for a month.

    Idempotent per (template, month): a template already materialized for the
    month is skipped, so re-running is safe. day_of_month is clamped to the
    month's last day (a day-31 rent template lands on Feb 28/29).
    """
    year, month_num = (int(part) for part in month.split("-"))
    last_day = calendar.monthrange(year, month_num)[1]

    created: list[Expense] = []
    skipped = 0
    for row in conn.execute("SELECT * FROM recurring_expenses ORDER BY id").fetchall():
        already = conn.execute(
            "SELECT 1 FROM recurring_runs WHERE recurring_id = ? AND month = ?",
            (row["id"], month),
        ).fetchone()
        if already is not None:
            skipped += 1
            continue
        spent_on = date(year, month_num, min(row["day_of_month"], last_day))
        created.append(
            _insert_expense(
                conn,
                ExpenseIn(
                    description=row["description"],
                    amount_cents=row["amount_cents"],
                    category=row["category"],
                    spent_on=spent_on,
                ),
            )
        )
        conn.execute(
            "INSERT INTO recurring_runs (recurring_id, month) VALUES (?, ?)", (row["id"], month)
        )
    conn.commit()
    return MaterializeResult(month=month, created=created, skipped=skipped)


@app.get("/recurring/{recurring_id}", response_model=Recurring)
def get_recurring(recurring_id: int, conn: sqlite3.Connection = Depends(get_db)) -> Recurring:
    row = conn.execute(
        "SELECT * FROM recurring_expenses WHERE id = ?", (recurring_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="recurring expense not found")
    return Recurring(**dict(row))


@app.put("/recurring/{recurring_id}", response_model=Recurring)
def update_recurring(
    recurring_id: int, template: RecurringIn, conn: sqlite3.Connection = Depends(get_db)
) -> Recurring:
    cur = conn.execute(
        "UPDATE recurring_expenses SET description = ?, amount_cents = ?, category = ?,"
        " day_of_month = ? WHERE id = ?",
        (
            template.description,
            template.amount_cents,
            template.category,
            template.day_of_month,
            recurring_id,
        ),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="recurring expense not found")
    return Recurring(id=recurring_id, **template.model_dump())


@app.delete("/recurring/{recurring_id}", status_code=204)
def delete_recurring(recurring_id: int, conn: sqlite3.Connection = Depends(get_db)) -> None:
    cur = conn.execute("DELETE FROM recurring_expenses WHERE id = ?", (recurring_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="recurring expense not found")


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@app.get("/reports/spending")
def spending_report(
    start: date | None = None,
    end: date | None = None,
    category: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Spending aggregated by category and by month, with optional filters."""
    where = "WHERE 1=1"
    params: list[str] = []
    if start is not None:
        where += " AND spent_on >= ?"
        params.append(start.isoformat())
    if end is not None:
        where += " AND spent_on <= ?"
        params.append(end.isoformat())
    if category is not None:
        where += " AND category = ?"
        params.append(category)

    by_category = {
        row["category"]: row["total_cents"]
        for row in conn.execute(
            f"SELECT category, SUM(amount_cents) AS total_cents FROM expenses {where}"
            " GROUP BY category ORDER BY category",
            params,
        )
    }
    by_month = {
        row["month"]: row["total_cents"]
        for row in conn.execute(
            f"SELECT substr(spent_on, 1, 7) AS month, SUM(amount_cents) AS total_cents"
            f" FROM expenses {where} GROUP BY month ORDER BY month",
            params,
        )
    }
    return {
        "by_category": by_category,
        "by_month": by_month,
        "total_cents": sum(by_category.values()),
    }
