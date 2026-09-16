# Module 2 — Mobile Client Framework Selection

**Status:** Decided 2026-09-15, in conversation (not a numbered PIYA ticket — CLAUDE.md and
`docs/sow.md` only ever say "Android client," with no framework named anywhere in the tickets or
SOW). This doc exists so the choice is a recorded decision rather than something implicit in
`.claude/agents/frontend-lead.md`, which was already written assuming Flutter.

**Decides for:** All of `docs/tickets/module2-mobile.md` (PIYA-201–217).

## Decision

**Flutter**, targeting Android only (per `docs/sow.md` Section 4 — no cross-platform requirement
exists; Flutter is used for its tooling/ecosystem, not for iOS support).

## Rationale

- `.claude/agents/frontend-lead.md` — the agent CLAUDE.md designates as the mandatory reviewer for
  every Module 2 change — is written specifically for Flutter (state management, widget structure,
  Flutter-specific FR-21 guidance). Choosing native Kotlin would have required rewriting that agent
  first.
- No conflicting signal exists elsewhere: `docs/sow.md` and `CLAUDE.md` both only say "Android
  client," never "native Android" or a specific language, so nothing is contradicted by picking
  Flutter.

## Repo structure implication

The Flutter project lives at `mobile/` in this same repo (not a separate repository), so ticket
branches/commits for Module 2 stay unified with Module 1/3 history. Standard Flutter build
artifacts (`.dart_tool/`, `build/`, `.flutter-plugin-dependencies`, etc.) are added to the root
`.gitignore`.

## Implications for dependent tickets

- **PIYA-201–213 (UI tickets):** built as Flutter widgets/screens under `mobile/lib/`.
- **PIYA-214 (Auth Flow Integration), FR-21:** secure token storage uses `flutter_secure_storage`
  (Keystore-backed on Android), matching frontend-lead.md's existing guidance to avoid plain
  `SharedPreferences`.
- **frontend-lead review scope:** unchanged — the agent's Flutter assumption is now backed by this
  decision doc instead of being an undocumented default.
