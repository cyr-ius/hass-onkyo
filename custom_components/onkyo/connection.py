"""Onkyo Connection Manager - Fixed for HA 2025.10.0."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from eiscp import eISCP

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
                if not self._is_connected:
                    self._is_connected = True  # Assume connected initially

                result = await self.hass.async_add_executor_job(
                    self._receiver.command, command, *args
                )
                self._last_command_time = self.hass.loop.time()
                self._reconnect_attempt = 0  # Reset on success
                return result
            except Exception as err:
                _LOGGER.debug("Error sending command %s: %s", command, err)
                self._is_connected = False
                # Don't raise, return None to allow graceful degradation
                return None

    async def _rate_limit(self) -> None:
        """Ensure minimum delay between commands."""
        now = self.hass.loop.time()
        elapsed = now - self._last_command_time
        if elapsed < COMMAND_DELAY:
            await asyncio.sleep(COMMAND_DELAY - elapsed)

    async def _async_reconnect(self) -> None:
        """Reconnect to the receiver with exponential backoff."""
        self._reconnect_attempt += 1
        delay = min(
            RECONNECT_DELAY_BASE * (2 ** (self._reconnect_attempt - 1)),
            RECONNECT_DELAY_MAX,
        )
        _LOGGER.debug("Attempting reconnect in %s seconds (attempt %d)", 
                     delay, self._reconnect_attempt)
        await asyncio.sleep(delay)

        try:
            _LOGGER.info("Reconnecting to Onkyo receiver...")
            # Test with a simple command
            result = await self.hass.async_add_executor_job(
                self._receiver.command, "system-power", "query"
            )
            if result:
                self._is_connected = True
                self._reconnect_attempt = 0
                _LOGGER.info("Successfully reconnected to Onkyo receiver.")
            else:
                raise ConnectionError("Command returned no result")
        except Exception as err:
            _LOGGER.warning("Reconnect failed: %s", err)
            if self._reconnect_attempt >= 5:
                _LOGGER.error(
                    "Failed to reconnect after %d attempts.",
                    self._reconnect_attempt
                )
                self._is_connected = False
            raise

    async def async_close(self) -> None:
        """Close the connection to the receiver."""
        _LOGGER.debug("Closing connection to Onkyo receiver.")
        try:
            await self.hass.async_add_executor_job(self._receiver.disconnect)
        except Exception as err:
            _LOGGER.debug("Error during disconnect: %s", err)
        finally:
            self._is_connected = False
