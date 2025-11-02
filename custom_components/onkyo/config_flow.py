"""
Onkyo Config Flow with Enhanced Error Handling
==============================================

Fixes for configuration issues related to 2024.9+ breaking changes.
Provides robust setup even when receiver is temporarily unavailable.
Compatible with HA 2025.10.0
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from eiscp import eISCP

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_MAX_VOLUME,
    CONF_RECEIVER_MAX_VOLUME,
    CONF_SOURCES,
    CONF_VOLUME_RESOLUTION,
    DEFAULT_RECEIVER_MAX_VOLUME,
    DEFAULT_VOLUME_RESOLUTION,
    DOMAIN,
)
from .helpers import build_sources_list

_LOGGER = logging.getLogger(__name__)

# Volume resolution options (steps from min to max volume)
VOLUME_RESOLUTION_OPTIONS = [50, 80, 100, 200]

DEFAULT_NAME = "Onkyo Receiver"


class OnkyoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Handle a config flow for Onkyo.
    
    Enhanced with better error handling for 2024.9+ and 2025.10+ compatibility.
    """

    VERSION = 2
    
    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices: dict[str, Any] = {}
        self._host: str | None = None
        self._name: str | None = None
    
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - manual configuration."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            host = user_input[CONF_HOST]
            
            # Set unique ID based on host
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()
            
            # Try to connect to the receiver
            result = await self._async_try_connect(host)
            
            # Get sources list
            sources = build_sources_list()
            
            # Create entry data
            entry_data = {
                CONF_HOST: host,
                CONF_NAME: user_input.get(CONF_NAME, DEFAULT_NAME),
            }
            
            # Create options with defaults
            entry_options = {
                CONF_RECEIVER_MAX_VOLUME: user_input.get(
                    CONF_RECEIVER_MAX_VOLUME, DEFAULT_RECEIVER_MAX_VOLUME
                ),
                CONF_VOLUME_RESOLUTION: DEFAULT_VOLUME_RESOLUTION,
                CONF_MAX_VOLUME: 100,
                CONF_SOURCES: sources,
            }
            
            if result["success"] or result.get("allow_setup", False):
                if not result["success"]:
                    _LOGGER.warning(
                        "Could not verify connection to %s, but allowing setup. "
                        "Error: %s",
                        host,
                        result.get("error")
                    )
                
                # Create entry with options
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, DEFAULT_NAME),
                    data=entry_data,
                    options=entry_options,
                )
            else:
                # Hard failure - invalid host or other issue
                errors["base"] = result.get("error", "unknown")
        
        # Show the form
        data_schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
            vol.Optional(
                CONF_RECEIVER_MAX_VOLUME,
                default=DEFAULT_RECEIVER_MAX_VOLUME
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=200)),
        })
        
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )
    
    async def async_step_ssdp(
        self, discovery_info: dict[str, Any]
    ) -> FlowResult:
        """Handle SSDP discovery."""
        host = discovery_info.get("host") or discovery_info.get("ssdp_location", "").split("://")[1].split(":")[0]
        name = discovery_info.get("friendlyName", "").replace("._eISCP._tcp.local.", "")
        
        if not host:
            return self.async_abort(reason="no_host")
        
        # Set unique ID
        await self.async_set_unique_id(host)
        self._abort_if_unique_id_configured()
        
        self._host = host
        self._name = name or DEFAULT_NAME
        
        # Store discovered device
        self._discovered_devices[host] = {
            "name": self._name,
            "host": host,
        }
        
        # Try to connect
        result = await self._async_try_connect(host)
        
        if not result["success"]:
            _LOGGER.info(
                "Discovered Onkyo receiver at %s but cannot connect yet",
                host
            )
        
        return await self.async_step_discovery_confirm()
    
    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery."""
        if user_input is not None:
            # Get sources list
            sources = build_sources_list()
            
            return self.async_create_entry(
                title=self._name,
                data={
                    CONF_HOST: self._host,
                    CONF_NAME: self._name,
                },
                options={
                    CONF_RECEIVER_MAX_VOLUME: DEFAULT_RECEIVER_MAX_VOLUME,
                    CONF_VOLUME_RESOLUTION: DEFAULT_VOLUME_RESOLUTION,
                    CONF_MAX_VOLUME: 100,
                    CONF_SOURCES: sources,
                },
            )
        
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "name": self._name,
                "host": self._host,
            },
        )
    
    async def _async_try_connect(self, host: str) -> dict[str, Any]:
        """
        Try to connect to the receiver.
        
        Returns:
            dict with 'success', 'error', and 'allow_setup' keys
        """
        try:
            # Try to create receiver instance
            receiver = eISCP(host)
            
            try:
                # Attempt basic connection test with timeout
                await self.hass.async_add_executor_job(
                    receiver.command, "system-power", "query"
                )
                
                # Connection successful
                _LOGGER.info("Successfully connected to Onkyo receiver at %s", host)
                return {"success": True}
                
            except TimeoutError:
                # Timeout - receiver might be off or in standby
                _LOGGER.info(
                    "Connection to %s timed out - receiver may be off",
                    host
                )
                return {
                    "success": False,
                    "error": "timeout",
                    "allow_setup": True  # Allow setup, will connect when on
                }
                
            except ConnectionRefusedError:
                # Connection refused - check if host is valid
                _LOGGER.warning("Connection refused by %s", host)
                return {
                    "success": False,
                    "error": "connection_refused",
                    "allow_setup": True
                }
                
            except OSError as err:
                # Network error - might be temporary
                _LOGGER.warning("Network error connecting to %s: %s", host, err)
                return {
                    "success": False,
                    "error": "network_error",
                    "allow_setup": True
                }
                
            finally:
                # Clean up connection
                try:
                    await self.hass.async_add_executor_job(receiver.disconnect)
                except Exception:
                    pass
                
        except ImportError:
            _LOGGER.error("onkyo-eiscp library not found")
            return {
                "success": False,
                "error": "library_missing",
                "allow_setup": False
            }
            
        except Exception as err:
            _LOGGER.error("Unexpected error connecting to %s: %s", host, err)
            return {
                "success": False,
                "error": "unknown",
                "allow_setup": False
            }
    
    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return OnkyoOptionsFlowHandler(config_entry)


class OnkyoOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Onkyo options."""
    
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
    
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            # Validate volume settings
            max_volume = user_input[CONF_RECEIVER_MAX_VOLUME]
            
            if max_volume < 1 or max_volume > 200:
                errors[CONF_RECEIVER_MAX_VOLUME] = "invalid_max_volume"
            else:
                # Update the config entry options
                return self.async_create_entry(title="", data=user_input)
        
        # Get current settings
        current_max_volume = self.config_entry.options.get(
            CONF_RECEIVER_MAX_VOLUME,
            DEFAULT_RECEIVER_MAX_VOLUME
        )
        
        current_resolution = self.config_entry.options.get(
            CONF_VOLUME_RESOLUTION,
            DEFAULT_VOLUME_RESOLUTION
        )
        
        current_max_vol_pct = self.config_entry.options.get(
            CONF_MAX_VOLUME,
            100
        )
        
        current_sources = self.config_entry.options.get(
            CONF_SOURCES,
            build_sources_list()
        )
        
        options_schema = vol.Schema({
            vol.Required(
                CONF_RECEIVER_MAX_VOLUME,
                default=current_max_volume
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=200)),
            vol.Required(
                CONF_VOLUME_RESOLUTION,
                default=current_resolution
            ): vol.In(VOLUME_RESOLUTION_OPTIONS),
            vol.Required(
                CONF_MAX_VOLUME,
                default=current_max_vol_pct
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        })
        
        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
        )
