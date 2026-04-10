from functools import wraps
from inspect import iscoroutinefunction

from .asyncio_tracing import (
    wide_logger_for_asyncio_stack,
    enable_asyncio_tracing,
    finalize_wide_logged_asyncio_stack,
)
from .logger import wide_logger_for_stack, WideLogger, WideLoggerHandlerFilter

__all__ = (
    "wide_logger",
    "WideLogger",
    "WideLoggerHandlerFilter",
)


def wide_logger(
    argsless_func=None,
    *,
    context: dict = None,
    use_root_context: bool = True,
    output_logger: str = None,
):
    """A decorator that provides wide event logs

    Callable either standalone or with the keyword arguments above. Must be wrapping a method whose
    code uses a logger with a handler that has the `WideLoggerHandlerFilter` configured (or
    propagates to such a logger). Usage example, assuming the root logger's handler has
    `WideLoggerHandlerFilter` attached:

        import logging
        from wide_logger import wide_logger

        logger = logging.getLogger()

        @wide_logger
        def logged_func():
            logger.debug("A message that will be logged as an event")

        @wide_logger(context={"source": "device_processor"})
        def logged_func_with_context():
            logger.info("Another event message", extra={"another_context_item": True})

    It is safe to call a method that is wrapped in @wide_logger from another wrapped method. In this
    case, the outer @wide_logger will always be used (e.g. in the example above calling
    `logged_func_with_context()` from within `logged_func` would not result in the context
    containing the "source" entry, because only the outermost wide_logger would be used).

    Safe to use in either asyncio or sync code, but please note that asyncio support will
    monkey-patch `asyncio.create_task()`.
    """

    def decorator(func):
        # Check if we are working with an async method, as that requires different logic
        if iscoroutinefunction(func):
            # Ensure we can track wide loggers across task boundaries
            enable_asyncio_tracing()

            @wraps(func)
            async def wrapper(*args, **kwargs):
                # First check if we already have a logger in our stack, traversing task boundaries
                existing_logger = wide_logger_for_asyncio_stack()
                __wide_logger__ = (
                    WideLogger(
                        entrypoint=f"{func.__module__}.{func.__name__}",
                        context=context,
                        use_root_context=use_root_context,
                        output_logger=output_logger,
                    )
                    if not existing_logger
                    else existing_logger
                )
                # Then execute our coroutine
                try:
                    return await func(*args, **kwargs)
                finally:
                    # And finally if this is our final wrapped method, log the wide event and clean
                    # up our async task tracking
                    if not existing_logger:
                        __wide_logger__.finalize()
                        finalize_wide_logged_asyncio_stack()

        else:
            # Otherwise we can use our standard sync handling logic
            @wraps(func)
            def wrapper(*args, **kwargs):
                # First check if we already have a WideLogger in our stack
                existing_logger = wide_logger_for_stack()
                __wide_logger__ = (
                    WideLogger(
                        entrypoint=f"{func.__module__}.{func.__name__}",
                        context=context,
                        use_root_context=use_root_context,
                        output_logger=output_logger,
                    )
                    if not existing_logger
                    else existing_logger
                )
                # Then execute our function
                try:
                    return func(*args, **kwargs)
                finally:
                    # And finally log the wide event with our root logger, if necessary
                    if not existing_logger:
                        __wide_logger__.finalize()

        return wrapper

    return decorator(argsless_func) if callable(argsless_func) else decorator
