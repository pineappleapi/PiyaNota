"""Operator CLI: turn an uploaded score into audio until the pipeline runs server-side.

Workflow: ``fetch-pages`` the standardized pages, run Stage 1-5 locally, then ``complete``.
Reads DATABASE_URL and storage settings from the PIYA_* environment (backend.config).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from backend import background, completion, db
from backend.config import load_settings
from backend.storage import Storage, build_storage, new_key

VOICES = ("soprano", "alto", "tenor", "bass")
DEFAULT_REVIEW: dict[str, object] = {
    "reviewNeeded": True, "reasons": ["clef_key_unvalidated"], "items": [], "truncated": False,
}
# Empty timing file when the operator supplies none; the app treats it as "no highlight data".
EMPTY_TIMING = b"{}"
COORD_NOTE = (
    "fetch-pages downloads the standardized pages; the timing file's x/y must be measured on "
    "those same pixels."
)


def _fetch_pages(storage: Storage, job_id: int, out_dir: Path) -> int:
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT page_index, object_key FROM job_pages WHERE job_id = %s ORDER BY page_index", (job_id,)
        ).fetchall()
    out_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        (out_dir / f"page_{row['page_index']:03d}.jpg").write_bytes(storage.get(row["object_key"]))
    print(f"wrote {len(rows)} page(s) to {out_dir}")
    return 0 if rows else 1


def _complete(storage: Storage, args: argparse.Namespace) -> int:
    audio_dir = Path(args.audio_dir)
    if any(p.suffix.lower() == ".mid" for p in audio_dir.iterdir()):
        print("error: .mid files found; render audio to .mp3 first", file=sys.stderr)
        return 2
    report: dict[str, Any] = json.loads(Path(args.report).read_text("utf-8")) if args.report else {}
    if args.review:
        review = json.loads(Path(args.review).read_text("utf-8"))
    else:
        review = report["review"] if "review" in report else DEFAULT_REVIEW
    failed: dict[str, str] = {k.capitalize(): v for k, v in report.get("failedVoiceCauses", {}).items()}
    for name in report.get("failedVoices", []):
        failed.setdefault(str(name).capitalize(), "unreadable")
    for item in args.failed:
        voice, _, cause = item.partition(":")
        if voice.strip().lower() not in VOICES:
            print(f"error: unknown voice {voice!r} in --failed", file=sys.stderr)
            return 2
        failed[voice.strip().capitalize()] = cause.strip() or "unreadable"
    voices = {v: audio_dir / f"{v}.mp3" for v in VOICES if v.capitalize() not in failed}
    missing = [p.name for p in voices.values() if not p.is_file()]
    if missing:
        print(f"error: missing audio file(s) in {audio_dir}: {', '.join(missing)}", file=sys.stderr)
        return 2
    with db.transaction() as conn:
        page0 = conn.execute(
            "SELECT object_key FROM job_pages WHERE job_id = %s AND page_index = 0", (args.job_id,)
        ).fetchone()
    thumb = completion.make_thumbnail(storage.get(page0["object_key"])) if page0 else None
    uploads: dict[str, tuple[bytes, str]] = {
        new_key("audio", "mp3"): (p.read_bytes(), "audio/mpeg") for p in voices.values()
    }
    audio_keys = dict(zip(voices, uploads))
    timing_key = new_key("timing", "json")
    uploads[timing_key] = (Path(args.timing).read_bytes() if args.timing else EMPTY_TIMING, "application/json")
    thumb_key = None
    if thumb is not None:
        thumb_key = new_key("thumbs", "jpg")
        uploads[thumb_key] = (thumb, "image/jpeg")
    background.reserve_keys(uploads)
    try:
        for key, (data, ctype) in uploads.items():
            storage.put(key, data, ctype)
        with db.transaction() as conn:
            score_id = completion.complete_job(
                conn, args.job_id, audio_keys=audio_keys, timing_key=timing_key,
                failed_voices=list(failed), failed_voice_causes=failed, review=review,
                muted_measures=report.get("mutedMeasures", []), thumbnail_key=thumb_key,
            )
    except Exception:
        _discard(storage, uploads)
        raise
    if score_id is None:
        _discard(storage, uploads)
        print(f"job {args.job_id} was cancelled or no longer exists; uploads discarded", file=sys.stderr)
        return 1
    print(f"job {args.job_id} complete: score {score_id}")
    return 0


def _discard(storage: Storage, keys: Any) -> None:
    """Delete uploads of a failed completion; the reservation rows retry any that fail."""
    for key in keys:
        try:
            storage.delete(key)
        except Exception as exc:  # noqa: BLE001 - the hourly reservation cleans up what this misses
            print(f"warning: could not delete {key} ({type(exc).__name__})", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobs_cli", description=__doc__, epilog=COORD_NOTE)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list-queued", help="show queued jobs")
    p = sub.add_parser("fetch-pages", help="download a job's standardized pages", epilog=COORD_NOTE)
    p.add_argument("job_id", type=int)
    p.add_argument("out_dir")
    p = sub.add_parser("complete", help="upload audio and finish a job", epilog=COORD_NOTE)
    p.add_argument("job_id", type=int)
    p.add_argument("--audio-dir", required=True, help="dir with soprano.mp3, alto.mp3, tenor.mp3, bass.mp3")
    p.add_argument("--timing", help="timing JSON; x/y on the fetch-pages pixels")
    p.add_argument("--review", help="review JSON file")
    p.add_argument("--report", help="JSON from stage5_synthesis.run_full_pipeline_with_report()")
    p.add_argument("--failed", action="append", default=[], metavar="VOICE:CAUSE", help="e.g. tenor:unreadable")
    p = sub.add_parser("fail", help="mark a job failed")
    p.add_argument("job_id", type=int)
    p.add_argument("reason")
    p.add_argument("--page", type=int)
    return parser


def main(argv: Sequence[str], storage: Storage | None = None) -> int:
    """Run one CLI command; ``storage`` is injectable for tests."""
    args = build_parser().parse_args(argv)
    settings = load_settings()
    db.init_pool(settings.database_url, max_size=2, prepare_threshold=settings.db_prepare_threshold)
    store = storage if storage is not None else build_storage(settings)
    if args.cmd == "list-queued":
        with db.transaction() as conn:
            for r in conn.execute(
                "SELECT id, user_id, title, page_count, created_at FROM jobs WHERE status = 'queued' ORDER BY id"
            ).fetchall():
                print(f"{r['id']}\tuser={r['user_id']}\t{r['page_count']}p\t{r['created_at']:%Y-%m-%d %H:%M}\t{r['title']}")
        return 0
    if args.cmd == "fetch-pages":
        return _fetch_pages(store, args.job_id, Path(args.out_dir))
    if args.cmd == "complete":
        return _complete(store, args)
    with db.transaction() as conn:
        updated = completion.fail_job(conn, args.job_id, args.reason, args.page)
    if not updated:
        print(f"error: job {args.job_id} not found or already finished", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    code = main(sys.argv[1:])
    db.close_pool()
    sys.exit(code)
