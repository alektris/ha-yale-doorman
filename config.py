"""Configuration for Yale Doorman L3S BLE Monitor."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_DATA_DIR = os.path.expanduser("~/.yale-doorman")
DEFAULT_CONFIG_FILE = os.path.join(DEFAULT_DATA_DIR, "config.json")
DEFAULT_WEB_PORT = 8099


@dataclass
class PollConfig:
    """Adaptive polling configuration."""

    quiet_interval_sec: int = 1800      # 30 minutes during quiet hours
    normal_interval_sec: int = 600      # 10 minutes normally
    active_interval_sec: int = 120      # 2 minutes after recent activity
    active_decay_sec: int = 600         # How long "active" mode lasts (10 min)
    battery_poll_interval_sec: int = 3600  # Battery changes slowly, poll hourly
    quiet_hours_start: int = 1          # 1 AM
    quiet_hours_end: int = 6            # 6 AM


@dataclass
class Config:
    """Main application configuration."""

    # Yale Home credentials (for initial key fetch)
    yale_username: str = ""
    yale_password: str = ""
    yale_login_method: str = "email"  # "email" or "phone"
    yale_brand: str = "yale_global"   # "yale_global" for European Yale

    # Lock identification
    lock_name: str = ""          # Local BLE name (e.g., "Aug-XXXX")
    lock_address: str = ""       # BLE MAC address
    lock_id: str = ""            # Yale cloud lock ID (auto-discovered)

    # BLE keys (auto-fetched from cloud)
    lock_key: str = ""
    lock_key_index: int = 0

    # Communication settings
    always_connected: bool = False     # False = disconnect/reconnect (saves battery)
    idle_disconnect_delay: float = 5.1  # Seconds before disconnect after operation

    # Polling
    poll: PollConfig = field(default_factory=PollConfig)

    # Web dashboard
    web_port: int = DEFAULT_WEB_PORT
    web_host: str = "0.0.0.0"

    # Paths
    data_dir: str = DEFAULT_DATA_DIR

    @property
    def keys_file(self) -> str:
        return os.path.join(self.data_dir, "keys.json")

    @property
    def events_file(self) -> str:
        return os.path.join(self.data_dir, "events.jsonl")

    @property
    def auth_cache_file(self) -> str:
        return os.path.join(self.data_dir, "auth_token.json")

    @property
    def config_file(self) -> str:
        return os.path.join(self.data_dir, "config.json")

    def save(self) -> None:
        """Save configuration to disk."""
        os.makedirs(self.data_dir, exist_ok=True)
        data = {
            "yale_username": self.yale_username,
            "yale_password": self.yale_password,
            "yale_login_method": self.yale_login_method,
            "yale_brand": self.yale_brand,
            "lock_name": self.lock_name,
            "lock_address": self.lock_address,
            "lock_id": self.lock_id,
            "lock_key": self.lock_key,
            "lock_key_index": self.lock_key_index,
            "always_connected": self.always_connected,
            "idle_disconnect_delay": self.idle_disconnect_delay,
            "web_port": self.web_port,
            "web_host": self.web_host,
            "poll": {
                "quiet_interval_sec": self.poll.quiet_interval_sec,
                "normal_interval_sec": self.poll.normal_interval_sec,
                "active_interval_sec": self.poll.active_interval_sec,
                "active_decay_sec": self.poll.active_decay_sec,
                "battery_poll_interval_sec": self.poll.battery_poll_interval_sec,
                "quiet_hours_start": self.poll.quiet_hours_start,
                "quiet_hours_end": self.poll.quiet_hours_end,
            },
        }
        with open(self.config_file, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, config_file: str | None = None) -> Config:
        """Load configuration from disk."""
        path = config_file or DEFAULT_CONFIG_FILE
        config = cls()
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            config.yale_username = data.get("yale_username", "")
            config.yale_password = data.get("yale_password", "")
            config.yale_login_method = data.get("yale_login_method", "email")
            config.yale_brand = data.get("yale_brand", "yale_global")
            config.lock_name = data.get("lock_name", "")
            config.lock_address = data.get("lock_address", "")
            config.lock_id = data.get("lock_id", "")
            config.lock_key = data.get("lock_key", "")
            config.lock_key_index = data.get("lock_key_index", 0)
            config.always_connected = data.get("always_connected", False)
            config.idle_disconnect_delay = data.get("idle_disconnect_delay", 5.1)
            config.web_port = data.get("web_port", DEFAULT_WEB_PORT)
            config.web_host = data.get("web_host", "0.0.0.0")
            if "poll" in data:
                poll_data = data["poll"]
                config.poll = PollConfig(
                    quiet_interval_sec=poll_data.get("quiet_interval_sec", 1800),
                    normal_interval_sec=poll_data.get("normal_interval_sec", 600),
                    active_interval_sec=poll_data.get("active_interval_sec", 120),
                    active_decay_sec=poll_data.get("active_decay_sec", 600),
                    battery_poll_interval_sec=poll_data.get(
                        "battery_poll_interval_sec", 3600
                    ),
                    quiet_hours_start=poll_data.get("quiet_hours_start", 1),
                    quiet_hours_end=poll_data.get("quiet_hours_end", 6),
                )
            # Override data_dir if the config was loaded from a non-default path
            if config_file:
                config.data_dir = str(Path(config_file).parent)
        return config
