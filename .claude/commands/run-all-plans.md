---
description: "Execute all PLAN.md files sequentially via ralph-loop until all complete"
argument-hint: ""
---

# Run All Plans

Execute all MailPilot plans sequentially. Each plan runs in a fresh subagent context. The ralph-loop stop hook feeds the prompt back after each plan until all are done.

## Current State

Plans and summaries:
```!
for dir in ae-cc/planning/phases/*/; do
  phase=$(basename "$dir")
  plans=$(ls "$dir"*-PLAN.md 2>/dev/null | wc -l | tr -d ' ')
  summaries=$(ls "$dir"*-SUMMARY.md 2>/dev/null | wc -l | tr -d ' ')
  echo "$phase: $summaries/$plans complete"
done
```

## Setup Ralph Loop

Create the ralph-loop state file to begin autonomous execution:

```!
mkdir -p .claude

cat > .claude/ralph-loop.local.md <<FRONTMATTER
---
active: true
iteration: 1
session_id: ${CLAUDE_CODE_SESSION_ID:-}
max_iterations: 20
completion_promise: "ALL PLANS COMPLETE"
started_at: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
---

FRONTMATTER

cat >> .claude/ralph-loop.local.md <<'PROMPTBODY'
# Execute Next MailPilot Plan

You are in a ralph-loop executing all plans for the MailPilot project. Each iteration you find the next unexecuted plan, run it via subagent, verify the result, then exit. The stop hook feeds this prompt back for the next plan.

## Step 1: Discover State

Run this to see current progress:

```bash
echo "=== Plan Status ==="
for dir in ae-cc/planning/phases/*/; do
  phase=$(basename "$dir")
  for plan in "$dir"*-PLAN.md; do
    [ -f "$plan" ] || continue
    base=$(basename "$plan" | sed 's/-PLAN.md//')
    summary="$dir${base}-SUMMARY.md"
    if [ -f "$summary" ]; then
      echo "  [x] $base"
    else
      echo "  [ ] $base  <-- NEXT"
    fi
  done
done
```

## Step 2: Identify Next Plan

From the output above, find the FIRST plan marked `[ ]` (no SUMMARY.md).

- Matching: `XX-YY-PLAN.md` is done when `XX-YY-SUMMARY.md` exists in the same directory.
- If ALL plans show `[x]`: go to Step 5.
- If a `[ ]` plan is found: go to Step 3.

## Step 3: Execute Plan via Subagent

Spawn a single Agent (general-purpose subagent) to execute the plan. Use the Agent tool with this prompt (replace PLAN_PATH with the actual path):

---

Execute the plan at PLAN_PATH.

This is a fully autonomous plan with no checkpoints.

Instructions:
1. Read the plan file for objective, context, and tasks
2. Read files listed in the plan's <context> section (BRIEF.md, ROADMAP.md, prior SUMMARYs, source files)
3. Read ~/.claude/plugins/marketplaces/ae-cc/skills/create-plans/workflows/execute-phase.md for deviation rules:
   - Rule 1: Auto-fix bugs immediately
   - Rule 2: Auto-add missing critical functionality
   - Rule 3: Auto-fix blockers
   - Rule 4: STOP and ask user for architectural changes
   - Rule 5: Log enhancements to ae-cc/planning/ISSUES.md
4. Execute ALL tasks sequentially
5. Run all checks from the plan's <verification> section
6. Confirm <success_criteria> are met
7. Create SUMMARY.md in the same directory as the PLAN.md using this format:

   # Phase [X] Plan [Y]: [Name] Summary

   **[Substantive one-liner of what shipped]**

   ## Accomplishments
   - [Key outcome 1]
   - [Key outcome 2]

   ## Files Created/Modified
   - `path/file` - Description

   ## Decisions Made
   [Key decisions or "None - followed plan"]

   ## Deviations from Plan
   [Deviations with rule applied, or "None - executed exactly as written"]

   ## Issues Encountered
   [Problems/resolutions or "None"]

   ## Next Step
   [Ready for next plan or phase complete]

8. Update ae-cc/planning/ROADMAP.md:
   - Mark this plan's checkbox: `- [ ]` to `- [x]`
   - Update Progress table plan count (e.g., "1/3" to "2/3")
   - If LAST plan in phase: mark phase status "Complete" with today's date, check the phase checkbox
9. Stage all changes and commit:
   git add -A
   git commit -m "feat(XX-YY): [one-liner from SUMMARY]"

Report: plan name, SUMMARY path, commit hash, issues encountered.

---

Wait for the subagent to complete.

## Step 4: Verify Result

After the subagent returns:

1. Check SUMMARY was created:
   ```bash
   ls ae-cc/planning/phases/*/XX-YY-SUMMARY.md 2>/dev/null
   ```

2. Check commit:
   ```bash
   git log --oneline -1
   ```

3. If SUMMARY is missing but work was done: create the SUMMARY yourself from the subagent's report, update ROADMAP, and commit.

4. If total failure (nothing done): log what happened. Exit this iteration — the loop will retry on the next pass.

After verification, exit normally. The ralph-loop stop hook feeds this prompt back for the next plan.

## Step 5: All Plans Complete

If Step 2 found no remaining plans:

1. Final verification:
   ```bash
   echo "=== Final Check ==="
   total_plans=0; total_summaries=0
   for dir in ae-cc/planning/phases/*/; do
     plans=$(ls "$dir"*-PLAN.md 2>/dev/null | wc -l)
     summaries=$(ls "$dir"*-SUMMARY.md 2>/dev/null | wc -l)
     total_plans=$((total_plans + plans))
     total_summaries=$((total_summaries + summaries))
     phase=$(basename "$dir")
     [ "$plans" -eq "$summaries" ] && echo "  OK $phase" || echo "  INCOMPLETE $phase ($summaries/$plans)"
   done
   echo "Total: $total_summaries/$total_plans"
   ```

2. If any INCOMPLETE: go back to Step 3 with the missing plan.

3. If all complete: ensure ROADMAP shows all phases as Complete. Fix if needed and commit.

4. Output the completion promise:

   <promise>ALL PLANS COMPLETE</promise>

## Rules

- ONE plan per iteration. Execute one, verify, exit.
- Execute plans IN ORDER: 01-01, 01-02, 01-03, 02-01, 02-02, ...
- Always use the Agent tool (subagent) for execution — never run plan tasks in this context.
- Do NOT invoke slash commands or skills — all logic is in this prompt.
- Do NOT output the completion promise until ALL plans genuinely have SUMMARY.md files.
PROMPTBODY

echo ""
echo "=== Ralph Loop Activated ==="
echo "Task: Execute all MailPilot plans (13 plans, 5 phases)"
echo "Max iterations: 20"
echo "Completion promise: ALL PLANS COMPLETE"
echo "To cancel: /cancel-ralph"
```

Now begin the first iteration. Follow the prompt in `.claude/ralph-loop.local.md` — find the first plan without a SUMMARY.md and execute it via subagent.

**CRITICAL:** Execute ONE plan, verify the result, then exit. The ralph-loop stop hook will feed the prompt back for the next plan automatically.
