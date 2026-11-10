"""Map the worker's free-text ``jobs.failure_reason`` to the stable codes the app parses.

One place owns the contract (app enum: lib/models/processing_status.dart ``FailureReason``). The worker keeps
writing human-readable text; the API reports the code in ``failureReason`` and the raw text in ``failureDetail``.
Text this table does not know passes through unchanged, which the app reads as ``unknown`` (generic copy).
"""

from __future__ import annotations

# Keys are the exact strings written by backend/worker/pipeline.py, worker/main.py, worker/queue.py.
_CODES: dict[str, str] = {
    "no readable page": "preprocessing_error",
    "unreadable page image": "preprocessing_error",
    "could not encode the cleaned page": "preprocessing_error",
    "could not encode the display page": "preprocessing_error",
    "no readable staves": "no_staff_detected",
    # Input-caused (bad photo); the app has no transcription code and a retake is the only remedy.
    "could not read the notation": "no_staff_detected",
    "no readable staves, please retake clearer photos of your pages": "incomplete_voice_sequence",
    "audio rendering failed": "synthesis_failed",
    "no playable audio could be built": "synthesis_failed",
    "max_runtime_exceeded": "stage_timeout",
    "worker_timeout": "server_restart",  # heartbeat died: the worker was killed or restarted
    "service misconfigured": "internal_error",
    "conversion failed": "internal_error",
    "no pages": "internal_error",
}


def failure_code(reason: str | None) -> str | None:
    """The app-facing code for a stored reason; unrecognised text is returned as is."""
    return None if reason is None else _CODES.get(reason, reason)
