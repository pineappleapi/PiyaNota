"""Input pages for the preliminary digital-vs-camera evaluation (shared by both drivers and the scorer).

Digital pages are the user's PDFs rendered at DIGITAL_DPI (grayscale PNG). Camera pages are the phone
photos of printed copies of the same PDFs (checked page by page: photo pN == PDF page N, except Both Sides
Now, whose 7 photos are PDF pages 1-4 and 6-8).
"""
from __future__ import annotations

from pathlib import Path

PHOTOS = Path("D:/PiyaNota/data/piyanota_dataset")
BSN_PHOTOS = Path("D:/PiyaNota/data/raw/Raw")
DIGITAL = Path(__file__).resolve().parents[1] / "eval_digital" / "pages"
DIGITAL_DPI = 300

# piece -> page numbers that have ground truth (DSMN GT covers photo/PDF pages 1-5 only)
NOTE_GT_PIECES: dict[str, list[int]] = {
    "non_nobis_domine": [1, 2, 3, 4],
    "honneur_a_toi": [1, 2, 3],
    "gaano_ko_ikaw_kamahal": list(range(1, 10)),
    "handog": list(range(1, 15)),
    "dont_stop_me_now": [1, 2, 3, 4, 5],
}
DIGITAL_PIECES = ["non_nobis_domine", "dont_stop_me_now", "gaano_ko_ikaw_kamahal"]  # PDFs with note GT

# Scope rule (docs/sow.md: open-score SATB, one staff per voice): a page is scored only if every system on it is
# exactly S/A/T/B. Stage 2 accepts or rejects whole pages, so the rule is applied per page. These pages hold a
# solo staff (Non Nobis p4) or divisi systems of 5-7 staves (Handog), all marked "excluded" in their GT.
OUT_OF_SCOPE_PAGES: dict[str, list[int]] = {"non_nobis_domine": [4], "handog": [3, 4, 5, 6, 7, 8, 9, 10, 12]}

# Both Sides Now: staff-count GT only (no note GT). PDF page -> photo file; expected staves per PDF page.
BSN_PHOTO_OF_PDF_PAGE = {1: "IMG_1081.JPG", 2: "IMG_1082.JPG", 3: "IMG_1083.JPG", 4: "IMG_1084.JPG",
                         6: "IMG_1086.JPG", 7: "IMG_1087.JPG", 8: "IMG_1088.JPG"}
BSN_EXPECTED_STAVES = {1: 12, 2: 12, 3: 12, 4: 12, 5: 12, 6: 12, 7: 12, 8: 8, 9: 8}


def conditions() -> list[tuple[str, str, list[int]]]:
    """(condition, piece, pages) for every run."""
    out: list[tuple[str, str, list[int]]] = [("camera", p, pages) for p, pages in NOTE_GT_PIECES.items()]
    out += [("digital", p, NOTE_GT_PIECES[p]) for p in DIGITAL_PIECES]
    out += [("camera", "both_sides_now", sorted(BSN_PHOTO_OF_PDF_PAGE)),
            ("digital", "both_sides_now", sorted(BSN_EXPECTED_STAVES))]
    return out


def page_path(condition: str, piece: str, page: int) -> Path:
    if condition == "digital":
        return DIGITAL / f"{piece}_pg{page:02d}.png"
    if piece == "both_sides_now":
        return BSN_PHOTOS / BSN_PHOTO_OF_PDF_PAGE[page]
    return PHOTOS / f"{piece}_pg{page:02d}.jpg"
