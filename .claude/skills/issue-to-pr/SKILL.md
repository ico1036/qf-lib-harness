---
name: issue-to-pr
description: >-
  Autonomously turn a ready GitHub issue into a pull request — pick an eligible
  task (skipping any labeled needs-human), check its dependencies are closed,
  implement it on a branch, run its tests, and open a PR that closes the issue.
  Stops at the open PR for a human to merge. Use when the user wants to "자율
  주행"/"auto"/"work the issues"/"이슈 보고 PR" without hand-holding. Takes an
  optional issue number, or picks the next ready issue; --loop drains all ready
  issues. Pairs with issue-author but runs independently on any conforming issue.
---

# issue-to-pr

Drive a `type:task` issue to an open PR, unattended. Read
`.claude/skills/CONVENTIONS.md` first — labels, dependency (`Depends on #N`),
`## Verify`, and the `needs-human` skip rule all come from there.

## Hard rules

- **Skip `needs-human`.** Never work an issue carrying that label.
- **Only `type:task`.** Never implement an epic or feature directly.
- **Stop at the open PR.** Do not merge. A human merges. (`Closes #N` in the PR
  body so the merge closes the issue.)
- **One branch + one PR per issue.**

## Steps

1. **Select the issue.**
   - If given `--issue N`, use it (abort if it has `needs-human` or isn't `type:task`).
   - Otherwise list candidates:
     `gh issue list --repo <repo> --label type:task --state open --json number,title,body,labels`
     drop any with `needs-human` or `blocked`.
   - **Ready check:** parse `Depends on #N` from the body; the issue is ready only
     if every referenced issue is closed (`gh issue view N --json state`). Pick the
     first ready one (lowest number).
   - If none are ready, report that and stop.

2. **Branch.** `git checkout -b issue-<N>-<slug>` off the default branch (pull first).

3. **Implement.** Read the issue body (context + acceptance criteria) and the repo;
   make the smallest change that satisfies the acceptance criteria. Follow existing
   patterns. Do not edit FROZEN files (e.g. `alpha_lab/core.py`, `pipeline.py`)
   unless the issue explicitly authorizes it.

4. **Verify.** Run the issue's `## Verify` command(s); fall back to the repo default
   `uv run --with pytest python -m pytest`. Capture output.

5. **On green → open PR.**
   `gh pr create --repo <repo> --base <default> --head <branch> --title … --body …`
   with `Closes #N`, a summary of the change, and the pasted verification output.
   Then **stop** — leave it for human review/merge.

6. **On red or genuine ambiguity → do not PR.** Comment on the issue with the
   failing output / the blocking question, add the `blocked` label, leave the
   branch, and move on. Never open a PR with failing checks.

7. **--loop (optional).** Repeat from step 1 until no ready issue remains. Report a
   summary: PRs opened, issues blocked, issues skipped (and why).

## Guardrails

- Evidence before claims: only call a task done after the Verify command actually
  passed — paste the output into the PR.
- Reversible only: if work would touch something matching the `needs-human`
  criteria but the label is missing, stop and flag it rather than proceeding.
- Never force-push, never delete branches you didn't create, never merge.
