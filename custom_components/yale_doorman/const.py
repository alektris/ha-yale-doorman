"""Constants for the Yale Doorman L3S integration."""

DOMAIN = "yale_doorman"

# Config flow keys
CONF_LOCAL_NAME = "local_name"
CONF_KEY = "key"
CONF_SLOT = "slot"

# Options flow keys
CONF_ALWAYS_CONNECTED = "always_connected"
CONF_ACTIVE_HOURS_START = "active_hours_start"
CONF_ACTIVE_HOURS_END = "active_hours_end"
CONF_ACTIVE_POLL_INTERVAL = "active_poll_interval"
CONF_IDLE_POLL_INTERVAL = "idle_poll_interval"

# Defaults
DEFAULT_ALWAYS_CONNECTED = True
DEFAULT_ACTIVE_HOURS_START = "06:00"
DEFAULT_ACTIVE_HOURS_END = "23:00"
DEFAULT_ACTIVE_POLL_INTERVAL = 120
DEFAULT_IDLE_POLL_INTERVAL = 1800

# Timeouts
DEVICE_TIMEOUT = 55
