"""Constants for the Yale Doorman L3S integration."""

DOMAIN = "yale_doorman"

# Config flow keys
CONF_LOCAL_NAME = "local_name"
CONF_KEY = "key"
CONF_SLOT = "slot"

# Options flow keys
CONF_ALWAYS_CONNECTED = "always_connected"
CONF_WEEKDAY_START = "weekday_start"
CONF_WEEKDAY_END = "weekday_end"
CONF_WEEKEND_START = "weekend_start"
CONF_WEEKEND_END = "weekend_end"
CONF_WEEKEND_DAYS = "weekend_days"

# Defaults
DEFAULT_ALWAYS_CONNECTED = True
DEFAULT_WEEKDAY_START = "06:00"
DEFAULT_WEEKDAY_END = "23:00"
DEFAULT_WEEKEND_START = "08:00"
DEFAULT_WEEKEND_END = "23:30"
DEFAULT_WEEKEND_DAYS = [4, 5]  # Fri, Sat

# Timeouts
DEVICE_TIMEOUT = 55
