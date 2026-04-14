import pytest

from wide_logger.asyncio_tracing import disable_asyncio_tracing


@pytest.fixture(autouse=True)
def reset_asyncio_tracing():
    """Restore asyncio.create_task after each test.

    Wrapping any async function with @wide_logger calls enable_asyncio_tracing(),
    which monkey-patches asyncio.create_task. Without cleanup this leaks across
    the whole test session.
    """
    yield
    disable_asyncio_tracing()
