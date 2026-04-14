"""Unit tests for wide_logger/asyncio_tracing.py"""

import asyncio

from wide_logger import WideLogger, wide_logger
from wide_logger.asyncio_tracing import (
    _clear_task_tree,
    _patched_create_task,
    _task_tree,
    disable_asyncio_tracing,
    enable_asyncio_tracing,
    finalize_wide_logged_asyncio_stack,
    wide_logger_for_asyncio_stack,
)


# ---------------------------------------------------------------------------
# enable / disable
# ---------------------------------------------------------------------------


def test_enable_disable_patches_create_task():
    original = asyncio.create_task
    enable_asyncio_tracing()
    assert asyncio.create_task is _patched_create_task
    assert asyncio.create_task is not original


def test_enable_disable_is_idempotent():
    enable_asyncio_tracing()
    first_patch = asyncio.create_task
    enable_asyncio_tracing()
    assert asyncio.create_task is first_patch


def test_enable_disable_restores_original():
    original = asyncio.create_task
    enable_asyncio_tracing()
    disable_asyncio_tracing()
    assert asyncio.create_task is original


def test_enable_disable_disable_is_idempotent():
    original = asyncio.create_task
    disable_asyncio_tracing()  # called without prior enable
    assert asyncio.create_task is original


def test_enable_disable_clears_task_tree_on_disable():
    enable_asyncio_tracing()
    fake_task = object()
    _task_tree[fake_task] = {"__wide_logger__": WideLogger("test")}
    disable_asyncio_tracing()
    assert len(_task_tree) == 0


# ---------------------------------------------------------------------------
# _clear_task_tree
# ---------------------------------------------------------------------------


def test_clear_task_tree_no_op_for_unknown_task():
    fake_task = object()
    # Should not raise
    _clear_task_tree(fake_task)


async def test_clear_task_tree_clears_single_task():
    enable_asyncio_tracing()
    wl = WideLogger("test")

    async def noop():
        pass

    __wide_logger__ = wl  # noqa: F841 — picked up by wide_logger_for_stack
    task = asyncio.create_task(noop())
    assert task in _task_tree
    _clear_task_tree(task)
    assert task not in _task_tree
    await task  # prevent "task destroyed but pending" warning


async def test_clear_task_tree_clears_children_recursively():
    enable_asyncio_tracing()
    wl = WideLogger("test")

    async def noop():
        pass

    __wide_logger__ = wl  # noqa: F841
    parent_task = asyncio.create_task(noop())
    child_task = asyncio.create_task(noop())
    # Manually wire up parent → child relationship
    _task_tree[parent_task]["children"].append(child_task)
    _task_tree[child_task] = {
        "parent": parent_task,
        "__wide_logger__": wl,
        "children": [],
    }
    _clear_task_tree(parent_task)
    assert parent_task not in _task_tree
    assert child_task not in _task_tree
    await parent_task
    await child_task


# ---------------------------------------------------------------------------
# _patched_create_task
# ---------------------------------------------------------------------------


async def test_patched_create_task_returns_valid_task():
    enable_asyncio_tracing()

    async def noop():
        pass

    task = asyncio.create_task(noop())
    assert isinstance(task, asyncio.Task)
    await task


async def test_patched_create_task_not_stored_without_wide_logger():
    enable_asyncio_tracing()

    async def noop():
        pass

    task = asyncio.create_task(noop())
    assert task not in _task_tree
    await task


async def test_patched_create_task_stored_with_wide_logger_in_stack():
    enable_asyncio_tracing()
    wl = WideLogger("test")

    async def noop():
        pass

    __wide_logger__ = wl  # noqa: F841 — picked up by wide_logger_for_stack
    task = asyncio.create_task(noop())
    assert task in _task_tree
    assert _task_tree[task]["__wide_logger__"] is wl
    await task


async def test_patched_create_task_stores_parent_reference():
    enable_asyncio_tracing()
    wl = WideLogger("test")

    async def noop():
        pass

    current = asyncio.current_task()
    __wide_logger__ = wl  # noqa: F841
    task = asyncio.create_task(noop())
    assert _task_tree[task]["parent"] is current
    await task


async def test_patched_create_task_registers_child_on_parent():
    enable_asyncio_tracing()
    wl = WideLogger("test")

    current = asyncio.current_task()
    _task_tree[current] = {"parent": None, "__wide_logger__": wl, "children": []}

    async def noop():
        pass

    __wide_logger__ = wl  # noqa: F841
    task = asyncio.create_task(noop())
    assert task in _task_tree[current]["children"]
    await task


async def test_patched_create_task_inherits_wide_logger_from_task_tree():
    """If current task is in _task_tree, its wide_logger is used for the new child."""
    enable_asyncio_tracing()
    wl = WideLogger("inherited")
    current = asyncio.current_task()
    _task_tree[current] = {"parent": None, "__wide_logger__": wl, "children": []}

    async def noop():
        pass

    task = asyncio.create_task(noop())
    assert _task_tree[task]["__wide_logger__"] is wl
    await task


# ---------------------------------------------------------------------------
# wide_logger_for_asyncio_stack
# ---------------------------------------------------------------------------


async def test_wide_logger_for_asyncio_stack_returns_none_with_no_context():
    result = wide_logger_for_asyncio_stack()
    assert result is None


async def test_wide_logger_for_asyncio_stack_returns_logger_from_task_tree():
    enable_asyncio_tracing()
    wl = WideLogger("tree")
    current = asyncio.current_task()
    _task_tree[current] = {"parent": None, "__wide_logger__": wl, "children": []}
    assert wide_logger_for_asyncio_stack() is wl


async def test_wide_logger_for_asyncio_stack_falls_back_to_stack_inspection():
    __wide_logger__ = WideLogger("stack")
    result = wide_logger_for_asyncio_stack()
    assert result is __wide_logger__


async def test_wide_logger_for_asyncio_stack_task_tree_takes_priority():
    enable_asyncio_tracing()
    tree_wl = WideLogger("from tree")
    stack_wl = WideLogger("from stack")
    current = asyncio.current_task()
    _task_tree[current] = {
        "parent": None,
        "__wide_logger__": tree_wl,
        "children": [],
    }
    __wide_logger__ = stack_wl  # noqa: F841
    assert wide_logger_for_asyncio_stack() is tree_wl


# ---------------------------------------------------------------------------
# finalize_wide_logged_asyncio_stack
# ---------------------------------------------------------------------------


async def test_finalize_wide_logged_asyncio_stack_clears_current_task():
    enable_asyncio_tracing()
    current = asyncio.current_task()
    wl = WideLogger("test")
    _task_tree[current] = {"parent": None, "__wide_logger__": wl, "children": []}
    finalize_wide_logged_asyncio_stack()
    assert current not in _task_tree


async def test_finalize_wide_logged_asyncio_stack_no_op_when_not_in_tree():
    # Should not raise even if current task has no entry
    finalize_wide_logged_asyncio_stack()


async def test_finalize_wide_logged_asyncio_stack_clears_entire_subtree():
    enable_asyncio_tracing()
    current = asyncio.current_task()
    wl = WideLogger("test")
    fake_child = object()
    fake_grandchild = object()
    _task_tree[current] = {
        "parent": None,
        "__wide_logger__": wl,
        "children": [fake_child],
    }
    _task_tree[fake_child] = {
        "parent": current,
        "__wide_logger__": wl,
        "children": [fake_grandchild],
    }
    _task_tree[fake_grandchild] = {
        "parent": fake_child,
        "__wide_logger__": wl,
        "children": [],
    }
    finalize_wide_logged_asyncio_stack()
    assert current not in _task_tree
    assert fake_child not in _task_tree
    assert fake_grandchild not in _task_tree


async def test_finalize_wide_logged_asyncio_stack_walks_to_root():
    """finalize() should clear from the root of the tree, not just the leaf."""
    enable_asyncio_tracing()
    current = asyncio.current_task()
    wl = WideLogger("test")
    fake_root = object()
    _task_tree[fake_root] = {
        "parent": None,
        "__wide_logger__": wl,
        "children": [current],
    }
    _task_tree[current] = {
        "parent": fake_root,
        "__wide_logger__": wl,
        "children": [],
    }
    finalize_wide_logged_asyncio_stack()
    assert fake_root not in _task_tree
    assert current not in _task_tree


# ---------------------------------------------------------------------------
# End-to-end async integration
# ---------------------------------------------------------------------------


async def test_async_end_to_end_events_collected_across_tasks(logger_handler):
    """Events logged in a spawned task must appear in the outer @wide_logger."""
    with logger_handler(
        "test_async_end_to_end.test_async_end_to_end_events_collected_across_tasks"
    ) as (logger, handler):

        @wide_logger(output_logger=logger.name)
        async def inner():
            logger.info("inner task event")

        @wide_logger(output_logger=logger.name)
        async def outer():
            logger.debug("outer event")
            await inner()

        await outer()
        assert len(handler.records) == 1
        wl: WideLogger = handler.records[0].msg
        messages = [e["msg"] for e in wl.events]
        assert "outer event" in messages
        assert "inner task event" in messages


async def test_async_end_to_end_task_tree_empty_after_completion(logger_handler):
    """The task tree should be garbage-collected after the outermost decorator finishes."""
    with logger_handler(
        "test_async_end_to_end.test_async_end_to_end_task_tree_empty_after_completion"
    ) as (logger, handler):

        @wide_logger(output_logger=logger.name)
        async def func():
            logger.info("event")

        await func()
        assert len(_task_tree) == 0
