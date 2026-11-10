"""Tests for the score library, result, edit and delete endpoints (PIYA-308, 309, V2 B5)."""

from __future__ import annotations

import types
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from psycopg.types.json import Jsonb

from backend import background, db
from backend.tests.test_jobs_submit import _err, _signup, _storage, headers  # noqa: F401

VOICES = ("soprano", "alto", "tenor", "bass")


@pytest.fixture(autouse=True)
def _clean(db_clean: None) -> None:
    """Every test starts with empty tables."""


def _uid(email: str = "a@example.com") -> int:
    with db.transaction() as conn:
        return int(conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()["id"])


def _score(
    user_id: int,
    title: str = "Bayan Ko",
    arranger: str | None = "Pia",
    *,
    thumb: bool = True,
    tag: str = "",
    failed: tuple[str, ...] = (),
    midi: bool = False,
) -> tuple[int, int]:
    """A finished score with job, 2 pages, tracks and timing; returns (score_id, job_id)."""
    with db.transaction() as conn:
        s = conn.execute(
            "INSERT INTO scores (user_id, title, arranger, page_count, tempo_source, review, "
            "thumbnail_key, failed_voices) VALUES (%s, %s, %s, 2, 'user', %s, %s, %s) RETURNING id",
            (user_id, title, arranger, Jsonb({"reviewNeeded": False}),
             f"thumbs/{tag}t.jpg" if thumb else None, Jsonb(list(failed))),
        ).fetchone()
        j = conn.execute(
            "INSERT INTO jobs (user_id, score_id, status, source, page_count, title, arranger, "
            "tempo_source) VALUES (%s, %s, 'complete', 'images', 2, %s, %s, 'user') RETURNING id",
            (user_id, s["id"], title, arranger),
        ).fetchone()
        for i in range(2):
            conn.execute(
                "INSERT INTO job_pages (job_id, page_index, object_key, width, height) "
                "VALUES (%s, %s, %s, %s, 600)", (j["id"], i, f"pages/{tag}{i}.jpg", 800 + i),
            )
        for v in VOICES:
            if v not in failed:
                conn.execute(
                    "INSERT INTO audio_tracks (score_id, voice, file_key, midi_key) VALUES (%s, %s, %s, %s)",
                    (s["id"], v, f"audio/{tag}{v}.mp3", f"midi/{tag}{v}.mid" if midi else None),
                )
        conn.execute(
            "INSERT INTO timing_metadata (score_id, metadata_key) VALUES (%s, %s)",
            (s["id"], f"timing/{tag}.json"),
        )
    return int(s["id"]), int(j["id"])


def _retake(user_id: int, old_job: int, status: str = "queued") -> int:
    with db.transaction() as conn:
        row = conn.execute(
            "INSERT INTO jobs (user_id, status, source, page_count, title, tempo_source, "
            "replaces_job_id) VALUES (%s, %s, 'images', 1, 'Bayan Ko', 'user', %s) RETURNING id",
            (user_id, status, old_job),
        ).fetchone()
        conn.execute(
            "INSERT INTO job_pages (job_id, page_index, object_key, width, height) "
            "VALUES (%s, 0, 'pages/retake0.jpg', 10, 10)", (row["id"],),
        )
    return int(row["id"])


def test_library_empty_list(client: FlaskClient, headers: dict[str, str]) -> None:
    res = client.get("/api/scores", headers=headers)
    assert res.status_code == 200 and res.get_json()["data"] == {"scores": []}
    assert res.get_json()["message"] == "Score library retrieved"


def test_library_entry_omits_absent_fields(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, _ = _score(_uid(), arranger=None, thumb=False)
    (entry,) = client.get("/api/scores", headers=headers).get_json()["data"]["scores"]
    assert entry["scoreId"] == sid and entry["pageCount"] == 2
    assert entry["lastProcessedAt"].endswith("Z")
    assert not {"lastAccessedAt", "arranger", "thumbnailUrl"} & set(entry)


def test_library_order_and_search(client: FlaskClient, headers: dict[str, str]) -> None:
    uid = _uid()
    a, _ = _score(uid, "Bayan Ko", "Zed", tag="a")
    b, _ = _score(uid, "Lupang Hinirang", "Bayani", tag="b")
    c, _ = _score(uid, "Other", None, tag="c")
    with db.transaction() as conn:
        conn.execute(
            "UPDATE scores SET last_accessed_at = now() + interval '1 hour' WHERE id = %s", (a,)
        )

    def ids(query: str) -> list[int]:
        res = client.get("/api/scores" + query, headers=headers)
        assert res.status_code == 200
        return [s["scoreId"] for s in res.get_json()["data"]["scores"]]

    assert ids("") == [a, c, b]
    assert ids("?search=bay") == [a, b]
    assert ids("?search=%25") == [] and ids("?search=_") == []
    assert ids("?search=%20%20") == [a, c, b]
    _err(client.get("/api/scores?search=" + "x" * 101, headers=headers), 400, "search_too_long")


def test_library_only_own_scores(client: FlaskClient, headers: dict[str, str]) -> None:
    other = _signup(client, "b@example.com")
    _score(_uid("b@example.com"))
    assert client.get("/api/scores", headers=headers).get_json()["data"]["scores"] == []
    assert len(client.get("/api/scores", headers=other).get_json()["data"]["scores"]) == 1


def test_library_thumbnail_signed(client: FlaskClient, headers: dict[str, str]) -> None:
    _score(_uid(), tag="x")
    (entry,) = client.get("/api/scores", headers=headers).get_json()["data"]["scores"]
    assert entry["thumbnailUrl"] == "https://storage.test/thumbs/xt.jpg?sig=fake"


def test_signed_url_ttls(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, _ = _score(_uid(), tag="x")
    storage = _storage(client.application)
    client.get("/api/scores", headers=headers)
    assert storage.ttls["thumbs/xt.jpg"] == 3600
    client.get(f"/api/scores/{sid}/result", headers=headers)
    assert storage.ttls["pages/x0.jpg"] == 21600
    assert all(t == 21600 for k, t in storage.ttls.items() if k.startswith(("audio/", "timing/")))


def test_result_shape_and_touch(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, jid = _score(_uid())
    res = client.get(f"/api/scores/{sid}/result", headers=headers)
    assert res.status_code == 200
    assert res.get_json()["message"] == "Processed score result retrieved"
    data = res.get_json()["data"]
    assert data["jobId"] == f"job_{jid}" and data["scoreId"] == sid and data["arranger"] == "Pia"
    assert set(data["audioTracks"]) == set(VOICES)
    assert data["scoreImages"] == [f"https://storage.test/pages/{i}.jpg?sig=fake" for i in range(2)]
    assert data["scoreImageSizes"] == [{"width": 800, "height": 600}, {"width": 801, "height": 600}]
    assert data["timingMetadataUrl"].startswith("https://storage.test/timing/")
    assert data["review"] == {"reviewNeeded": False} and data["failedVoices"] == []
    assert {"tempoBpm", "title", "mutedMeasures", "failedVoiceCauses"} <= set(data)
    with db.transaction() as conn:
        row = conn.execute("SELECT last_accessed_at FROM scores WHERE id = %s", (sid,)).fetchone()
    assert row["last_accessed_at"] is not None


def _last_accessed(sid: int) -> Any:
    with db.transaction() as conn:
        return conn.execute("SELECT last_accessed_at FROM scores WHERE id = %s", (sid,)).fetchone()["last_accessed_at"]


def test_result_touch_false_skips_last_accessed(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, _ = _score(_uid())
    res = client.get(f"/api/scores/{sid}/result?touch=false", headers=headers)
    assert res.status_code == 200 and "audioFiles" in res.get_json()["data"]
    assert _last_accessed(sid) is None


def test_result_version_stable_and_changes_with_files(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, _ = _score(_uid(), tag="v")
    url = f"/api/scores/{sid}/result"
    v1 = client.get(url, headers=headers).get_json()["data"]["version"]
    assert client.get(url, headers=headers).get_json()["data"]["version"] == v1  # new signatures, same version
    with db.transaction() as conn:
        conn.execute("UPDATE scores SET title = 'Renamed' WHERE id = %s", (sid,))
    v2 = client.get(url, headers=headers).get_json()["data"]["version"]
    assert v2 != v1  # displayed non-file fields change it, so ?version= cannot return a stale title
    with db.transaction() as conn:
        conn.execute("UPDATE scores SET arranger = 'A', tempo_bpm = tempo_bpm + 1 WHERE id = %s", (sid,))
    v3 = client.get(url, headers=headers).get_json()["data"]["version"]
    assert v3 not in (v1, v2)
    assert client.get(f"{url}?version={v2}", headers=headers).get_json()["data"].get("unchanged") is None
    with db.transaction() as conn:
        conn.execute("UPDATE audio_tracks SET file_key = 'audio/vnew.mp3' WHERE score_id = %s AND voice = 'alto'", (sid,))
    assert client.get(url, headers=headers).get_json()["data"]["version"] != v3


def test_result_unchanged_skips_storage_work(
    client: FlaskClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sid, _ = _score(_uid(), tag="u")
    url = f"/api/scores/{sid}/result"
    version = client.get(url, headers=headers).get_json()["data"]["version"]
    storage = _storage(client.application)

    def boom(*a: Any, **k: Any) -> Any:
        raise AssertionError("storage touched")

    monkeypatch.setattr(storage, "size", boom)
    monkeypatch.setattr(storage, "signed_url", boom)
    res = client.get(f"{url}?version={version}&touch=false", headers=headers)
    assert res.status_code == 200 and res.get_json()["data"] == {"unchanged": True, "version": version}


def test_result_stale_version_returns_full_payload(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, _ = _score(_uid())
    data = client.get(f"/api/scores/{sid}/result?version=stale", headers=headers).get_json()["data"]
    assert "unchanged" not in data and "audioFiles" in data and data["version"] != "stale"


def test_result_unchanged_other_user_404(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, _ = _score(_uid())
    version = client.get(f"/api/scores/{sid}/result", headers=headers).get_json()["data"]["version"]
    other = _signup(client, "b@example.com")
    _err(client.get(f"/api/scores/{sid}/result?version={version}", headers=other), 404, "score_not_found")


def test_result_lists_file_ids_sizes_and_midi(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, _ = _score(_uid(), tag="m", midi=True)
    storage = _storage(client.application)
    keys = ["timing/m.json", "pages/m0.jpg", "pages/m1.jpg",
            *(f"audio/m{v}.mp3" for v in VOICES), *(f"midi/m{v}.mid" for v in VOICES)]
    for i, k in enumerate(keys):
        storage.put(k, b"x" * (i + 1), "x")
    data = client.get(f"/api/scores/{sid}/result", headers=headers).get_json()["data"]

    def entry(k: str) -> dict[str, Any]:
        return {"url": f"https://storage.test/{k}?sig=fake", "fileId": k, "sizeBytes": keys.index(k) + 1}

    assert data["audioFiles"] == {v: entry(f"audio/m{v}.mp3") for v in VOICES}
    assert data["midiTracks"] == {v: entry(f"midi/m{v}.mid") for v in VOICES}
    assert data["pageFiles"] == [entry("pages/m0.jpg"), entry("pages/m1.jpg")]
    assert data["timingFile"] == entry("timing/m.json")
    assert data["audioTracks"]["alto"] == entry("audio/malto.mp3")["url"]  # old fields unchanged


def test_result_size_failure_gives_null_size_not_500(
    client: FlaskClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sid, _ = _score(_uid(), tag="f")

    def boom(key: str) -> int:
        raise RuntimeError("down")

    monkeypatch.setattr(_storage(client.application), "size", boom)
    res = client.get(f"/api/scores/{sid}/result", headers=headers)
    assert res.status_code == 200
    alto = res.get_json()["data"]["audioFiles"]["alto"]
    assert alto["sizeBytes"] is None and alto["fileId"] == "audio/falto.mp3" and alto["url"]


def test_result_partial_midi_lists_only_voices_with_midi(
    client: FlaskClient, headers: dict[str, str]
) -> None:
    sid, _ = _score(_uid(), tag="p", midi=True)
    with db.transaction() as conn:
        conn.execute("UPDATE audio_tracks SET midi_key = NULL WHERE score_id = %s AND voice IN ('tenor', 'bass')", (sid,))
    data = client.get(f"/api/scores/{sid}/result", headers=headers).get_json()["data"]
    assert set(data["midiTracks"]) == {"soprano", "alto"}


def test_result_old_score_without_midi_has_null_midi_tracks(
    client: FlaskClient, headers: dict[str, str]
) -> None:
    sid, _ = _score(_uid())
    data = client.get(f"/api/scores/{sid}/result", headers=headers).get_json()["data"]
    assert data["midiTracks"] is None and set(data["audioFiles"]) == set(VOICES)


def test_result_midi_combined_entry_and_null_for_old_score(client: FlaskClient, headers: dict[str, str]) -> None:
    old, _ = _score(_uid(), tag="o")
    data = client.get(f"/api/scores/{old}/result", headers=headers).get_json()["data"]
    assert data["midiCombined"] is None
    sid, _ = _score(_uid(), tag="c", midi=True)
    with db.transaction() as conn:
        conn.execute("UPDATE scores SET midi_combined_key = 'midi/comb.mid' WHERE id = %s", (sid,))
    _storage(client.application).put("midi/comb.mid", b"abc", "audio/midi")
    data = client.get(f"/api/scores/{sid}/result", headers=headers).get_json()["data"]
    assert data["midiCombined"] == {"url": "https://storage.test/midi/comb.mid?sig=fake", "fileId": "midi/comb.mid",
                                    "sizeBytes": 3}


def test_purge_deleted_score_queues_combined_midi(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, _ = _score(_uid(), tag="d", midi=True)
    with db.transaction() as conn:
        conn.execute("UPDATE scores SET midi_combined_key = 'midi/dcomb.mid', deleted_at = now() - interval '8 days' "
                     "WHERE id = %s", (sid,))
        assert background.purge_deleted_scores(conn) == 1
        queued = {r["object_key"] for r in conn.execute("SELECT object_key FROM storage_deletions")}
    assert "midi/dcomb.mid" in queued  # FR-12: the blob is not orphaned


def test_result_failed_voice_has_no_track(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, _ = _score(_uid(), failed=("tenor",))
    data = client.get(f"/api/scores/{sid}/result", headers=headers).get_json()["data"]
    assert set(data["audioTracks"]) == {"soprano", "alto", "bass"}
    assert data["failedVoices"] == ["tenor"]


def test_result_other_user_404(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, _ = _score(_uid())
    other = _signup(client, "b@example.com")
    _err(client.get(f"/api/scores/{sid}/result", headers=other), 404, "score_not_found")


def test_result_survives_touch_failure(
    client: FlaskClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import psycopg

    from backend import routes_scores

    sid, _ = _score(_uid())
    real = routes_scores.db
    calls = {"n": 0}

    def flaky(*a: Any, **k: Any) -> Any:
        calls["n"] += 1
        if calls["n"] > 1:  # the read transaction passes, the touch fails
            raise psycopg.OperationalError("boom")
        return real.transaction(*a, **k)

    # Patch only the route module's reference; auth uses the real db module.
    monkeypatch.setattr(routes_scores, "db", types.SimpleNamespace(transaction=flaky))
    assert client.get(f"/api/scores/{sid}/result", headers=headers).status_code == 200


def test_patch_title_and_clear_arranger(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, jid = _score(_uid())
    body = {"title": "  New  ", "arranger": None}
    res = client.patch(f"/api/scores/{sid}", json=body, headers=headers)
    assert res.status_code == 200 and res.get_json()["message"] == "Score updated"
    data = res.get_json()["data"]
    assert data["title"] == "New" and "arranger" not in data and "lastAccessedAt" not in data
    with db.transaction() as conn:
        job = conn.execute("SELECT title, arranger FROM jobs WHERE id = %s", (jid,)).fetchone()
    assert (job["title"], job["arranger"]) == ("New", None)
    res = client.patch(f"/api/scores/{sid}", json={"arranger": "Zed"}, headers=headers)
    assert res.get_json()["data"]["title"] == "New" and res.get_json()["data"]["arranger"] == "Zed"


def test_patch_errors(client: FlaskClient, headers: dict[str, str]) -> None:
    uid = _uid()
    sid, jid = _score(uid)
    path = f"/api/scores/{sid}"
    _err(client.patch(path, json={"title": "  "}, headers=headers), 400, "title_required")
    _err(client.patch(path, json={"title": None}, headers=headers), 400, "title_required")
    long = client.patch(path, json={"arranger": "x" * 121}, headers=headers)
    _err(long, 400, "arranger_too_long")
    _err(client.patch(path, json={"title": 5}, headers=headers), 400, "title_invalid")
    _err(client.patch(path, data="[]", content_type="application/json", headers=headers),
         400, "invalid_json")
    other = _signup(client, "b@example.com")
    _err(client.patch(path, json={"title": "Hax"}, headers=other), 404, "score_not_found")
    _retake(uid, jid)
    _err(client.patch(path, json={"title": "Late"}, headers=headers), 409, "retake_in_progress")
    with db.transaction() as conn:
        row = conn.execute("SELECT title FROM scores WHERE id = %s", (sid,)).fetchone()
    assert row["title"] == "Bayan Ko"


def test_delete_hides_but_keeps_data(
    client: FlaskClient, app: Flask, headers: dict[str, str]
) -> None:
    sid, jid = _score(_uid(), tag="d", midi=True)
    keep, _ = _score(_uid(), "Keep", tag="k")
    res = client.delete(f"/api/scores/{sid}", headers=headers)
    assert res.status_code == 200 and res.get_json()["message"] == "Score deleted"
    listed = client.get("/api/scores", headers=headers).get_json()["data"]["scores"]
    assert [s["scoreId"] for s in listed] == [keep]
    _err(client.get(f"/api/scores/{sid}/result", headers=headers), 404, "score_not_found")
    with db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM storage_deletions").fetchone()["n"] == 0
        assert conn.execute("SELECT 1 FROM jobs WHERE id = %s", (jid,)).fetchone() is not None


def test_delete_other_user_404(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, _ = _score(_uid())
    other = _signup(client, "b@example.com")
    _err(client.delete(f"/api/scores/{sid}", headers=other), 404, "score_not_found")
    assert len(client.get("/api/scores", headers=headers).get_json()["data"]["scores"]) == 1


def test_delete_cancels_running_retake(client: FlaskClient, headers: dict[str, str]) -> None:
    uid = _uid()
    sid, jid = _score(uid, tag="d")
    rid = _retake(uid, jid, "transcribing")
    assert client.delete(f"/api/scores/{sid}", headers=headers).status_code == 200
    with db.transaction() as conn:
        status = conn.execute("SELECT status FROM jobs WHERE id = %s", (rid,)).fetchone()["status"]
        queued = {r["object_key"] for r in conn.execute("SELECT object_key FROM storage_deletions")}
    assert status == "cancelled" and not queued  # its pages are queued by the day-7 purge


def test_result_filters_old_review_rows_on_read(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, _ = _score(_uid())
    old = {"reviewNeeded": True, "reasons": ["voice_unreadable", "meter_change"], "truncated": False,
           "items": [{"code": "meter_change", "bar": 2}, {"code": "voice_unreadable", "voice": "alto"}]}
    with db.transaction() as conn:
        conn.execute("UPDATE scores SET review = %s WHERE id = %s", (Jsonb(old), sid))
    review = client.get(f"/api/scores/{sid}/result", headers=headers).get_json()["data"]["review"]
    assert review == {"reviewNeeded": True, "reasons": ["voice_unreadable"], "truncated": False,
                      "items": [{"code": "voice_unreadable", "voice": "alto"}]}
    old["reasons"], old["items"] = ["meter_change"], [{"code": "meter_change"}]
    with db.transaction() as conn:
        conn.execute("UPDATE scores SET review = %s WHERE id = %s", (Jsonb(old), sid))
    review = client.get(f"/api/scores/{sid}/result", headers=headers).get_json()["data"]["review"]
    assert review["reviewNeeded"] is False and review["items"] == []


def test_client_review_codes_match_stage5() -> None:
    """The API venv cannot import stage5 (cv2/torch), so read the constant from source."""
    import ast
    from pathlib import Path

    from backend.routes_scores import CLIENT_REVIEW_CODES

    tree = ast.parse((Path(__file__).resolve().parents[2] / "stage5_synthesis.py").read_text(encoding="utf-8"))
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(target, ast.Name) and target.id == "CLIENT_REVIEW_CODES" and node.value is not None:
            assert CLIENT_REVIEW_CODES == frozenset(ast.literal_eval(node.value.args[0]))
            return
    raise AssertionError("CLIENT_REVIEW_CODES not found in stage5_synthesis.py")


def test_result_midi_only_score_has_empty_audio_and_midi_tracks(client: FlaskClient, headers: dict[str, str]) -> None:
    sid, _ = _score(_uid(), tag="n", midi=True)
    with db.transaction() as conn:
        conn.execute("UPDATE audio_tracks SET file_key = NULL WHERE score_id = %s", (sid,))
    data = client.get(f"/api/scores/{sid}/result", headers=headers).get_json()["data"]
    assert data["audioTracks"] == {} and data["audioFiles"] == {}
    assert set(data["midiTracks"]) == set(VOICES)
