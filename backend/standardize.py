"""Upload standardization (PIYA-320) and PDF page iteration (PIYA-310).

Render free is ~0.1 CPU / 512 MB, so everything here works one page at a time and runs under
``INTAKE_SEMAPHORE``: one decode in flight per process also serializes pdfium, which is not
thread-safe.
"""

from __future__ import annotations

import io
import threading
from collections.abc import Iterator
from typing import Literal, NamedTuple

import pypdfium2
from PIL import Image

from backend.config import _DEFAULTS
from backend.envelope import ApiError

MAX_PDF_PAGES = 20
JPEG_QUALITY = 90
PDF_POINTS_PER_INCH = 72
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PDF_MAGIC = b"%PDF-"

# Held around every decode/standardize/rasterize call. Not reentrant: callers must not hold it
# when calling the public functions below.
INTAKE_SEMAPHORE = threading.BoundedSemaphore(1)

# Pillow can raise any of these from a truncated or malformed stream.
_DECODE_ERRORS = (OSError, SyntaxError, ValueError, EOFError)


class StandardPage(NamedTuple):
    jpeg: bytes
    width: int
    height: int


def sniff(data: bytes) -> Literal["jpeg", "png", "pdf"] | None:
    """Identify the upload type from magic bytes only; the client's MIME type is untrusted."""
    if data.startswith(JPEG_MAGIC):
        return "jpeg"
    if data.startswith(PNG_MAGIC):
        return "png"
    if data.startswith(PDF_MAGIC):
        return "pdf"
    return None


def _encode(img: Image.Image, max_side_px: int) -> StandardPage:
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        img = Image.new("RGB", rgba.size, "white")  # JPEG has no alpha; white matches paper
        img.paste(rgba, mask=rgba.getchannel("A"))
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((max_side_px, max_side_px), Image.Resampling.LANCZOS)  # never upscales
    buf = io.BytesIO()
    # No exif/icc_profile arguments: Pillow then writes neither, which is the privacy requirement.
    img.save(buf, "JPEG", quality=JPEG_QUALITY)
    return StandardPage(buf.getvalue(), img.width, img.height)


def standardize_pil(
    img: Image.Image, page_index: int, *, max_side_px: int = _DEFAULTS["standard_max_side_px"]
) -> StandardPage:
    """Downscale and re-encode an already-decoded image (used for rendered PDF pages)."""
    with INTAKE_SEMAPHORE:
        try:
            return _encode(img, max_side_px)
        except _DECODE_ERRORS as exc:
            raise ApiError(422, "corrupt_image", "The image could not be decoded", page_index=page_index) from exc


def standardize_image(
    data: bytes,
    page_index: int,
    *,
    max_pixels: int = _DEFAULTS["max_image_pixels"],
    max_side_px: int = _DEFAULTS["standard_max_side_px"],
) -> StandardPage:
    """Decode a JPEG/PNG upload into a standard JPEG page.

    EXIF orientation is deliberately ignored (never ``exif_transpose``): the pipeline's
    deskew expects the pixels exactly as the app captured them.
    """
    too_big = ApiError(413, "image_pixels_too_large", "The image has too many pixels", page_index=page_index)
    with INTAKE_SEMAPHORE:
        try:
            img = Image.open(io.BytesIO(data))
            if img.width * img.height > max_pixels:  # header-only check, before any pixel decode
                raise too_big
            if img.format == "JPEG":
                img.draft("RGB", (max_side_px, max_side_px))  # DCT-domain downscale saves memory
            img.load()
            return _encode(img, max_side_px)
        except Image.DecompressionBombError as exc:
            raise too_big from exc
        except _DECODE_ERRORS as exc:
            raise ApiError(422, "corrupt_image", "The image could not be decoded", page_index=page_index) from exc


def iter_pdf_pages(
    data: bytes,
    *,
    max_side_px: int = _DEFAULTS["standard_max_side_px"],
    dpi: int = _DEFAULTS["pdf_render_dpi"],
) -> Iterator[Image.Image]:
    """Validate the PDF now, then lazily render one page per ``next()``.

    Validation is eager (this is a plain function returning a generator) so encrypted, corrupt
    and over-long PDFs fail before the caller has stored anything. Each page is rendered at
    ``dpi`` but capped so its long side is at most ``max_side_px``; no PNG round trip.
    """
    with INTAKE_SEMAPHORE:
        try:
            pdf = pypdfium2.PdfDocument(data)
            count = len(pdf)
        except pypdfium2.PdfiumError as exc:
            raise ApiError(422, "corrupt_or_encrypted_pdf", "The PDF is corrupt or encrypted") from exc
        if count > MAX_PDF_PAGES:
            pdf.close()
            raise ApiError(400, "too_many_pages", f"A score may have at most {MAX_PDF_PAGES} pages")
    return _render_pages(pdf, count, max_side_px, dpi)


def _render_pages(pdf: pypdfium2.PdfDocument, count: int, max_side_px: int, dpi: int) -> Iterator[Image.Image]:
    try:
        for index in range(count):
            # Lock per page, not across the yield, so a slow consumer cannot starve other requests.
            with INTAKE_SEMAPHORE:
                try:
                    page = pdf[index]
                    width, height = page.get_size()
                    scale = min(dpi / PDF_POINTS_PER_INCH, max_side_px / max(width, height))
                    img = page.render(scale=scale).to_pil().convert("RGB")
                    page.close()
                except pypdfium2.PdfiumError as exc:
                    raise ApiError(
                        422, "corrupt_or_encrypted_pdf", "The PDF is corrupt or encrypted"
                    ) from exc
            yield img
    finally:
        with INTAKE_SEMAPHORE:
            pdf.close()
