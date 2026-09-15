# Step 1: Font Re-Rendering of CameraPrIMuS (Kaggle)

Implements step 1 of `docs/decisions/piya-106-crnn-font-retraining-plan.md`. Produces new,
already-labeled training images in 4 real music-engraving font styles the CRNN has never seen,
without any manual transcription.

**Now built directly into `training/pianota-transcription-training.ipynb`** as its first section
(the notebook Step 2 fine-tuning will extend) — this file is the standalone writeup/rationale; run the
notebook cells rather than copy-pasting from here if you're doing this for real. Switched from Colab
to Kaggle (2026-09-15) because the base CRNN training run already lives there (see CLAUDE.md: "trained
separately on Kaggle"), it can attach the CameraPrIMuS dataset natively with no download step, and it
supports unattended background execution via Save & Run All.

**Verified locally before writing this guide** (2026-09-14): confirmed CameraPrIMuS ships a `.mei`
file per sample alongside `.agnostic`/`.semantic`/`.png`; confirmed Verovio (pip-installable, no
license) bundles 5 distinct SMuFL music fonts (`Leipzig`, `Bravura`, `Petaluma`, `Gootville`,
`Leland`); confirmed all 5 render the same sample `.mei` to a single-page, single-system SVG at a
tightly-cropped ~180px height — the same shape as CameraPrIMuS's own strips. The SVG→PNG step needs
a native `cairo` library, which isn't present in this repo's Windows dev venv but installs cleanly
on Kaggle's Ubuntu runtime with one `apt-get` line (below).

## Why re-render instead of hand-labeling

Every `.mei` file already encodes the exact same note/rest/clef/beam sequence as its sibling
`.agnostic`/`.semantic` files — re-rendering it through a different font changes *only* the glyph
shapes on the page, not the music. So the existing label files are valid, unmodified ground truth
for every new render. This is the "free labels" move ml-cv-lead's review recommended before any
hand-labeling of real Filipino sheet music.

## Kaggle setup

1. Open (or create) the notebook in Kaggle, then **Add Data** → search `cameraprimus` → attach
   `piamac/cameraprimus`. It mounts read-only at
   `/kaggle/input/datasets/piamac/cameraprimus/CameraPrIMuS - Copy` — the same path
   `pianota-transcription-training.ipynb`'s existing cells already read from, so no download/auth step
   is needed (unlike Colab, which had to `kagglehub.dataset_download` it over the network each run).
2. **Settings → Internet: On** (needs phone verification on your Kaggle account once) — required for
   the `apt-get`/`pip install` calls below.
3. Accelerator: **None**. This step is pure CPU (SVG rendering) — leave your GPU quota for step 2.

```python
# Cell 1 — system + Python deps for SVG rasterization
!apt-get -qq update && apt-get -qq install -y libcairo2
!pip install -q verovio cairosvg
```

## Rendering script

```python
# Cell 2 — render every sample through each font
import verovio, cairosvg, os, glob, shutil, re
from pathlib import Path

CPM_ROOT   = Path("/kaggle/input/datasets/piamac/cameraprimus/CameraPrIMuS - Copy")
CORPUS_DIR = CPM_ROOT / "Corpus"
OUT_DIR    = Path("/kaggle/working/cpm_font_augmented")
FONTS      = ["Bravura", "Petaluma", "Gootville", "Leland"]   # Leipzig == Verovio's own default;
                                                                # CPM's original .png was NOT rendered
                                                                # by Verovio, so Leipzig is already a
                                                                # genuinely new glyph style too -- add
                                                                # it back into FONTS for a 5th condition.

RENDER_OPTS = {
    "inputFrom": "mei",
    "breaks": "none",          # force a single system -- matches CPM's tightly-cropped strip shape
    "adjustPageHeight": True,
    "adjustPageWidth": True,
    "header": "none",
    "footer": "none",
    "scale": 100,
    "pageMarginTop": 0,
    "pageMarginBottom": 0,
    "pageMarginLeft": 0,
    "pageMarginRight": 0,
}

mei_files = sorted(CORPUS_DIR.rglob("*.mei"))
print(f"Found {len(mei_files):,} .mei files")

failures = []
for i, mei_path in enumerate(mei_files):
    stem = mei_path.stem
    sample_dir = mei_path.parent
    agnostic_src = sample_dir / f"{stem}.agnostic"
    semantic_src = sample_dir / f"{stem}.semantic"
    if not agnostic_src.exists():
        continue  # skip anything without ground truth to pair against

    for font in FONTS:
        out_sample_dir = OUT_DIR / font / stem
        out_sample_dir.mkdir(parents=True, exist_ok=True)
        png_path = out_sample_dir / f"{stem}.png"
        if png_path.exists():
            continue  # resumable -- skip work already done in a prior run

        try:
            tk = verovio.toolkit()
            tk.setOptions({**RENDER_OPTS, "font": font})
            if not tk.loadFile(str(mei_path)):
                failures.append((stem, font, "loadFile returned False"))
                continue
            svg = tk.renderToSVG(1)
            svg_path = out_sample_dir / f"{stem}.svg"
            svg_path.write_text(svg, encoding="utf-8")
            cairosvg.svg2png(url=str(svg_path), write_to=str(png_path),
                              background_color="white", scale=2.0)
            svg_path.unlink()  # keep only the PNG once rasterized

            # copy the ORIGINAL, unmodified labels next to the new render --
            # the music content is identical, so these are still correct ground truth
            shutil.copy(agnostic_src, out_sample_dir / f"{stem}.agnostic")
            if semantic_src.exists():
                shutil.copy(semantic_src, out_sample_dir / f"{stem}.semantic")
        except Exception as e:
            failures.append((stem, font, str(e)))

    if (i + 1) % 2000 == 0:
        print(f"  [{i+1:,} / {len(mei_files):,}]")

print(f"\nDone. {len(failures)} failures out of {len(mei_files) * len(FONTS):,} attempted renders.")
for stem, font, err in failures[:20]:
    print(f"  FAILED {stem} / {font}: {err}")
```

## Running it unattended

Kaggle's **Save Version → Save & Run All (Commit)** executes the notebook top-to-bottom on Kaggle's
servers and keeps going after you close the tab — useful here since ~4,000 samples × 4 fonts will take
a while on CPU. You'll get notified when the run finishes.

## Sanity checks before moving to step 2 (fine-tuning)

Do these before trusting the output — a silent rendering bug here would poison every downstream step:

1. **Visually spot-check ~10 samples per font.** Open a handful of the new PNGs next to the
   original CameraPrIMuS `.png` for the same stem. Confirm: single staff line, correct clef/notes,
   no clipped noteheads/stems at the image edges, no leftover title/composer text (there shouldn't
   be any — `header`/`footer` are set to `"none"`).
2. **Confirm label parity.** For a few samples, re-open the copied `.agnostic` file and manually
   count clef/note/barline tokens against what's visible in the new PNG — they must match exactly,
   since nothing about the token sequence should have changed.
3. **Check file counts.** `len(mei_files) * len(FONTS)` PNGs expected (minus any in `failures`).
   A large failure count on one specific font (rather than scattered across all) suggests a
   font-specific glyph-coverage gap worth investigating before using that font's output.
4. **Persist the result** — `/kaggle/working` is cleaned up between sessions unless committed. After
   a successful **Save & Run All**, open that run's Output tab and click **+ New Dataset** to turn
   `cpm_font_augmented` into its own Kaggle dataset — attach it as input to the step 2 fine-tuning
   notebook directly, no zip/Drive step needed.

## What this does NOT yet do

- Does not touch the training loop or `CameraPrIMuSDataset` in
  `training/pianota-transcription-training.ipynb` — that's step 2 (fine-tuning), not started.
- Does not add Condition B (realistic strip context / label-text clutter) — the script above is
  Condition A only (bare re-render). ml-cv-lead's review flagged that Condition B needs testing too
  before concluding font-swap alone closes the gap; that requires compositing label-style text next
  to the rendered staff and is a follow-up, not part of this step.
- Does not include a distorted/camera-simulation pass over the new font renders — the existing
  `CameraPrIMuSDataset._augment()` pipeline (brightness/shadow/rotation/blur/perspective/elastic)
  can likely be reused as-is in step 2 once these renders are wired into the dataset loader.
