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
import urllib.parse

from homeassistant.components import ssdp
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
    
    async def async_step_ssdp(self, discovery_info: ssdp.SsdpServiceInfo) -> FlowResult:
        """Handle SSDP discovery."""
        # Extract host and name from discovery info
        host = urllib.parse.urlparse(discovery_info.ssdp_location).hostname
        name = discovery_info.upnp.get("friendlyName", DEFAULT_NAME)

        # Filter out non-eISCP devices
        if "eISCP" not in discovery_info.ssdp_st:
            return self.async_abort(reason="not_eiscp_device")

        if not host:
            return self.async_abort(reason="no_host")

        # Set unique ID and abort if already configured
        await self.async_set_unique_id(host)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._host = host
        self._name = name.replace("._eISCP._tcp.local.", "")

        # Store discovered device information
        self._discovered_devices[host] = {"name": self._name, "host": host}

        # Attempt to connect to verify device is responsive
        result = await self._async_try_connect(host)
        if not result["success"]:
            _LOGGER.info("Discovered Onkyo receiver at %s, but connection failed.", host)
            # Allow setup even if connection fails, as receiver may be in standby
        
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
        
        Returns a dict with 'success', 'error', and 'allow_setup' keys.
        """
        receiver = None
        try:
            # Create receiver instance and test connection
            receiver = eISCP(host)
            await self.hass.async_add_executor_job(
                receiver.command, "system-power", "query"
            )
            _LOGGER.info("Successfully connected to Onkyo receiver at %s", host)
            return {"success": True}

        except (TimeoutError, ConnectionRefusedError, OSError) as err:
            # These errors are expected if the receiver is off or unavailable
            _LOGGER.info("Connection to %s failed: %s", host, err)
            return {"success": False, "error": "cannot_connect", "allow_setup": True}

        except ImportError:
            # This is a fatal error
            _LOGGER.error("onkyo-eiscp library not found")
            return {"success": False, "error": "library_missing", "allow_setup": False}
            
        except Exception as err:
            # Other unexpected errors
            _LOGGER.error("Unexpected error connecting to %s: %s", host, err)
            return {"success": False, "error": "unknown", "allow_setup": False}

        finally:
            # Ensure the connection is always closed
            if receiver:
                try:
                    await self.hass.async_add_executor_job(receiver.disconnect)
                except Exception:
                    pass  # Ignore errors on disconnect
    
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
        if user_input is not None:
            # No validation needed as voluptuous handles it
            return self.async_create_entry(title="", data=user_input)

        # Define the options schema
        options_schema = vol.Schema({
            vol.Required(
                CONF_RECEIVER_MAX_VOLUME,
                default=self.config_entry.options.get(
                    CONF_RECEIVER_MAX_VOLUME, DEFAULT_RECEIVER_MAX_VOLUME
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=200)),
            vol.Required(
                CONF_VOLUME_RESOLUTION,
                default=self.config_entry.options.get(
                    CONF_VOLUME_RESOLUTION, DEFAULT_VOLUME_RESOLUTION
                ),
            ): vol.In(VOLUME_RESOLUTION_OPTIONS),
            vol.Required(
                CONF_MAX_VOLUME,
                default=self.config_entry.options.get(CONF_MAX_VOLUME, 100),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        })

        return self.async_show_form(step_id="init", data_schema=options_schema)
