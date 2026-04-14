"""Tests for wide_logger/django.py (async)

Skipped automatically when Django is not installed.
"""

import pytest

django = pytest.importorskip("django", reason="Django not installed")

from django.conf import settings  # noqa: E402
from django.http import HttpResponse  # noqa: E402
from django.test import RequestFactory  # noqa: E402

from wide_logger import WideLogger  # noqa: E402
from wide_logger.django import WideLoggerMiddleware  # noqa: E402


def _configure_django():
    if not settings.configured:
        settings.configure(
            USE_TZ=True,
            DATABASES={},
        )


_configure_django()


async def test_async_view_response_returned():
    async def view(request):
        return HttpResponse("async ok")

    middleware = WideLoggerMiddleware(view)
    response = await middleware(RequestFactory().get("/"))
    assert response.status_code == 200


async def test_async_view_events_emitted(logger_handler, monkeypatch):
    with logger_handler("test_django_async.test_async_view_events_emitted") as (
        logger,
        handler,
    ):
        monkeypatch.setattr(
            settings, "WIDE_LOGGER_OUTPUT_LOGGER", logger.name, raising=False
        )

        async def view(request):
            logger.info("async request")
            return HttpResponse("ok")

        middleware = WideLoggerMiddleware(view)
        await middleware(RequestFactory().get("/"))
        assert len(handler.records) == 1
        assert isinstance(handler.records[0].msg, WideLogger)


async def test_async_reads_use_root_context_setting(logger_handler, monkeypatch):
    with logger_handler(
        "test_django_async.test_async_reads_use_root_context_setting"
    ) as (logger, handler):
        monkeypatch.setattr(
            settings, "WIDE_LOGGER_USE_ROOT_CONTEXT", False, raising=False
        )
        monkeypatch.setattr(
            settings, "WIDE_LOGGER_OUTPUT_LOGGER", logger.name, raising=False
        )

        async def view(request):
            logger.info("event", extra={"key": "val"})
            return HttpResponse("ok")

        middleware = WideLoggerMiddleware(view)
        await middleware(RequestFactory().get("/"))
        wide_log: WideLogger = handler.records[0].msg
        # use_root_context=False means context is in events, not root
        assert wide_log.context == {}
        assert wide_log.events[0]["context"] == {"key": "val"}


async def test_async_default_settings_when_absent(monkeypatch):
    """Middleware should use sensible defaults when settings are not configured."""
    monkeypatch.delattr(settings, "WIDE_LOGGER_USE_ROOT_CONTEXT", raising=False)
    monkeypatch.delattr(settings, "WIDE_LOGGER_OUTPUT_LOGGER", raising=False)

    async def view(request):
        return HttpResponse("ok")

    # Should not raise regardless of missing settings
    WideLoggerMiddleware(view)
