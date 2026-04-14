"""Tests for the @wide_logger decorator (wide_logger/__init__.py)"""

import logging

import pytest

from .conftest import CapturingHandler
from wide_logger import WideLogger, wide_logger


def test_decorator_no_args_no_parens():
    @wide_logger
    def func():
        return "inner-response"

    assert func() == "inner-response"


def test_decorator_no_args_with_parens():
    @wide_logger()
    def func():
        return "inner-response"

    assert func() == "inner-response"


def test_decorator_with_keyword_args():
    @wide_logger(context={"k": "v"}, use_root_context=False, output_logger=None)
    def func():
        return "inner-response"

    assert func() == "inner-response"


def test_decorator_wraps_function():
    @wide_logger
    def my_named_function():
        """Example docstring."""
        pass

    assert my_named_function.__name__ == "my_named_function"
    assert my_named_function.__doc__ == "Example docstring."


def test_decorator_sets_entrypoint(logger_handler):
    """The code entrypoint for the logger is set properly upon instantiation"""
    with logger_handler() as (logger, handler):

        @wide_logger
        def my_named_entrypoint():
            logger.info("Trigger logging")

        my_named_entrypoint()
        assert len(handler.records) == 1
        assert handler.records[0].msg.entrypoint.endswith(".my_named_entrypoint")


def test_decorator_exceptions(logger_handler):
    """Uncaught exceptions do not prevent finalizing the wide logger"""
    with logger_handler() as (logger, handler):

        @wide_logger
        def func():
            logger.info("Logged before raising")
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            func()

        # The final wide log is emitted despite the uncaught exception
        assert len(handler.records) == 1
        assert isinstance(handler.records[0].msg, WideLogger)


def test_decorator_nested_logger(logger_handler):
    """When @wide_logger is nested, the outer logger should collect all events."""
    with logger_handler() as (logger, handler):

        @wide_logger
        def inner():
            logger.info("from inner")

        @wide_logger
        def outer():
            logger.debug("from outer")
            inner()

        outer()
        # Only the outer finalize() should have fired, resulting in one wide log record
        assert len(handler.records) == 1
        wide_log: WideLogger = handler.records[0].msg
        assert wide_log.events[0]["msg"] == "from outer"
        assert wide_log.events[1]["msg"] == "from inner"
        # Verify that the entrypoint is "outer" which means we are properly using the outer logger
        assert wide_log.entrypoint.endswith(".outer")


def test_decorator_custom_output_logger(logger_handler):
    """Final logged record must be output to the specified logger, if passed"""
    with logger_handler() as (logger, handler):
        # Configure our final handler
        final_handler_name = f"{logger.name}.final"
        final_handler = CapturingHandler()
        final_logger = logging.getLogger(final_handler_name)
        final_logger.setLevel(logging.DEBUG)
        final_logger.propagate = False
        final_logger.addHandler(final_handler)

        @wide_logger(output_logger=final_handler_name)
        def func():
            logger.info("event")

        func()
        # Only the final logger receives an entry
        assert len(handler.records) == 0
        assert len(final_handler.records) == 1
        assert isinstance(final_handler.records[0].msg, WideLogger)

        # Clean things up, just in case
        final_logger.removeHandler(final_handler)
        final_logger.propagate = True


def test_decorator_static_context(logger_handler):
    """Passing static context elements to the decorator saves them to the outer context"""
    with logger_handler() as (logger, handler):

        @wide_logger(context={"static": "context"})
        def func():
            logger.info("event", extra={"static": "context 2"})

        func()
        # Verify the context is saved and wasn't overwritten by the log's context
        assert len(handler.records) == 1
        assert handler.records[0].msg.context["static"] == "context"


def test_decorator_defaults_to_root_context(logger_handler):
    """By default, context elements are populated at the root"""
    with logger_handler() as (logger, handler):

        @wide_logger
        def func():
            logger.info("event 1", extra={"key": "info item"})
            logger.warning("event 2", extra={"key": "warning item"})

        func()
        # Verify the root context is the first entry passed
        assert len(handler.records) == 1
        assert handler.records[0].msg.context["key"] == "info item"


def test_decorator_no_root_context(logger_handler):
    """Opting out of root context causes all context items to be saved on individual events"""
    with logger_handler() as (logger, handler):

        @wide_logger(use_root_context=False)
        def func():
            logger.info("event 1", extra={"key": "info item"})
            logger.warning("event 2", extra={"key": "warning item"})

        func()
        # Verify the root context is the first entry passed
        assert len(handler.records) == 1
        wide_log: WideLogger = handler.records[0].msg
        assert wide_log.context == {}
        assert len(wide_log.events) == 2
        assert wide_log.events[0]["context"] == {"key": "info item"}
        assert wide_log.events[1]["context"] == {"key": "warning item"}


def test_decorator_individual_records_captured(logger_handler):
    """Logged records inside @wide_logger must be captured in the wide log."""
    with logger_handler() as (logger, handler):

        @wide_logger
        def func():
            logger.debug("event 1")
            logger.warning("event 2")
            logger.info("event 3")

        func()
        # Only the single final wide log should have been emitted
        assert len(handler.records) == 1
        # Verify that the final event is output with the max log level
        assert handler.records[0].levelno == logging.WARNING
        # Verify that the events are captured
        wide_log: WideLogger = handler.records[0].msg
        assert len(wide_log.events) == 3
        assert wide_log.events[0]["msg"] == "event 1"
        assert wide_log.events[1]["msg"] == "event 2"
        assert wide_log.events[2]["msg"] == "event 3"
