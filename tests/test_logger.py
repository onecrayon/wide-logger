"""Unit tests for wide_logger/logger.py"""

import json
import logging
import os
from base64 import b64encode
from datetime import datetime, timezone

from wide_logger import WideLogger, WideLoggerHandlerFilter
from wide_logger.logger import (
    context_dict_from_extra,
    json_dump_fallback,
    wide_logger_for_stack,
)

from .conftest import CapturingHandler


def make_record(
    name="test.logger",
    level=logging.INFO,
    pathname=None,
    lineno=42,
    msg="test message",
    exc_info=None,
    **extra,
) -> logging.LogRecord:
    """Factory for creating LogRecord instances in tests.

    Extra kwargs are set directly in the record's __dict__ to simulate the `extra=` logging kwarg.
    """
    if pathname is None:
        import os

        pathname = os.path.abspath(__file__)
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname=pathname,
        lineno=lineno,
        msg=msg,
        args=None,
        exc_info=exc_info,
    )
    for key, value in extra.items():
        record.__dict__[key] = value
    return record


# ---------------------------------------------------------------------------
# context_dict_from_extra
# ---------------------------------------------------------------------------


def test_context_dict_empty_record_returns_empty_dict():
    record = make_record()
    assert context_dict_from_extra(record) == {}


def test_context_dict_extra_keys_are_returned():
    record = make_record(user_id=123, action="click")
    result = context_dict_from_extra(record)
    assert result == {"user_id": 123, "action": "click"}


# ---------------------------------------------------------------------------
# json_dump_fallback
# ---------------------------------------------------------------------------


def test_json_dump_fallback_datetime_returns_isoformat():
    dt = datetime(2026, 4, 14, 12, 30, 0, tzinfo=timezone.utc)
    assert json_dump_fallback(dt) == "2026-04-14T12:30:00+00:00"


def test_json_dump_fallback_datetime_without_tz():
    dt = datetime(2026, 4, 14, 12, 30, 0)
    assert json_dump_fallback(dt) == "2026-04-14T12:30:00"


def test_json_dump_fallback_valid_utf8_bytes_returns_decoded_string():
    assert json_dump_fallback(b"ASCII approved") == "ASCII approved"


def test_json_dump_fallback_empty_bytes_returns_empty_string():
    assert json_dump_fallback(b"") == ""


def test_json_dump_fallback_invalid_utf8_bytes_returns_base64():
    raw = b"\xff\xfe"
    assert json_dump_fallback(raw) == b64encode(raw).decode()


def test_json_dump_fallback_arbitrary_object_returns_repr():
    class Unserializable:
        def __repr__(self):
            return "Unserializable()"

    assert json_dump_fallback(Unserializable()) == "Unserializable()"


# ---------------------------------------------------------------------------
# WideLogger.__init__
# ---------------------------------------------------------------------------


def test_wide_logger_init_entrypoint_stored():
    wl = WideLogger("my.module.func")
    assert wl.entrypoint == "my.module.func"


def test_wide_logger_init_started_at_is_utc_datetime():
    before = datetime.now(tz=timezone.utc)
    wl = WideLogger("test")
    after = datetime.now(tz=timezone.utc)
    assert before <= wl.started_at <= after
    assert wl.started_at.tzinfo == timezone.utc


def test_wide_logger_init_default_context_is_empty():
    assert WideLogger("test").context == {}


def test_wide_logger_init_passed_context_is_stored():
    ctx = {"source": "worker", "env": "prod"}
    assert WideLogger("test", context=ctx).context == ctx


def test_wide_logger_init_events_is_empty_list():
    assert WideLogger("test").events == []


def test_wide_logger_init_max_log_level_starts_at_notset():
    assert WideLogger("test")._max_log_level == logging.NOTSET


def test_wide_logger_init_highest_log_name_starts_as_none():
    assert WideLogger("test")._highest_log_name is None


# ---------------------------------------------------------------------------
# WideLogger.log_record — event structure
# ---------------------------------------------------------------------------


def test_log_record_event_has_required_keys():
    wl = WideLogger("test")
    wl.log_record(make_record(level=logging.INFO, msg="hello", lineno=10))
    event = wl.events[0]
    assert "level" in event
    assert event["level"] == "INFO"
    assert "msg" in event
    assert event["msg"] == "hello"
    assert "at" in event
    assert "from" in event


def test_log_record_event_at_is_utc_datetime():
    wl = WideLogger("test")
    wl.log_record(make_record())
    at = wl.events[0]["at"]
    assert isinstance(at, datetime)
    assert at.tzinfo == timezone.utc


def test_log_record_event_from_is_relative_path_with_lineno():
    wl = WideLogger("test")
    abs_path = os.path.abspath(__file__)
    wl.log_record(make_record(pathname=abs_path, lineno=77))
    root_dir = os.getcwd()
    assert wl.events[0]["from"] == f"{os.path.relpath(abs_path, root_dir)}#77"


def test_log_record_multiple_events_appended_in_order():
    wl = WideLogger("test")
    wl.log_record(make_record(msg="first"))
    wl.log_record(make_record(msg="second"))
    assert len(wl.events) == 2
    assert wl.events[0]["msg"] == "first"
    assert wl.events[1]["msg"] == "second"


# ---------------------------------------------------------------------------
# WideLogger.log_record — level tracking
# ---------------------------------------------------------------------------


def test_log_record_max_level_updated_on_first_record():
    wl = WideLogger("test")
    wl.log_record(make_record(level=logging.INFO))
    assert wl._max_log_level == logging.INFO


def test_log_record_higher_level_replaces_max():
    wl = WideLogger("test")
    wl.log_record(make_record(level=logging.INFO))
    wl.log_record(make_record(level=logging.ERROR))
    assert wl._max_log_level == logging.ERROR


def test_log_record_lower_level_does_not_replace_max():
    wl = WideLogger("test")
    wl.log_record(make_record(level=logging.ERROR))
    wl.log_record(make_record(level=logging.DEBUG))
    assert wl._max_log_level == logging.ERROR


# ---------------------------------------------------------------------------
# WideLogger.log_record — highest_log_name tracking
# ---------------------------------------------------------------------------


def test_log_record_first_non_root_record_sets_log_name():
    wl = WideLogger("test")
    wl.log_record(make_record(name="app.module"))
    assert wl._highest_log_name == "app.module"


def test_log_record_root_logger_sets_name_to_empty_string():
    wl = WideLogger("test")
    wl.log_record(make_record(name="root"))
    assert wl._highest_log_name == ""


def test_log_record_shorter_name_replaces_longer():
    wl = WideLogger("test")
    wl.log_record(make_record(name="app.module"))  # 1 dot
    wl.log_record(make_record(name="app"))  # 0 dots
    assert wl._highest_log_name == "app"


def test_log_record_longer_name_does_not_replace_shorter():
    wl = WideLogger("test")
    wl.log_record(make_record(name="app.module"))  # 1 dot
    wl.log_record(make_record(name="app.module.sub"))  # 2 dots
    assert wl._highest_log_name == "app.module"


def test_log_record_same_depth_name_does_not_replace():
    wl = WideLogger("test")
    wl.log_record(make_record(name="app"))
    wl.log_record(make_record(name="other"))
    assert wl._highest_log_name == "app"


def test_log_record_name_not_tracked_when_output_logger_set():
    wl = WideLogger("test", output_logger="explicit.logger")
    wl.log_record(make_record(name="app.module"))
    assert wl._highest_log_name is None


# ---------------------------------------------------------------------------
# WideLogger.log_record — exception handling
# ---------------------------------------------------------------------------


def test_log_record_no_exc_info_produces_no_traceback_key():
    wl = WideLogger("test")
    wl.log_record(make_record())
    assert "traceback" not in wl.events[0]


def test_log_record_exc_info_as_tuple():
    wl = WideLogger("test")
    try:
        raise ValueError("tuple case")
    except ValueError as e:
        wl.log_record(make_record(exc_info=(type(e), e, e.__traceback__)))
    assert "traceback" in wl.events[0]
    assert "ValueError" in wl.events[0]["traceback"]
    assert "tuple case" in wl.events[0]["traceback"]


def test_log_record_exc_info_as_exception_instance():
    wl = WideLogger("test")
    exc = RuntimeError("instance case")
    wl.log_record(make_record(exc_info=exc))
    assert "traceback" in wl.events[0]
    assert "RuntimeError" in wl.events[0]["traceback"]
    assert "instance case" in wl.events[0]["traceback"]


def test_log_record_exc_info_true_captures_active_exception():
    wl = WideLogger("test")
    try:
        raise TypeError("active exception")
    except TypeError:
        wl.log_record(make_record(exc_info=True))
    assert "traceback" in wl.events[0]
    assert "TypeError" in wl.events[0]["traceback"]
    assert "active exception" in wl.events[0]["traceback"]


def test_log_record_exc_info_tuple_with_none_produces_no_traceback():
    wl = WideLogger("test")
    wl.log_record(make_record(exc_info=(None, None, None)))
    assert "traceback" not in wl.events[0]


# ---------------------------------------------------------------------------
# WideLogger.log_record — context with use_root_context=True (default)
# ---------------------------------------------------------------------------


def test_log_record_new_context_key_promoted_to_root():
    wl = WideLogger("test", use_root_context=True)
    wl.log_record(make_record(user_id=42))
    assert wl.context == {"user_id": 42}
    assert "context" not in wl.events[0]


def test_log_record_duplicate_context_key_same_value_stays_in_root_only():
    wl = WideLogger("test", use_root_context=True)
    wl.log_record(make_record(user_id=42))
    wl.log_record(make_record(user_id=42))
    assert wl.context == {"user_id": 42}
    assert "context" not in wl.events[0]
    assert "context" not in wl.events[1]


def test_log_record_duplicate_context_key_different_value_goes_to_event():
    wl = WideLogger("test", use_root_context=True)
    wl.log_record(make_record(user_id=42))
    wl.log_record(make_record(user_id=99))
    assert wl.context["user_id"] == 42
    assert wl.events[1]["context"] == {"user_id": 99}


def test_log_record_mixed_new_and_differing_context():
    wl = WideLogger("test", use_root_context=True)
    wl.log_record(make_record(env="prod"))
    wl.log_record(make_record(env="prod", request_id="abc"))
    assert wl.context == {"env": "prod", "request_id": "abc"}
    assert "context" not in wl.events[0]
    assert "context" not in wl.events[1]


def test_log_record_pre_populated_context_key_treated_as_known():
    """Keys in the initial context dict should not be promoted (already there)."""
    wl = WideLogger("test", context={"source": "worker"}, use_root_context=True)
    wl.log_record(make_record(source="worker"))
    assert "context" not in wl.events[0]


def test_log_record_pre_populated_context_key_different_value_goes_to_event():
    wl = WideLogger("test", context={"source": "worker"}, use_root_context=True)
    wl.log_record(make_record(source="override"))
    assert wl.events[0]["context"] == {"source": "override"}
    assert wl.context["source"] == "worker"


# ---------------------------------------------------------------------------
# WideLogger.log_record — context with use_root_context=False
# ---------------------------------------------------------------------------


def test_log_record_context_always_in_event_when_not_using_root():
    wl = WideLogger("test", use_root_context=False)
    wl.log_record(make_record(user_id=42))
    wl.log_record(make_record(user_id=42))
    assert wl.context == {}
    assert wl.events[0]["context"] == {"user_id": 42}
    assert wl.events[1]["context"] == {"user_id": 42}


def test_log_record_no_context_produces_no_context_key():
    wl = WideLogger("test", use_root_context=False)
    wl.log_record(make_record())
    assert "context" not in wl.events[0]


# ---------------------------------------------------------------------------
# WideLogger.finalize
# ---------------------------------------------------------------------------


def test_finalize_returns_false_with_no_events():
    assert WideLogger("test").finalize() is False


def test_finalize_returns_true_with_events(logger_handler):
    with logger_handler("test_logger.test_finalize_returns_true_with_events") as (
        logger,
        handler,
    ):
        wl = WideLogger("test", output_logger=logger.name)
        wl.log_record(make_record(level=logging.INFO))
        assert wl.finalize() is True
        assert len(handler.records) == 1
        assert handler.records[0].msg is wl


def test_finalize_logs_at_max_level(logger_handler):
    with logger_handler("test_logger.test_finalize_logs_at_max_level") as (
        logger,
        handler,
    ):
        wl = WideLogger("test", output_logger=logger.name)
        wl.log_record(make_record(level=logging.DEBUG))
        wl.log_record(make_record(level=logging.ERROR))
        wl.log_record(make_record(level=logging.WARNING))
        wl.finalize()
        assert len(handler.records) == 1
        assert handler.records[0].levelno == logging.ERROR


def test_finalize_uses_output_logger_when_set(logger_handler):
    with logger_handler("test_logger.test_finalize_uses_output_logger_when_set") as (
        logger,
        handler,
    ):
        wl = WideLogger("test", output_logger=logger.name)
        wl.log_record(make_record())
        wl.finalize()
        assert len(handler.records) == 1


# ---------------------------------------------------------------------------
# WideLogger.__str__
# ---------------------------------------------------------------------------


def test_str_returns_valid_json():
    wl = WideLogger("test.entrypoint")
    wl.log_record(make_record())
    assert isinstance(json.loads(str(wl)), dict)


def test_str_contains_required_keys():
    wl = WideLogger("test.entrypoint")
    wl.log_record(make_record())
    parsed = json.loads(str(wl))
    assert "entrypoint" in parsed
    assert parsed["entrypoint"] == "test.entrypoint"
    assert "started_at" in parsed
    assert "ended_at" in parsed
    assert "events" in parsed


def test_str_context_absent_when_empty():
    wl = WideLogger("test")
    wl.log_record(make_record())
    assert "context" not in json.loads(str(wl))


def test_str_context_present_when_populated():
    wl = WideLogger("test", context={"key": "val"})
    wl.log_record(make_record())
    assert json.loads(str(wl))["context"] == {"key": "val"}


def test_str_ended_at_is_after_started_at():
    wl = WideLogger("test")
    wl.log_record(make_record())
    parsed = json.loads(str(wl))
    assert datetime.fromisoformat(parsed["ended_at"]) >= datetime.fromisoformat(
        parsed["started_at"]
    )


def test_str_events_serialized():
    wl = WideLogger("test")
    wl.log_record(make_record(msg="first"))
    wl.log_record(make_record(msg="second"))
    parsed = json.loads(str(wl))
    assert len(parsed["events"]) == 2
    assert parsed["events"][0]["msg"] == "first"
    assert parsed["events"][1]["msg"] == "second"


# ---------------------------------------------------------------------------
# wide_logger_for_stack
# ---------------------------------------------------------------------------


def test_wide_logger_for_stack_returns_none_outside_stack():
    assert wide_logger_for_stack() is None


def test_wide_logger_for_stack_returns_logger_from_enclosing_frame():
    __wide_logger__ = WideLogger("test.entrypoint")
    assert wide_logger_for_stack() is __wide_logger__


def test_wide_logger_for_stack_finds_logger_in_indirect_caller():
    __wide_logger__ = WideLogger("outer")

    def inner():
        return wide_logger_for_stack()

    assert inner() is __wide_logger__


def test_wide_logger_for_stack_returns_innermost_logger():
    """When nested, the innermost __wide_logger__ is returned first."""
    __wide_logger__ = WideLogger("outer")  # noqa: F841

    def inner_scope():
        __wide_logger__ = WideLogger("inner")
        return wide_logger_for_stack()

    assert inner_scope().entrypoint == "inner"


# ---------------------------------------------------------------------------
# WideLoggerHandlerFilter
# ---------------------------------------------------------------------------


def test_handler_filter_wide_logger_message_passes_through():
    """The final log (msg=WideLogger instance) must never be suppressed."""
    wl = WideLogger("test")
    assert WideLoggerHandlerFilter().filter(make_record(msg=wl)) is True


def test_handler_filter_record_outside_stack_passes_through():
    assert WideLoggerHandlerFilter().filter(make_record()) is True


def test_handler_filter_record_inside_stack_is_intercepted():
    __wide_logger__ = WideLogger("test")
    assert WideLoggerHandlerFilter().filter(make_record()) is False


def test_handler_filter_intercepted_record_added_to_wide_logger():
    __wide_logger__ = WideLogger("test")
    record = make_record(msg="captured event", level=logging.WARNING)
    WideLoggerHandlerFilter().filter(record)
    assert len(__wide_logger__.events) == 1
    assert __wide_logger__.events[0]["msg"] == "captured event"


def test_handler_filter_placed_on_logger_misses_propagated_records():
    """Documents the known footgun: filters on loggers don't cover propagated records.

    Python's callHandlers() walks the logger hierarchy and calls handler.handle()
    directly — it never goes through parent.handle(), so a filter on a parent *logger*
    is never consulted for records that propagate up from child loggers. The filter
    must be on the *handler* to intercept those records.
    """
    filter = WideLoggerHandlerFilter()
    capture = CapturingHandler()

    parent = logging.getLogger("test.filter.parent")
    child = logging.getLogger("test.filter.parent.child")
    parent.setLevel(logging.DEBUG)
    parent.propagate = False
    parent.addHandler(capture)  # plain handler — no filter attached
    parent.addFilter(filter)  # filter on the logger itself (wrong placement)
    child.setLevel(logging.DEBUG)
    try:
        __wide_logger__ = WideLogger("test")  # noqa: F841
        child.info("should be intercepted")
        # The record propagated from child straight to capture without the
        # parent-logger filter ever being consulted.
        assert len(capture.records) == 1
    finally:
        parent.removeHandler(capture)
        parent.removeFilter(filter)
        parent.propagate = True
