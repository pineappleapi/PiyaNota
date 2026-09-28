# Preliminary results: how to present them in the WCTP 2026 abstract

Written 2026-09-28. Numbers come from `D:\PiyaNota-training\data\eval_prelim\` (`REPORT.md`,
`TEMPLATE_tables.md`, `runs/results.json`). If those files are re-run, re-check every number here.

## The recommendation

A one-page abstract has room for **one small table plus two or three results sentences**:

1. **The table shows only the final system** (fine-tuned CRNN + clef/key classifier) on digital vs
   camera input, filling your template (Staff detection / SER / Pitch accuracy × Digital / Camera / Δ).
   Report the two seeds as a range.
2. **One sentence for the internal baseline** (where you started). It is the controlled comparison,
   so it is the evidence that your changes did something. It doesn't need its own table.
3. **One clause for SKIMusic.** It is the benchmark the proposal committed to, so leave it out of the
   table and cite it in the sentence with a "different data and metric" qualifier.
4. **Leave out** the no-classifier ablation, per-piece splits, CIs, the other Chapter 2 studies (Liu,
   Martinez-Sevilla, Camera-PrIMuS SOTA) and the v1 test set. They go in the full paper, where there is
   room for caveats.

The reason: in the abstract, a reader should see *what the system does now* and *how much camera
capture costs*. The ablation and the literature comparison both need caveats, and an abstract has no
room for them.

## Table 1 (for the abstract)

Test set: 2 Filipino/Latin SATB pieces (Non Nobis Domine pp. 1–3, Gaano Ko Ikaw Kamahal pp. 1–9),
12 pages, 100 staves, 1,008 notes per condition. Each page appears as a digital PDF render and as a
phone photo of the printed page. Δ = Camera − Digital.

| Input | Staff detection* | SER ↓ | Pitch accuracy ↑ |
|---|---|---|---|
| Digital | 100% | 25.0–25.5% | 88.7–89.1% |
| Camera | 100% | 33.8–34.8% | 83.3–83.4% |
| **Δ (pp)** | **0.0** | **+8.8 to +9.2** | **−5.4 to −5.7** |

\* Staff detection is stave recall: the share of ground-truth staves found and assigned the right
voice. **It is not mAP50**, because these pages have no bounding-box annotations. Rename the template
column, or add this footnote. Don't label it mAP50.

Ranges are the two fine-tuning seeds. Report both; never pick the better seed.

## Final abstract (v9, in `PiyaNota_WCTP_Abstract_revised.docx` / `.pdf`)

148 words by Word's own count. Word counts en-dash ranges differently from a plain split, so always
re-check the count in Word after an edit.

> Choral singing, a centuries-old Filipino tradition, thrives in churches, schools, and communities,
> yet many choir members cannot read sheet music and learn their parts from conductors. Optical Music
> Recognition (OMR) models degrade on phone photos and are rarely deployed; commercial apps assume
> musical literacy, and the only Filipino system is rule-based, piano-only. PiyaNota is an Android app
> converting smartphone photos of open-score SATB (Soprano, Alto, Tenor, Bass) scores into per-voice
> piano audio. YOLOv8 isolates each staff; a convolutional recurrent network fine-tuned on multi-font
> renderings, with a clef and key-signature classifier, transcribes it. On 12 pages, digital and
> photographed, all 100 staves were detected; camera pitch accuracy reached 83.3–83.4% (88.7–89.1%
> digital), up from under 5% initially, though symbol error remains 33.8–34.8%. PiyaNota contributes,
> to our knowledge, the first annotated Filipino SATB dataset, a pipeline tested on phone photos, and
> an app for singers without formal training.

The opening states a checkable fact (a centuries-old tradition, §2.2.1 of the proposal) instead of an
uncited value claim such as "central to Filipino culture".

Keywords: Optical Music Recognition, SATB Choral Music, Music Literacy, Filipino Choral Music, Mobile
Application, Camera-Captured Sheet Music, YOLOv8, Convolutional Recurrent Neural Network.

### Structure mapping

| Part (thesis format) | Guide component | Sentence |
|---|---|---|
| Motivation | Context | "Choral singing, a centuries-old Filipino tradition, … yet many choir members cannot read sheet music…" |
| Problem + gap | Problem | "OMR models … degrade on phone photos and are rarely deployed…; commercial apps assume musical knowledge…; SKIMusic … rule-based and piano-only." |
| Objective | Approach | "PiyaNota is an Android app converting…" |
| Method | Approach | "YOLOv8 isolates each staff; a convolutional recurrent network…" |
| Results | Results | "On 12 pages … 83.3–83.4% … up from under 5% … symbol error remains 33.8–34.8%." |
| Contribution | Implication | "PiyaNota contributes the first annotated Filipino SATB dataset…" |

### Why this gap and contribution (decided with the user, 2026-09-28)

- **The gap is deployment and usability, not accuracy alone.**
  - OMR research reports benchmark accuracy but rarely documents integrating a model into a usable
    app, and phone photos degrade it (Liu 2023; Tuggener 2024; Castellanos 2025 in Ch. 2).
  - Commercial apps assume the user can already read music (Morell 2024).
  - SKIMusic is the only Filipino precedent, and it is rule-based and piano-only.
- **Dropped:** "commercial apps assume users can correct the output". PiyaNota can't correct scores
  either and isn't 100% accurate, so the contrast was unfair.
- **Dropped:** the "clef bottleneck / benchmark" contribution. It is a finding, not the thesis's
  purpose.
- **The contribution** matches the thesis purpose and research questions:
  - the Filipino SATB dataset (RQ1/RQ2 evaluation data);
  - a documented pipeline tested on real phone photos (RQ1/RQ2);
  - an app for singers without formal training (RQ3, SUS).

## WCTP 2026 call-for-abstracts compliance

| Requirement | Status |
|---|---|
| Single PDF | ✅ Submit `PiyaNota_WCTP_Abstract_revised.pdf`, not the .docx. |
| Title | ✅ |
| All authors with affiliations | ✅ CICS, DLSU-D |
| Student author identified, with programme and year | ✅ BS CS with Specialization in Intelligent Systems, 4th Year |
| Abstract of 70–150 words | ✅ 148 words (Word's count) |
| Contact author: name, phone, email | ✅ |
| Optional supporting material, at most 1 extra page | ✅ Page 2 only; the PDF is 2 pages |
| English, unpublished work | ✅ |
| Topic fit | ✅ Human-Centered Computing (mobile), Computing Methodologies (ML), Applied Computing (education) |
| Deadline | **Sep 30, 2026.** Workshop Nov 25–27, De La Salle Lipa. |

## Check against the abstract-writing guide

| Guide rule | Status |
|---|---|
| Context in 1–2 sentences | ✅ 1 sentence |
| Problem in 1 sentence | ✅ One compound sentence carrying 3 gaps. It is dense but within the rule. |
| Approach in 1–2 sentences | ✅ 2 sentences |
| Quantitative results in 2–3 sentences | ⚠️ 1 sentence. The 150-word cap forces this. It gives concrete numbers, a baseline gain and the weakness (SER). |
| Implication in 1 sentence | ✅ A contribution list rather than a "so what", which suits a work-in-progress abstract |
| No citations | ✅ SKIMusic is named as a system, not cited |
| No maths or symbols | ✅ |
| No future tense | ✅ The remaining work is on page 2, not in the abstract |
| Acronyms spelled out | ✅ OMR and SATB are spelled out. CRNN is replaced with words. YOLOv8 is a model name and is left as is. |
| Length of 150–250 words | Overridden by the CFP's 150-word maximum |

### Remaining weaknesses (for the user or adviser to decide)

- **"first annotated Filipino SATB dataset"** is now hedged with "to our knowledge". The scored test set is 2 pieces, and one (Non Nobis Domine) is Latin, so describe the dataset honestly in the paper.
- **"the only Filipino system"** (SKIMusic, now unnamed) is unhedged. It is only as strong as the Ch. 2
  search.
- **The Figure 1 legend** marks stages as Complete/Implemented/Fine-tuning. Check that it still
  matches reality, and that "Integration pending" agrees with the Remaining Work paragraph.

## Proposal-level flags (not for the abstract; fix in the manuscript)

- **Hypothesis (≥85% symbol recognition on mobile photos) is not met** if it is read as 1 − SER:
  camera ≈ 65–66%. Camera pitch accuracy (83.3–83.4%, CI 79.8–86.6%) is also short of 85%. State
  this plainly in the results.
- **SO4** says rule-based clef-aware mapping. The clef/key classifier is a method deviation, so
  document it in Ch. 3 with the no-classifier ablation (11–22% pitch accuracy) as the justification.
- **§2.1.2 and §1.6 describe SATB as closed score** (voices sharing two staves). PiyaNota's scope is
  open score, so reframe these sections. §1.6's "validated pipeline for polyphonic choral notation"
  overclaims.
- **§1.7 promises 10 scores**, but the preliminary test uses 2 pieces (12 pages).

## Things the abstract must not claim

- **"Beats SKIMusic's 30.2% SER threshold."** It doesn't: camera SER is 33.8–34.8%. The proposal's
  conversion (69.8% accuracy ≈ 30.2% SER) is also not valid, because SER counts inserted symbols and
  element accuracy doesn't. Compare on pitch accuracy vs element accuracy only, with the qualifier.
  Raise the conversion with your adviser separately.
- **"Meets the ≥85% target."** Camera pitch is 83.3–83.4% and its 95% CI is 79.8–86.6%, so it's
  inconclusive; digital clears it. If you mention the target, say camera input is "approaching" it.
- **"Transcribes timing/rhythm accurately."** Pitch accuracy ignores duration. SER includes rhythm and
  is 25–35%.
- **Anything implying no false notes.** Note precision is 66–69%: about 1 in 3 output notes is extra
  or wrong-pitched, and the pitch-accuracy metric doesn't penalise that. You don't need this in a
  one-page abstract, but don't write anything that contradicts it (e.g. "accurate audio").
- **"Evaluated on Filipino choral repertoire" as if it were a large corpus.** It's 2 pieces. Use
  "preliminary".

## What goes in the full paper instead

- **Table 2, ablation:** base → fine-tuned (no classifier) → fine-tuned + classifier, digital and
  camera, seeds as ranges. That is `TEMPLATE_tables.md` as generated.
- **Literature comparison table:**
  - Include SKIMusic, Liu et al. (2023), Martinez-Sevilla et al. (2025), and the Camera-PrIMuS ceiling
    (Ma 2026 / Castellanos 2025).
  - Label the table "not directly comparable".
  - Optionally add your own CRNN's clean Camera-PrIMuS number as a bridge row.
- **Caveats:**
  - The test set is small (2 pieces).
  - The test set was changed after v1 results were seen. The v1 numbers are kept for an appendix.
  - Scope rule: the solo/divisi pages were excluded.
  - Staff detection is recall, not mAP50.
  - Note precision.
  - CIs.
