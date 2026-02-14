"""Web dashboard for Yale Doorman L3S BLE Monitor.

Provides a real-time web interface with Server-Sent Events (SSE)
for live sensor data updates.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from aiohttp import web

from state import StateManager, StateEvent, DoormanState
from scheduler import AdaptiveScheduler

_LOGGER = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class Dashboard:
    """Web dashboard with SSE for live updates."""

    def __init__(
        self,
        state_manager: StateManager,
        scheduler: AdaptiveScheduler,
        host: str = "0.0.0.0",
        port: int = 8099,
    ):
        self._state = state_manager
        self._scheduler = scheduler
        self._host = host
        self._port = port
        self._app = web.Application()
        self._runner: web.AppRunner | None = None
        self._sse_clients: list[web.StreamResponse] = []
        self._diagnostics_callback = None

        # Register state change callback for SSE
        self._state.register_callback(self._on_state_change)

        # Setup routes
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/api/state", self._handle_state)
        self._app.router.add_get("/api/events", self._handle_events)
        self._app.router.add_get("/api/events/stream", self._handle_sse)
        self._app.router.add_get("/api/diagnostics", self._handle_diagnostics)
        self._app.router.add_static("/static", STATIC_DIR, show_index=False)

    def set_diagnostics_callback(self, callback) -> None:
        """Set a callback to get diagnostics from other components."""
        self._diagnostics_callback = callback

    def _on_state_change(self, state: DoormanState, event: StateEvent) -> None:
        """Push state update to all SSE clients."""
        data = {
            "type": "state_update",
            "state": state.to_dict(),
            "event": event.to_dict(),
        }
        asyncio.ensure_future(self._broadcast_sse(data))

    async def _broadcast_sse(self, data: dict) -> None:
        """Send data to all connected SSE clients."""
        payload = f"data: {json.dumps(data)}\n\n"
        dead_clients = []

        for client in self._sse_clients:
            try:
                await client.write(payload.encode("utf-8"))
            except (ConnectionResetError, ConnectionAbortedError, Exception):
                dead_clients.append(client)

        for client in dead_clients:
            self._sse_clients.remove(client)

    async def _handle_index(self, request: web.Request) -> web.Response:
        """Serve the dashboard HTML page."""
        index_path = os.path.join(STATIC_DIR, "index.html")
        if os.path.exists(index_path):
            return web.FileResponse(index_path)
        return web.Response(text="Dashboard HTML not found", status=404)

    async def _handle_state(self, request: web.Request) -> web.Response:
        """Return current state as JSON."""
        return web.json_response({
            "state": self._state.state.to_dict(),
            "scheduler": self._scheduler.get_status(),
        })

    async def _handle_events(self, request: web.Request) -> web.Response:
        """Return recent events as JSON."""
        count = int(request.query.get("count", "50"))
        return web.json_response({
            "events": self._state.event_log.recent(count),
        })

    async def _handle_diagnostics(self, request: web.Request) -> web.Response:
        """Return diagnostics info."""
        diag = {
            "scheduler": self._scheduler.get_status(),
            "sse_clients": len(self._sse_clients),
        }
        if self._diagnostics_callback:
            diag["ble"] = self._diagnostics_callback()
        return web.json_response(diag)

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        """Handle SSE connection from browser."""
        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
            },
        )
        await response.prepare(request)

        # Send current state immediately
        initial = {
            "type": "initial_state",
            "state": self._state.state.to_dict(),
            "events": self._state.event_log.recent(20),
        }
        await response.write(f"data: {json.dumps(initial)}\n\n".encode("utf-8"))

        self._sse_clients.append(response)
        _LOGGER.debug("SSE client connected (%d total)", len(self._sse_clients))

        try:
            # Keep connection alive with heartbeats
            while True:
                await asyncio.sleep(30)
                try:
                    await response.write(b": heartbeat\n\n")
                except (ConnectionResetError, ConnectionAbortedError):
                    break
        except asyncio.CancelledError:
            pass
        finally:
            if response in self._sse_clients:
                self._sse_clients.remove(response)
            _LOGGER.debug(
                "SSE client disconnected (%d remaining)", len(self._sse_clients)
            )

        return response

    async def start(self) -> None:
        """Start the web server."""
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        _LOGGER.info(
            "Dashboard running at http://%s:%d",
            self._host,
            self._port,
        )

    async def stop(self) -> None:
        """Stop the web server."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        _LOGGER.info("Dashboard stopped")
