"""Authentication module for Yale Home cloud API.

Handles two authentication paths:
1. Session-based auth (for yale_home, august, yale_access brands)
2. OAuth2 Authorization Code flow (for yale_global, yale_august brands)

For OAuth2, we start a temporary local HTTP server to capture the
authorization callback, then exchange the code for access tokens.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
import uuid
import webbrowser
from copy import copy
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

from yalexs.api_async import ApiAsync
from yalexs.authenticator_async import AuthenticatorAsync
from yalexs.authenticator_common import AuthenticationState
from yalexs.const import BRAND_CONFIG, Brand, BrandConfig

from config import Config

_LOGGER = logging.getLogger(__name__)

# OAuth2 endpoints for Yale/August ecosystem
OAUTH2_AUTHORIZE = "https://oauth.aaecosystem.com/authorize"
OAUTH2_TOKEN = "https://oauth.aaecosystem.com/access_token"
LOCAL_REDIRECT_PORT = 8976


def _get_redirect_uri() -> str:
    """Build redirect URI using the server's LAN IP address.

    Uses the IP address rather than hostname because mDNS (.local)
    hostnames may not resolve from all devices on the network.
    """
    import socket
    try:
        # Get the LAN IP by connecting to an external address
        # (no actual traffic is sent)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return f"http://{ip}:{LOCAL_REDIRECT_PORT}/callback"
    except Exception:
        pass
    return f"http://localhost:{LOCAL_REDIRECT_PORT}/callback"


def _get_install_id(data_dir: str) -> str:
    """Get or create a persistent install ID."""
    install_id_file = os.path.join(data_dir, "install_id")
    if os.path.exists(install_id_file):
        with open(install_id_file) as f:
            return f.read().strip()
    install_id = str(uuid.uuid4())
    os.makedirs(data_dir, exist_ok=True)
    with open(install_id_file, "w") as f:
        f.write(install_id)
    return install_id


def _brand_requires_oauth(brand: str) -> bool:
    """Check if a brand needs OAuth authentication."""
    try:
        brand_enum = Brand(brand)
        config = BRAND_CONFIG.get(brand_enum)
        return config.require_oauth if config else False
    except ValueError:
        return False


# ─── OAuth2 Authorization Code Flow ──────────────────────────────

class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth2 callback redirect."""

    auth_code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "error" in params:
            _OAuthCallbackHandler.error = params["error"][0]
            self._respond(
                "❌ Authentication Error",
                f"Error: {params['error'][0]}. "
                f"Description: {params.get('error_description', ['Unknown'])[0]}",
            )
        elif "code" in params:
            _OAuthCallbackHandler.auth_code = params["code"][0]
            _OAuthCallbackHandler.state = params.get("state", [None])[0]
            self._respond(
                "✅ Authentication Successful",
                "You can close this browser tab and return to the terminal.",
            )
        else:
            self._respond("❓ Unexpected Response", f"Parameters: {params}")

    def _respond(self, title: str, message: str):
        html = f"""<!DOCTYPE html>
<html>
<head><title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif;
       display: flex; justify-content: center; align-items: center;
       height: 100vh; margin: 0; background: #0a0e1a; color: #f3f4f6; }}
.card {{ background: rgba(17,24,39,0.8); border: 1px solid rgba(75,85,99,0.3);
         border-radius: 16px; padding: 40px; text-align: center; max-width: 400px; }}
h1 {{ font-size: 1.5rem; margin-bottom: 12px; }}
p {{ color: #9ca3af; font-size: 0.9rem; }}
</style></head>
<body><div class="card"><h1>{title}</h1><p>{message}</p></div></body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass  # Suppress access logs


async def _oauth2_authenticate(config: Config) -> dict | None:
    """Perform OAuth2 Authorization Code flow.

    Supports two modes:
    1. Local callback server — browser redirects to this machine
    2. Manual URL paste — user copies the redirect URL from their
       browser (for headless servers)

    Returns dict with 'access_token' and 'refresh_token' on success.
    """
    import base64

    redirect_uri = _get_redirect_uri()

    brand = config.yale_brand
    try:
        brand_enum = Brand(brand)
        brand_config = BRAND_CONFIG.get(brand_enum)
    except ValueError:
        _LOGGER.error("Unknown brand: %s", brand)
        return None

    client_id = brand_config.api_key
    state = secrets.token_urlsafe(32)

    # PKCE (Proof Key for Code Exchange)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge_b64 = (
        base64.urlsafe_b64encode(code_challenge)
        .rstrip(b"=")
        .decode()
    )

    # Build authorization URL
    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge_b64,
        "code_challenge_method": "S256",
    }
    auth_url = f"{OAUTH2_AUTHORIZE}?{urlencode(auth_params)}"

    # Reset handler state
    _OAuthCallbackHandler.auth_code = None
    _OAuthCallbackHandler.state = None
    _OAuthCallbackHandler.error = None

    # Start local callback server (bind to 0.0.0.0 for network access)
    server = None
    try:
        server = HTTPServer(("0.0.0.0", LOCAL_REDIRECT_PORT), _OAuthCallbackHandler)
        server_thread = Thread(target=server.handle_request, daemon=True)
        server_thread.start()
        _LOGGER.debug("OAuth callback server started on port %d", LOCAL_REDIRECT_PORT)
    except OSError as e:
        _LOGGER.warning("Could not start callback server: %s", e)

    print(f"\n{'='*60}")
    print(f"🔐 Yale OAuth2 Authentication")
    print(f"{'='*60}\n")
    print(f"1. Open this URL in any browser (phone, laptop, etc.):\n")
    print(f"   {auth_url}\n")
    print(f"2. Log in with your Yale Home credentials.")
    print(f"3. After authorizing, your browser will redirect to a URL")
    print(f"   starting with: {redirect_uri}?code=...\n")

    if server:
        print(f"   If you're on the SAME machine, this should happen")
        print(f"   automatically.\n")

    print(f"   If you're on a DIFFERENT device (e.g., phone), the")
    print(f"   redirect page won't load. That's OK!")
    print(f"   Just copy the FULL URL from your browser's address bar")
    print(f"   and paste it below.\n")
    print(f"{'='*60}")

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    # Wait for callback OR manual input
    auth_code = None

    # Use a thread to read manual input while waiting for callback
    manual_input = {"url": None}

    def _read_manual_input():
        try:
            url = input("\n   Paste redirect URL here (or press Enter to wait): ").strip()
            if url:
                manual_input["url"] = url
        except (EOFError, KeyboardInterrupt):
            pass

    input_thread = Thread(target=_read_manual_input, daemon=True)
    input_thread.start()

    timeout = 300
    start = time.time()
    while time.time() - start < timeout:
        # Check callback server
        if _OAuthCallbackHandler.auth_code is not None:
            auth_code = _OAuthCallbackHandler.auth_code
            break
        if _OAuthCallbackHandler.error is not None:
            _LOGGER.error("OAuth2 error: %s", _OAuthCallbackHandler.error)
            if server:
                server.server_close()
            return None

        # Check manual input
        if manual_input["url"]:
            parsed = urlparse(manual_input["url"])
            params = parse_qs(parsed.query)
            if "code" in params:
                auth_code = params["code"][0]
                break
            elif "error" in params:
                _LOGGER.error("OAuth2 error: %s", params["error"][0])
                if server:
                    server.server_close()
                return None

        await asyncio.sleep(0.5)

    if server:
        server.server_close()

    if auth_code is None:
        _LOGGER.error("OAuth2 timeout: No authorization code received")
        return None

    print(f"\n   ✅ Authorization code received!")

    # Exchange authorization code for tokens
    token_data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(OAUTH2_TOKEN, data=token_data) as resp:
            if resp.status != 200:
                body = await resp.text()
                _LOGGER.error(
                    "Token exchange failed (HTTP %d): %s", resp.status, body
                )
                return None

            tokens = await resp.json()
            _LOGGER.info("OAuth2 token exchange successful")

            # Cache the tokens
            token_file = os.path.join(config.data_dir, "oauth_tokens.json")
            tokens["obtained_at"] = time.time()
            with open(token_file, "w") as f:
                json.dump(tokens, f, indent=2)
            _LOGGER.info("OAuth2 tokens cached to %s", token_file)

            return tokens


async def _refresh_oauth_token(config: Config) -> dict | None:
    """Refresh an expired OAuth2 access token."""
    token_file = os.path.join(config.data_dir, "oauth_tokens.json")
    if not os.path.exists(token_file):
        return None

    with open(token_file) as f:
        tokens = json.load(f)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return None

    try:
        brand_enum = Brand(config.yale_brand)
        brand_config = BRAND_CONFIG.get(brand_enum)
        client_id = brand_config.api_key
    except (ValueError, AttributeError):
        return None

    token_data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(OAUTH2_TOKEN, data=token_data) as resp:
            if resp.status != 200:
                _LOGGER.warning("Token refresh failed (HTTP %d)", resp.status)
                return None

            new_tokens = await resp.json()
            new_tokens["obtained_at"] = time.time()
            # Keep refresh token if not returned
            if "refresh_token" not in new_tokens:
                new_tokens["refresh_token"] = refresh_token
            with open(token_file, "w") as f:
                json.dump(new_tokens, f, indent=2)
            _LOGGER.info("OAuth2 token refreshed")
            return new_tokens


async def _get_oauth_access_token(config: Config) -> str | None:
    """Get a valid OAuth2 access token, refreshing if needed."""
    token_file = os.path.join(config.data_dir, "oauth_tokens.json")
    if not os.path.exists(token_file):
        return None

    with open(token_file) as f:
        tokens = json.load(f)

    access_token = tokens.get("access_token")
    expires_in = tokens.get("expires_in", 3600)
    obtained_at = tokens.get("obtained_at", 0)

    # Check if token is still valid (with 5 minute buffer)
    if time.time() < obtained_at + expires_in - 300:
        return access_token

    # Try to refresh
    _LOGGER.info("OAuth2 token expired, refreshing...")
    new_tokens = await _refresh_oauth_token(config)
    if new_tokens:
        return new_tokens.get("access_token")

    return None


# ─── Session-based Auth (for non-OAuth brands) ──────────────────

async def _session_authenticate(
    session: aiohttp.ClientSession, config: Config
) -> tuple[ApiAsync, object] | None:
    """Authenticate using session-based auth (non-OAuth brands)."""
    install_id = _get_install_id(config.data_dir)

    try:
        api = ApiAsync(session, brand=config.yale_brand)
        authenticator = AuthenticatorAsync(
            api,
            login_method=config.yale_login_method,
            username=config.yale_username,
            password=config.yale_password,
            install_id=install_id,
            access_token_cache_file=config.auth_cache_file,
        )

        await authenticator.async_setup_authentication()
        authentication = await authenticator.async_authenticate()

        if authentication.state == AuthenticationState.REQUIRES_VALIDATION:
            _LOGGER.info(
                "Verification code required. Check your %s for a code.",
                config.yale_login_method,
            )
            code = input("Enter verification code: ").strip()
            result = await authenticator.async_validate_verification_code(code)
            _LOGGER.info("Validation result: %s", result)
            authentication = await authenticator.async_authenticate()

        if authentication.state == AuthenticationState.AUTHENTICATED:
            _LOGGER.info("Session-based authentication successful")
            return api, authentication

        _LOGGER.warning(
            "Session auth failed: %s", authentication.state
        )
        return None

    except Exception as e:
        _LOGGER.warning("Session auth error: %s", e)
        return None


# ─── Public API ──────────────────────────────────────────────────

async def authenticate_and_get_locks(config: Config) -> dict:
    """Authenticate with Yale Home cloud and discover locks.

    Returns a dict with lock details including BLE keys.
    """
    os.makedirs(config.data_dir, exist_ok=True)

    if _brand_requires_oauth(config.yale_brand):
        # OAuth2 flow
        _LOGGER.info("Brand '%s' requires OAuth2 authentication", config.yale_brand)

        # Check for existing valid token first
        access_token = await _get_oauth_access_token(config)
        if not access_token:
            tokens = await _oauth2_authenticate(config)
            if not tokens:
                raise RuntimeError(
                    "OAuth2 authentication failed. Please try again."
                )
            access_token = tokens["access_token"]

        # Use the OAuth token with the API
        async with aiohttp.ClientSession() as session:
            api = ApiAsync(session, brand=config.yale_brand)
            # Patch brand config to skip OAuth check for API calls
            api.brand_config = BrandConfig(
                name=api.brand_config.name,
                branding=api.brand_config.branding,
                access_token_header=api.brand_config.access_token_header,
                api_key_header=api.brand_config.api_key_header,
                branding_header=api.brand_config.branding_header,
                api_key=api.brand_config.api_key,
                supports_doorbells=api.brand_config.supports_doorbells,
                supports_alarms=api.brand_config.supports_alarms,
                require_oauth=False,
                base_url=api.brand_config.base_url,
                configuration_url=api.brand_config.configuration_url,
                pubnub_subscribe_token=api.brand_config.pubnub_subscribe_token,
                pubnub_publish_token=api.brand_config.pubnub_publish_token,
            )

            return await _fetch_locks_with_token(api, access_token)
    else:
        # Session-based auth
        async with aiohttp.ClientSession() as session:
            result = await _session_authenticate(session, config)
            if not result:
                raise RuntimeError(
                    "Authentication failed. Please check your credentials."
                )
            api, authentication = result
            return await _fetch_locks_with_token(api, authentication.access_token)


async def _fetch_locks_with_token(api: ApiAsync, access_token: str) -> dict:
    """Fetch lock details using an access token."""
    locks = await api.async_get_locks(access_token)

    if not locks:
        raise RuntimeError("No locks found on your Yale Home account")

    _LOGGER.info("Found %d lock(s):", len(locks))
    lock_details = []
    for lock in locks:
        detail = await api.async_get_lock_detail(access_token, lock.device_id)
        _LOGGER.info(
            "  - %s (ID: %s, Model: %s)",
            lock.device_name,
            lock.device_id,
            getattr(detail, "model", "unknown"),
        )
        lock_details.append({
            "device_id": lock.device_id,
            "device_name": lock.device_name,
            "serial": getattr(lock, "serial_number", ""),
            "model": getattr(detail, "model", ""),
            "mac_address": getattr(detail, "mac_address", ""),
        })

    # Attempt to get BLE keys via the operable locks endpoint
    operable_locks = await api.async_get_operable_locks(access_token)
    _LOGGER.info(
        "Found %d operable lock(s) with BLE keys", len(operable_locks)
    )

    return {
        "access_token": access_token,
        "locks": lock_details,
        "operable_locks": [
            {
                "device_id": l.device_id,
                "device_name": l.device_name,
                "serial": getattr(l, "serial_number", ""),
            }
            for l in operable_locks
        ],
    }


async def fetch_ble_keys(config: Config) -> dict | None:
    """Fetch BLE keys from the cloud and cache them locally.

    Returns dict with 'key' and 'slot' if successful.
    """
    # Check cache first
    if os.path.exists(config.keys_file):
        with open(config.keys_file) as f:
            cached = json.load(f)
        if cached.get("key") and cached.get("slot") is not None:
            _LOGGER.info("Using cached BLE keys from %s", config.keys_file)
            return cached

    _LOGGER.info("Fetching BLE keys from Yale Home cloud...")

    try:
        result = await authenticate_and_get_locks(config)
        access_token = result["access_token"]
    except RuntimeError as e:
        _LOGGER.error("Authentication failed: %s", e)
        return None

    lock_id = config.lock_id
    if not lock_id and result["locks"]:
        lock_id = result["locks"][0]["device_id"]
        _LOGGER.info(
            "Auto-selected lock: %s (%s)",
            result["locks"][0]["device_name"],
            lock_id,
        )

    if not lock_id:
        _LOGGER.error("No lock found")
        return None

    # Try to get lock detail with BLE keys
    async with aiohttp.ClientSession() as session:
        api = ApiAsync(session, brand=config.yale_brand)
        # Patch for OAuth brands
        if _brand_requires_oauth(config.yale_brand):
            api.brand_config = BrandConfig(
                name=api.brand_config.name,
                branding=api.brand_config.branding,
                access_token_header=api.brand_config.access_token_header,
                api_key_header=api.brand_config.api_key_header,
                branding_header=api.brand_config.branding_header,
                api_key=api.brand_config.api_key,
                supports_doorbells=api.brand_config.supports_doorbells,
                supports_alarms=api.brand_config.supports_alarms,
                require_oauth=False,
                base_url=api.brand_config.base_url,
                configuration_url=api.brand_config.configuration_url,
                pubnub_subscribe_token=api.brand_config.pubnub_subscribe_token,
                pubnub_publish_token=api.brand_config.pubnub_publish_token,
            )

        try:
            detail = await api.async_get_lock_detail(access_token, lock_id)
            key_data = None
            if hasattr(detail, "offline_key") and detail.offline_key:
                key_data = {
                    "key": detail.offline_key,
                    "slot": getattr(detail, "offline_slot", 0),
                    "lock_id": lock_id,
                }
            elif hasattr(detail, "key") and detail.key:
                key_data = {
                    "key": detail.key,
                    "slot": getattr(detail, "key_slot", 0),
                    "lock_id": lock_id,
                }

            if key_data:
                with open(config.keys_file, "w") as f:
                    json.dump(key_data, f, indent=2)
                _LOGGER.info("BLE keys cached to %s", config.keys_file)
                return key_data

            _LOGGER.warning(
                "Could not extract BLE keys from lock detail. "
                "You may need to provide them manually in the config."
            )
            return None
        except Exception as e:
            _LOGGER.error("Error fetching lock detail: %s", e)
            return None
