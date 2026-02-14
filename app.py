#!/usr/bin/env python3
"""Yale Doorman L3S BLE Monitor – Main Entry Point.

Orchestrates BLE monitoring, adaptive polling, and the web dashboard.

Usage:
    python3 app.py                     # Run the full application
    python3 app.py --scan-only         # Scan for Yale BLE devices
    python3 app.py --auth-only         # Authenticate and discover locks
    python3 app.py --poll-once         # Connect, read state, and exit
    python3 app.py --setup             # Interactive setup wizard

Environment:
    YALE_USERNAME   Yale Home email (overrides config)
    YALE_PASSWORD   Yale Home password (overrides config)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys

from config import Config
from state import StateManager
from scheduler import AdaptiveScheduler
from ble_monitor import YaleBLEMonitor, scan_for_yale_locks
from dashboard import Dashboard
import auth

_LOGGER = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    # Reduce noise from libraries
    logging.getLogger("bleak").setLevel(logging.WARNING)
    logging.getLogger("yalexs_ble").setLevel(logging.INFO)
    logging.getLogger("yalexs_ble_adv").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


async def cmd_scan() -> None:
    """Scan for Yale BLE devices."""
    print("\n🔍 Scanning for Yale/August BLE devices...\n")
    devices = await scan_for_yale_locks(timeout=15.0)

    if not devices:
        print("❌ No Yale/August BLE devices found.")
        print("   Make sure the lock is powered on and in Bluetooth range.")
        print("   Tip: Some locks advertise as 'Aug-XXXX' or with a")
        print("   specific service UUID (0000fe24-...). Try moving closer.")
    else:
        print(f"\n✅ Found {len(devices)} device(s):\n")
        for d in devices:
            print(f"   Name:    {d['name']}")
            print(f"   Address: {d['address']}")
            print(f"   RSSI:    {d['rssi']} dBm")
            if d['service_uuids']:
                print(f"   UUIDs:   {', '.join(d['service_uuids'])}")
            print()


async def cmd_auth(config: Config) -> None:
    """Authenticate with Yale Home and discover locks."""
    if not config.yale_username or not config.yale_password:
        print("❌ Yale Home credentials not configured.")
        print("   Set them in the config or use --setup")
        return

    print("\n🔐 Authenticating with Yale Home cloud...\n")
    try:
        result = await auth.authenticate_and_get_locks(config)
        print(f"\n✅ Authentication successful!")
        print(f"   Found {len(result['locks'])} lock(s):")
        for lock in result['locks']:
            print(f"   - {lock['device_name']} ({lock['device_id']})")
            print(f"     Model: {lock.get('model', 'unknown')}")
            print(f"     Serial: {lock.get('serial', 'unknown')}")

        # Try to fetch BLE keys
        if result['locks']:
            config.lock_id = result['locks'][0]['device_id']
            config.save()
            print(f"\n   Auto-selected lock: {result['locks'][0]['device_name']}")

            key_data = await auth.fetch_ble_keys(config)
            if key_data:
                config.lock_key = key_data['key']
                config.lock_key_index = key_data['slot']
                config.save()
                print("   ✅ BLE keys obtained and cached!")
            else:
                print("   ⚠️  Could not auto-fetch BLE keys.")
                print("      You may need to provide them manually.")

    except Exception as e:
        print(f"❌ Authentication failed: {e}")


async def cmd_poll_once(config: Config) -> None:
    """Connect to the lock, read state, and exit."""
    if not config.lock_key:
        print("❌ No BLE key configured. Run --auth-only first.")
        return

    print("\n📡 Connecting to lock and reading state...\n")

    state_mgr = StateManager(config.events_file)
    monitor = YaleBLEMonitor(config, state_mgr)

    update_received = asyncio.Event()

    def on_change(state, event):
        update_received.set()

    state_mgr.register_callback(on_change)

    await monitor.start()

    # Wait for first update
    try:
        await asyncio.wait_for(update_received.wait(), timeout=30.0)
    except asyncio.TimeoutError:
        print("⏳ Timeout waiting for lock response. The lock may be out of range.")
        await monitor.stop()
        return

    # Give a moment for all state to arrive
    await asyncio.sleep(3)

    state = state_mgr.state
    print(f"   Lock:     {state.lock_state}")
    print(f"   Door:     {state.door_state}")
    print(f"   Battery:  {state.battery_level}%" if state.battery_level else "   Battery:  Unknown")
    print(f"   Doorbell: {'Ringing' if state.doorbell_ringing else 'Idle'}")
    print(f"   Model:    {state.lock_model}")
    print(f"   Serial:   {state.lock_serial}")
    print(f"   RSSI:     {state.rssi} dBm" if state.rssi else "   RSSI:     Unknown")
    print()

    await monitor.stop()


async def cmd_setup(config: Config) -> None:
    """Interactive setup wizard."""
    print("\n🔧 Yale Doorman L3S BLE Monitor – Setup\n")
    print("This wizard will help you configure the app.\n")

    # Yale Home credentials
    print("Step 1: Yale Home credentials")
    print("  These are used once to fetch BLE encryption keys.\n")
    username = input(f"  Email [{config.yale_username or 'none'}]: ").strip()
    if username:
        config.yale_username = username

    password = input(f"  Password [{'*****' if config.yale_password else 'none'}]: ").strip()
    if password:
        config.yale_password = password

    method = input(f"  Login method (email/phone) [{config.yale_login_method}]: ").strip()
    if method in ("email", "phone"):
        config.yale_login_method = method

    brand = input(f"  Brand (yale_global/yale_home/august) [{config.yale_brand}]: ").strip()
    if brand:
        config.yale_brand = brand

    # Lock address
    print("\nStep 2: Lock identification")
    print("  Run --scan-only to find your lock's BLE address.\n")
    address = input(f"  BLE MAC address [{config.lock_address or 'auto'}]: ").strip()
    if address:
        config.lock_address = address

    name = input(f"  BLE local name [{config.lock_name or 'auto'}]: ").strip()
    if name:
        config.lock_name = name

    # Web dashboard
    print("\nStep 3: Web dashboard")
    port = input(f"  Dashboard port [{config.web_port}]: ").strip()
    if port and port.isdigit():
        config.web_port = int(port)

    # Save
    os.makedirs(config.data_dir, exist_ok=True)
    config.save()
    print(f"\n✅ Configuration saved to {config.config_file}")
    print(f"   Data directory: {config.data_dir}\n")

    # Offer to authenticate
    if config.yale_username and config.yale_password:
        do_auth = input("  Authenticate now and fetch BLE keys? (y/n): ").strip().lower()
        if do_auth == 'y':
            await cmd_auth(config)


async def run_app(config: Config) -> None:
    """Run the full application."""
    if not config.lock_key:
        if not config.lock_address and not config.lock_name:
            print("❌ No lock configured. Run with --setup first.")
            return
        print("⚠️  No BLE key configured. The app will start but cannot")
        print("   communicate with the lock until keys are provided.")
        print("   Run with --auth-only to obtain keys.\n")

    state_mgr = StateManager(config.events_file)
    scheduler = AdaptiveScheduler(config.poll)
    monitor = YaleBLEMonitor(config, state_mgr)
    dashboard = Dashboard(
        state_mgr, scheduler,
        host=config.web_host,
        port=config.web_port,
    )
    dashboard.set_diagnostics_callback(monitor.get_diagnostics)

    # Wire up activity callback to scheduler
    monitor.register_activity_callback(scheduler.on_activity)

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def handle_signal():
        _LOGGER.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    # Start components
    _LOGGER.info("Starting Yale Doorman L3S BLE Monitor...")
    await dashboard.start()

    if config.lock_key:
        await monitor.start()

    # Run scheduler and poll callback
    async def poll_callback():
        """Called by the scheduler to trigger a poll."""
        await monitor.poll_state()

    scheduler_task = asyncio.create_task(scheduler.run(poll_callback))

    _LOGGER.info(
        "App running. Dashboard: http://%s:%d",
        config.web_host,
        config.web_port,
    )

    # Wait for shutdown
    await shutdown_event.wait()

    # Cleanup
    _LOGGER.info("Shutting down...")
    scheduler.stop()
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    await monitor.stop()
    await dashboard.stop()
    _LOGGER.info("Shutdown complete.")


def main():
    parser = argparse.ArgumentParser(
        description="Yale Doorman L3S BLE Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config", "-c",
        help="Path to config file",
        default=None,
    )
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="Scan for Yale BLE devices and exit",
    )
    parser.add_argument(
        "--auth-only",
        action="store_true",
        help="Authenticate with Yale Home and exit",
    )
    parser.add_argument(
        "--poll-once",
        action="store_true",
        help="Connect, read state, and exit",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Interactive setup wizard",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose logging",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        help="Override dashboard port",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    config = Config.load(args.config)

    # Environment variable overrides
    if os.environ.get("YALE_USERNAME"):
        config.yale_username = os.environ["YALE_USERNAME"]
    if os.environ.get("YALE_PASSWORD"):
        config.yale_password = os.environ["YALE_PASSWORD"]
    if args.port:
        config.web_port = args.port

    if args.scan_only:
        asyncio.run(cmd_scan())
    elif args.auth_only:
        asyncio.run(cmd_auth(config))
    elif args.poll_once:
        asyncio.run(cmd_poll_once(config))
    elif args.setup:
        asyncio.run(cmd_setup(config))
    else:
        asyncio.run(run_app(config))


if __name__ == "__main__":
    main()
