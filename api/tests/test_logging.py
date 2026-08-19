"""Tests for the JSON log formatter."""

import json
import logging

from meetingiq.observability.logging import JsonFormatter


def _format(record: logging.LogRecord) -> dict:
    return json.loads(JsonFormatter().format(record))


def _record(**kwargs) -> logging.LogRecord:
    record = logging.LogRecord(
        name="meetingiq.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=kwargs.pop("msg", "hello"),
        args=kwargs.pop("args", None),
        exc_info=kwargs.pop("exc_info", None),
    )
    for key, value in kwargs.items():
        setattr(record, key, value)
    return record


def test_emits_the_core_fields():
    payload = _format(_record())

    assert payload["level"] == "INFO"
    assert payload["logger"] == "meetingiq.test"
    assert payload["message"] == "hello"
    assert payload["ts"].endswith("+00:00")


def test_interpolates_message_args():
    payload = _format(_record(msg="retrieved %d chunks", args=(7,)))

    assert payload["message"] == "retrieved 7 chunks"


def test_promotes_extras_to_top_level_fields():
    """`extra=` is how call sites attach structured context; it must survive."""
    payload = _format(_record(meeting_id="m-1", latency_ms=42))

    assert payload["meeting_id"] == "m-1"
    assert payload["latency_ms"] == 42


def test_includes_exception_text():
    try:
        raise ValueError("nope")
    except ValueError:
        import sys

        payload = _format(_record(exc_info=sys.exc_info()))

    assert "ValueError: nope" in payload["exception"]


def test_output_is_a_single_line():
    """Multi-line records would break line-oriented log shippers."""
    payload = JsonFormatter().format(_record(msg="line one\nline two"))

    assert "\n" not in payload


def test_drops_uvicorns_ansi_duplicate_message():
    """uvicorn attaches `color_message`; escape codes do not belong in JSON logs."""
    payload = _format(_record(color_message="Started server process [\x1b[36m%d\x1b[0m]"))

    assert "color_message" not in payload
