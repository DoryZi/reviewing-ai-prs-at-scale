# Reviewing AI PRs at Scale: 5 Levers to Stop Drowning

**AI made writing code nearly free. It did not make *reviewing* it free.** With agent
loops producing thousand-line PRs faster than anyone can read them, review — not
code — is the bottleneck. This repo is a hands-on, reproducible demo of five levers
you can pull to survive the flood, ordered from **free and instant** to **paid and
thorough**, where each lever catches what the previous one missed.

The demo app is a deliberately boring expense tracker API (`app/`). The
`feature/budgets-reports` branch is a real, unreviewed, AI-built **637-line PR**
([#1](https://github.com/DoryZi/self-healing-reviews/pull/1)) — the "giant PR" every
lever is measured against.

## The 5 levers

| # | Lever | Cost | When | What it catches |
|---|-------|------|------|-----------------|
| 1 | **Static hooks** — ruff + Semgrep on the staged index, in a git pre-commit hook. **The self-healing trick:** every review finding becomes a new Semgrep rule, so the free layer gets permanently smarter. | $0, zero context, ~2s | every commit | lint, format, injectable-SQL *shapes* |
| 2 | **Local AI review** — `/code-review` before push, gated into a Claude hook so the agent *cannot* commit unreviewed code; feed findings straight back to fix. | subscription | before commit | real correctness/security bugs green tests hide |
| 3 | **Adversarial / cross-model** — a *different* model reviews the diff; different model, different blind spots. | subscription/API | before PR | what your primary model is blind to |
| 4 | **CI safety net** — CodeRabbit / Greptile as the final independent gate on the PR. | paid | on PR | the backstop |
| 5 | **Explain it back** — read the agent's half-page explanation of what it built and its own riskiest spots, not the 3,000-line diff. | subscription | after the task | the intent, at human scale |

Levers 1 and 2 are built and demoed in this repo; 3–5 are documented patterns.

## Quick start

```bash
uv sync
git config core.hooksPath .githooks   # arm lever 1 (the git pre-commit hook)
uv run pytest                          # the app works
uv run uvicorn app.main:app --reload   # run it
```

Then walk `scenes/phase-1-hooks/README.md` — a self-contained, reproducible demo of
lever 1, including the self-healing loop.

## The self-healing trick (lever 1's payoff)

Static rules only know the bugs you've already taught them. So **when a more
expensive lever (an AI review, a human) finds a real bug, you encode it as a Semgrep
rule on the spot.** The next time that pattern appears — from you, a teammate, or an
agent loop — the free layer kills it at commit time in two seconds. The review stack
heals around every wound; the cheap layer learns from the expensive ones.

## Layering, not duplication

Static checks (ruff, Semgrep) run in `.githooks/pre-commit` for **every** committer —
human or agent — against the staged index. The Claude hook
(`.claude/hooks/code-review-gate.sh`) adds only the one thing git can't: it refuses to
let the **agent** commit until an AI review has passed on exactly this diff (attested
by hash, single-use, no magic bypass word). Fast checks for everyone; deep review
forced on the machine that writes the most code.
