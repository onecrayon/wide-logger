import inspect
import json
import logging.config
import os
import sys
import traceback
from base64 import b64encode
from datetime import datetime, timezone

# Grab our current working directory once upon initial load so that we can generate relative paths
_CWD = os.getcwd()
# Constant set for checking if a key is a default LogRecord attribute (can't dynamically generate
#  because some attributes are only populated by formatters, and even then it isn't guaranteed)
_LOG_RECORD_DEFAULT_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
    # These are generated optionally by formatters
    "asctime",
    "message",
}


def context_dict_from_extra(record: logging.LogRecord) -> dict:
    """Extracts any keys added to the record via `extra` and returns as a dict"""
    extra = {}
    for key, value in record.__dict__.items():
        if key in _LOG_RECORD_DEFAULT_ATTRS:
            continue
        extra[key] = value
    return extra


def json_dump_fallback(value) -> str:
    """Default handling for arbitrary JSON output to ensure the JSON parsing doesn't kill things"""
    if isinstance(value, datetime):
        return value.isoformat()
    elif isinstance(value, bytes):
        # For bytes, we first try to decode them into UTF-8 (as this is the best for referencing in
        #  logs when it is possible) and if there are illegal bytes we base64 encode them instead
        try:
            return value.decode()
        except UnicodeDecodeError:
            return b64encode(value).decode()
    else:
        # If all else fails, just return the repr of the object
        return repr(value)


class WideLogger:
    """Class for constructing wide, structured event logs

    This class is not meant to be accessed directly; instead it is meant to be implicitly created
    via the `@wide_logger` decorator defined in `__init__.py`.
    """

    _entrypoint: str
    _started_at: datetime
    _context: dict
    _events: list[dict]
    _use_root_context: bool
    _output_logger: str
    # These are used to control the final logging behavior; max level dictates the level we output
    #  the final log at, and the highest log name dictates which logger we emit it from if no output
    #  logger name is passed
    _max_log_level: int = logging.NOTSET
    _highest_log_name: str = None

    def __init__(
        self,
        entrypoint: str,
        context: dict = None,
        use_root_context: bool = True,
        output_logger: str = None,
    ):
        self._started_at = datetime.now(tz=timezone.utc)
        self._entrypoint = entrypoint
        self._use_root_context = use_root_context
        self._output_logger = output_logger
        if context:
            self._context = context
        else:
            self._context = {}
        self._events = []

    def log_record(self, record: logging.LogRecord):
        """Logs a discrete event in the execution of the code this wide logger is wrapping"""
        # Set our internal tracking information for the final log
        if record.levelno > self._max_log_level:
            self._max_log_level = record.levelno
        # We only need to try to automatically detect a logger to use for our final log if it isn't
        #  explicitly set
        if self._output_logger is None:
            if record.name == "root":
                self._highest_log_name = ""
            elif self._highest_log_name is None or (
                self._highest_log_name.count(".") > record.name.count(".")
            ):
                self._highest_log_name = record.name
        # Convert our created timestamp into UTC time, determine our relative file path, and
        #  construct our context dict
        at = datetime.fromtimestamp(record.created, tz=timezone.utc)
        relative_path = os.path.relpath(record.pathname, _CWD)
        context = context_dict_from_extra(record)
        # We can now make our basic event record
        event: dict = {
            "level": record.levelname,
            "msg": record.msg,
            "at": at,
            "from": f"{relative_path}#{record.lineno}",
        }
        # And then append exception and context information to it, if necessary
        exception = None
        exc_info = record.exc_info
        if exc_info is True:
            exception = sys.exc_info()[1]
        elif isinstance(exc_info, Exception):
            exception = exc_info
        elif isinstance(exc_info, tuple):
            exception = exc_info[1]
        if exception is not None:
            event["traceback"] = "".join(traceback.format_exception(exception))
        if context:
            if self._use_root_context:
                event_context = {}
                for key, value in context.items():
                    # When promoting context items to root, only persist them in the event if they
                    #  differ from the cached root copy, and only promote them if there's no root
                    #  copy
                    if key in self._context:
                        if self._context[key] != value:
                            event_context[key] = value
                    else:
                        self._context[key] = value
                if event_context:
                    event["context"] = event_context
            else:
                event["context"] = context
        self._events.append(event)

    def finalize(self) -> bool:
        """Uses the highest-level detected logger to output itself as the final structured log

        Returns a bool: whether there was anything to output.
        """
        if not self._events:
            return False
        log_name = (
            self._output_logger
            if self._output_logger is not None
            else self._highest_log_name
        )
        logger = logging.getLogger(log_name)
        logger.log(self._max_log_level, self)
        return True

    @property
    def entrypoint(self) -> str:
        """Getter-only access to endpoint str for access through Formatters"""
        return self._entrypoint

    @property
    def started_at(self) -> datetime:
        """Getter-only access to started_at datetime for access through Formatters"""
        return self._started_at

    @property
    def context(self) -> dict:
        """Getter-only access to context dict for access through Formatters"""
        return self._context

    @property
    def events(self) -> list[dict]:
        """Getter-only access to events list for access through Formatters"""
        return self._events

    def __str__(self) -> str:
        """Generates dict representation of the wide event for logging

        This is done within the magic __str__ method instead of having an explicit `to_json()`
        method because it allows us to log the WideLogger instance itself when we're ready to emit
        the final wide log entry as an easy method to bypass the normal WideLoggerHandlerFilter
        without being able to communicate with it directly.
        """
        output_dict: dict = {
            "entrypoint": self._entrypoint,
            "started_at": self._started_at,
            "ended_at": datetime.now(tz=timezone.utc),
        }
        if self._context:
            output_dict["context"] = self._context
        output_dict["events"] = self._events
        return json.dumps(output_dict, default=json_dump_fallback)


def wide_logger_for_stack() -> WideLogger | None:
    """Returns the WideLogger instantiated in the current stack, if one exists

    Aggressively deletes references to frames because the Python docs warn these can lead to memory
    leaks as they are not by default garbage collected.
    """
    wide_logger = None
    try:
        frame = inspect.currentframe()
        while frame:
            if "__wide_logger__" in frame.f_locals:
                return frame.f_locals["__wide_logger__"]
            frame = frame.f_back
    finally:
        del frame
    return wide_logger


class WideLoggerHandlerFilter:
    """WideLoggerHandlerFilter intercepts log events when in the correct stack context

    Please note that it needs to be installed on a *handler*, NOT a logger! This is important
    because filters on loggers are not invoked for propagated events, but filters on handlers are
    always invoked when the handler tries to emit an event.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, WideLogger):
            return True
        # Check if we have a WideLogger instance in our current stack
        wide_logger_instance = wide_logger_for_stack()
        if wide_logger_instance:
            wide_logger_instance.log_record(record)
            return False
        return True
