# PIYA-106: Chord / divisi music semantics (choral-conductor answer to chord plan Open Question 3)

**Status:** ADVISORY, 2026-10-01. No code changed. Companion to `piya-106-chord-vocabulary-plan.md` (ml-cv-lead,
not edited here). Labels used below: **[theory]** = notation fact, **[convention]** = usual engraving/choir practice
that some publishers break, **[judgment]** = my recommendation for a practice track; push back on these.

**Binding user decision (2026-10-01):** a divisi chord in one voice plays BOTH notes in that voice's audio track.
Everything below takes that as given. Where I say "do not play" it is about notes that are **not divisi** (cue,
ossia, optional alternatives), so it does not conflict with the decision.

**Verdict:** The rule is sound and Stage 4/5 already handle same-rhythm chords correctly. The real risks are in
Stage 3's tie, dot and accidental attachment, which today point at `events[-1]` (the last note emitted). With
chords, that is the wrong member. Two further gaps sit outside the CRNN: split-stem rhythms and the 8-staff
SSAATTBB layout.

---

## 1. How divisi appears in open-score SATB, and whether "play both" applies

| Form | What it looks like | How common (judgment, octavo/hymn/Filipino arrangement repertoire) | Play both? |
|---|---|---|---|
| **Same-stem chord** | Two (rarely three) noteheads on one stem, same duration | **Most common.** Typical at cadences (final chord split for a full triad, Bass octave doubling), climaxes. Often with "div." text above | **Yes.** This is exactly the user's case |
| **Split stems, same rhythm** | Two noteheads at the same x, upper part stems up, lower stems down | **Common.** House style of many publishers for "div." even when rhythm is identical | **Yes.** Musically identical to a same-stem chord. Treat as a chord |
| **Split stems, different rhythms** | Two independent layers on one staff (e.g. upper holds a half note while lower sings two quarters; one layer rests while the other sings) | **Occasional.** Imitative entries inside a section, moving inner part under a held note | **Yes in principle** (each layer with its own rhythm). Not representable in v1 (see Q2). Flag |
| **"div." / "unis." text** | Text above the staff | Common as an *annotation* to the forms above | The text adds nothing to the audio. The noteheads already say what to play. No action needed |
| **Divisi on extra staves** (S1/S2 on two staves, SSAATTBB system of 5-8 staves) | The system grows from 4 staves to 5-8 for a passage | **Common in larger works** and in some Filipino concert arrangements | Not a chord at all. It breaks Stage 2's voice assignment (see Q6, item F) |
| **Cue-size notes** | Small noteheads, usually another part's line printed during this part's rests to help the entry, sometimes with the other voice's name | Occasional in choral octavos | **No [convention].** The singer does not sing them. Playing them puts another voice's line into this track. Skip if detected; v1 cannot detect size (Q7) |
| **Optional / ad-lib small notes** (e.g. small low D2 in Bass on the final chord, "opt." / "ad lib.") | A small notehead stacked with a normal one, or an alternative in parentheses | Occasional, mostly Bass low octaves and Soprano high descants | **No: play only the normal-size note [judgment].** Most of the section sings the main note. Flag as `optional_note_present` if detected |
| **Ossia** | A short extra staff above the main staff, partial width, small notes | **Rare** in SATB choral | **No.** Play the main staff. Ossia staves also break the 4-staves-per-system count (Q6, item F) |
| **Shared staff** ("Women" or "S. A." on one staff for a passage in an otherwise open score) | Two *different voices* on one staff with split stems | Rare in open score (it is closed score; out of scope) | **No.** This is not divisi. "Play both" would put Alto notes in the Soprano track. Flag/out of scope |

[theory] In a vocal staff, a chord always means divisi: one singer cannot produce two pitches. So any chord the
pipeline decodes in a voice staff is either divisi (play both), an optional/cue note (do not play), or a
recognition error. That gives a cheap validator (Q7, V1-V3).

## 2. Split stems with different rhythms

**What one track should play [judgment]:** the two layers superimposed, each with its own rhythm, exactly as a
pianist would play the staff. Merging both layers into the one voice track is right (it is one section's
track, per the user decision). The problem is representing the rhythm, not the merge.

**Why v1 cannot do it:** the plan's Option A (`chordnote` inherits the base note's duration; chord plan §2.2,
§2.4) can only express chords whose members all have the same length. A layer that rests while the other sings
cannot be expressed either: the rest token advances `current_tick` the same way a note does.

Concrete failure, 4/4, Alto: beat 1 upper G4 half note (stem up), lower E4 quarter then D4 quarter (stem down).
- Correct audio: G4 sounds for 2 beats; E4 sounds beat 1, D4 sounds beat 2.
- Likely decode: `note.half(E4) chordnote(G4) note.quarter(D4)`. Both chord members become half notes and D4 lands on
  beat 3. The bar is a quarter over. `_repair_overflow` (`stage4_reconstruction.py:1143-1226`) then scales a run,
  clips, or drops a note. It is flagged `review_needed`, but the client sees a generic overflow code.
- Layer-rest variant: an upper quarter rest over a lower quarter note decodes as rest then note in sequence.
  Same overflow; the rest pushes the lower note late.

**Recommendation:** flag, do not repair. If a bar that contains a `chord_id` overflows, Stage 4 should emit a
specific `divisi_rhythm_split_suspected` (review_needed) instead of run-scaling or clipping the bar. Run
scaling invents a rhythm nobody sings. Severity: wrong rhythm.

## 3. Unisons inside a divisi

[theory] There are two engraved forms. (a) One notehead with two stems (up and down) means both parts sing the
same pitch. (b) Two noteheads side by side at the same pitch, used when the parts have different durations
(e.g. a half and a quarter on G4).

**Play once [judgment, strong].** On a piano, one key cannot sound twice. Two note-ons at the same pitch and onset
only make the note louder and risk hanging note-offs. Stage 5's collapse of identical (onset, pitch) notes to the
longest one (`stage5_synthesis.py:151-157`) is **exactly right** for both forms: (a) and (b) both play the
pitch once, sustained for the longer value.

Risk to note: form (b) is two noteheads at nearly the same x. The CRNN will probably emit them as two sequential
notes, not a chord. That doubles the time and makes the bar overflow (same class as Q2). Form (a) is one notehead
and decodes as one note. That is correct.

A divisi that ends on a tied unison (upper part holds G4 tied, lower part rises to G4): when it is engraved as one
notehead with the tie on the upper stem, the result is one held G4 with no re-attack. That is acceptable
[judgment]: the lower singers still hear their target pitch.

## 4. Ties and accidentals inside chords

**Ties [theory]:** a tie belongs to one notehead. In a chord, any subset of members can be tied; untied members
are struck again. Engraving puts each tie arc next to its own notehead, so the agnostic `slur.start-<pos>` /
`slur.end-<pos>` position identifies the member (within about ±1 staff step: the arc sits just above or below the
head).

- Stage 4 is ready for this. `_resolve_ties` keys open ties by pitch (`stage4_reconstruction.py:1309,1318`), so a
  tie on one chord member merges only that member. That is correct.
- **Stage 3 attaches ties to the wrong member.** `slur.start` marks `events[-1]` (`stage3_transcription.py:1756-1761`).
  With chordnotes emitted bottom to top, that is always the **top** note. `slur.end` sets one pending flag that
  goes to the **next note emitted**, which is the next chord's **bottom** note (`:1763-1772`, `:1672`, `:1682-1687`).
  `_infer_ties_from_slurs` then needs same pitch AND an end mark on the same member (`stage4_reconstruction.py:1266-1272`).
  Example: Alto, key C, 4/4. Beat 4 has the chord E4+G4 with both notes tied into a half-note chord on bar 2 beat 1.
  Correct: both pitches sound for 3 beats with one attack. Predicted: G4 carries both starts, and E4 (the bottom
  note) carries the end. Neither member matches, so **both notes are struck again on the downbeat**. A singer
  hears a new syllable that is not there. Severity: wrong rhythm.
  **Fix:** attach each `slur.start/end` to the chord member nearest its position. Keep the end marks per member
  (one per position, not one pending flag).
- Tie carry of an accidental across the barline uses one `last_note_step` / `last_note_alteration`
  (`stage3_transcription.py:1632-1635,1642`). Inside a chord that holds only the last emitted member. Example:
  Bass, key C. Bar 5 ends on the chord B♭2+D3 with B♭2 tied across the barline. Correct bar 6: B♭2 continues.
  Predicted: `last_note_step` is D3's step, so the tied note falls back to the key and plays **B2 natural**.
  Severity: wrong notes. **Fix:** keep a step-to-alteration map for the previous onset's members.

**Accidentals [theory]:** an accidental applies to its own notehead and to every later note **on the same staff
position (same octave) on that staff until the barline**. This covers both divisi parts, including the other
stem direction. [convention] Many editors also add a courtesy accidental in the other part. The courtesy sets
the same absolute alteration, so it must not shift the pitch twice.
- `measure_alterations` is keyed by staff step and reset at the barline (`stage3_transcription.py:1629-1639,1696`).
  That is **already correct** for chords and split stems. It is octave-specific and shared across both layers.
  Because it sets the absolute alteration (BUG-024), a courtesy accidental cannot double-shift.
- The open piece is attaching the accidental to its member. The chord plan's x-order linearization puts all of a
  chord's accidentals before the base note. The current anchoring rule (the accidental must sit on the *next*
  note's position) drops an accidental meant for the upper member as "unanchored" (BUG-033 flag), and that gives
  a wrong note. Match by position across the whole chord, as the chord plan §2.2 already proposes. I confirm
  that this is the musically right rule.

**Dots [theory]** (not asked, but the same attachment bug): a dotted chord prints **one dot per notehead**, stacked
vertically at the same x. A note on a line gets its dot in the space above. A double dot is two dots side by side
at the **same** height. Stage 3 counts consecutive dots on `events[-1]` as extra dots (`stage3_transcription.py:1545-1564`).
Example: Soprano, 3/4, dotted-half chord G4+B4. Tokens: `note.half-L2 chordnote-L3 dot-S2 dot-S3`. Predicted: B4
becomes a **double-dotted** half (1680 ticks), G4 stays a plain half (960), and the cursor moves 960. The bar is
underfull and the two members end at different times. Correct: both members last 1440. **Fix:** dots at different
positions after a chord dot the whole chord once. Repeated dots at the same position are double dots. This also
contradicts chord plan §2.2 ("one `dot-*` token per chord"): real engraving shows one dot per member, so the
converter label must match the image.

## 5. End of a divisi passage

[theory/convention] The passage ends with a single notehead on a single stem, or a single notehead with two stems
(unison) in split-stem writing, optionally with "unis." text. Divisi on extra staves ends when the system
returns to 4 staves, usually with "unis." or a bracket.

**The pipeline does not need to detect it for audio.** Under "play both", the notation is the state: one note
means one pitch, a chord means both pitches. No mode carries over between onsets, so there is nothing to reset. It
would only matter for a future "play only my divisi line" option (out of v1). The one exception is the
extra-staves form. Its start and end change the staff count per system, and that does need detection, in Stage 2,
not Stage 3/4 (Q6, item F).

## 6. Stage 4/5 behaviour under "play both"

Correct as written (do not churn):
- `_measure_ticks` and `_make_slots` count each onset once, using its longest member (`stage4_reconstruction.py:275-287,981-991`).
  This is right for chords, and measure-sum validation stays valid.
- `_rescale_slots` gives every member of a slot the same duration (`:1015-1033`). That is right under Option A,
  since members share a duration anyway.
- The confidence-based drop excludes onsets with more than one event (`:1205-1209`), so it can never delete one
  half of a chord. Correct.
- `_clip_to_bar` / `_keep_last_ticks` work per event (`:1105-1140`). Chord members share onset and duration, so
  they are trimmed together. Correct.
- `_resolve_ties` is pitch-keyed (`:1309-1341`). Correct per member, once Stage 3 attaches ties correctly (Q4).
- Stage 5 writes one track and can hold simultaneous notes (`stage5_synthesis.py:197-205`). The unison collapse is
  correct (Q3).

Would break, or needs a decision:
- **A. Tie attribution** (Stage 3, Q4): ties land on the wrong member, so the chord re-strikes. Wrong rhythm.
- **B. Tie-carried accidental** (Stage 3, Q4): only the last member is remembered. Wrong notes.
- **C. Dots on chords** (Stage 3, Q4): one member gets double-dotted and the others are not dotted at all. Wrong rhythm.
- **D. Split-rhythm layers** (Stage 3 representation + Stage 4 overflow repair, Q2): bars are rescaled into a rhythm
  nobody sings. Flag with a specific code instead.
- **E. Ties into a split layer:** `_resolve_ties` only looks at the very next onset group (`stage4_reconstruction.py:1336-1338`).
  If an upper held note is tied while the lower layer moves (the next onset group is the lower layer's
  note), the tie is reported unresolved and the note is struck again. Under Option A this cannot happen yet. Revisit
  only if layers are ever represented. Then the right rule is "next onset where this pitch's layer has a note".
- **F. Divisi on extra staves (Stage 2, not chord work, highest impact):** `stage2_detection.py:114` only rejects a
  staff count not divisible by 4. An 8-staff SSAATTBB system passes and is split into two "systems", S A T B and
  S A T B (`VOICE_MAP`, `:146`). Soprano 2 becomes Alto, Alto 1 becomes Tenor, and so on. The second half is also
  placed later in time. Silent: wrong notes and wrong structure. A 5-7 staff system, or a partial-width ossia staff,
  raises or misaligns. **Minimum fix:** detect systems by bracket/barline span or by staff count per system
  (both are already available from Stage 1 tracking). A system whose staff count is not 4 is flagged
  `system_staff_count_not_4` (review_needed), never silently re-chunked.
- **G. Same-pitch overlap clipping** (`stage5_synthesis.py:163-171`): for a held upper note with the lower layer
  striking the same pitch later, the held note is cut at the new onset. That is the only thing one piano key can
  do, so it is fine. Better: extend the later note to the later of the two ends so the pitch keeps sounding to the
  end of the held value. Only relevant once layers exist (D).
- **H. Loudness [judgment, low priority]:** two notes at `MIDI_VOLUME` 100 (`stage5_synthesis.py:39`) make divisi bars
  audibly louder than unison bars in the same track. That is acceptable for v1. If the user notices, scale velocity
  per chord member (e.g. about 100/sqrt(n)).

## 7. Validators and what v1 can leave out

Cheap deterministic checks that catch hallucinated or dropped chordnotes (these can feed ml-cv-lead's
chord-precision/calibration work; I am not judging the experiment):
- **V1 interval:** a chord whose two members are more than an octave apart (more than 12 semitones) in S/A/T is
  almost never divisi [convention]. Flag. In Bass, exactly an octave is common (cadential low octave). Allow 12,
  flag more than 12.
- **V2 size:** 3 or more members in one voice staff ("div. a 3") is rare. Flag `review_needed`. Keep all
  members playing, per the user decision.
- **V3 impossible chord:** a chordnote on the base's own staff position cannot be engraved on one stem.
  Treat it as an orphan (Stage 5's collapse would hide it silently).
- **V4 range:** the existing voice-range checks apply to every member. A divisi extends a range by a few
  semitones, not by an octave.
- **V5 overflow in a chord bar:** see Q2 (`divisi_rhythm_split_suspected`).

Rare enough to leave out of v1 (flag `review_needed` where detectable, otherwise list as known-lost): split-stem
different rhythms and layer rests, triple divisi, cue notes, optional small notes, ossia, temporary shared
staves, side-by-side unison heads. Displaced-notehead seconds are **not rare** in contemporary and Filipino
arrangements (added-2nd and sus clusters at cadences). They should be in v1's labels if the converter can
produce them, or at least appear in the known-lost list with a measured count.

## Summary table

| Case | Behaviour | Needs detection | First version |
|---|---|---|---|
| Same-stem chord, same rhythm | Play all members, same onset/duration | Y (chordnote tokens) | **In** |
| Split stems, same rhythm | Same as a chord; play both | Y (converter must group by x, not by shared stem) | **In** |
| Split stems, different rhythms / layer rests | Ideal: superimpose layers. v1: no repair, flag `divisi_rhythm_split_suspected` | Y (overflow in a chord bar) | Out (flag) |
| "div." / "unis." text | No effect; noteheads decide | N | In (nothing to do) |
| Return to unison | One note means one pitch; no state to reset | N | In (nothing to do) |
| Unison inside divisi (1 head 2 stems, or 2 heads) | Play once, longest value (Stage 5 collapse) | N for 1 head; 2 heads decode as sequential notes, so flag via overflow | In / flag |
| Tie on one chord member | Hold that member only; re-strike the others | Y (attach slur by position) | **In (Stage 3 fix A)** |
| Tie-carried accidental in a chord | Carried for the tied member only | Y (per-member carry) | **In (Stage 3 fix B)** |
| Accidental on one chord member | Applies to that position for the rest of the bar, both layers; courtesy does not double-shift | Y (position-match to member) | **In** (bar-state logic already correct) |
| Dotted chord (one dot per head) | Dot the whole chord once; same-height repeat = double dot | Y (dot positions) | **In (Stage 3 fix C)** |
| Triple divisi (3+ members) | Play all, flag | Y (count) | In, flagged |
| Interval > octave in S/A/T, > octave in B | Play, flag as likely misread | Y (validator) | In, flagged |
| Cue-size notes | Do not play | Y (needs size; not available) | Out (known-lost) |
| Optional/ad-lib small note | Play normal-size note only | Y (size) | Out (known-lost) |
| Ossia staff | Play main staff only | Y (Stage 2 staff count/width) | Out (flag) |
| Divisi on extra staves (5-8 per system) | Map each staff to its section; at minimum never re-chunk silently | Y (Stage 2 staves per system) | **Flag in v1** (silent mis-assignment today) |
| Shared staff ("Women", "S. A.") | Not divisi; out of scope | Y | Out (flag) |
| Displaced-notehead seconds | Play both | Y | In if converter supports, else known-lost with count |
