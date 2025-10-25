"""
Onkyo Integration - Main Setup Module
======================================

Complete integration setup with fixes for:
- Issue #125768: Breaking changes in HA 2024.9+
- Issue #123143: Command concurrency problems
- Compatibility with HA 2025.10.0

This module handles:
- Config entry setup and unload
- Platform loading
- Migration from older versions
- Error recovery and resilience
"""

from __future__ import annotations

import asyncio
import logging

from eiscp import eISCP

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_MAX_VOLUME,
    CONF_RECEIVER_MAX_VOLUME,
    CONF_SOURCES,
    CONF_VOLUME_RESOLUTION,
    DEFAULT_RECEIVER_MAX_VOLUME,
    DEFAULT_VOLUME_RESOLUTION,
    DOMAIN,
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
        receiver.command("system-power", "query")
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
        "Migrating Onkyo config entry from version %s",
        entry.version
    )
    
    # Version 1 to 2: Add volume settings and sources
    if entry.version == 1:
        from .helpers import build_sources_list
        
        new_data = {**entry.data}
        new_options = {**entry.options} if entry.options else {}
        
        # Add default volume settings if not present
        if CONF_RECEIVER_MAX_VOLUME not in new_options:
            new_options[CONF_RECEIVER_MAX_VOLUME] = DEFAULT_RECEIVER_MAX_VOLUME
            _LOGGER.debug("Added default max volume setting")
        
        if CONF_VOLUME_RESOLUTION not in new_options:
            new_options[CONF_VOLUME_RESOLUTION] = DEFAULT_VOLUME_RESOLUTION
            _LOGGER.debug("Added default volume resolution setting")
        
        if CONF_MAX_VOLUME not in new_options:
            new_options[CONF_MAX_VOLUME] = 100
            _LOGGER.debug("Added default max volume percentage")
        
        # Add default sources if not present
        if CONF_SOURCES not in new_options:
            new_options[CONF_SOURCES] = build_sources_list()
            _LOGGER.debug("Added default sources list")
        
        # Update the entry
        hass.config_entries.async_update_entry(
            entry,
            data=new_data,
            options=new_options,
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
