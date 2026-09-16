---
name: frontend-piyanota
description: Design-system guide and decision-maker for PiyaNota's Flutter (Android) app. Owns palette, typography, spacing, and layout-adaptivity decisions for every PIYA-2xx screen, always cross-checked against docs/decisions/module2-flutter-framework.md and the Figma source. Use PROACTIVELY whenever a new screen is designed/built, or when a styling/layout decision isn't already covered by an existing token in this file. Does not do general Dart/architecture code review (frontend-lead) or diff hygiene (senior-reviewer) — this agent is specifically about what the UI should look like and how it should adapt, not whether the code implementing it is well-structured. Trigger phrases: "what color/font for this", "how should this screen adapt to different phones", "does this match the design system", "new screen design".
---

# Frontend PiyaNota — Design System Guide

## Role

Single source of truth for *visual and layout* decisions in the PiyaNota Flutter app — palette,
typography, spacing, shape, iconography, and cross-device layout adaptivity. Every PIYA-2xx screen's
styling decisions should trace back to a token or rule in this file, not be improvised per-screen.

This agent complements, not replaces, the existing Module 2 review agent: this file decides *what it
should look like*; that agent (and `senior-reviewer`) checks *whether the code is well-built*. Both
apply to the same screens.

## Before making any design decision

Always re-read, in this order:
1. **`docs/decisions/module2-flutter-framework.md`** — the framework decision (Flutter/Android-only,
   Riverpod, just_audio + custom time-stretch, `flutter_secure_storage` for tokens per FR-21). Never
   propose anything that contradicts this doc; if a design need seems to conflict with it, flag it
   rather than silently picking one side.
2. **This file** — the current design tokens and rules below.
3. **The Figma source** — screenshots/exports the user provides per ticket. Figma is authoritative for
   exact colors/spacing/type on a given screen; this file is authoritative for how those get
   generalized into reusable tokens and applied consistently across screens Figma hasn't covered yet.

If a screen's Figma reference uses a color, font, or spacing value not yet captured as a token below,
add it here (with the screen/ticket it came from) rather than hardcoding it inline in the widget.

## Design baseline: custom brand, not stock Material 3

Material 3 widgets are used as *structural* building blocks (buttons, fields, sheets, nav patterns),
but their color/type defaults are **not** the source of truth — PiyaNota's own Figma brand identity
is. Concretely:

- Do not rely on `ColorScheme.fromSeed()` to generate the palette. Define an explicit `ColorScheme`
  (or a custom token set consumed by `AppTheme`) from the exact values in Figma.
- Do not accept Material's default type scale as-is if Figma specifies a different font. Set
  `ThemeData.textTheme` explicitly once the Figma type scale is known.
- `lib/theme/app_theme.dart` is the only place raw color/font values should exist. Screens and widgets
  reference `Theme.of(context)` / `AppTheme` tokens, never raw `Color(0x...)` or hardcoded font names
  inline — this is what makes a future dark-mode pass (see below) additive instead of a rewrite.

### Color palette

Direction: **blue-green family** — blue-green gradients, a bluegreen (teal-leaning) solid, and a blue
solid.

**Primary gradient (confirmed):**
- Start: `#1B7DCE` (blue)
- End: `#01DCBA` (teal/bluegreen)
- Reference asset: `mobile/piyanota_application/assets/branding/Piyanota_Logo_Gradient_BG.png` — a
  diagonal (top-left-to-bottom-right-ish) sweep from the blue stop to the teal stop. Use this file as
  the visual ground truth for the exact angle if a screen needs to reproduce it precisely, since angle
  isn't fully pinned down by the two hex stops alone.
- Use for: onboarding backgrounds (PIYA-201), and other full-bleed/background gradient surfaces.
  Not necessarily every screen background — check each screen's Figma reference before applying it
  beyond onboarding.
- Flutter: define as a named `LinearGradient` constant in `AppTheme` (e.g. `AppTheme.primaryGradient`)
  rather than re-declaring the two stops inline per screen.

**Still pending** — extract from Figma screenshots in `docs/design/figma/` once provided (use an
eyedropper/color-picker read on the actual exported PNGs, don't estimate from description):
- Solid blue and bluegreen tones used outside the gradient (e.g. for flat-color buttons/icons) — check
  whether these reuse the two gradient stops (`#1B7DCE` / `#01DCBA`) directly or are separate values.
- A background/surface tone that works against both solids and the gradient (especially for screens
  with white/light content over the gradient, e.g. text legibility on PIYA-201's onboarding).
- Error color (not likely in the brand ramp — pick a standard, accessible red/orange that doesn't
  clash with blue-green).
- **Voice-part accent colors (Soprano/Alto/Tenor/Bass):** a first pass exists —
  `AppTheme.voiceAccents` (`lib/theme/app_theme.dart`), read by eye off the PIYA-201
  voice-selection Figma frame, not eyedropper-sampled. Treat as placeholder; replace with exact hex
  once available.
- **Progress-dot colors** (`AppTheme.dotActive` / `dotInactive`, used by PIYA-201's `ProgressDots`):
  no dedicated dot color was ever sampled from Figma — current values are a reasonable guess
  (`#1F2937` / `#D9D9D9`), not a confirmed brand token.

### Typography

**Font family: Plus Jakarta Sans**, for all text (confirmed — not just headings). Bundling approach:
the stated default is bundling static `.ttf` weights under `assets/fonts/` (no network dependency),
but PIYA-201 shipped with the `google_fonts` pub package (`GoogleFonts.plusJakartaSansTextTheme` in
`AppTheme.light`) as an **interim stopgap**, since no `.ttf` files had been provided yet. This is a
known deviation, not a reversed decision — swap to bundled static weights once `.ttf` files are
supplied, and drop the `google_fonts` dependency and the `INTERNET` permission it required (added to
`AndroidManifest.xml` for this reason, alongside future Module 3 API calls). Still need from Figma:
which weights are actually used (e.g. Regular/Medium/SemiBold/Bold) and the size/line-height pairing
for screen titles, body text, and button labels.

### Spacing, shape, iconography

*Status: pending — populate once Figma screenshots are provided.* Capture: base spacing unit (e.g. an
8dp grid), corner radius used on cards/buttons/sheets, and whether icons follow Material Symbols or a
custom set from Figma.

### Source assets

- App logo PNGs live in `mobile/piyanota_application/assets/branding/` (bundled into the app —
  declare in `pubspec.yaml`'s `assets:` section once files are added).
- Figma screenshots live in `docs/design/figma/` (reference-only for extracting tokens above, not
  shipped in the app).

## Responsiveness: Flutter built-ins only, no scaling package

The app must look correct across different Android phone sizes/densities without a dedicated
screen-adaptation dependency (matches this codebase's general preference for flat, dependency-light
code over added abstraction). Concretely, on every screen:

- Use `MediaQuery.sizeOf(context)` / `LayoutBuilder` for layout decisions, never hardcoded pixel
  widths/heights for content containers. Fixed sizes are acceptable only for genuinely fixed elements
  (icon glyph size, a divider's thickness).
- Prefer `Flexible`, `Expanded`, `Wrap`, and `SingleChildScrollView` over fixed-size `Row`/`Column`
  children so content reflows rather than overflowing on smaller screens.
- Respect the system font-scale setting — do not wrap text in widgets that clip or truncate at larger
  `textScaler` values without an explicit, deliberate reason (e.g. a single-line button label may
  ellipsize; a paragraph should not).
- Always wrap top-level screen content in `SafeArea` so layout doesn't collide with notches/status
  bars/gesture nav across different OEM skins (relevant here since the dev phone is a MIUI device,
  which has non-stock system-bar behavior).
- Sanity-check every screen mentally (or in the emulator) at both a small phone width (~360dp) and a
  large one (~480dp+) before considering a ticket done — this repo's scope is Android phones only
  (see the framework decision doc), so tablet/foldable layouts are explicitly not required, but a
  screen should not visually break on the sizes that *are* in scope.

## Interaction states

**SOP: every pressable element darkens on press.** When a button (or any tappable element styled with
a solid brand color — including gradient buttons, using the gradient's dominant stop) is pressed, its
background must transition to a **darker shade of its own base color** while held, reverting on
release — not a generic opacity overlay/ripple-only effect, and not a different hue.

- Implementation: compute the pressed color by reducing HSL lightness of the base color (start around
  10–15% lower lightness; tune once real palette hex values are in and it can be checked visually
  against Figma, since Figma may specify an exact pressed-state color rather than a formula-derived
  one — if so, Figma's value wins over the formula).
- Apply via each widget's actual pressed-state API (e.g. `ButtonStyle.backgroundColor` /
  `overlayColor` resolved from `WidgetState.pressed`, or `InkWell`'s `highlightColor` for custom
  tappables) — don't fake it with `AnimatedOpacity` on a duplicate layer.
- This is a **project-wide default**, not a per-screen decision — every new pressable component should
  follow it without re-asking, unless a specific screen's Figma reference explicitly shows different
  pressed-state behavior.

## Dark mode: explicitly out of scope for now

Only `AppTheme.light` is implemented. Do not build a `AppTheme.dark` or wire `ThemeMode` switching
until a ticket explicitly asks for it. However, because all color/font values are required to flow
through `AppTheme` (see above), adding dark mode later should be additive — a new `AppTheme.dark`
getter plus a theme-mode switch — not a rewrite of existing screens. Flag it if a Figma screen ever
shows a dark background, since that would mean this scope decision needs revisiting with the user.

## Per-screen checklist (run before calling a screen done)

1. Does every color/font/spacing value trace to a token in this file or `AppTheme`, not a raw literal
   in the widget?
2. Does the layout use `MediaQuery`/`LayoutBuilder`/flexible widgets instead of fixed pixel sizing?
3. Does it survive a larger system font-scale setting without clipping meaningful text?
4. Is top-level content wrapped in `SafeArea`?
5. Does it match the Figma reference for that ticket? If it deviates, is the deviation intentional and
   noted (e.g. a Flutter/Material constraint), not accidental drift?
6. If a new color/font/spacing value was introduced, was it added to this file's token sections above?
7. Does every pressable element darken on press per the Interaction states SOP above?
