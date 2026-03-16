"""Notification bus — publish/subscribe for pipeline events.

Phase 3 provides a SQLite-backed implementation (polling).  A Redis
implementation can be swapped in via ``config.yaml`` when scaling is needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from crew.db.store import TaskStore

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """A single pipeline event."""

    task_id: str
    event: str
    payload: dict[str, Any]


class NotificationBus(ABC):
    """Abstract notification bus."""

    @abstractmethod
    async def publish(self, task_id: str, event: str, payload: dict[str, Any]) -> None:
        """Publish an event."""

    @abstractmethod
    async def subscribe(
        self,
        task_id: str,
        poll_interval: float = 1.0,
    ) -> AsyncIterator[Event]:
        """Yield events for *task_id* as they arrive."""
        ...  # pragma: no cover


class SQLiteNotificationBus(NotificationBus):
    """Notification bus backed by the SQLite ``notifications`` table.

    Subscribing polls the table at *poll_interval* seconds.  This is simple
    and adequate for single-machine / low-concurrency deployments.  For higher
    throughput, swap in ``RedisNotificationBus``.
    """

    def __init__(self, store: TaskStore) -> None:
        self._store = store

    async def publish(self, task_id: str, event: str, payload: dict[str, Any]) -> None:
        self._store.push_notification(task_id, event, payload)

    async def subscribe(
        self,
        task_id: str,
        poll_interval: float = 1.0,
    ) -> AsyncIterator[Event]:
        """Poll for new notifications and yield them."""
        last_id = 0
        while True:
            notifications = self._store.get_unconsumed_notifications(task_id, since_id=last_id)
            for n in notifications:
                payload = json.loads(n.payload) if n.payload else {}
                yield Event(task_id=n.task_id, event=n.event, payload=payload)
                last_id = max(last_id, n.id)
            await asyncio.sleep(poll_interval)


def create_notification_bus(
    bus_type: str,
    store: TaskStore | None = None,
) -> NotificationBus:
    """Factory function for notification bus creation.

    ``bus_type`` is ``"sqlite"`` (default) or ``"redis"`` (not yet implemented).
    """
    if bus_type == "sqlite":
        if store is None:
            raise ValueError("SQLite notification bus requires a TaskStore instance")
        return SQLiteNotificationBus(store)
    raise ValueError(f"Unknown notification bus type: {bus_type!r}. Use 'sqlite'.")
