"""Adaptive polling scheduler for Yale Doorman L3S BLE Monitor.

Adjusts poll frequency based on time-of-day and recent activity to
minimize battery drain on the lock while staying responsive.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from config import PollConfig

_LOGGER = logging.getLogger(__name__)


class AdaptiveScheduler:
    """Manages adaptive polling intervals."""

    def __init__(self, poll_config: PollConfig):
        self._config = poll_config
        self._last_activity_time: float = 0
        self._last_poll_time: float = 0
        self._last_battery_poll_time: float = 0
        self._poll_task: asyncio.Task | None = None
        self._running = False
        self._poll_callback = None

    def on_activity(self) -> None:
        """Called when any lock activity is detected.

        Switches to high-frequency polling temporarily.
        """
        self._last_activity_time = time.monotonic()
        _LOGGER.debug("Activity detected, switching to active polling")

    def _is_quiet_hours(self) -> bool:
        """Check if we're in quiet hours."""
        hour = datetime.now().hour
        start = self._config.quiet_hours_start
        end = self._config.quiet_hours_end
        if start < end:
            return start <= hour < end
        else:
            # Wraps around midnight
            return hour >= start or hour < end

    def _is_active_mode(self) -> bool:
        """Check if we're in active mode (recent activity)."""
        if self._last_activity_time == 0:
            return False
        elapsed = time.monotonic() - self._last_activity_time
        return elapsed < self._config.active_decay_sec

    def get_next_poll_interval(self) -> float:
        """Calculate the next poll interval in seconds."""
        if self._is_active_mode():
            interval = self._config.active_interval_sec
            mode = "active"
        elif self._is_quiet_hours():
            interval = self._config.quiet_interval_sec
            mode = "quiet"
        else:
            interval = self._config.normal_interval_sec
            mode = "normal"

        _LOGGER.debug(
            "Poll mode: %s, interval: %ds", mode, interval
        )
        return float(interval)

    def should_poll_battery(self) -> bool:
        """Check if it's time to poll battery (separate, slower interval)."""
        if self._last_battery_poll_time == 0:
            return True
        elapsed = time.monotonic() - self._last_battery_poll_time
        return elapsed >= self._config.battery_poll_interval_sec

    def mark_polled(self) -> None:
        """Mark that a poll just occurred."""
        self._last_poll_time = time.monotonic()

    def mark_battery_polled(self) -> None:
        """Mark that a battery poll just occurred."""
        self._last_battery_poll_time = time.monotonic()

    async def run(self, poll_callback) -> None:
        """Run the adaptive polling loop."""
        self._poll_callback = poll_callback
        self._running = True
        _LOGGER.info("Adaptive scheduler started")

        while self._running:
            interval = self.get_next_poll_interval()
            try:
                await asyncio.sleep(interval)
                if self._running and self._poll_callback:
                    try:
                        await self._poll_callback()
                        self.mark_polled()
                    except Exception as e:
                        _LOGGER.error("Poll callback error: %s", e)
            except asyncio.CancelledError:
                break

        _LOGGER.info("Adaptive scheduler stopped")

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()

    def get_status(self) -> dict:
        """Get scheduler status for diagnostics."""
        return {
            "mode": (
                "active" if self._is_active_mode()
                else "quiet" if self._is_quiet_hours()
                else "normal"
            ),
            "next_interval_sec": self.get_next_poll_interval(),
            "last_activity_ago_sec": (
                round(time.monotonic() - self._last_activity_time, 1)
                if self._last_activity_time else None
            ),
            "last_poll_ago_sec": (
                round(time.monotonic() - self._last_poll_time, 1)
                if self._last_poll_time else None
            ),
            "should_poll_battery": self.should_poll_battery(),
        }
