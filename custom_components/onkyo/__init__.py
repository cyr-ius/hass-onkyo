"""
Onkyo Integration - Main Setup Module
======================================

Complete integration setup with fixes for:
- Issue #125768: Breaking changes in HA 2024.9+
- Issue #123143: Command concurrency problems

This module handles:
- Config entry setup and unload
- Platform loading
- Migration from older versions
- Error recovery and resilience
"""

import asyncio
import logging
from typing import Any
from eiscp import eISCP

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    CONF_RECEIVER_MAX_VOLUME,
    CONF_VOLUME_RESOLUTION,
    DEFAULT_RECEIVER_MAX_VOLUME,
    DEFAULT_VOLUME_RESOLUTION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.MEDIA_PLAYER]

# Timeout for initial connection attempts
CONNECTION_TIMEOUT = 10


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """
    Set up the Onkyo component.
    
    YAML configuration is no longer supported - only config flow.
    """
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Set up Onkyo from a config entry.
    
    Enhanced with robust error handling to prevent setup failures
    when receiver is temporarily unavailable.
    """
    host = entry.data[CONF_HOST]
    
    _LOGGER.debug("Setting up Onkyo integration for %s", host)
    
    # Initialize the receiver connection
    try:
        receiver = await _async_setup_receiver(hass, entry)
        
    except asyncio.TimeoutError:
        _LOGGER.warning(
            "Timeout connecting to Onkyo receiver at %s. "
            "The receiver may be powered off or in standby. "
            "Integration will retry when the receiver becomes available.",
            host
        )
        # Don't raise ConfigEntryNotReady - allow setup to continue
        # The media player will handle reconnection
        receiver = eISCP(host)
        
    except OSError as err:
        _LOGGER.warning(
            "Network error connecting to Onkyo receiver at %s: %s. "
            "Integration will retry when network is available.",
            host,
            err
        )
        # Allow setup to continue - will reconnect later
        receiver = eISCP(host)
        
    except Exception as err:
        _LOGGER.error(
            "Unexpected error setting up Onkyo receiver at %s: %s",
            host,
            err
        )
        # Only raise for truly unexpected errors
        raise ConfigEntryNotReady(
            f"Unexpected error connecting to receiver: {err}"
        ) from err
    
    # Store the receiver instance and entry data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "receiver": receiver,
        "host": host,
        "name": entry.data.get(CONF_NAME, "Onkyo Receiver"),
        "entry": entry,
    }
    
    # Set up the media player platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    
    _LOGGER.info("Successfully set up Onkyo integration for %s", host)
    
    return True


async def _async_setup_receiver(
    hass: HomeAssistant,
    entry: ConfigEntry
) -> eISCP:
    """
    Set up the receiver connection with timeout.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        
    Returns:
        eISCP receiver instance
        
    Raises:
        asyncio.TimeoutError: If connection times out
        OSError: If network error occurs
    """
    host = entry.data[CONF_HOST]
    
    _LOGGER.debug("Connecting to Onkyo receiver at %s", host)
    
    # Create receiver instance
    receiver = eISCP(host)
    
    # Try to establish connection with timeout
    try:
        await asyncio.wait_for(
            hass.async_add_executor_job(_test_connection, receiver),
            timeout=CONNECTION_TIMEOUT
        )
        
        _LOGGER.info("Successfully connected to Onkyo receiver at %s", host)
        return receiver
        
    except asyncio.TimeoutError:
        _LOGGER.debug("Connection to %s timed out", host)
        # Clean up the connection attempt
        try:
            await hass.async_add_executor_job(receiver.disconnect)
        except Exception:
            pass
        raise
        
    except Exception as err:
        _LOGGER.debug("Error connecting to %s: %s", host, err)
        # Clean up
        try:
            await hass.async_add_executor_job(receiver.disconnect)
        except Exception:
            pass
        raise


def _test_connection(receiver: eISCP) -> bool:
    """
    Test connection to receiver (sync function for executor).
    
    Args:
        receiver: eISCP receiver instance
        
    Returns:
        True if connection successful
        
    Raises:
        Various exceptions if connection fails
    """
    # Try a simple command to verify connection
    try:
        # Query power state - this is a lightweight command
        receiver.command("system-power query")
        return True
    except Exception as err:
        _LOGGER.debug("Connection test failed: %s", err)
        raise


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Unload a config entry.
    
    Properly cleans up connections and removes platforms.
    """
    _LOGGER.debug("Unloading Onkyo integration for entry %s", entry.entry_id)
    
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )
    
    if unload_ok:
        # Clean up the receiver connection
        if entry.entry_id in hass.data[DOMAIN]:
            receiver_data = hass.data[DOMAIN][entry.entry_id]
            receiver = receiver_data["receiver"]
            
            try:
                await hass.async_add_executor_job(receiver.disconnect)
                _LOGGER.debug("Disconnected from receiver")
            except Exception as err:
                _LOGGER.debug("Error disconnecting receiver: %s", err)
            
            # Remove from hass.data
            hass.data[DOMAIN].pop(entry.entry_id)
        
        # Clean up domain data if empty
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
        
        _LOGGER.info("Successfully unloaded Onkyo integration")
    
    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    Handle options update.
    
    Called when user changes options via UI.
    """
    _LOGGER.debug("Updating options for Onkyo integration")
    
    # Reload the config entry to apply new options
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Migrate old config entries to new format.
    
    Handles version upgrades gracefully.
    """
    _LOGGER.debug(
        "Migrating Onkyo config entry from version %s.%s",
        entry.version,
        entry.minor_version
    )
    
    # Version 1 to 2: Add volume settings
    if entry.version == 1:
        new_data = {**entry.data}
        
        # Add default volume settings if not present
        if CONF_RECEIVER_MAX_VOLUME not in new_data:
            new_data[CONF_RECEIVER_MAX_VOLUME] = DEFAULT_RECEIVER_MAX_VOLUME
            _LOGGER.debug("Added default max volume setting")
        
        if CONF_VOLUME_RESOLUTION not in new_data:
            new_data[CONF_VOLUME_RESOLUTION] = DEFAULT_VOLUME_RESOLUTION
            _LOGGER.debug("Added default volume resolution setting")
        
        # Update the entry
        hass.config_entries.async_update_entry(
            entry,
            data=new_data,
            version=2
        )
        
        _LOGGER.info("Successfully migrated Onkyo config entry to version 2")
    
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    Handle removal of an entry.
    
    Clean up any persistent data.
    """
    _LOGGER.debug("Removing Onkyo config entry %s", entry.entry_id)
    
    # Perform any cleanup needed
    # Currently nothing persistent to clean up
    pass


# Helper functions for connection management

async def async_test_connection(hass: HomeAssistant, host: str) -> dict[str, Any]:
    """
    Test connection to a receiver.
    
    Used by config flow and diagnostics.
    
    Args:
        hass: Home Assistant instance
        host: Receiver host/IP address
        
    Returns:
        Dict with 'success' bool and optional 'error' message
    """
    try:
        receiver = eISCP(host)
        
        try:
            await asyncio.wait_for(
                hass.async_add_executor_job(_test_connection, receiver),
                timeout=5
            )
            
            return {"success": True}
            
        finally:
            try:
                await hass.async_add_executor_job(receiver.disconnect)
            except Exception:
                pass
                
    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": "timeout",
            "message": "Connection timed out - receiver may be off"
        }
        
    except ConnectionRefusedError:
        return {
            "success": False,
            "error": "connection_refused",
            "message": "Connection refused - check host and network"
        }
        
    except OSError as err:
        return {
            "success": False,
            "error": "network_error",
            "message": f"Network error: {err}"
        }
        
    except Exception as err:
        return {
            "success": False,
            "error": "unknown",
            "message": f"Unexpected error: {err}"
        }


def get_receiver_info(receiver: eISCP) -> dict[str, Any]:
    """
    Get information about the receiver.
    
    Used for diagnostics and device info.
    
    Args:
        receiver: eISCP receiver instance
        
    Returns:
        Dict with receiver information
    """
    info = {
        "host": receiver.host,
        "port": receiver.port,
        "model": "Unknown",
        "connected": False,
    }
    
    try:
        # Try to get model info
        # Note: This is a sync call, should be called from executor
        model_info = receiver.info
        if model_info:
            info["model"] = model_info.get("model", "Unknown")
            info["connected"] = True
    except Exception as err:
        _LOGGER.debug("Could not get receiver info: %s", err)
    
    return info


# Error recovery utilities

class ReceiverConnectionError(Exception):
    """Exception raised when receiver connection fails."""
    pass


class ReceiverCommandError(Exception):
    """Exception raised when receiver command fails."""
    pass


async def async_retry_connection(
    hass: HomeAssistant,
    receiver: eISCP,
    max_attempts: int = 3,
    delay: float = 2.0
) -> bool:
    """
    Retry connection to receiver with exponential backoff.
    
    Args:
        hass: Home Assistant instance
        receiver: eISCP receiver instance
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        
    Returns:
        True if connection successful, False otherwise
    """
    for attempt in range(max_attempts):
        try:
            await asyncio.wait_for(
                hass.async_add_executor_job(_test_connection, receiver),
                timeout=5
            )
            _LOGGER.info(
                "Successfully reconnected to receiver on attempt %d",
                attempt + 1
            )
            return True
            
        except Exception as err:
            if attempt < max_attempts - 1:
                wait_time = delay * (2 ** attempt)
                _LOGGER.debug(
                    "Connection attempt %d failed: %s. Retrying in %.1fs",
                    attempt + 1,
                    err,
                    wait_time
                )
                await asyncio.sleep(wait_time)
            else:
                _LOGGER.warning(
                    "Failed to reconnect after %d attempts",
                    max_attempts
                )
    
    return False


# Platform-specific helpers

def get_volume_resolution(entry: ConfigEntry) -> int:
    """
    Get volume resolution from config entry.
    
    Checks options first, then data, then uses default.
    """
    return entry.options.get(
        CONF_VOLUME_RESOLUTION,
        entry.data.get(CONF_VOLUME_RESOLUTION, DEFAULT_VOLUME_RESOLUTION)
    )


def get_max_volume(entry: ConfigEntry) -> int:
    """
    Get maximum volume from config entry.
    
    Checks options first, then data, then uses default.
    """
    return entry.options.get(
        CONF_RECEIVER_MAX_VOLUME,
        entry.data.get(CONF_RECEIVER_MAX_VOLUME, DEFAULT_RECEIVER_MAX_VOLUME)
    )


def calculate_volume(
    ha_volume: float,
    max_volume: int,
    resolution: int
) -> int:
    """
    Calculate receiver volume from HA volume level.
    
    Args:
        ha_volume: HA volume (0.0-1.0)
        max_volume: Maximum volume limit (1-100)
        resolution: Volume steps (50, 80, 100, or 200)
        
    Returns:
        Receiver volume level
    """
    # Convert HA volume to receiver scale
    scaled_volume = ha_volume * (max_volume / 100) * resolution
    return int(scaled_volume)


def calculate_ha_volume(
    receiver_volume: int,
    max_volume: int,
    resolution: int
) -> float:
    """
    Calculate HA volume from receiver volume level.
    
    Args:
        receiver_volume: Receiver volume level
        max_volume: Maximum volume limit (1-100)
        resolution: Volume steps (50, 80, 100, or 200)
        
    Returns:
        HA volume (0.0-1.0)
    """
    # Convert receiver volume to HA scale
    return (receiver_volume / resolution) / (max_volume / 100)
