import inspect
import logging
from contextlib import contextmanager
from pathlib import Path

import pytest

from wide_logger import WideLoggerHandlerFilter


class CapturingHandler(logging.Handler):
    """A logging handler that stores emitted records for later assertion."""

    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord):
        self.records.append(record)


@pytest.fixture
def capturing_handler():
    """A capturing handler with WideLoggerHandlerFilter attached."""
    handler = CapturingHandler()
    handler.addFilter(WideLoggerHandlerFilter())
    return handler


@pytest.fixture
def logger_handler(capturing_handler):
    """Returns a context manager that yields a paired logger and handler instance for use in tests

    Implemented as a context manager method rather than a standard fixture to allow us to scope the
    logger to the specific test method.
    """

    @contextmanager
    def _setup_wide_logger(logger_name: str = None):
        # Create a custom logger based on the current test name so by default we don't accidentally
        #  reuse logger singletons
        if logger_name is None:
            try:
                frame = inspect.currentframe().f_back
                parent_path = Path(frame.f_code.co_filename)
                logger_name = f"tests.{parent_path.stem}.{frame.f_code.co_name}"
            finally:
                del frame
        # Configure the logger to capture everything and yield it
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        logger.addHandler(capturing_handler)
        try:
            yield logger, capturing_handler
        finally:
            # Clean up the logger, just in case we somehow end up with overlap
            logger.removeHandler(capturing_handler)
            logger.propagate = True

    return _setup_wide_logger
