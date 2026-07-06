#!/usr/bin/env bash
# PreToolUse(Bash) hook: gate `git commit` behind a /code-review pass.
#
# ONE gate, run only on a real `git commit`: /code-review. A hook cannot run a
# slash command, so this BLOCKS the commit and injects an instruction telling the
# in-session agent to run the review/self-heal loop, then re-commit with
# SKIP_CODE_REVIEW=1 paired with a fresh attestation of the reviewed diff — so no
# infinite loop and no "magic word" bypass.
#
# Static checks (ruff lint/format, Semgrep) are deliberately NOT duplicated here:
# they live in .githooks/pre-commit, which git runs for EVERY committer — human
# or agent — against the staged index. This hook adds only what git can't:
# forcing the agent through an AI review before it may land code.
#
# The self-heal loop is BOUNDED (MAX_ITERS attempts), after which the instruction
# tells the agent to ASK the human instead of burning tokens forever.
#
# Reads the hook payload on stdin (JSON). Allows everything that is not a real
# `git commit` SUBCOMMAND (so `git log --grep commit` is not mistaken for one).
# Exit 0 with JSON is the documented "deny with decision" path; a parse/jq/tool
# failure exits 0 (fail-open) so the hook never wedges git.
set -uo pipefail

# Max self-heal attempts before we stop and ask the human (Semgrep + review).
MAX_ITERS=5

payload="$(cat)"

# Extract the Bash command being run. Fail open (allow) if we can't read it.
command="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null)"
[ -z "$command" ] && exit 0

# Emit a PreToolUse "deny" decision (reason + agent-facing instruction) and exit.
deny() {
  jq -n --arg reason "$1" --arg ctx "$2" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason,
      additionalContext: $ctx
    }
  }'
  exit 0
}

# Decide if this command runs `git commit` as a SUBCOMMAND — not merely a line
# that contains the word "commit" as an argument (`git log --grep commit`,
# `git checkout commit`). We find each `git` token, skip its global options
# (and the separate argument of value-taking ones like `-C <path>`, `-c k=v`),
# and gate only when the first real subcommand token is exactly `commit`.
# A subshell/&&/; chain can hold several `git` calls, so we check them all.
is_git_commit() {
  awk -v RS='[;&|()\n]+' '
    {
      n = split($0, t, /[[:space:]]+/)
      for (i = 1; i <= n; i++) {
        if (t[i] != "git") continue
        # walk forward to the first non-option token = the subcommand
        for (j = i + 1; j <= n; j++) {
          tok = t[j]
          if (tok == "") continue
          if (tok == "-C" || tok == "-c" || tok == "--git-dir" \
              || tok == "--work-tree" || tok == "--namespace") { j++; continue }
          if (substr(tok, 1, 1) == "-") continue          # other global flag
          if (tok == "commit") { print "yes"; exit }      # the subcommand
          break                                           # some other subcommand
        }
      }
    }
  ' <<<"$1"
}

# Only a real `git commit` is gated; everything else passes straight through.
if [ "$(is_git_commit "$command")" != "yes" ]; then
  exit 0
fi

# Static checks (ruff + Semgrep) already gate every commit via .githooks/pre-commit,
# for humans and agents alike — no duplication here.
# Absolute git-dir so the attestation path is stable regardless of the hook's cwd
# (a relative `.git` would otherwise resolve against whatever directory we're in).
git_dir="$(git rev-parse --absolute-git-dir 2>/dev/null)"

# ── The gate: /code-review, bound to an attestation of THIS staged diff ──────
# The `SKIP_CODE_REVIEW=1` token is necessary but NOT sufficient on its own: a bare
# token would let any commit skip review (the "magic word" hole). It must be paired
# with a fresh ATTESTATION — `scripts/ops/attest-review.sh` writes the sha1 of the
# staged diff (`git diff --cached`) to `$git_dir/.review-attest` after /code-review
# passes. This hook recomputes that hash now and allows the bypass ONLY when it
# matches: the token then authorizes a commit of the EXACT code that was reviewed,
# not arbitrary later edits. The attestation is single-use (consumed on a match) so
# it cannot be replayed for a different commit.
#
# A PreToolUse hook only reliably receives the command TEXT, not the child process
# env: a `SKIP_CODE_REVIEW=1 git commit …` PREFIX sets the var for git, not for this
# hook. So detect BOTH the var in our own env (if the runner forwards it) AND a
# leading `SKIP_CODE_REVIEW=1`/`=true` assignment in the command string. The string
# match is an env-assignment PREFIX only (start, or right after a `;`/`&&`/`|` chain
# operator, optionally alongside other leading `VAR=val`), so the token as an
# ARGUMENT (e.g. `-m SKIP_CODE_REVIEW=1`) does NOT count — that must still be gated.
bypass_requested="no"
if [ "${SKIP_CODE_REVIEW:-}" = "1" ] || [ "${SKIP_CODE_REVIEW:-}" = "true" ]; then
  bypass_requested="yes"
elif printf '%s' "$command" \
   | grep -Eq '(^|[;&|][[:space:]]*)([[:alnum:]_]+=[^[:space:]]*[[:space:]]+)*SKIP_CODE_REVIEW=(1|true)[[:space:]]'; then
  bypass_requested="yes"
fi

attest="$git_dir/.review-attest"

if [ "$bypass_requested" = "yes" ]; then
  # Hash the staged diff the same way attest-review.sh does. Fail-open (allow) if we
  # cannot compute it at all (no git/sha1) — a tooling gap must never wedge git, and
  # the human still typed the explicit bypass token.
  cur_diff_hash="$(git diff --cached 2>/dev/null | sha1sum 2>/dev/null | cut -d' ' -f1)"
  if [ -z "$cur_diff_hash" ]; then
    exit 0
  fi
  attested_hash=""
  [ -f "$attest" ] && attested_hash="$(sed -n '1p' "$attest" 2>/dev/null)"
  if [ -n "$attested_hash" ] && [ "$attested_hash" = "$cur_diff_hash" ]; then
    # Attestation matches THIS staged diff → allow, and consume it (single-use).
    rm -f "$attest" 2>/dev/null || true
    exit 0
  fi
  # Token present but no matching attestation: stale (code changed since review) or
  # missing entirely. Deny — the token alone is not enough.
  if [ -n "$attested_hash" ]; then
    reason="Bypass rejected: the review attestation is STALE — the staged diff changed since /code-review ran. Re-review, re-attest, then commit."
  else
    reason="Bypass rejected: SKIP_CODE_REVIEW=1 requires a fresh review attestation for this staged diff (none found)."
  fi
  read -r -d '' instruction <<TXT
The SKIP_CODE_REVIEW=1 token is no longer sufficient on its own — it must be bound to
an attestation of the EXACT staged diff being committed:

1. Run \`/code-review --fix\` at medium effort on the staged diff. Fix any findings
   and re-stage until it is clean. (Stop after ${MAX_ITERS} iterations and ask the
   human if it will not come clean.)
2. Attest the reviewed diff: \`bash scripts/ops/attest-review.sh\` — this records the
   sha1 of \`git diff --cached\` so the hook knows review covered THIS code.
3. Commit with the token: \`SKIP_CODE_REVIEW=1 git commit -m "<message>"\`.

If you stage MORE changes after attesting, the hash no longer matches and the bypass
is rejected again — re-attest after the final stage. The attestation is single-use.
TXT
  deny "$reason" "$instruction"
fi

# No bypass token at all: block the commit and hand the agent the review loop.
reason="Commit gated: changes must pass /code-review first."

read -r -d '' instruction <<TXT
This commit was blocked by the code-review gate. Run the review/self-heal loop now:

1. Run \`/code-review --fix\` at medium effort on the staged diff.
2. If it is clean, attest the reviewed diff with \`bash scripts/ops/attest-review.sh\`
   (records the sha1 of the staged diff), then re-issue the SAME commit prefixed with
   the bypass token: \`SKIP_CODE_REVIEW=1 git commit -m "<message>"\`. The attestation
   binds the token to THIS exact diff, so it cannot skip review on other code.
3. If findings remain, fix them, re-stage, and repeat from step 1.
4. Stop after ${MAX_ITERS} iterations total. If it is still not clean, summarize
   the remaining findings and ASK the human — do NOT commit.

Re-attest if you stage more changes after reviewing — the attestation is bound to the
staged diff and is single-use.
TXT

deny "$reason" "$instruction"
