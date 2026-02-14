# Yale Doorman L3S — Home Assistant Custom Integration

Custom Home Assistant integration for the **Yale Doorman L3S** smart lock via Bluetooth Low Energy (BLE).

Provides real-time lock state, door sensor, battery monitoring, and lock/unlock control — all over direct BLE communication using offline keys (no cloud dependency).

## Features

- 🔒 **Lock Entity** — Lock, unlock, and secure mode control
- 🚪 **Door Sensor** — Real-time open/closed detection
- 🔋 **Battery Sensors** — Battery percentage and voltage
- 📡 **Signal Strength** — BLE RSSI monitoring
- 🔔 **Doorbell Sensor** — Ring detection (if supported)
- ⏰ **Active Hours** — Configurable always-connected window to save battery
- 📊 **Polling** — Configurable fallback polling outside active hours

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots → **Custom repositories**
3. Add this repository URL as **Integration**
4. Search for "Yale Doorman" and install
5. Restart Home Assistant

### Manual

1. Copy `custom_components/yale_doorman/` to your HA `custom_components/` directory
2. Restart Home Assistant

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Yale Doorman L3S**
3. Enter your lock's BLE details:
   - **BLE Address** — MAC address (e.g. `98:1B:B5:B0:8C:A9`)
   - **Local Name** — BLE broadcast name (e.g. `L700RXG`)
   - **BLE Key** — 32-character hex offline key
   - **Key Slot** — Key index (usually `1`)

### Getting Your BLE Key

The BLE offline key can be extracted from Home Assistant's built-in Yale integration debug logs:

1. Temporarily add the official Yale integration in HA
2. Enable debug logging for `yalexs_ble`
3. Look for `offline_key` and `slot` in the logs
4. Remove the official integration and use this custom one instead

## Configuration Options

After setup, click **Configure** on the integration to adjust:

| Option | Default | Description |
|--------|---------|-------------|
| Always Connected | On | Stay connected for real-time events |
| Active Hours Start | 06:00 | When to enable always-connected mode |
| Active Hours End | 23:00 | When to switch to polling mode |
| Active Poll Interval | 120s | Poll interval during active hours |
| Idle Poll Interval | 1800s | Poll interval outside active hours |

## Requirements

- Home Assistant 2024.1 or newer
- Bluetooth adapter accessible to HA
- Yale Doorman L3S lock with BLE offline key

## License

MIT
