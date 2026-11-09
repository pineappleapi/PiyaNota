"""Intake benchmark (PIYA-101 AC4 / PIYA-310 AC6): `python -m backend.scripts.bench_intake`.

Docker is unavailable on the dev PC, so this times the host and projects Render free
(~0.1 CPU) by multiplying by RENDER_SLOWDOWN. B2 upload time is excluded (not available here).
Fixtures are generated in a child process so the parent's peak RSS reflects only standardization.
"""

from __future__ import annotations

import ctypes
import io
import random
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from backend import standardize

IMAGE_COUNT = 20
PDF_PAGE_COUNT = 20
IMAGE_SIZE = (4000, 3000)  # 12 MP
LETTER_PX = (1275, 1650)  # US letter at 150 dpi, embedded by Pillow's PDF writer
RENDER_SLOWDOWN = 10  # Render free is ~0.1 CPU
GATE_SECONDS = 15.0
GATE_PEAK_MB = 350.0
BYTES_PER_MB = 1024 * 1024
NOISE_SIGMA = 20
JPEG_FIXTURE_QUALITY = 90


def _photo_like(seed: int) -> Image.Image:
    """Noisy gradient with shapes: noise makes the JPEG realistically large (3-5 MB)."""
    rng = random.Random(seed)
    noise = Image.effect_noise(IMAGE_SIZE, NOISE_SIGMA)
    img = Image.merge("RGB", (noise, noise.transpose(Image.Transpose.FLIP_LEFT_RIGHT), noise))
    draw = ImageDraw.Draw(img)
    for _ in range(40):
        x, y = rng.randrange(IMAGE_SIZE[0]), rng.randrange(IMAGE_SIZE[1])
        draw.ellipse((x, y, x + 300, y + 200), outline=(255, 255, 255), width=6)
    return img.filter(ImageFilter.GaussianBlur(0.6))


def _generate(directory: Path) -> None:
    for i in range(IMAGE_COUNT):
        _photo_like(i).save(directory / f"img{i}.jpg", "JPEG", quality=JPEG_FIXTURE_QUALITY)
    pages = []
    for i in range(PDF_PAGE_COUNT):
        page = Image.new("RGB", LETTER_PX, "white")
        draw = ImageDraw.Draw(page)
        for staff in range(8):
            for line in range(5):
                y = 150 + staff * 180 + line * 12
                draw.line((100, y, LETTER_PX[0] - 100, y), fill="black", width=2)
            for note in range(30):
                draw.ellipse((120 + note * 36, 140 + staff * 180, 140 + note * 36, 156 + staff * 180), fill="black")
        draw.text((100, 60), f"Page {i + 1}", fill="black")
        pages.append(page)
    pages[0].save(directory / "score.pdf", "PDF", save_all=True, append_images=pages[1:], resolution=150)


def _peak_rss_mb() -> float:
    if sys.platform == "win32":
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t)
                for name in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
                )
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.c_void_p(process), ctypes.byref(counters), counters.cb
        )
        return counters.PeakWorkingSetSize / BYTES_PER_MB
    import resource  # POSIX only; ru_maxrss is KiB on Linux

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--gen":
        _generate(Path(sys.argv[2]))
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, "-m", "backend.scripts.bench_intake", "--gen", tmp], check=True)
        sizes = [(Path(tmp) / f"img{i}.jpg").stat().st_size / BYTES_PER_MB for i in range(IMAGE_COUNT)]
        pdf_bytes = (Path(tmp) / "score.pdf").read_bytes()

        start = time.perf_counter()
        for i in range(IMAGE_COUNT):
            standardize.standardize_image((Path(tmp) / f"img{i}.jpg").read_bytes(), i)
        img_s = time.perf_counter() - start
        img_peak = _peak_rss_mb()

        start = time.perf_counter()
        count = 0
        for page in standardize.iter_pdf_pages(pdf_bytes):
            standardize.standardize_pil(page, count)
            count += 1
        pdf_s = time.perf_counter() - start
        pdf_peak = _peak_rss_mb()  # cumulative process peak, so >= image peak

    print(f"fixtures: {IMAGE_COUNT} JPEGs 12 MP, {min(sizes):.1f}-{max(sizes):.1f} MB each; "
          f"{count}-page PDF {len(pdf_bytes) / BYTES_PER_MB:.1f} MB")
    print("B2 upload time excluded (not available on this host).")
    for label, secs, peak in (("20 images", img_s, img_peak), ("20-page PDF", pdf_s, pdf_peak)):
        print(f"{label}: host {secs:.2f} s, projected Render {secs * RENDER_SLOWDOWN:.1f} s, peak RSS {peak:.0f} MB")
    blocked = img_s * RENDER_SLOWDOWN > GATE_SECONDS or max(img_peak, pdf_peak) > GATE_PEAK_MB
    print("GATE: " + ("BLOCKED" if blocked else "PASS") +
          f" (images projected <= {GATE_SECONDS:.0f} s, peak <= {GATE_PEAK_MB:.0f} MB)")
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
