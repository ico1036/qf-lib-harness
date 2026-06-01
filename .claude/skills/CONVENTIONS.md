# Issue / PR conventions (shared)

Both `issue-author` and `issue-to-pr` talk to each other **only** through GitHub
Issues on this repo — never by calling each other. This file is the contract.

## Labels

| Label | Meaning |
|---|---|
| `type:epic` | Top-level goal. Contains features. Never worked directly. |
| `type:feature` | A shippable slice of an epic. Contains tasks. |
| `type:task` | A single, PR-sized unit of work. The only level `issue-to-pr` acts on. |
| `needs-human` | Human verification required → **`issue-to-pr` skips it.** |
| `blocked` | Has unmet dependencies, or a previous autopilot attempt failed. |

Create any missing labels with `gh label create <name> --repo <repo>` (idempotent;
ignore "already exists").

## Hierarchy — GitHub native sub-issues

Link a child to its parent via the sub-issues API:

```bash
# resolve the child issue's node id, then attach to parent
gh api repos/{owner}/{repo}/issues/{parent_number}/sub_issues \
  -f sub_issue_id={child_issue_id}
```

If the sub-issues API is unavailable, fall back to: add `Part of #<parent>` as the
first line of the child body, and a task-list (`- [ ] #<child>`) in the parent body.

## Dependencies (ordering between tasks)

A task that must wait for others lists them in its body, one per line:

```
Depends on #12
Depends on #15
```

A task is **ready** only when every `Depends on #N` issue is closed.

## Verify section

Each `type:task` body SHOULD include how to prove it works:

```
## Verify
uv run --with pytest python -m pytest alpha_lab/tests
```

If absent, the repo default is `uv run --with pytest python -m pytest`.

## needs-human criteria

Mark `needs-human` when the task touches any of:
- secrets / auth / credentials
- money, live trading, order execution
- irreversible ops (deletes, data migrations, force-push, publishing/release)
- public contracts (API surface, the pinned qf-lib rev, packaging)
- ambiguous or missing acceptance criteria
- architecture / cross-cutting design decisions

Otherwise (well-specified + reversible + has a runnable Verify) → leave unlabeled
so autopilot may take it.
