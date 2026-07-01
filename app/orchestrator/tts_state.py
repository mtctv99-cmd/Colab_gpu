import asyncio

# Global store for tracking sync TTS generation callers awaiting completion.
# Maps task_id (str) -> asyncio.Event.
_pending_direct_events: dict[str, asyncio.Event] = {}
