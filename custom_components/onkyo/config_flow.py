"""Config flow to configure onkyo component."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from eiscp import eISCP as onkyo_rcv
from homeassistant import config_entries
from homeassistant.components.persistent_notification import create as notify_create
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.service_info.ssdp import (
    ATTR_UPNP_FRIENDLY_NAME,
    SsdpServiceInfo,
)

from .const import (
    CONF_MAX_VOLUME,
    CONF_RECEIVER_MAX_VOLUME,
    CONF_SOUNDS_MODE,
    CONF_SOURCES,
    DEFAULT_NAME,
    DEFAULT_RECEIVER_MAX_VOLUME,
    DEFAULT_SOUNDS_MODE_SELECTED,
    DEFAULT_SOURCES_SELECTED,
    DOMAIN,
    MAX_NAME_LENGTH,
    SUPPORTED_MAX_VOLUME,
    UNKNOWN_ID,
    UNKNOWN_MODEL,
)
from .helpers import build_selected_dict, build_sounds_mode_list, build_sources_list

DEFAULT_SOURCES = build_sources_list()
DEFAULT_SOUNDS_MODE = build_sounds_mode_list()

RECEIVER_MAX_VOLUME_VALIDATOR = vol.All(vol.Coerce(int), vol.Range(min=1))

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_MAX_VOLUME, default=SUPPORTED_MAX_VOLUME): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=100)
        ),
        vol.Required(
            CONF_RECEIVER_MAX_VOLUME, default=DEFAULT_RECEIVER_MAX_VOLUME
        ): RECEIVER_MAX_VOLUME_VALIDATOR,
        vol.Optional(CONF_SOURCES, default=DEFAULT_SOURCES_SELECTED): cv.multi_select(
            DEFAULT_SOURCES
        ),
        vol.Optional(
            CONF_SOUNDS_MODE, default=DEFAULT_SOUNDS_MODE_SELECTED
        ): cv.multi_select(DEFAULT_SOUNDS_MODE),
    }
)

_LOGGER = logging.getLogger(__name__)


class ReceiverUnknown(Exception):
    """The host did not identify itself as an Onkyo receiver."""


def _probe_receiver(host: str) -> str:
    """Query the receiver identity and return its identifier (blocking I/O)."""
    receiver = onkyo_rcv(host)
    try:
        identifier = receiver.identifier
        model_name = receiver.model_name
    except (AttributeError, ValueError) as error:
        # eiscp raises AttributeError when the UDP answer is not a valid ECN reply.
        raise ReceiverUnknown from error
    finally:
        receiver.disconnect()

    if not identifier or identifier == UNKNOWN_ID or model_name == UNKNOWN_MODEL:
        raise ReceiverUnknown
    return identifier


def _sanitize_name(name: Any) -> str:
    """Return a printable, bounded name announced by a device."""
    cleaned = "".join(char for char in str(name or "") if char.isprintable()).strip()
    return cleaned[:MAX_NAME_LENGTH] or DEFAULT_NAME


class OnkyoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Onkyo configuration flow."""

    VERSION = 1

    def __init__(self):
        """Initialize."""
        self.is_imported = False
        self._discovered: dict[str, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler()

    async def async_step_import(self, import_info) -> FlowResult:
        """Set the config entry up from yaml."""
        self.is_imported = True
        return await self.async_step_user(import_info)

    async def async_step_user(
        self, user_input: Mapping[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        errors = {}
        if user_input:
            host = user_input[CONF_HOST]
            try:
                identifier = await self.hass.async_add_executor_job(
                    _probe_receiver, host
                )
            except OSError as error:
                _LOGGER.error("Unable to connect to receiver at %s (%s)", host, error)
                errors["base"] = "cannot_connect"
            except ReceiverUnknown:
                errors["base"] = "receiver_unknown"
            else:
                await self.async_set_unique_id(identifier)
                self._abort_if_unique_id_configured()
                return self._async_create_receiver_entry(user_input)

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_ssdp(self, discovery_info: SsdpServiceInfo) -> FlowResult:
        """Handle a discovered device."""
        host = urlparse(discovery_info.ssdp_location).hostname
        if not host:
            return self.async_abort(reason="cannot_connect")

        self._async_abort_entries_match({CONF_HOST: host})

        try:
            identifier = await self.hass.async_add_executor_job(_probe_receiver, host)
        except OSError:
            return self.async_abort(reason="cannot_connect")
        except ReceiverUnknown:
            return self.async_abort(reason="receiver_unknown")

        await self.async_set_unique_id(identifier)
        self._abort_if_unique_id_configured()

        name = _sanitize_name(discovery_info.upnp.get(ATTR_UPNP_FRIENDLY_NAME))
        self._discovered = {CONF_HOST: host, CONF_NAME: name}
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: Mapping[str, Any] | None = None
    ) -> FlowResult:
        """Ask the user to confirm a discovered receiver."""
        if user_input is not None:
            return self._async_create_receiver_entry(self._discovered)

        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "name": self._discovered[CONF_NAME],
                "host": self._discovered[CONF_HOST],
            },
        )

    @callback
    def _async_create_receiver_entry(self, user_input: Mapping[str, Any]) -> FlowResult:
        """Create the config entry with its initial options."""
        data = dict(user_input)
        if self.is_imported:
            notify_create(
                self.hass,
                "The import of the Onkyo configuration was successful. \
                Please remove the platform from the YAML configuration file",
                "Onkyo Import",
            )
        srcs_list = build_selected_dict(
            sources=data.pop(CONF_SOURCES, DEFAULT_SOURCES_SELECTED)
        )
        snds_list = build_selected_dict(
            sounds=data.pop(CONF_SOUNDS_MODE, DEFAULT_SOUNDS_MODE_SELECTED)
        )

        return self.async_create_entry(
            title=data.get(CONF_NAME, DEFAULT_NAME),
            data=data,
            options={
                CONF_SOURCES: srcs_list,
                CONF_SOUNDS_MODE: snds_list,
                CONF_MAX_VOLUME: data.get(CONF_MAX_VOLUME, SUPPORTED_MAX_VOLUME),
                CONF_RECEIVER_MAX_VOLUME: data.get(
                    CONF_RECEIVER_MAX_VOLUME, DEFAULT_RECEIVER_MAX_VOLUME
                ),
            },
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options."""

    def __init__(self):
        """Initialize options flow."""
        self._other_options: dict[str, Any] = {}
        self._sources_names: dict[str, str] = {}

    async def async_step_init(
        self, user_input: Mapping[str, Any] | None = None
    ) -> FlowResult:
        """Select sources."""
        errors = {}
        # Per-entry copy: never mutate the module-level DEFAULT_SOURCES.
        self._sources_names = {
            **DEFAULT_SOURCES,
            **self.config_entry.options.get(CONF_SOURCES, {}),
        }

        if user_input is not None:
            options = dict(user_input)
            sources_selected = options.pop(CONF_SOURCES, [])
            options[CONF_SOUNDS_MODE] = build_selected_dict(
                sounds=options.get(CONF_SOUNDS_MODE, [])
            )
            if sources_selected:
                self._other_options = options
                return await self.async_step_custom_sources(
                    sources_selected=sources_selected
                )
            return self.async_create_entry(title="", data={**options, CONF_SOURCES: {}})

        select_sources = list(self.config_entry.options.get(CONF_SOURCES, {}).keys())
        select_sounds_mode = list(
            self.config_entry.options.get(CONF_SOUNDS_MODE, {}).keys()
        )
        supported_max_volume = self.config_entry.options.get(
            CONF_MAX_VOLUME, SUPPORTED_MAX_VOLUME
        )
        default_receiver_max_volume = self.config_entry.options.get(
            CONF_RECEIVER_MAX_VOLUME, DEFAULT_RECEIVER_MAX_VOLUME
        )
        sources_schema = vol.Schema(
            {
                vol.Required(CONF_MAX_VOLUME, default=supported_max_volume): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=100)
                ),
                vol.Required(
                    CONF_RECEIVER_MAX_VOLUME, default=default_receiver_max_volume
                ): RECEIVER_MAX_VOLUME_VALIDATOR,
                vol.Optional(CONF_SOURCES, default=select_sources): cv.multi_select(
                    self._sources_names
                ),
                vol.Optional(
                    CONF_SOUNDS_MODE, default=select_sounds_mode
                ): cv.multi_select(DEFAULT_SOUNDS_MODE),
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=sources_schema, errors=errors
        )

    async def async_step_custom_sources(
        self,
        user_input: Mapping[str, Any] | None = None,
        sources_selected: list[str] | None = None,
    ) -> FlowResult:
        """Rename sources."""
        if user_input is not None:
            data = {**self._other_options, CONF_SOURCES: dict(user_input)}
            return self.async_create_entry(title="", data=data)

        schema = {}
        for source in sources_selected or []:
            schema.update(
                {
                    vol.Required(
                        source, default=self._sources_names.get(source, source)
                    ): cv.string
                }
            )
        data_schema = vol.Schema(schema)
        return self.async_show_form(step_id="custom_sources", data_schema=data_schema)
