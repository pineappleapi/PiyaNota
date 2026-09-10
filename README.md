# PiyaNota — Proof-of-Concept Setup Guide

## Project Structure

```
piyanota/
├── stage1_preprocessing.py   # Stage 1: Image preprocessing
├── stage2_detection.py       # Stage 2: YOLOv8 staff detection
├── run_pipeline.py           # Main runner (Stage 1 → 2)
├── requirements.txt          # Python dependencies
└── data/
    ├── dataset.yaml          # YOLOv8 training config
    ├── raw/                  # ← PUT YOUR SCORE IMAGES HERE
    ├── preprocessed/         # Auto-created by Stage 1
    ├── strips/               # Auto-created by Stage 2
    └── images/ + labels/     # Your annotated training data
```

---

## Step-by-Step VSCode Setup

### 1. Install Prerequisites

- **Python 3.10+** — https://www.python.org/downloads/
  - During install, check ✅ "Add Python to PATH"
- **VSCode** — https://code.visualstudio.com/
- **Git** (optional but recommended) — https://git-scm.com/

---

### 2. Open the Project in VSCode

1. Create a folder on your computer, e.g. `C:\Projects\piyanota` (Windows) or `~/projects/piyanota` (Mac/Linux)
2. Copy all the files from this package into that folder
3. Open VSCode → **File → Open Folder** → select the folder

---

### 3. Install the Python Extension

1. In VSCode, press `Ctrl+Shift+X` (Extensions sidebar)
2. Search **Python** → install the one by Microsoft
3. Search **Pylance** → install it too (better autocomplete)

---

### 4. Create a Virtual Environment

Open the VSCode terminal: **Terminal → New Terminal** (or `` Ctrl+` ``)

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Mac / Linux
python3 -m venv venv
source venv/bin/activate
```

You should see `(venv)` appear at the start of your terminal prompt.

---

### 5. Select the Virtual Environment in VSCode

1. Press `Ctrl+Shift+P` → type **Python: Select Interpreter**
2. Choose the one that shows `venv` in the path (e.g. `.\venv\Scripts\python.exe`)

---

### 6. Install Dependencies

In the terminal (with venv active):

```bash
pip install -r requirements.txt
```

This installs OpenCV, NumPy, and Ultralytics YOLOv8.
YOLOv8 will also auto-download `yolov8n.pt` on first run (~6 MB).

> **If you have an NVIDIA GPU**, install PyTorch with CUDA for faster training:
> ```bash
> pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
> pip install ultralytics opencv-python numpy Pillow PyYAML
> ```

---

### 7. Add Your Score Images

Place your SATB score photos (JPG or PNG) inside `data/raw/`.
Even 1–2 images work for a demo.

---

### 8. Run the Pipeline

```bash
# Basic run (Stage 1 + Stage 2):
python run_pipeline.py --input data/raw

# With debug images saved (shows each preprocessing step):
python run_pipeline.py --input data/raw --debug
```

Outputs appear in:
- `data/preprocessed/` — thresholded, skew-corrected pages
- `data/strips/` — individual staff strips per voice

---

### 9. (Optional) Training YOLOv8

Once you have annotated images:

```bash
python run_pipeline.py --train --data data/dataset.yaml --epochs 50
```

Best weights saved to: `runs/train/piyanota_staff_detector/weights/best.pt`

Then use them:
```bash
python run_pipeline.py --input data/raw --weights runs/train/piyanota_staff_detector/weights/best.pt
```

---

### 10. Evaluating the Trained Model (mAP)

```bash
python run_pipeline.py --eval \
  --weights runs/train/piyanota_staff_detector/weights/best.pt \
  --data data/dataset.yaml
```

This prints **mAP50** and **mAP50-95** — the metrics from your Sprint 4 acceptance criteria.

---

## Annotating Your SATB Score Images (for Training)

Use **Roboflow** (free, web-based):
1. Go to https://roboflow.com → create a free account
2. Create a project → Object Detection → class name: `staff`
3. Upload your score images → draw bounding boxes around each staff line
4. Export as **YOLOv8 format** → download and place in `data/images/` and `data/labels/`

Aim for at least **50–80 annotated staff regions** for fine-tuning.

---

## What to Show at Your Defense

| What | Where |
|---|---|
| Preprocessed image (thresholded, skew-corrected) | `data/preprocessed/` |
| Debug intermediates (each preprocessing step) | `data/debug/` (run with `--debug`) |
| Detected staff strips per voice | `data/strips/` |
| Training loss curve (if trained) | `runs/train/.../results.png` |
| mAP scores (if trained) | Terminal output of `--eval` |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: ultralytics` | Run `pip install -r requirements.txt` with venv active |
| `No images found` | Make sure images are in `data/raw/` and are `.jpg` or `.png` |
| `No staff regions detected` | Try a clearer photo; the pretrained model may not recognize music staves yet — train first |
| VSCode doesn't find Python | Press `Ctrl+Shift+P` → Python: Select Interpreter → pick the venv one |
