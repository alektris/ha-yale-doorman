"""State management and event logging for Yale Doorman L3S."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)


@dataclass
class DoormanState:
    """Current state of the Yale Doorman L3S."""

    lock_state: str = "unknown"       # locked, unlocked, locking, unlocking, jammed, unknown
    door_state: str = "unknown"       # open, closed, ajar, unknown
    battery_level: int | None = None  # 0-100 percentage
    battery_voltage: float | None = None
    doorbell_ringing: bool = False
    auto_lock_enabled: bool = False
    auto_lock_duration: int = 0
    connected: bool = False
    rssi: int | None = None           # Signal strength
    lock_model: str = ""
    lock_serial: str = ""
    lock_firmware: str = ""
    last_updated: str = ""
    last_activity: str = ""
    last_activity_type: str = ""       # lock, unlock, door_open, door_close, doorbell

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def copy(self) -> DoormanState:
        return DoormanState(**asdict(self))


@dataclass
class StateEvent:
    """A single state change event."""

    timestamp: str
    event_type: str          # lock_state, door_state, battery, doorbell, connection
    old_value: str
    new_value: str
    source: str = "ble"      # ble, poll, system

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventLog:
    """Append-only log of state change events."""

    def __init__(self, events_file: str, max_memory_events: int = 500):
        self._events_file = events_file
        self._max_memory = max_memory_events
        self._events: list[StateEvent] = []
        self._load_recent()

    def _load_recent(self) -> None:
        """Load recent events from disk."""
        if not os.path.exists(self._events_file):
            return
        try:
            with open(self._events_file) as f:
                lines = f.readlines()
            # Load last N events
            for line in lines[-self._max_memory:]:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    self._events.append(StateEvent(**data))
        except Exception as e:
            _LOGGER.warning("Error loading events: %s", e)

    def add(self, event: StateEvent) -> None:
        """Add an event to the log."""
        self._events.append(event)
        # Trim in-memory list
        if len(self._events) > self._max_memory:
            self._events = self._events[-self._max_memory:]
        # Append to file
        try:
            os.makedirs(os.path.dirname(self._events_file), exist_ok=True)
            with open(self._events_file, "a") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except Exception as e:
            _LOGGER.error("Error writing event: %s", e)

    def recent(self, count: int = 50) -> list[dict]:
        """Get the most recent events."""
        return [e.to_dict() for e in self._events[-count:]]


class StateManager:
    """Manages the current state and tracks changes."""

    def __init__(self, events_file: str):
        self.state = DoormanState()
        self.event_log = EventLog(events_file)
        self._callbacks: list = []

    def register_callback(self, callback) -> None:
        """Register a callback for state changes."""
        self._callbacks.append(callback)

    def _notify(self, event: StateEvent) -> None:
        """Notify all registered callbacks of a state change."""
        for cb in self._callbacks:
            try:
                cb(self.state, event)
            except Exception as e:
                _LOGGER.error("Error in state callback: %s", e)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def update_lock_state(self, new_state: str, source: str = "ble") -> bool:
        """Update lock state, returns True if changed."""
        if new_state == self.state.lock_state:
            return False
        old = self.state.lock_state
        self.state.lock_state = new_state
        self.state.last_updated = self._now()
        self.state.last_activity = self._now()
        self.state.last_activity_type = new_state
        event = StateEvent(
            timestamp=self._now(),
            event_type="lock_state",
            old_value=old,
            new_value=new_state,
            source=source,
        )
        self.event_log.add(event)
        self._notify(event)
        _LOGGER.info("Lock state: %s → %s (via %s)", old, new_state, source)
        return True

    def update_door_state(self, new_state: str, source: str = "ble") -> bool:
        """Update door state, returns True if changed."""
        if new_state == self.state.door_state:
            return False
        old = self.state.door_state
        self.state.door_state = new_state
        self.state.last_updated = self._now()
        self.state.last_activity = self._now()
        self.state.last_activity_type = f"door_{new_state}"
        event = StateEvent(
            timestamp=self._now(),
            event_type="door_state",
            old_value=old,
            new_value=new_state,
            source=source,
        )
        self.event_log.add(event)
        self._notify(event)
        _LOGGER.info("Door state: %s → %s (via %s)", old, new_state, source)
        return True

    def update_battery(
        self, level: int, voltage: float | None = None, source: str = "ble"
    ) -> bool:
        """Update battery level, returns True if changed."""
        if level == self.state.battery_level:
            return False
        old = str(self.state.battery_level) if self.state.battery_level is not None else "unknown"
        self.state.battery_level = level
        self.state.battery_voltage = voltage
        self.state.last_updated = self._now()
        event = StateEvent(
            timestamp=self._now(),
            event_type="battery",
            old_value=old,
            new_value=str(level),
            source=source,
        )
        self.event_log.add(event)
        self._notify(event)
        _LOGGER.info("Battery: %s%% → %s%% (via %s)", old, level, source)
        return True

    def update_doorbell(self, ringing: bool, source: str = "ble") -> bool:
        """Update doorbell state, returns True if changed."""
        if ringing == self.state.doorbell_ringing:
            return False
        old = "ringing" if self.state.doorbell_ringing else "idle"
        new = "ringing" if ringing else "idle"
        self.state.doorbell_ringing = ringing
        self.state.last_updated = self._now()
        if ringing:
            self.state.last_activity = self._now()
            self.state.last_activity_type = "doorbell"
        event = StateEvent(
            timestamp=self._now(),
            event_type="doorbell",
            old_value=old,
            new_value=new,
            source=source,
        )
        self.event_log.add(event)
        self._notify(event)
        _LOGGER.info("Doorbell: %s → %s (via %s)", old, new, source)
        return True

    def update_connection(self, connected: bool, rssi: int | None = None) -> None:
        """Update connection status."""
        changed = connected != self.state.connected
        self.state.connected = connected
        self.state.rssi = rssi
        self.state.last_updated = self._now()
        if changed:
            event = StateEvent(
                timestamp=self._now(),
                event_type="connection",
                old_value="connected" if not connected else "disconnected",
                new_value="connected" if connected else "disconnected",
                source="system",
            )
            self.event_log.add(event)
            self._notify(event)

    def update_lock_info(
        self, model: str = "", serial: str = "", firmware: str = ""
    ) -> None:
        """Update lock hardware info."""
        self.state.lock_model = model
        self.state.lock_serial = serial
        self.state.lock_firmware = firmware

    def update_auto_lock(self, enabled: bool, duration: int = 0) -> None:
        """Update auto-lock settings."""
        self.state.auto_lock_enabled = enabled
        self.state.auto_lock_duration = duration
