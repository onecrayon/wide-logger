"""Support for tracking WideLogger instances across asyncio task boundaries

Tracing is complicated in asyncio contexts because invoking an async method creates a task, which
breaks the ability to recurse up the code stack. In order to get around this, we need to
explicitly track the parent context when a task is created (which happens implicitly when calling
an async method like `await my_async_method()`). To do this, we are monkey-patching
asyncio.create_task() so that we can capture relevant stack information as tasks are created.
These global variables are used to allow us to toggle the patch on or off at will (though
generally it will simply be enabled the first time we invoke `@wide_logger` in an async context
and then never be reverted).
"""
import asyncio
from typing import Callable, Optional

from .logger import wide_logger_for_stack, WideLogger

# These methods are used as internal globals for tracking monkey-patching state
_original_create_task: Optional[Callable] = None
_is_asyncio_tracing_enabled = False
# This is used as an internal global which associates Task instances to their related parent,
#  children, and related WideLogger instance.
_task_tree: dict[asyncio.Task, dict] = {}


def _clear_task_tree(parent_task: asyncio.Task):
    """Recursively clears all children for a given parent from our task tree

    This is invoked automatically when an asyncio @wide_logger decorated method completes.
    """
    if parent_task not in _task_tree:
        return
    children = _task_tree[parent_task].get("children", [])
    for child in children:
        _clear_task_tree(child)
    del _task_tree[parent_task]


def _patched_create_task(*args, **kwargs) -> asyncio.Task:
    """Monkey patched asyncio.create_task which tracks parent relationships

    This allows us to step back across frames across task boundaries in order to identify WideLogger
    decorated code paths.
    """
    # If we don't have our original create_task, something has gone badly awry
    if _original_create_task is None:
        raise RuntimeError(
            "WideLogger patched asyncio.create_task called prior to patch"
        )
    parent = asyncio.current_task()
    # First look for our logger in the previously-traced parent stacks
    wide_logger = _task_tree.get(parent, {}).get("__wide_logger__")
    # If we don't have one for whatever reason, check our current stack
    if wide_logger is None:
        wide_logger = wide_logger_for_stack()
    task = _original_create_task(*args, **kwargs)
    # If we have no wide logger, there's no reason to stick this in our tree, because it will never
    #  be needed.
    if wide_logger is None:
        return task
    # Otherwise save our bi-directional task relationships (child relationships are necessary so we
    # can garbage collect full trees from the root parent when __wide_logger__ defined completes).
    # Wide logger instances are saved at every level to reduce the need to recurse through the tree.
    _task_tree[task] = {
        "parent": parent,
        "__wide_logger__": wide_logger,
        "children": [],
    }
    if parent in _task_tree:
        _task_tree[parent]["children"].append(task)
    return task


def enable_asyncio_tracing():
    """Globally enables asyncio stack tracing"""
    global _original_create_task, _is_asyncio_tracing_enabled
    if _is_asyncio_tracing_enabled:
        return

    _is_asyncio_tracing_enabled = True
    _original_create_task = asyncio.create_task
    asyncio.create_task = _patched_create_task


def disable_asyncio_tracing():
    """Globally disabled asyncio stack tracing

    Not currently used by the project outside of testing, as disabling async support has no
    appreciable benefit under normal usage.
    """
    global _original_create_task, _is_asyncio_tracing_enabled, _task_tree
    if not _is_asyncio_tracing_enabled:
        return

    asyncio.create_task = _original_create_task
    _is_asyncio_tracing_enabled = False
    _original_create_task = None
    _task_tree = {}


def wide_logger_for_asyncio_stack() -> Optional[WideLogger]:
    """Async-compatible version of the standard `wide_logger_for_stack()`"""
    # First check if we have a cached wide logger from our parent stacks
    current_task = asyncio.current_task()
    wide_logger = _task_tree.get(current_task, {}).get("__wide_logger__")
    # If we don't have a wide logger, check our current stack
    if wide_logger is None:
        wide_logger = wide_logger_for_stack()
    return wide_logger


def finalize_wide_logged_asyncio_stack():
    """Garbage collects cached task information after a wide_logger is finalized

    We can do this bi-directionally, because there is only ever one wide logger alive in a given
    stack. If child tasks have not completed at this point, it means they were improperly awaited
    and since the wide_logger instance is no longer active they might as well be ditched from
    memory; any further logging from them will show up in the standard logs.
    """
    task = asyncio.current_task()
    # Walk up the tree to find our outermost parent
    parent_task = _task_tree.get(task, {}).get("parent")
    while parent_task in _task_tree:
        parent_task = _task_tree[parent_task].get("parent")
    # Now that we have our root parent, recursively clear all child tasks
    _clear_task_tree(parent_task)
