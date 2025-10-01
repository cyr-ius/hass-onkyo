"""Onkyo Connection Manager."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from eiscp import eISCP as OnkyoReceiver
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)

# Connection settings
CONNECTION_TIMEOUT = 10  # seconds
RECONNECT_DELAY_BASE = 1  # seconds
RECONNECT_DELAY_MAX = 60  # seconds
COMMAND_DELAY = 0.15  # seconds between commands


class OnkyoConnectionManager:
    """Manages the connection to an Onkyo receiver."""

    def __init__(self, hass: HomeAssistant, receiver: OnkyoReceiver) -> None:
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
                if not self._is_connected:
                    await self._async_reconnect()

                result = await self.hass.async_add_executor_job(
                    self._receiver.command, command, *args
                )
                self._last_command_time = self.hass.loop.time()
                return result
            except Exception as err:
                _LOGGER.error("Error sending command %s: %s", command, err)
                self._is_connected = False
                raise HomeAssistantError(f"Failed to send command: {err}") from err

    async def _rate_limit(self) -> None:
        """Ensure minimum delay between commands."""
        now = self.hass.loop.time()
        elapsed = now - self._last_command_time
        if elapsed < COMMAND_DELAY:
            await asyncio.sleep(COMMAND_DELAY - elapsed)

    async def _async_reconnect(self) -> None:
        """Reconnect to the receiver with exponential backoff."""
        while True:
            self._reconnect_attempt += 1
            delay = min(
                RECONNECT_DELAY_BASE * (2 ** (self._reconnect_attempt - 1)),
                RECONNECT_DELAY_MAX,
            )
            _LOGGER.debug("Attempting reconnect in %s seconds", delay)
            await asyncio.sleep(delay)

            try:
                _LOGGER.info("Reconnecting to Onkyo receiver...")
                await self.hass.async_add_executor_job(self._receiver.connect)
                self._is_connected = True
                self._reconnect_attempt = 0
                _LOGGER.info("Successfully reconnected to Onkyo receiver.")
                return
            except Exception as err:
                _LOGGER.warning("Reconnect failed: %s", err)
                if self._reconnect_attempt >= 5:  # Limit reconnect attempts
                    _LOGGER.error(
                        "Failed to reconnect after multiple attempts. Giving up."
                    )
                    raise HomeAssistantError("Failed to reconnect to receiver") from err

    async def async_close(self) -> None:
        """Close the connection to the receiver."""
        _LOGGER.debug("Closing connection to Onkyo receiver.")
        await self.hass.async_add_executor_job(self._receiver.disconnect)
        self._is_connected = False
