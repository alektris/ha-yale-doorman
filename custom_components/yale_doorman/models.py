"""Data models for the Yale Doorman L3S integration."""

from __future__ import annotations

from dataclasses import dataclass

from yalexs_ble import PushLock


@dataclass
class YaleDoormanData:
    """Runtime data for the Yale Doorman integration."""

    title: str
    lock: PushLock
    always_connected: bool
