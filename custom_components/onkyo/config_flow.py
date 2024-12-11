"""Config flow to configure onkyo component."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from eiscp import eISCP as onkyo_rcv
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import ssdp
from homeassistant.components.persistent_notification import create as notify_create
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

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
    SUPPORTED_MAX_VOLUME,
    UNKNOWN_MODEL,
)
from .helpers import build_selected_dict, build_sounds_mode_list, build_sources_list

DEFAULT_SOURCES = build_sources_list()
DEFAULT_SOUNDS_MODE = build_sounds_mode_list()

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_MAX_VOLUME, default=SUPPORTED_MAX_VOLUME): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=100)
        ),
        vol.Required(
            CONF_RECEIVER_MAX_VOLUME, default=DEFAULT_RECEIVER_MAX_VOLUME
        ): cv.positive_int,
        vol.Optional(CONF_SOURCES, default=DEFAULT_SOURCES_SELECTED): cv.multi_select(
            DEFAULT_SOURCES
        ),
        vol.Optional(
            CONF_SOUNDS_MODE, default=DEFAULT_SOUNDS_MODE_SELECTED
        ): cv.multi_select(DEFAULT_SOUNDS_MODE),
    }
)

_LOGGER = logging.getLogger(__name__)


class OnkyoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Onkyo configuration flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        """Initialize."""
        self.is_imported = False

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler()

    async def async_step_import(self, import_info):
        """Set the config entry up from yaml."""
        self.is_imported = True
        return await self.async_step_user(import_info)

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors = {}
        if user_input:
            host = user_input[CONF_HOST]
            try:
                receiver = onkyo_rcv(host)

                await self.async_set_unique_id(receiver.identifier)
                self._abort_if_unique_id_configured()

                if receiver.model_name == UNKNOWN_MODEL:
                    errors["base"] = "receiver_unknown"

            except OSError as error:
                _LOGGER.error("Unable to connect to receiver at %s (%s)", host, error)
                errors["base"] = "cannot_connect"
            else:
                if self.is_imported:
                    notify_create(
                        self.hass,
                        "The import of the Onkyo configuration was successful. \
                        Please remove the platform from the YAML configuration file",
                        "Onkyo Import",
                    )
                srcs_list = build_selected_dict(
                    sources=user_input.pop(CONF_SOURCES, [])
                )
                snds_list = build_selected_dict(
                    sounds=user_input.pop(CONF_SOUNDS_MODE, [])
                )

                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                    options={
                        CONF_SOURCES: srcs_list,
                        CONF_SOUNDS_MODE: snds_list,
                        CONF_MAX_VOLUME: user_input[CONF_MAX_VOLUME],
                        CONF_RECEIVER_MAX_VOLUME: user_input[CONF_RECEIVER_MAX_VOLUME],
                    },
                )
        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_ssdp(self, discovery_info):
        """Handle a discovered device."""
        hostname = urlparse(discovery_info.ssdp_location).hostname
        friendly_name = discovery_info.upnp[ssdp.ATTR_UPNP_FRIENDLY_NAME]

        self._async_abort_entries_match({CONF_HOST: hostname})
        user_input = {
            CONF_HOST: hostname,
            CONF_NAME: friendly_name,
        }
        return await self.async_step_user(user_input)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options."""

    def __init__(self):
        """Initialize options flow."""
        self._other_options = None

    async def async_step_init(self, user_input=None):
        """Select sources."""
        errors = {}

        if user_input is not None:
            if user_input.get(CONF_SOURCES):
                sources_selected = user_input.pop(CONF_SOURCES)
                user_input.update(
                    {
                        CONF_SOUNDS_MODE: build_selected_dict(
                            sounds=user_input.get(CONF_SOUNDS_MODE, [])
                        )
                    }
                )
                self._other_options = user_input
                return await self.async_step_custom_sources(
                    sources_selected=sources_selected
                )
            return self.async_create_entry(
                title="", data={CONF_SOURCES: {}, CONF_SOUNDS_MODE: {}}
            )

        for key, value in self.config_entry.options.get(CONF_SOURCES, {}).items():
            DEFAULT_SOURCES[key] = value

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
                ): cv.positive_int,
                vol.Optional(CONF_SOURCES, default=select_sources): cv.multi_select(
                    DEFAULT_SOURCES
                ),
                vol.Optional(
                    CONF_SOUNDS_MODE, default=select_sounds_mode
                ): cv.multi_select(DEFAULT_SOUNDS_MODE),
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=sources_schema, errors=errors
        )

    async def async_step_custom_sources(self, user_input=None, sources_selected=None):
        """Rename sources."""
        if user_input is not None:
            data = {CONF_SOURCES: user_input}
            data.update(self._other_options)
            return self.async_create_entry(title="", data=data)

        schema = {}
        for source in sources_selected:
            schema.update(
                {
                    vol.Required(
                        source, default=DEFAULT_SOURCES.get(source, source)
                    ): cv.string
                }
            )
        data_schema = vol.Schema(schema)
        return self.async_show_form(step_id="custom_sources", data_schema=data_schema)
