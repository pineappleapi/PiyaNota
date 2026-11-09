Resume PiyaNota. Read docs/plans/2026-11-09-ui-batch-handoff.md fully (state, 10 tasks, reference images, method). Worktree: D:\PiyaNota\.claude\worktrees\feature-piya106-overnight-cancel-logging-ui, branch feature/piya106-overnight-cancel-logging-ui.

Goal: finish ALL tasks in the handoff (I, II, III, IV, V, General). Do not stop, hand back, or ask "should I continue" until every task is implemented, tested, reviewed and the phone build is installed. The only allowed pauses: (a) the one up-front question batch below, (b) a hard blocker you cannot resolve, (c) actions that need my word (commit, merge, push, migration, deploy).

Step 0 (one message, then proceed): ask me the two open questions at the end of the handoff (system-notification approach, worker progress change allowed). If I do not answer, use the recommended defaults: local notifications; worker progress change allowed with backend-lead review.

Efficiency rules (token saving):
- You are the coordinator. Do not read large files yourself; delegate. One subagent per task, explicit model each time: haiku for lookups/mechanical edits, sonnet for implementation and tests, opus ONLY for senior-reviewer / backend-lead / frontend-lead review and design calls. No opus for coding.
- Briefs under 15 lines: task text copied from the handoff, files to touch, acceptance checks, "report in under 10 lines". Independent tasks (e.g. I, III, V-backend) run in parallel in separate subagents when they touch different files; tasks touching the same file (mixer_sheet.dart, playback_screen.dart) run sequentially.
- Run only the tests of touched files, never the full suite until the final gate (once). Use the venv python for backend tests. Forward slashes in Bash paths.
- Sample colours from the reference images with a pixel tool (design-fidelity rule). Never eyeball.
- State planned change plus one-line risk before each edit (as the subagent's first line in its report).
- Never read or print C:\Users\paul_\start-piyanota-worker.ps1.

Flow:
1. Order: I, III, II, General, V, IV. After each three tasks, update the Progress log in the handoff, commit nothing, and continue immediately (do not /clear unless context is nearly full; if it is, write handoff-latest state into the Progress log first, then tell me to /clear and give the one-line resume prompt).
2. After all tasks: run the full Flutter test suite once, plus backend tests touched. Then frontend-lead review (all app changes), backend-lead review (any backend change), senior-reviewer on the whole diff. Fix every blocker they raise, re-run affected tests.
3. Restart the worker if backend changed (TaskStop old, start via the powershell command in the handoff). Build release APK and `adb -s 622ad04c install -r`. Give me a short phone-test checklist covering each task.
4. Final report: what changed per task, files, test results, review verdicts, open items. Then ask for my word to commit, merge to main and push. Do not do those without it.

Rules: no commit/merge/push/migration/deploy without my word. Ignore the formatting-only change in reset_code_waits.dart. Keep replies terse.
