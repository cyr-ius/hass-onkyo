"""The onkyo component."""

from __future__ import annotations

import logging

from homeassistant import config_entries
from homeassistant.components.media_player.const import DOMAIN as media_domain
from homeassistant.config import config_per_platform
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, PLATFORMS
from .coordinator import OnkyoUpdateCoordinator

type OnkyoConfigEntry = ConfigEntry[OnkyoUpdateCoordinator]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config):
    """Set up the onkyo environment."""
    hass.data.setdefault(DOMAIN, {})

    # Import configuration from media_player platform
    config_platform = config_per_platform(config, media_domain)
    for p_type, p_config in config_platform:
        if p_type != DOMAIN:
            continue

        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_IMPORT},
                data=p_config,
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: OnkyoConfigEntry) -> bool:
    """Set the config entry up."""
    coordinator = OnkyoUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    entry.async_on_unload(entry.add_update_listener(update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def update_listener(hass, entry):
    """Update options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: OnkyoConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = entry.runtime_data
        await hass.async_add_executor_job(coordinator.receiver.disconnect)
    return unload_ok


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
