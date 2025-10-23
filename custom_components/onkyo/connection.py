"""Onkyo Connection Manager - Fixed for HA 2025.10.0."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from eiscp import eISCP

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Connection settings
CONNECTION_TIMEOUT = 10  # seconds
RECONNECT_DELAY_BASE = 1  # seconds
RECONNECT_DELAY_MAX = 60  # seconds
COMMAND_DELAY = 0.15  # seconds between commands


class OnkyoConnectionManager:
    """Manages the connection to an Onkyo receiver."""

    def __init__(self, hass: HomeAssistant, receiver: eISCP) -> None:
        """Initialize the connection manager."""
        self.hass = hass
        self._receiver = receiver
        self._lock = asyncio.Lock()
        self._last_command_time = 0.0
        self._reconnect_attempt = 0
        self._is_connected = False

    @property
    def connected(self) -> bool:
        """Return True if the connection is active."""
        return self._is_connected

    async def async_send_command(self, command: str, *args: Any) -> Any:
        """Send a command to the receiver with locking and rate limiting."""
        async with self._lock:
            await self._rate_limit()
            try:
                if not self._is_connected and not self._is_connecting:
                    # Attempt to reconnect before sending the command
                    await self._async_reconnect()

                if not self._is_connected:
                    # If still not connected, fail gracefully
                    _LOGGER.debug("Not connected, command '%s' failed.", command)
                    return None

                result = await self.hass.async_add_executor_job(
                    self._receiver.command, command, *args
                )
                self._last_command_time = self.hass.loop.time()
                return result

            except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as err:
                _LOGGER.debug("Connection error sending command '%s': %s", command, err)
                self._is_connected = False
                return None
            except Exception as err:
                _LOGGER.error("Unexpected error sending command '%s': %s", command, err)
                self._is_connected = False
                return None

    async def _rate_limit(self) -> None:
        """Ensure minimum delay between commands."""
        elapsed = self.hass.loop.time() - self._last_command_time
        if elapsed < COMMAND_DELAY:
            await asyncio.sleep(COMMAND_DELAY - elapsed)

    async def _async_reconnect(self) -> None:
        """Reconnect to the receiver with exponential backoff."""
        if self._is_connecting:
            return  # Avoid concurrent reconnects

        self._is_connecting = True
        self._is_connected = False

        for attempt in range(1, 6):  # Try up to 5 times
            delay = min(RECONNECT_DELAY_BASE * (2 ** (attempt - 1)), RECONNECT_DELAY_MAX)
            _LOGGER.debug("Attempting reconnect in %s seconds (attempt %d)", delay, attempt)
            await asyncio.sleep(delay)

            try:
                if await self.async_test_connection():
                    _LOGGER.info("Successfully reconnected to Onkyo receiver.")
                    self._is_connected = True
                    break  # Exit loop on success
            except Exception as err:
                _LOGGER.debug("Reconnect attempt %d failed: %s", attempt, err)

        self._is_connecting = False

    async def async_test_connection(self) -> bool:
        """Test the connection with a simple command."""
        try:
            async with asyncio.timeout(CONNECTION_TIMEOUT):
                result = await self.hass.async_add_executor_job(
                    self._receiver.command, "system-power", "query"
                )
                return bool(result)
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as err:
            _LOGGER.debug("Connection test failed: %s", err)
            return False

    async def async_close(self) -> None:
        """Close the connection to the receiver."""
        _LOGGER.debug("Closing connection to Onkyo receiver.")
        self._is_connected = False
        try:
            await self.hass.async_add_executor_job(self._receiver.disconnect)
        except Exception as err:
            _LOGGER.debug("Error during disconnect: %s", err)
