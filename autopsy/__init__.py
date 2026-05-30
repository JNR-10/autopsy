"""autopsy - your agent died. here's why.

Public API. Users only need::

    from autopsy import lens, log, LensConfig

    @lens.trace
    async def my_agent(query):
        ...

    log("retry", attempt=3)
"""
from __future__ import annotations

from typing import Any

from autopsy.core.config import LensConfig, load_config_from_env
from autopsy.core.context import current_parent_id, current_session
from autopsy.core.decorator import LensDecorator
from autopsy.core.events import EventKind, LogEvent
from autopsy.core.ulid import new_ulid

__version__ = "0.2.0"

lens = LensDecorator(config=load_config_from_env())


def log(name: Any, /, **attributes: Any) -> None:
    """Emit a structured breadcrumb attached to the current session.

    No-op if there is no active autopsy session. Never raises.
    """
    try:
        session = current_session()
        if session is None:
            return
        ev = LogEvent(
            event_id=new_ulid(),
            parent_id=current_parent_id(),
            session_id=session.session_id,
            trace_id=session.session_id,
            timestamp_ns=__import__("time").time_ns(),
            kind=EventKind.LOG,
            name=str(name),
            attributes={k: v for k, v in attributes.items()},
        )
        session.record_event(ev)
    except Exception:
        return


__all__ = ["lens", "log", "LensConfig", "__version__"]
