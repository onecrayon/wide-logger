from inspect import iscoroutinefunction, markcoroutinefunction

from django.conf import settings

from . import wide_logger


class WideLoggerMiddleware:
    """Django middleware for wrapping all views with @wide_logger"""

    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        # The following logic is lifted from the Django's native MiddlewareMixin
        self.async_mode = iscoroutinefunction(get_response)
        if self.async_mode:
            # Mark the class as async-capable, but do the actual switch inside
            # __call__ to avoid swapping out dunder methods.
            markcoroutinefunction(self)
        # Grab our configurable settings for the global wide_logger
        use_root_context = getattr(settings, "WIDE_LOGGER_USE_ROOT_CONTEXT", True)
        output_logger = getattr(settings, "WIDE_LOGGER_OUTPUT_LOGGER", None)
        self.get_response = wide_logger(
            get_response, use_root_context=use_root_context, output_logger=output_logger
        )

    def __call__(self, request):
        # Exit out to async mode, if needed
        if self.async_mode:
            return self.__acall__(request)
        response = self.get_response(request)
        return response

    async def __acall__(self, request):
        """
        Async version of __call__ that is swapped in when an async request
        is running.
        """
        response = await self.get_response(request)
        return response
