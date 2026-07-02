# Scene 1 — Hooks: free, instant, zero context

**The claim:** you already own static tools (linter, formatter, Semgrep). Wire them
into a pre-commit hook and a whole class of bugs never reaches a reviewer — human
or AI. Cost: $0. Context consumed: none.

## Setup (once)

```bash
git config core.hooksPath .githooks
uv sync
```

## The demo

1. Show the clean app works:

   ```bash
   uv run pytest
   uv run uvicorn app.main:app --reload
   curl -s -X POST localhost:8000/expenses \
     -H 'content-type: application/json' \
     -d '{"description":"coffee","amount_cents":450,"category":"food"}'
   ```

2. Plant the bug. In `app/main.py`, replace the parameterized category filter in
   `list_expenses` with the f-string version (this is *exactly* the kind of code an
   agent loop produces when it "just makes the filter work"):

   ```python
   rows = conn.execute(f"SELECT * FROM expenses WHERE category = '{category}'").fetchall()
   ```

3. Try to commit it:

   ```bash
   git add app/main.py && git commit -m "feat: filter expenses by category"
   ```

   The hook blocks the commit — Semgrep's `no-fstring-sql` rule fires with the
   injection warning. The bug died before any review, any CI minute, any token.

4. Restore the safe version — the bug is in BOTH the index (you staged it) and the
   worktree, so restore both:

   ```bash
   git restore --staged --worktree app/main.py
   ```

## The line that matters

> Everything else in the review stack costs money or context. Hooks cost neither —
> they run in seconds, on every commit, forever.

Next scene: what happens when a review finds a bug the rules *didn't* know about —
and the stack teaches itself (`scenes/phase-2-self-healing`).
