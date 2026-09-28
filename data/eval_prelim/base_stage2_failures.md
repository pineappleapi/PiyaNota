# Base model (original main-branch pipeline): Stage 2 page rejections

Run: `run_base_original.py`, 2026-09-28, CPU. Every failure is the same Stage 2 guard,
`unsupported_staff_layout`: the stave count after filtering/dedup is not divisible by 4, so the whole page is rejected
and none of its strips reach Stage 3. The scorer counts all GT staves on a rejected page as missed.
"Detected" = staves YOLO found after dedup; "expected" = staves in the GT for that page (Both Sides Now: counted
from the PDF). Log: `log_base.txt`; per-page Stage 1/2 output: `runs/<condition>/<piece>/base_pageNN_log.txt`.

33 rejected pages out of 60 page runs.

| Condition | Piece | Rejected / total | Page (detected / expected staves) |
|---|---|---|---|
| camera | Non Nobis Domine | 3 / 4 | p2 (9/8), p3 (13/12), p4 (9/10) |
| camera | Honneur a Toi | 3 / 3 | p1 (7/8), p2 (10/12), p3 (10/8) |
| camera | Gaano Ko Ikaw Kamahal | 3 / 9 | p1 (7/8), p6 (9/8), p7 (9/8) |
| camera | Handog | 10 / 14 | p1 (9/8), p2 (9/8), p3 (11/9), p5 (5/5), p8 (6/6), p9 (7/6), p10 (13/10), p11 (10/8), p12 (10/9), p14 (9/8) |
| camera | Don't Stop Me Now | 2 / 5 | p1 (13/12), p4 (10/12) |
| camera | Both Sides Now | 6 / 7 | PDF p1 (13/12), p2 (10/12), p3 (13/12), p6 (9/12), p7 (10/12), p8 (6/8) |
| digital | Non Nobis Domine | 2 / 4 | p1 (9/8), p4 (11/10) |
| digital | Don't Stop Me Now | 2 / 5 | p1 (11/12), p4 (10/12) |
| digital | Both Sides Now | 2 / 9 | p8 (10/8), p9 (9/8) |

Notes:
- Some rejections are structural, not detection errors: the page really does have a stave count that isn't a
  multiple of 4. These are Non Nobis p4 (5 staves per system, 10 expected) and Handog p3/p5/p8/p9/p10/p12
  (divisi/reduced systems: 9, 5, 6, 6, 10, 9 expected). Even a perfect detector would be rejected on these pages.
- The rest are detection errors, mostly over-detection (+1 stave: lyric/text bands or page borders detected as
  a staff) plus some under-detection. Camera pages have far more of these than digital pages.
- A page that passes the guard isn't necessarily correct: e.g. digital DSMN p3 passed with 8 strips against
  12 expected staves, and camera Handog p4 (12/10), p6 (8/7) and p7 (8/7) passed with the wrong count, so
  voice labels on those pages are misassigned. Detection correctness is scored separately (staff-detection recall), not by pass/fail.
