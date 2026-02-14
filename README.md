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

## Configuration

### Method 1: Auto-Discovery (Recommended)
1. Ensure your Yale Doorman L3S lock is within Bluetooth range of your Home Assistant server (or a Bluetooth proxy).
2. Go to **Settings > Devices & Services**.
3. You should see a new discovered device: **Yale Doorman**.
4. Click **Configure**.
5. If you have the **August** cloud integration installed and configured, the offline key may be automatically filled in for you.
   - If not, you will need to manually enter the **BLE Offline Key** (32-character hex) and **Slot**.
6. Submit the form.

### Method 2: Manual Setup
1. Go to **Settings > Devices & Services**.
2. Click **Add Integration** and search for **Yale Doorman L3S**.
3. Enter the **BLE Address** (e.g., `AA:BB:CC:DD:EE:FF`).
4. Enter the **BLE Offline Key** and **Slot**.
5. Submit.

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
