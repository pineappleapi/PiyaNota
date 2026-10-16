# Claude Code Plugins in PiyaNota: caveman, ponytail, superpowers

How to combine the three installed plugins so Claude spends fewer tokens without lowering the
quality bar set in `CLAUDE.md`. Versions this guide was written against: caveman 4.0.1,
ponytail 5.2.0, superpowers 7.0.0.

## What each plugin does

| Plugin | What it saves | How it works | Auto-on? |
|---|---|---|---|
| **caveman** | Output tokens (chat replies) | Terse voice. Code, commands, paths, numbers and errors stay exact. | Yes (hook) |
| **ponytail** | Code size and rework | Builds the smallest complete change and says what was skipped and what is risky. | Yes (hook, `full` level) |
| **superpowers** | Wasted runs (wrong direction, false "done") | Process skills: brainstorm → plan → execute → verify. | Bootstrap only. Skills fire when relevant. |

Rule of thumb: **caveman = how Claude talks, ponytail = how much Claude builds,
superpowers = the order Claude works in.** The three don't overlap, so they stack.

## Precedence: `CLAUDE.md` wins

The plugins are defaults. Project rules override them. Known conflicts:

| Conflict | Resolution |
|---|---|
| `/caveman-commit` writes Conventional Commits (`feat: ...`) | The project format is `PIYA-XXX: <summary>`. Don't use `/caveman-commit` here, or tell it to use the PIYA format. Never commit without review. |
| ponytail "smallest change" may skip type hints and docstrings | Strict typing, Google-style docstrings, named constants and no silent `except:` are still required. Minimal scope, not minimal quality. |
| ponytail may leave `shortcut:` comments | Allowed, but every one is debt. Run `/ponytail-debt` before a merge and log real debt in `docs/bug-tracker.md`. |
| superpowers TDD assumes a test suite | This repo has none. Use TDD for new pure functions (e.g. `infer_pitch()` logic) and skip it for notebooks and training runs. |
| caveman voice in persisted text | caveman exempts code, comments, commits, docs, tickets and memory files. These stay in normal prose. If one comes out terse, ask for a rewrite. |
| `/caveman-compress` on `CLAUDE.md` | **Don't.** `CLAUDE.md` carries nuanced, hard-won findings (seed ranges, BUG-011 caveats, "report both seeds"). Compression risks losing a negation or a qualifier. If you try it anyway, diff against the backup line by line. |
| Agent rules (ml-cv-lead, senior-reviewer, etc.) | Still mandatory. Plugin reviewers supplement them and don't replace them. |

## Recommended workflow per ticket

Matches the 9-step workflow in `CLAUDE.md`.

1. **Plan.** For a small, clear ticket, plan inline. For a new feature or anything ambiguous,
   use `superpowers:brainstorming` and then `superpowers:writing-plans`. These cost tokens up
   front but prevent whole wrong-direction runs. Not worth it for a one-line fix.
2. **Explore.** Name the file when you know it, because a direct read is cheapest. Otherwise use
   the `caveman:cavecrew-investigator` agent or `/caveman-explore`. Both return compressed
   `file:line` hits, so the main context stays small. Use them in place of the default
   `Explore` agent for "where is X / what calls Y".
3. **Clarify.** Claude asks questions in full sentences even in caveman mode, so the answer comes
   back right the first time.
4. **Risk line.** Unchanged.
5. **Implement.**
   - Bug fix: `superpowers:systematic-debugging` first (root cause before fix), then the
     `caveman:surgical-patch` skill.
   - 1–2 file mechanical edit: the `caveman:cavecrew-builder` agent. It refuses 3+ files.
   - New feature: ponytail `full` (default) and `superpowers:executing-plans`.
   - Model or training code: **ml-cv-lead first** (CLAUDE.md rule). Then implement.
6. **Self-verify against each acceptance criterion.** Use `superpowers:verification-before-completion`
   or the `caveman:verify-and-stop` skill. Both demand real command output before any "done"
   claim. This matters given past false-confidence incidents (BUG-011's ~4.2% correction).
7. **Test.** Run the actual command and quote the output.
8. **Report.** caveman keeps this short. Check that every number and caveat survived.
9. **Review before commit.** Pick **one** cheap first-pass reviewer: `/ponytail-review` (logic,
   safety, bloat) or `/caveman-review` (one line per finding). Then the mandatory
   `senior-reviewer` agent before merge. Don't stack every reviewer: `/code-review`,
   superpowers `requesting-code-review`, ponytail and caveman reviews overlap heavily.

## Which tool for which PiyaNota situation

| Situation | Use |
|---|---|
| "Where is the clef reference table?" | `cavecrew-investigator` |
| Typo or rename in one stage script | `cavecrew-builder` |
| Stage 3 gives wrong pitches (ambiguous cause) | `superpowers:systematic-debugging` or `caveman:investigate-first`, then `choral-conductor` for music-theory correctness |
| Nondeterminism or GPU-flake investigation (BUG-013-style) | `caveman:investigate-first`: ranked hypotheses before edits |
| New Flask endpoint (Module 3) | ponytail `full` + `backend-lead` review |
| New Flutter screen (Module 2) | ponytail `full` + `frontend-lead` review |
| Restructure without behavior change | `caveman:safe-refactor` |
| DB schema change (PIYA-311) | `caveman:migration` (rollback plan) + `backend-lead` |
| Two independent tasks (e.g. Module 2 UI + a doc update) | `superpowers:dispatching-parallel-agents` |
| Isolated feature branch | `superpowers:using-git-worktrees` (merge still needs your OK) |
| "Is this over-engineered?" | `/ponytail-review` |
| Whole-repo health check before a milestone | `/ponytail-audit` (report only, changes nothing) |

## Modes and levels

**caveman** (voice):
- `/caveman`: default terse voice. Best for daily work.
- `/caveman ultra`: grammar stripped. Use only for quick status checks. Too lossy for
  ML-results discussion.
- `stop caveman` / `normal mode`: switch off. Use this when reading an ml-cv-lead review or a
  complex results summary where nuance matters more than tokens.
- `/caveman status`: show the current mode.

**ponytail** (scope):
- `/ponytail lite`: builds what was asked and names the smaller option. Use when the ticket's
  acceptance criteria are fixed and you don't want pushback.
- `/ponytail` (full, default): smallest complete change, says what was skipped and any risk.
- `/ponytail ultra`: also questions the request before building. Good for early-stage ideas,
  but annoying on well-specified tickets.
- `stop ponytail` / `/ponytail off`: switch off.

Change the startup defaults with environment variables or config files:
- `CAVEMAN_DEFAULT_MODE` / `~/.config/caveman/config.json` → `{"defaultMode": "manual"}` makes
  caveman opt-in.
- `PONYTAIL_DEFAULT_MODE` / `%APPDATA%\ponytail\config.json` → `{"defaultMode": "lite"}`.

## Token-saving habits that matter more than any plugin

- **Name files and symbols in the prompt.** Example: "fix `get_clef_reference()` in
  `stage3_transcription.py`" beats "fix the tenor bug".
- **One ticket per session**, or `/clear` between tickets. Long sessions re-send history on
  every turn.
- **Keep `MEMORY.md` and `docs/NEXT-SESSION.md` current.** Re-deriving state costs more than
  reading a short hand-off.
- **`CLAUDE.md` is loaded every turn.** It is long. Consider moving the dated history (the
  retraining-plan narrative, evaluation snapshot detail) into `docs/` and leaving one-line
  pointers. That trims input tokens on every message without lossy compression.
- **Don't spawn agents for trivial lookups.** Each agent starts cold. Use `cavecrew-*` only when
  the search is broad.
- `/caveman-stats` shows session token usage. `/ponytail-gain` shows ponytail's benchmark numbers.

## Quick reference

| Command | Effect |
|---|---|
| `/caveman-help`, `/ponytail-help` | Reference cards |
| `/ponytail-review` | Review the current diff |
| `/ponytail-audit` | Whole-repo audit report |
| `/ponytail-debt` | List `shortcut:` comments |
| `/caveman-review` | One-line-per-finding review |
| `/caveman-stats` | Session token usage |
| `stop caveman` / `stop ponytail` | Switch a mode off |
