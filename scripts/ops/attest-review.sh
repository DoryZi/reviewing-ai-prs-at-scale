#!/usr/bin/env bash
#
# attest-review.sh — record that /code-review passed on the CURRENTLY STAGED diff,
# so the commit gate (`.claude/hooks/code-review-gate.sh`) will honour a
# `SKIP_CODE_REVIEW=1` bypass for exactly this code.
#
# Why this exists: the bypass token alone was a "magic word" — it let ANY commit
# skip /code-review. Now the token is necessary but not sufficient: it must be paired
# with an attestation that binds it to the exact staged diff that was reviewed. Run
# this AFTER /code-review comes back clean and AFTER your final `git add`, then commit
# with the token. If you stage more changes afterward the attestation no longer
# matches (it is the sha1 of `git diff --cached`) and the gate rejects the bypass —
# re-run this script. The attestation is single-use: the gate consumes it on a match.
#
# This does NOT run /code-review for you and does NOT prove it ran — it records YOUR
# claim that the staged code was reviewed, scoped to that exact diff. Only run it when
# the review is genuinely clean.
#
# Writes the hash to `$(git rev-parse --absolute-git-dir)/.review-attest` — the same
# absolute git-dir the hook reads, so it is correct from any worktree.
set -euo pipefail

git_dir="$(git rev-parse --absolute-git-dir 2>/dev/null)" || {
  echo "[attest] not inside a git repository — nothing to attest." >&2
  exit 1
}

# Hash the staged diff EXACTLY as the gate does (git diff --cached | sha1sum).
diff_hash="$(git diff --cached | sha1sum | cut -d' ' -f1)"

if [ -z "$(git diff --cached --name-only)" ]; then
  echo "[attest] no staged changes — stage your reviewed changes first (git add …), then re-run." >&2
  exit 1
fi

printf '%s\n' "$diff_hash" >"$git_dir/.review-attest"
echo "[attest] reviewed staged diff attested (sha1 ${diff_hash:0:12}…)."
echo "[attest] now: SKIP_CODE_REVIEW=1 git commit -m \"<message>\"  (re-attest if you stage more)."
