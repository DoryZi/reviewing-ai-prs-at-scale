# Self-Healing Reviews

**A layered code-review stack that cuts the PR noise before it drowns your team.**

AI made writing code nearly free. It did not make *reviewing* it free — and with
agent loops producing thousand-line PRs, review is now the bottleneck. This repo is
a hands-on demo of a defense-in-depth answer: layers of review, ordered from free
and instant to paid and thorough, where each layer catches what the previous one
missed — and the cheap layers **learn from the expensive ones**.

The demo app is a deliberately boring expense tracker API (`app/`). Every scene
plants a realistic bug in it and shows a different layer catching it.

## The stack

| # | Layer | Cost | Runs | Scene |
|---|-------|------|------|-------|
| 1 | **Hooks + static tools** — ruff, Semgrep, wired into pre-commit | $0, zero context | every commit | [`scenes/phase-1-hooks`](scenes/phase-1-hooks/README.md) ✅ |
| 2 | **Self-healing loop** — every review finding becomes a Semgrep rule; the stack gets permanently smarter | $0 after the first catch | every commit | coming |
| 3 | **Local AI review** — `/code-review` before push; feed findings straight back to the agent | subscription | before push | coming |
| 4 | **Adversarial / cross-model review** — a *different* model reviews the diff; different blind spots | subscription/API | before PR | coming |
| 5 | **CI safety net** — CodeRabbit / Greptile as the final independent gate | paid | on PR | coming |
| 6 | **Explain it back** — read the agent's explanation of what it built, not the 3,000-line diff | subscription | after the task | coming |

## Quick start

```bash
uv sync
git config core.hooksPath .githooks   # arm layer 1
uv run pytest                          # the app works
uv run uvicorn app.main:app --reload   # run it
```

Then walk the scenes in order — each `scenes/phase-N-*/README.md` is a
self-contained, reproducible demo.

## Why "self-healing"?

Static rules only know the bugs you've already taught them. The core trick of this
stack: **when a more expensive layer (an AI review, a human) finds a real bug, you
encode it as a Semgrep rule on the spot.** The next time that bug pattern appears —
from you, a teammate, or an agent loop — the free layer kills it at commit time.
The review stack heals around every wound.
