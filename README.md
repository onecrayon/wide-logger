# Wide Logger for Python

Wide Logger is a zero-dependency module that provides wide, structured logging using Python's native
`logging` module. When code paths that have opted into wide logging do things like
`logger.info("Barred the foo")` it will not output an individual log entry but will instead be
output as a nested event within a single log entry that is output after the full code path has
completed.

The final log is structured JSON, and arbitrary context elements can be added using the standard
`extra` logging keyword argument: `logger.info("Barred the foo", extra={"foo": foo})`. The final
output log will look something like this (linebreaks and indentation added for legibility):

    {
      "entrypoint": "module.path.foo.wrapped_method",
      "started_at": "2026-04-09T18:15:34.122835+00:00",
      "ended_at": "2026-04-09T18:15:34.122972+00:00",
      "context": {"foo": "repr of `foo`"},
      "events": [
        {
          "level": "INFO",
          "msg": "Barred the foo",
          "at": "2026-04-09T18:15:34.122843+00:00",
          "from": "module/path/foo.py#123"
        }
      ]
    }

If you set `exc_info` your event will also have a `"traceback"` string. The level of the output
log will match the highest level of logged event; that is, the above example would be output at the
INFO level, but if you also logged an event with `logger.error("...")` it would be output at the
ERROR level instead.

## When to use it

Wide Logger is most appropriate either for projects that are already using Python's native logging
functionality and want to convert to more useful wide, structured logs piecemeal; or for projects
that have predictable entrypoints that can be automatically wrapped with the `@wide_logger`
decorator (e.g. wrapping all Django endpoint calls via middleware). It can also be used for new
projects, but because it is opt-in-via-decorator this will result in a lot of redundant decorators
in your code long-term.

## Getting Started

1. Install `wide-logger` using your preferred dependency management tool; e.g. 
   `poetry add wide-logger`
2. Modify your logging configuration to add the `WideLoggerHandlerFilter` to your preferred logger.
   For instance, if your current logging configuration looks like this:

        LOGGING = {
            "version": 1,
            "root": {
                "handlers": ["stderr"],
            },
            "handlers": {
                "stderr": {
                    "class": "logging.StreamHandler",
                },
            },
        }

   You would add the filter to your `stderr` handler:

        LOGGING = {
            "version": 1,
            "root": {
                "handlers": ["stderr"],
            },
            "filters": {
                "wide_logs": {
                    "()": "wide_logger.WideLoggerHandlerFilter",
                },
            },
            "handlers": {
                "stderr": {
                    "class": "logging.StreamHandler",
                    "filters": ["wide_logs"],
                },
            },
        }
   
   **IMPORTANT:** if you place the filter on a *logger* then it will only apply to messages sent
   *through that logger*. You need to attach the filter to a handler in order to ensure it will
   consume both propagated messages and messages logged directly to that logger.
3. Decorate entrypoints that should opt into wide logging with `@wide_logger`:

        from wide_logger import wide_logger
        
        @wide_logger
        def method_with_wide_logging():
            ...

The only requirement for a given codepath to be able to add events to the wide logger is that it
uses or propagates to a logger with the handler using the filter you added in step 2, and it is
called as part of a code stack that is wrapped with the `@wide_logger` decorator. This means that if
you put your filter on a root handler, all logged content in your project will be output as wide,
structured logs when accessed through the `@wide_logger` decorator.

### Using Django middleware

To automatically enable wide logging for all Django endpoints, instead of decorating endpoints as
per step 3 above, add the Django middleware in your app's settings file:

    MIDDLEWARE = [
        "wide_logger.django.WideLoggerMiddleware",
        ...
    ]

When using the Django middleware you can configure several `@wide_logger` parameters via your
settings module:

    WIDE_LOGGER_USE_ROOT_CONTEXT = False
    WIDE_LOGGER_OUTPUT_LOGGER = "logger.name"

## Context

To add context to your logs, pass contextual information alongside a normal log message using the
`extra` parameter:

    logger.info("Processing foo", extra={"foo": foo.id})

By default, context items will be populated in the root-level `"context"` property of your final
structured log, unless that key is already set and the value is not equal based on a Python `==`
test in which case it will be populated in a `"context"` property nested within that event.

If you would like all context to be nested in events (without any attempt to prevent duplicate
entries across events), you can do so via the decorator:

    @wide_logger(use_root_context=False)

## @wide_logger parameters

You can customize logging behavior by passing parameters to the `@wide_logger` decorator:

* `context={"key": "value"}`: pre-populate your log's context object with static values.
* `use_root_context=False`: as described above, this will opt out of the root-level context property
  and store all context within events (without attempting to avoid duplicate entries).
* `output_logger="logger.name"`: explicitly choose which logger you wish to use for the final
  structured log. If unspecified, it will be default to the earliest occurring, highest-level logger
  used to log events.

## Customizing output via Formatters

Wide Logger uses the standard Python logging module, so you can customize your final log output
using formatters. Because log events are captured via filter, formatters  will be applied to the
*final output log*, not the individual event messages.

Additionally, the final output log is passed as an instance of the internal `WideLogger` class
(which automatically renders to JSON when converted to a str). This means that if you wish to output
your logs in some other format (e.g. logfmt or similar), you can do like so:

    import logging
    from wide_logger import WideLogger
    
    class CustomFormatter(logging.Formatter):
        def format(record: logging.LogRecord) -> str:
            if isinstance(record.msg, WideLogger):
                # Generate a custom str representation of the wide log
                ...
            else:
                return super().format(record)

## How it works

When a log message is sent to a handler with the `WideLoggerHandlerFilter` attached, the filter
introspects the current executing code stack looking for a `__wide_logger__` variable (which is
defined by the decorator and contains a `WideLogger` instance). If it finds one, it appends the
message as an event and rejects the log record; otherwise, it allows the record to be emitted.

This has a couple important side effects:

1. Using Wide Logger introduces minor overhead, which gets a little worse the deeper your code
   execution stack grows. Counter-intuitively, it is possible for this overhead to actually be less
   than the overhead caused by emitting logs normally, however, because saving the record to memory
   often requires a lot less time than outputting the log with some form of I/O.
2. If you define a variable named `__wide_logger__` in your execution stack prior to logging
   anything, it will hijack the filter. **I do not recommend this** but if for whatever reason you
   want to use wide logging on code paths where the included decorator method is inappropriate, the
   option is there.

### asyncio support

Wide Logging can be used in asyncio contexts, but note that in order to do so it *monkey-patches
asyncio.create_task*. This is necessary because creating a task breaks stack frame boundaries (and
this happens implicitly when you invoke code like `await my_coroutine()`). To get around this, the
monkey-patch will store parent/child references for all asyncio tasks, along with any relevant
WideLogger instances (so in addition to the overhead already created by its standard behavior it
also introduces a bit of memory overhead to track task relationships).

## Contributing

TBD.
