---
name: issue-author
description: >-
  Turn a goal or spec into a hierarchy of GitHub issues (epic → feature → task)
  with grouping, dependency links, and a human-verification flag. Use when the
  user wants to "발행"/"create issues" from a feature idea, plan, or spec, or
  asks to break a goal into epics/features/tasks. Classifies which issues need
  human verification (needs-human) and shows the full tree for approval BEFORE
  creating anything on GitHub. Pairs with issue-to-pr but runs independently.
---

# issue-author

Decompose a goal into a reviewed tree of GitHub issues. Read
`.claude/skills/CONVENTIONS.md` first — it defines the labels, hierarchy,
dependency, and needs-human rules this skill applies.

## Output first

You produce, on the target repo (default `ico1036/qf-lib-harness`):
- one or more `type:epic` issues,
- `type:feature` issues linked under each epic (sub-issues),
- `type:task` issues linked under each feature, each with a `## Verify` block,
  `Depends on #N` lines where ordered, and a `needs-human` label when the
  criteria apply.

**Nothing is created until the user approves the proposed tree.**

## Steps

1. **Gather the goal.** Take the user's spec / feature request / doc. If the
   acceptance criteria are unclear, ask once — vague scope produces vague issues.

2. **Decompose & group.** Build the hierarchy:
   - epic = the outcome; feature = a shippable slice; task = one PR-sized change.
   - Group related tasks under the same feature; keep tasks small and isolated.
   - Add `Depends on #N` ordering only where one task genuinely needs another's
     result. Do not over-serialize.

3. **Classify needs-human.** For every node apply the CONVENTIONS criteria
   (secrets, money/trading, irreversible, public contracts, ambiguous, architecture
   → `needs-human`). Default tasks to autopilot-eligible (unlabeled) only when
   they are well-specified, reversible, and carry a runnable `## Verify`.

4. **Present the tree for approval.** Show it as an indented outline with, per
   node: title, type, needs-human flag, deps, and the Verify command for tasks.
   Ask the user to confirm or adjust (they may flip flags, merge, split, reorder).
   **Do not call `gh` until they approve.**

5. **Create on GitHub** (after approval), bottom-up so links resolve:
   - ensure labels exist (`gh label create …`, ignore "already exists");
   - `gh issue create --repo <repo> --title … --body … --label type:task[,needs-human]`;
   - capture each new issue number;
   - link children to parents via the sub-issues API (see CONVENTIONS), falling
     back to `Part of #<parent>` + parent task-list if unavailable.

6. **Report.** Print the created tree with issue numbers and which are
   `needs-human` (so the user knows what autopilot will skip).

## Guardrails

- Never create issues before approval.
- Idempotency: if asked to re-run, check for existing open issues with the same
  title before creating duplicates.
- Keep task bodies self-contained: context, acceptance criteria, `## Verify`,
  `Depends on #N`. `issue-to-pr` will act on the body alone.
