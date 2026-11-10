"""Live contract smoke test: python -m backend.scripts.smoke <base_url>

Walks the whole app-facing flow against a running API and asserts the shapes the Flutter client
parses. stdlib only, so it runs anywhere without the backend's dependencies. Creates a throwaway
account and deletes it at the end. Exit code 1 if any step fails.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from typing import Any

TIMEOUT_S = 120  # Render free cold start can take a minute or more
JOB_REF = re.compile(r"^job_[0-9]+$")
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
MAX_CAP_PROBES = 6  # server default cap is 2; stop well past it
PASSWORD = "smoke-pass-1"
NEW_PASSWORD = "smoke-pass-2"
# 240x160 grayscale staff-line JPEG (a real image: the server decodes and re-encodes it).
JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABQODxIPDRQSEBIXFRQYHjIhHhwcHj0sLiQySUBM"
    "S0dARkVQWnNiUFVtVkVGZIhlbXd7gYKBTmCNl4x9lnN+gXz/wAALCACgAPABAREA/8QAHwAA"
    "AQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQR"
    "BRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RF"
    "RkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ip"
    "qrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oACAEB"
    "AAA/AOzooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooo"
    "oooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooo"
    "oooooooooooooqrNptjcSmWezt5ZG6s8Skn8SKZ/Y+mf9A60/wC/C/4Uf2Ppn/QOtP8Avwv+"
    "FH9j6Z/0DrT/AL8L/hR/Y+mf9A60/wC/C/4Uf2Ppn/QOtP8Avwv+FH9j6Z/0DrT/AL8L/hR/"
    "Y+mf9A60/wC/C/4Uf2Ppn/QOtP8Avwv+FH9j6Z/0DrT/AL8L/hR/Y+mf9A60/wC/C/4Uf2Pp"
    "n/QOtP8Avwv+FH9j6Z/0DrT/AL8L/hR/Y+mf9A60/wC/C/4Uf2Ppn/QOtP8Avwv+FH9j6Z/0"
    "DrT/AL8L/hR/Y+mf9A60/wC/C/4Uf2Ppn/QOtP8Avwv+FH9j6Z/0DrT/AL8L/hR/Y+mf9A60"
    "/wC/C/4Uf2Ppn/QOtP8Avwv+FH9j6Z/0DrT/AL8L/hR/Y+mf9A60/wC/C/4Uf2Ppn/QOtP8A"
    "vwv+FH9j6Z/0DrT/AL8L/hR/Y+mf9A60/wC/C/4Uf2Ppn/QOtP8Avwv+FOTStPjdXjsLVXUg"
    "qywqCD6jirdFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFVZtNsbiUyz2dvLI3VniUk/iRTP7H0z"
    "/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fh"
    "f8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z"
    "/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fh"
    "f8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z"
    "/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fh"
    "f8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fhf8KP7H0z/oHWn/fhf8KcmlafG6vHYWqupBVlhUEH"
    "1HFW6KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKqzabY3Eplns7eWRurPEpJ/Eimf2Ppn/QOtP+"
    "/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2P"
    "pn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+"
    "/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2P"
    "pn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+"
    "/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2P"
    "pn/QOtP+/C/4Uf2Ppn/QOtP+/C/4Uf2Ppn/QOtP+/C/4U5NK0+N1eOwtVdSCrLCoIPqOKt0U"
    "UUUUUUUUUUUUUUUUUUUUUUUUUUUUUVVm02xuJTLPZ28sjdWeJST+JFM/sfTP+gdaf9+F/wAK"
    "P7H0z/oHWn/fhf8ACj+x9M/6B1p/34X/AAo/sfTP+gdaf9+F/wAKP7H0z/oHWn/fhf8ACj+x"
    "9M/6B1p/34X/AAo/sfTP+gdaf9+F/wAKP7H0z/oHWn/fhf8ACj+x9M/6B1p/34X/AAo/sfTP"
    "+gdaf9+F/wAKP7H0z/oHWn/fhf8ACj+x9M/6B1p/34X/AAo/sfTP+gdaf9+F/wAKP7H0z/oH"
    "Wn/fhf8ACj+x9M/6B1p/34X/AAo/sfTP+gdaf9+F/wAKP7H0z/oHWn/fhf8ACj+x9M/6B1p/"
    "34X/AAo/sfTP+gdaf9+F/wAKP7H0z/oHWn/fhf8ACj+x9M/6B1p/34X/AAo/sfTP+gdaf9+F"
    "/wAKP7H0z/oHWn/fhf8ACj+x9M/6B1p/34X/AAo/sfTP+gdaf9+F/wAKP7H0z/oHWn/fhf8A"
    "CnJpWnxurx2FqrqQVZYVBB9RxVuiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiqs2m2NxKZZ7O3l"
    "kbqzxKSfxIpn9j6Z/wBA60/78L/hR/Y+mf8AQOtP+/C/4Uf2Ppn/AEDrT/vwv+FH9j6Z/wBA"
    "60/78L/hR/Y+mf8AQOtP+/C/4Uf2Ppn/AEDrT/vwv+FH9j6Z/wBA60/78L/hR/Y+mf8AQOtP"
    "+/C/4Uf2Ppn/AEDrT/vwv+FH9j6Z/wBA60/78L/hR/Y+mf8AQOtP+/C/4Uf2Ppn/AEDrT/vw"
    "v+FH9j6Z/wBA60/78L/hR/Y+mf8AQOtP+/C/4Uf2Ppn/AEDrT/vwv+FH9j6Z/wBA60/78L/h"
    "R/Y+mf8AQOtP+/C/4Uf2Ppn/AEDrT/vwv+FH9j6Z/wBA60/78L/hR/Y+mf8AQOtP+/C/4Uf2"
    "Ppn/AEDrT/vwv+FH9j6Z/wBA60/78L/hR/Y+mf8AQOtP+/C/4Uf2Ppn/AEDrT/vwv+FH9j6Z"
    "/wBA60/78L/hR/Y+mf8AQOtP+/C/4U5NK0+N1eOwtVdSCrLCoIPqOKt0UUUUUUUUUUUUUUUU"
    "UUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUU"
    "UUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUU"
    "UUUUUUUUUUUUUUUUUUUV/9k="
)


class Reply:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status = status
        self.body = body


def call(
    base: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    json_body: dict[str, Any] | None = None,
    data: bytes | None = None,
    content_type: str | None = None,
) -> Reply:
    headers: dict[str, str] = {"User-Agent": "piyanota-smoke/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        data, content_type = json.dumps(json_body).encode(), "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return Reply(response.status, json.loads(response.read()))
    except urllib.error.HTTPError as exc:
        return Reply(exc.code, json.loads(exc.read()))


def multipart(fields: dict[str, str], jpeg: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, v in fields.items()
    ]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="pages"; filename="p.jpg"\r\n'
        "Content-Type: image/jpeg\r\n\r\n".encode() + jpeg + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def check(condition: bool, what: str) -> None:
    if not condition:
        raise AssertionError(what)


def envelope(reply: Reply, status: int) -> dict[str, Any]:
    check(reply.status == status, f"HTTP {reply.status}, expected {status}: {reply.body}")
    check(reply.body.get("success") is True, f"success is not true: {reply.body}")
    check(reply.body.get("status") == status, f"body status != {status}")
    check(isinstance(reply.body.get("message"), str), "message is not a string")
    return reply.body.get("data") or {}


def error(reply: Reply, status: int, code: str) -> None:
    check(reply.status == status, f"HTTP {reply.status}, expected {status}: {reply.body}")
    check(reply.body.get("success") is False, "success is not false")
    check(reply.body.get("error", {}).get("code") == code, f"error code != {code}: {reply.body}")


def run(base: str, check_cap: bool = False) -> int:
    email = f"smoke-{uuid.uuid4().hex[:12]}@example.com"
    state: dict[str, Any] = {"password": PASSWORD}

    def signup() -> None:
        data = envelope(call(base, "POST", "/api/auth/signup", json_body={
            "email": email, "password": PASSWORD, "passwordConfirmation": PASSWORD}), 201)
        check(isinstance(data["userId"], int), "userId is not an int")
        check(isinstance(data["sessionToken"], str) and data["sessionToken"], "no sessionToken")
        check(ISO_Z.match(data["expiresAt"]) is not None, f"expiresAt not Z: {data['expiresAt']}")
        state["token"] = data["sessionToken"]

    def account() -> None:
        data = envelope(call(base, "GET", "/api/account", token=state["token"]), 200)
        check(data["email"] == email, "account email mismatch")
        check(ISO_Z.match(data["accountCreatedAt"]) is not None, "accountCreatedAt not Z")

    def login() -> None:
        data = envelope(call(base, "POST", "/api/auth/login", json_body={
            "email": email, "password": PASSWORD}), 200)
        check(isinstance(data["userId"], int), "userId is not an int")
        state["token"] = data["sessionToken"]

    def submit() -> None:
        body, ctype = multipart({"title": "Smoke test"}, base64.b64decode(JPEG_B64))
        data = envelope(call(base, "POST", "/api/jobs", token=state["token"],
                             data=body, content_type=ctype), 202)
        check(JOB_REF.match(data["jobId"]) is not None, f"jobId not job_<n>: {data['jobId']}")
        check(isinstance(data["userId"], int), "userId is not an int")
        check(data["status"] == "queued", f"status {data['status']}")
        check(ISO_Z.match(data["submittedAt"]) is not None, "submittedAt not Z")
        state["job"] = data["jobId"]

    def status() -> None:
        data = envelope(call(base, "GET", f"/api/jobs/{state['job']}", token=state["token"]), 200)
        check(data["jobId"] == state["job"], "jobId mismatch")
        check(data["status"] == "queued", f"status {data['status']}")
        check(data["totalPages"] == 1, f"totalPages {data['totalPages']}")
        check(isinstance(data["percentComplete"], int), "percentComplete is not an int")

    def job_list() -> None:
        data = envelope(call(base, "GET", "/api/jobs", token=state["token"]), 200)
        check(any(j["jobId"] == state["job"] for j in data["jobs"]), "submitted job not in list")

    def cancel() -> None:
        data = envelope(call(base, "POST", f"/api/jobs/{state['job']}/cancel",
                             token=state["token"]), 200)
        check(data == {"jobId": state["job"], "status": "cancelled"}, f"cancel data {data}")

    def cancel_submission() -> None:
        csid = str(uuid.uuid4())
        data = envelope(call(base, "POST", f"/api/jobs/by-submission/{csid}/cancel", token=state["token"]), 200)
        check(data == {"clientSubmissionId": csid, "jobId": None, "status": "cancelled"}, f"cancel data {data}")
        body, ctype = multipart({"title": "Smoke test", "clientSubmissionId": csid}, base64.b64decode(JPEG_B64))
        error(call(base, "POST", "/api/jobs", token=state["token"], data=body, content_type=ctype),
              409, "submission_cancelled")

    def active_cap() -> None:
        """Opt-in (--check-active-cap): queues up to MAX_CAP_PROBES real jobs, always cancels them."""
        made: list[str] = []
        try:
            for _ in range(MAX_CAP_PROBES):
                body, ctype = multipart({"title": "Smoke cap"}, base64.b64decode(JPEG_B64))
                reply = call(base, "POST", "/api/jobs", token=state["token"], data=body, content_type=ctype)
                if reply.status == 429:
                    error(reply, 429, "too_many_active_jobs")
                    return
                made.append(envelope(reply, 202)["jobId"])
            raise AssertionError(f"no too_many_active_jobs after {MAX_CAP_PROBES} submits")
        finally:
            for ref in made:
                call(base, "POST", f"/api/jobs/{ref}/cancel", token=state["token"])

    def library() -> None:
        data = envelope(call(base, "GET", "/api/scores", token=state["token"]), 200)
        check(isinstance(data["scores"], list), "scores is not a list")
        for score in data["scores"]:
            check(isinstance(score["scoreId"], int), "scoreId is not an int")
            check(ISO_Z.match(score["lastProcessedAt"]) is not None, "lastProcessedAt not Z")

    def change_password() -> None:
        envelope(call(base, "POST", "/api/auth/change-password", token=state["token"], json_body={
            "currentPassword": PASSWORD, "newPassword": NEW_PASSWORD}), 200)
        state["password"] = NEW_PASSWORD  # later steps fall back to the old one if this failed

    def logout() -> None:
        envelope(call(base, "POST", "/api/auth/logout", token=state["token"]), 200)
        error(call(base, "GET", "/api/account", token=state["token"]), 401, "unauthorized")

    def delete_account() -> None:
        data = envelope(call(base, "POST", "/api/auth/login", json_body={
            "email": email, "password": state["password"]}), 200)
        token = data["sessionToken"]
        error(call(base, "DELETE", "/api/account", token=token, json_body={"password": "wrong-pass-1"}),
              403, "invalid_current_password")
        envelope(call(base, "DELETE", "/api/account", token=token, json_body={
            "password": state["password"]}), 200)
        error(call(base, "POST", "/api/auth/login", json_body={
            "email": email, "password": state["password"]}), 401, "invalid_credentials")

    steps: list[tuple[str, Callable[[], None]]] = [
        ("signup", signup), ("account", account), ("login", login), ("submit", submit),
        ("status", status), ("job_list", job_list), ("cancel", cancel),
        ("cancel submission", cancel_submission), ("library", library),
        ("change password", change_password), ("logout", logout), ("delete account", delete_account),
    ]
    if check_cap:
        steps.insert(steps.index(("library", library)), ("active cap", active_cap))
    failed = 0
    for name, step in steps:
        try:
            step()
            print(f"PASS {name}")
        except (AssertionError, KeyError, TypeError, urllib.error.URLError, ValueError) as exc:
            failed += 1
            print(f"FAIL {name}: {exc!r}")
            if name in ("signup", "login"):  # later steps need the token
                break
    return 1 if failed else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--check-active-cap"]
    if len(args) != 1:
        raise SystemExit("usage: python -m backend.scripts.smoke <base_url> [--check-active-cap]")
    sys.exit(run(args[0].rstrip("/"), "--check-active-cap" in sys.argv))
