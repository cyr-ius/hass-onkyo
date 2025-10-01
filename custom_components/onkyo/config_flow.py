"""
Onkyo Config Flow with Enhanced Error Handling
==============================================

Fixes for configuration issues related to 2024.9+ breaking changes.
Provides robust setup even when receiver is temporarily unavailable.
"""

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

_LOGGER = logging.getLogger(__name__)

# Constants
DOMAIN = "onkyo"
DEFAULT_NAME = "Onkyo Receiver"
CONF_RECEIVER_MAX_VOLUME = "receiver_max_volume"
CONF_VOLUME_RESOLUTION = "volume_resolution"
DEFAULT_RECEIVER_MAX_VOLUME = 100
DEFAULT_VOLUME_RESOLUTION = 80

# Volume resolution options (steps from min to max volume)
VOLUME_RESOLUTION_OPTIONS = [50, 80, 100, 200]


class OnkyoConfigFlow(config_entries.ConfigFlow):
    """
    Handle a config flow for Onkyo.
    
    Enhanced with better error handling for 2024.9+ compatibility.
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
            
            if result["success"]:
                # Connection successful
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, DEFAULT_NAME),
                    data={
                        CONF_HOST: host,
                        CONF_NAME: user_input.get(CONF_NAME, DEFAULT_NAME),
                        CONF_RECEIVER_MAX_VOLUME: DEFAULT_RECEIVER_MAX_VOLUME,
                        CONF_VOLUME_RESOLUTION: DEFAULT_VOLUME_RESOLUTION,
                    },
                )
            else:
                # Connection failed - but allow setup anyway
                # Receiver might be off or network issue
                if result.get("allow_setup", False):
                    _LOGGER.warning(
                        "Could not verify connection to %s, but allowing setup. "
                        "Error: %s",
                        host,
                        result.get("error")
                    )
                    
                    # Show warning to user
                    errors["base"] = "cannot_connect_will_retry"
                    
                    # Create entry anyway - will reconnect when receiver is available
                    return self.async_create_entry(
                        title=user_input.get(CONF_NAME, DEFAULT_NAME),
                        data={
                            CONF_HOST: host,
                            CONF_NAME: user_input.get(CONF_NAME, DEFAULT_NAME),
                            CONF_RECEIVER_MAX_VOLUME: DEFAULT_RECEIVER_MAX_VOLUME,
                            CONF_VOLUME_RESOLUTION: DEFAULT_VOLUME_RESOLUTION,
                        },
                    )
                else:
                    # Hard failure - invalid host or other issue
                    errors["base"] = result.get("error", "unknown")
        
        # Show the form
        data_schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        })
        
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "error_detail": errors.get("base", "")
            }
        )
    
    async def async_step_zeroconf(
        self, discovery_info: dict[str, Any]
    ) -> FlowResult:
        """Handle zeroconf discovery."""
        host = discovery_info.get("host")
        name = discovery_info.get("name", "").replace("._eISCP._tcp.local.", "")
        
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
            # Discovery found it but can't connect - might be off
            # Show confirmation anyway
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
            return self.async_create_entry(
                title=self._name,
                data={
                    CONF_HOST: self._host,
                    CONF_NAME: self._name,
                    CONF_RECEIVER_MAX_VOLUME: DEFAULT_RECEIVER_MAX_VOLUME,
                    CONF_VOLUME_RESOLUTION: DEFAULT_VOLUME_RESOLUTION,
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
            # Import pyeiscp here to avoid import issues
            from pyeiscp import eISCP
            
            # Try to create receiver instance
            receiver = eISCP(host)
            
            try:
                # Attempt basic connection test with timeout
                await self.hass.async_add_executor_job(
                    receiver.power
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
            _LOGGER.error("pyeiscp library not found")
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
            
            if max_volume < 1 or max_volume > 100:
                errors[CONF_RECEIVER_MAX_VOLUME] = "invalid_max_volume"
            else:
                # Update the config entry
                return self.async_create_entry(title="", data=user_input)
        
        # Get current settings
        current_max_volume = self.config_entry.options.get(
            CONF_RECEIVER_MAX_VOLUME,
            self.config_entry.data.get(
                CONF_RECEIVER_MAX_VOLUME,
                DEFAULT_RECEIVER_MAX_VOLUME
            )
        )
        
        current_resolution = self.config_entry.options.get(
            CONF_VOLUME_RESOLUTION,
            self.config_entry.data.get(
                CONF_VOLUME_RESOLUTION,
                DEFAULT_VOLUME_RESOLUTION
            )
        )
        
        options_schema = vol.Schema({
            vol.Required(
                CONF_RECEIVER_MAX_VOLUME,
                default=current_max_volume
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
            vol.Required(
                CONF_VOLUME_RESOLUTION,
                default=current_resolution
            ): vol.In(VOLUME_RESOLUTION_OPTIONS),
        })
        
        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
            description_placeholders={
                "current_max": str(current_max_volume),
                "current_resolution": str(current_resolution),
            }
        )