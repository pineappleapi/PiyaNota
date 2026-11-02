"""Tests for upload standardization (PIYA-320) and PDF page iteration (PIYA-310).

All fixtures are generated in code; no binaries are committed.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from backend import standardize
from backend.envelope import ApiError

EXIF_ORIENTATION_TAG = 0x0112
ROTATE_90_CW = 6


def _encode(img: Image.Image, fmt: str, **kwargs: object) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **kwargs)
    return buf.getvalue()


def make_pdf(pages: int) -> bytes:
    imgs = [Image.new("RGB", (200, 280), (255 - i * 5, 255, 255)) for i in range(pages)]
    return _encode(imgs[0], "PDF", save_all=True, append_images=imgs[1:])


def make_encrypted_pdf() -> bytes:
    """Minimal PDF whose trailer names a standard security handler with bogus keys."""
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 100 100]>>endobj\n"
        b"4 0 obj<</Filter/Standard/V 1/R 2/P -4/O(" + b"a" * 32 + b")/U(" + b"b" * 32 + b")>>endobj\n"
        b"trailer<</Root 1 0 R/Size 5/Encrypt 4 0 R/ID[<00><00>]>>\n%%EOF\n"
    )
    return body


def test_exif_orientation_ignored() -> None:
    img = Image.new("RGB", (40, 20), "red")
    exif = Image.Exif()
    exif[EXIF_ORIENTATION_TAG] = ROTATE_90_CW
    data = _encode(img, "JPEG", exif=exif)
    assert Image.open(io.BytesIO(data)).getexif()[EXIF_ORIENTATION_TAG] == ROTATE_90_CW

    page = standardize.standardize_image(data, 0)

    assert (page.width, page.height) == (40, 20)
    out = Image.open(io.BytesIO(page.jpeg))
    assert out.size == (40, 20)
    assert len(out.getexif()) == 0
    assert "icc_profile" not in out.info


def test_downscale_keeps_aspect() -> None:
    data = _encode(Image.new("RGB", (6000, 3000), "white"), "PNG")
    page = standardize.standardize_image(data, 0)
    assert (page.width, page.height) == (3000, 1500)
    assert Image.open(io.BytesIO(page.jpeg)).format == "JPEG"


def test_small_image_not_upscaled_and_alpha_flattened() -> None:
    data = _encode(Image.new("RGBA", (10, 10), (0, 0, 0, 0)), "PNG")
    page = standardize.standardize_image(data, 0)
    out = Image.open(io.BytesIO(page.jpeg))
    assert out.size == (10, 10)
    assert out.mode == "RGB"
    assert out.getpixel((5, 5))[0] > 240  # transparent pixels land on white


def test_pixel_cap_413_with_page_index() -> None:
    data = _encode(Image.new("RGB", (100, 100)), "PNG")
    with pytest.raises(ApiError) as exc:
        standardize.standardize_image(data, 3, max_pixels=5_000)
    assert (exc.value.status, exc.value.code, exc.value.page_index) == (413, "image_pixels_too_large", 3)


def test_corrupt_image_422() -> None:
    data = _encode(Image.new("RGB", (200, 200), "blue"), "JPEG")
    for bad in (data[: len(data) // 2], b"\xff\xd8\xff" + b"junk" * 10):
        with pytest.raises(ApiError) as exc:
            standardize.standardize_image(bad, 1)
        assert (exc.value.status, exc.value.code, exc.value.page_index) == (422, "corrupt_image", 1)


def test_sniff() -> None:
    assert standardize.sniff(_encode(Image.new("RGB", (4, 4)), "JPEG")) == "jpeg"
    assert standardize.sniff(_encode(Image.new("RGB", (4, 4)), "PNG")) == "png"
    assert standardize.sniff(make_pdf(1)) == "pdf"


def test_sniff_rejects_heic_webp() -> None:
    assert standardize.sniff(_encode(Image.new("RGB", (4, 4)), "WEBP")) is None
    assert standardize.sniff(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 20) is None
    assert standardize.sniff(_encode(Image.new("RGB", (4, 4)), "GIF")) is None
    assert standardize.sniff(b"") is None


def test_pdf_pages_iterated_one_by_one() -> None:
    pages = list(standardize.iter_pdf_pages(make_pdf(2)))
    assert len(pages) == 2
    assert all(isinstance(p, Image.Image) for p in pages)
    out = standardize.standardize_pil(pages[0], 0)
    assert Image.open(io.BytesIO(out.jpeg)).format == "JPEG"


def test_pdf_render_side_capped() -> None:
    pages = list(standardize.iter_pdf_pages(make_pdf(1), max_side_px=100))
    assert max(pages[0].size) <= 100


def test_pdf_errors() -> None:
    with pytest.raises(ApiError) as exc:
        standardize.iter_pdf_pages(make_pdf(21))
    assert (exc.value.status, exc.value.code) == (400, "too_many_pages")
    for bad in (make_encrypted_pdf(), b"%PDF-1.7\n" + b"garbage" * 20):
        with pytest.raises(ApiError) as exc:
            standardize.iter_pdf_pages(bad)
        assert (exc.value.status, exc.value.code) == (422, "corrupt_or_encrypted_pdf")


def test_twenty_pages_allowed() -> None:
    assert sum(1 for _ in standardize.iter_pdf_pages(make_pdf(20))) == 20


def test_intake_semaphore_is_bounded_one() -> None:
    assert standardize.INTAKE_SEMAPHORE.acquire(blocking=False)
    try:
        assert not standardize.INTAKE_SEMAPHORE.acquire(blocking=False)
    finally:
        standardize.INTAKE_SEMAPHORE.release()


@pytest.mark.parametrize("mode", ["P", "LA", "RGBA", "L", "RGB"])
def test_reduce_first_handles_every_mode(mode: str) -> None:
    img = Image.new("RGBA", (400, 300), (0, 0, 0, 0)).convert(mode)
    data = _encode(img, "PNG", transparency=0) if mode == "P" else _encode(img, "PNG")
    page = standardize.standardize_image(data, 0, max_side_px=100)
    assert max(page.width, page.height) == 100
    out = Image.open(io.BytesIO(page.jpeg))
    assert out.mode == "RGB"
    if mode in ("P", "LA", "RGBA"):
        assert out.getpixel((10, 10))[0] > 240  # transparent area flattened onto white


MEMORY_PNG_SIDE = 7000
# Measured 359 MB (decoder buffer ~196 MB + one reduced copy + resample); the unbounded version
# peaked at 727 MB. The limit sits between the two with headroom for allocator noise.
MEMORY_PEAK_LIMIT_MB = 450

_MEMORY_CHILD = """
import sys
from backend import standardize
from backend.scripts.bench_intake import _peak_rss_mb
page = standardize.standardize_image(open(sys.argv[1], 'rb').read(), 0)
print(_peak_rss_mb(), page.width, page.height)
"""


def test_large_rgba_png_memory_bounded(tmp_path: Path) -> None:
    """Pillow's C buffers are invisible to tracemalloc, so measure peak RSS in a fresh process."""
    png = tmp_path / "big.png"
    Image.new("RGBA", (MEMORY_PNG_SIDE, MEMORY_PNG_SIDE), (10, 20, 30, 128)).save(png)
    assert png.stat().st_size < 1024 * 1024  # tiny upload, ~196 MB once decoded
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", _MEMORY_CHILD, str(png)],
        cwd=repo_root, capture_output=True, text=True, check=True, timeout=120,
    )
    peak, width, height = result.stdout.split()
    assert max(int(width), int(height)) <= 3000
    assert float(peak) < MEMORY_PEAK_LIMIT_MB
