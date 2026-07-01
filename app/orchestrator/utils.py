import asyncio

_background_tasks: set[asyncio.Task] = set()

def _safe_create_task(coro) -> asyncio.Task:
    """Create a task and track it to prevent GC or leaks."""
    t = asyncio.create_task(coro)
    _background_tasks.add(t)
    t.add_done_callback(_background_tasks.discard)
    return t
