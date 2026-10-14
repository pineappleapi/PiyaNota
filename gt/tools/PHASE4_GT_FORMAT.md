# Phase 4 GT source format (PIYA-106, SER-15 plan Amendment 8.5)

One hand-written `gt/<piece>/gt_source.txt` per piece. `gt/tools/project_gt.py gt/<piece>` builds both scored
versions from it: `v1/gt.json` (without divisi) and `v2/gt.json` (with divisi). Nobody edits the outputs by hand.
The syntax is the dev GT syntax (Non Nobis Domine and the others), plus the divisi kinds below. Draft only from the
photos and the Stage 2 strip crops, never from a model decode (Amendment 8.4 firewall).

## 1. Strip lines

```
p<page>s<system> <Voice>: clef:<G|G8|F> key:<N><#|b> [time:<N/D|C|C/>] | <bar> | <bar> | ... | #slurs <n>
p<page>s<system> <Voice>: <EXCLUDED reason>
```

- Page and system numbers are 1-based, top to bottom, as Stage 2 cuts them. Voice is `Soprano`, `Alto`, `Tenor` or `Bass`.
- Soprano and Alto are `clef:G`, Bass is `clef:F`. Tenor is `clef:G8` (treble-8vb), `clef:G` (plain treble, sung an
  octave lower by convention) or `clef:F`. Pitches are written as **printed**; the builder lowers a treble-clef Tenor
  by 12 for the sounding pitch, and a bass-clef Tenor sounds as written. There are no C clefs.
- `key:` always carries a sign; no key signature is `key:0#`. The scorer cannot read a bare `key:0`.
- `time:` is written only where the meter is printed on that strip. `time:C` and `time:C/` are the common-time and cut-time
  signs; `N/D` is printed digits. 4/4 printed as digits is `time:4/4`.
- The first `|` after the header separates it; it is not a barline. Every later `|` is a printed barline. Write a
  final `|` only if the strip ends on a printed barline.
- `#slurs n` counts phrase slurs (curves over different pitches). They never become tokens.
- `#omitted n` counts symbols left out on purpose: cue notes, and small optional heads stacked on a normal note
  (write only the normal-size note). An ossia staff is not a strip.

## 2. Items inside a bar

| Item | Syntax | Notes |
|---|---|---|
| Note | `<d>[.|..]:[acc]<Pitch><oct>` | d in `w h q e s`; acc `^` sharp, `_` flat, `=` natural, only when printed |
| Rest | `r<d>[.]` | a whole rest fills the bar in any meter |
| Multi-bar rest | `mr:<n>` | |
| Beam group | `[ ... ]` | eighths and sixteenths drawn under one beam; `]?` if unsure |
| Tie out / in | `~` on the first note; `<~` on the note the tie arrives at | `~>` = tie leaves the strip |
| Grace note | `g<q|e|s>:[acc]<Pitch><oct>` | drawn, never timed |
| Fermata | `fermata` right before the note, rest or chord it sits on | once, even when split-stem layers print two |
| Mid-strip key | `key:<N><#|b>` where printed; `key:0#` = naturals on the old signature | add `!` when cancelling naturals are printed before the new signature (e.g. 2♯ to 1♯, or ♯ to ♭) |
| Mid-strip meter | `time:...` where printed | |
| Unsure | `?` after any item | counted, never changes the token |

## 3. Divisi and other regions the model cannot read (`<OOV:kind ...>`)

| Kind | Syntax | v1 | v2 |
|---|---|---|---|
| Same-stem chord | `<OOV:chord <d>[.|..] M1+M2[+M3]>` | `<OOV>` | expanded (section 4) |
| Split stem, same rhythm | `<OOV:splitstem <d>[.|..] M1+M2>` | `<OOV>` | expanded, the same as a chord |
| Triplet | `<OOV:triplet <d> ...>` | `<OOV>` | `<OOV>` |
| Split stem, different rhythm | `<OOV:twovoice <d> ...>` | `<OOV>` | `<OOV>` |

- **Which kind (first match wins):** `triplet` > `twovoice` > `splitstem` / `chord`. A chord inside a triplet is
  `triplet`.
  - `chord`: one stem, 2+ heads at different pitches. One stem has one duration.
  - `splitstem`: two stems with the same rhythm, one onset.
  - `twovoice`: the parts differ in rhythm, or one part rests while the other sings (never write a rest followed by a
    note), or two heads at the same pitch with different durations. The region runs from the onset where the parts
    split to the onset where they merge again.
  - One notehead with two stems (unison) is a plain note, not a region. Two same-pitch heads in a `chord` stop the build.
- **`<d>` is the total length of the region.** Three triplet quarters are `<OOV:triplet h ...>`. The scorer uses
  this length for the wildcard event.
- **Member** `M` = `[acc]<Pitch><oct>` plus an optional `~` (tied to the next item), `~>` (tie leaves the strip), `<~`
  (tie arrives) and `?`. Members may be written in any order; the builder sorts them bottom to top.
- A member accidental is written only when printed; it carries to the end of the bar like any other accidental.
- Seconds (displaced heads) need no tag: the builder finds them from the member steps.
- The text after `<d>` of a triplet or twovoice region is free, for the human reader. Write the notes there anyway, so
  a later version can expand them.
- Any other `<OOV:...>` kind (e.g. a repeat sign or a volta) makes the build fail. Leave out symbols the vocabulary
  has no token for (repeat dots, voltas, dynamics, text). Fermatas are out of thesis scope (plan Amendment 6), but they
  are still written, as the `fermata` item: the primary SER drops them from both sides, and the secondary full SER
  counts them.

## 4. v2 token order for one chord

`fermata` (if any), `slur.end-<pos>` for each tied-in member, then the accidentals bottom to top,
`note.<shape>-<lowest pos>`, `chordnote-<pos>` for the other members bottom to top, one `dot-<pos>` per head per dot
bottom to top, and `slur.start-<pos>` for each member tied onward. A space note's dot sits in its space; a line note's
dot sits in the space above, unless a higher member already has a dot there (a dotted second), when it moves to the
space below. `<shape>` is the beamed form inside `[ ]`, else the
duration name. The divisi arm's converter `<chord>` output must use this same order.

v2 gives one note event per member: same duration, a shared `chord` id, pitch from the key and bar accidentals, Tenor
minus 12.

## 5. Checks the builder runs

- v1 equals v2 once each expanded chord becomes one `<OOV>` (tokens and events, with ties and slurs dropped as the
  scorer drops them).
- `--parity`: v1 reproduces the committed dev `gt.json` of Non Nobis Domine, Honneur a Toi, Gaano and Handog.
- It prints only validity results and the strip count, never divisi or OOV counts (firewall).

## 6. Known limit

An accidental carried by a tie across a barline stays in force for the whole new bar, not only for the tied note
(the dev GT convention, kept so v1 matches dev; choral-conductor 2026-10-15). It matters only when the same letter
and octave appears again later in that bar without an accidental, which publishers usually avoid by restating it.
