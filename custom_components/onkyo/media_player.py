"""Support for Onkyo Receivers."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaType,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from . import OnkyoConfigEntry
from .const import (
    ACCEPTED_VALUES,
    ATTR_HDMI_OUTPUT,
    CONF_MAX_VOLUME,
    CONF_RECEIVER_MAX_VOLUME,
    CONF_SOUNDS_MODE,
    CONF_SOURCES,
    DEFAULT_NAME,
    DEFAULT_PLAYABLE_SOURCES,
    DOMAIN,
    SERVICE_SELECT_HDMI_OUTPUT,
)
from .helpers import reverse_mapping

SUPPORT_ONKYO_WO_VOLUME = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PLAY_MEDIA
)
SUPPORT_ONKYO = (
    SUPPORT_ONKYO_WO_VOLUME
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_STEP
)


ONKYO_SELECT_OUTPUT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(ATTR_HDMI_OUTPUT): vol.In(ACCEPTED_VALUES),
    }
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OnkyoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Onkyo entry."""
    coordinator = entry.runtime_data
    entities = [
        OnkyoDevice(coordinator, key)
        if key == "main"
        else OnkyoDeviceZone(coordinator, key)
        for key in coordinator.data
    ]

    async def async_service_handler(service: ServiceCall) -> None:
        """Handle for services."""
        for device in entities:
            if device.entity_id in service.data.get(ATTR_ENTITY_ID, []):
                device.select_output(service.data.get(ATTR_HDMI_OUTPUT))

    hass.services.async_register(
        DOMAIN,
        SERVICE_SELECT_HDMI_OUTPUT,
        async_service_handler,
        schema=ONKYO_SELECT_OUTPUT_SCHEMA,
    )

    async_add_entities(entities, True)


class OnkyoDevice(CoordinatorEntity, MediaPlayerEntity):
    """Representation of an Onkyo device."""

    _attr_supported_features = SUPPORT_ONKYO
    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator, zone: str):
        """Initialize the Onkyo Receiver."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.receiver = coordinator.receiver
        receiver_id = coordinator.receiver.info["identifier"]
        self.zone = zone
        self._attr_name = zone
        self._attr_unique_id = f"{receiver_id}_{zone}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, receiver_id)},
            "manufacturer": "Onkyo",
            "model": coordinator.receiver.model_name,
            "name": f"{DEFAULT_NAME} ({receiver_id})",
        }
        self._attr_extra_state_attributes = coordinator.data[self.zone].get(
            "attributes"
        )

        self.sources = coordinator.config_entry.options[CONF_SOURCES]
        self.sounds = coordinator.config_entry.options[CONF_SOUNDS_MODE]
        self.max_volume = coordinator.config_entry.options[CONF_MAX_VOLUME]
        self.receiver_max_volume = coordinator.config_entry.options[
            CONF_RECEIVER_MAX_VOLUME
        ]

    @property
    def state(self):
        """Return the state of the device."""
        return self.coordinator.data[self.zone].get("pwstate", STATE_OFF)

    @property
    def volume_level(self):
        """Return the volume level of the media player (0..1)."""
        return self.coordinator.data[self.zone].get("volume")

    @property
    def is_volume_muted(self):
        """Return boolean indicating mute status."""
        return self.coordinator.data[self.zone].get("muted")

    @property
    def source(self):
        """Return the current input source of the device."""
        return self.coordinator.data[self.zone].get("current_source")

    @property
    def source_list(self):
        """List of available input sources."""
        return list(self.sources.values())

    @property
    def sound_mode(self):
        """Return the sound mode of the entity."""
        sound_mode = self.coordinator.data[self.zone].get("sound_mode")
        return self.sounds.get(sound_mode)

    @property
    def sound_mode_list(self):
        """Dynamic list of available sound modes."""
        return list(self.sounds.values())

    async def async_command(self, command):
        """Run an eiscp command and catch connection errors."""
        try:
            result = await self.hass.async_add_executor_job(
                self.receiver.command, command
            )
        except (ValueError, OSError, AttributeError, AssertionError):
            if self.receiver.command_socket:
                self.receiver.command_socket = None
                _LOGGER.debug("Resetting connection to %s", self.name)
            else:
                _LOGGER.info(
                    "%s is disconnected. Attempting to reconnect (%s)",
                    self.name,
                    command,
                )
            return False
        _LOGGER.debug("Result for %s: %s", command, result)
        await self.coordinator.async_request_refresh()
        return result

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, input is range 0..1.

        However full volume on the amp is usually far too loud so allow the user to specify the upper range
        with CONF_MAX_VOLUME.  we change as per max_volume set by user. This means that if max volume is 80 then full
        volume in HA will give 80% volume on the receiver. Then we convert
        that to the correct scale for the receiver.
        """
        #        HA_VOL * (MAX VOL / 100) * MAX_RECEIVER_VOL
        await self.async_command(
            f"volume {int(volume * (self.max_volume / 100) * self.receiver_max_volume)}"
        )

    async def async_volume_up(self) -> None:
        """Increase volume by 1 step."""
        await self.async_command("volume level-up")

    async def async_volume_down(self) -> None:
        """Decrease volume by 1 step."""
        await self.async_command("volume level-down")

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute (true) or unmute (false) media player."""
        if mute:
            await self.async_command("audio-muting on")
        else:
            await self.async_command("audio-muting off")

    async def async_turn_on(self) -> None:
        """Turn the media player on."""
        await self.async_command("system-power on")

    async def async_turn_off(self) -> None:
        """Turn the media player off."""
        await self.async_command("system-power standby")

    async def async_select_source(self, source: str) -> None:
        """Set the input source."""
        reverse_sources = reverse_mapping(self.sources)
        if source in self.source_list:
            source = reverse_sources[source]
        await self.async_command(f"input-selector {source}")

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """Switch the sound mode of the entity."""
        reverse_sounds = reverse_mapping(self.sounds)
        sound_mode = reverse_sounds[sound_mode]
        await self.async_command(f"listening-mode {sound_mode}")

    async def async_play_media(
        self, media_type: MediaType, media_id: str, **kwargs: Any
    ) -> None:
        """Play radio station by preset number."""
        reverse_sources = reverse_mapping(self.sources)
        current_source = self.coordinator.data.get("current_source")
        source = reverse_sources[current_source]
        if media_type.lower() == "radio" and source in DEFAULT_PLAYABLE_SOURCES:
            await self.async_command(f"preset {media_id}")

    async def async_select_output(self, output: str) -> None:
        """Set hdmi-out."""
        await self.async_command(f"hdmi-output-selector={output}")


class OnkyoDeviceZone(OnkyoDevice):
    """Representation of an Onkyo device's extra zone."""

    def __init__(self, coordinator: DataUpdateCoordinator, zone: str) -> None:
        """Initialize the Zone with the zone identifier."""
        super().__init__(coordinator, zone)
        self.supports_volume = True

    @property
    def supported_features(self):
        """Return media player features that are supported."""
        if self.supports_volume:
            return SUPPORT_ONKYO
        return SUPPORT_ONKYO_WO_VOLUME

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, input is range 0..1.

        However full volume on the amp is usually far too loud so allow the user to specify the upper range
        with CONF_MAX_VOLUME.  we change as per max_volume set by user. This means that if max volume is 80 then full
        volume in HA will give 80% volume on the receiver. Then we convert
        that to the correct scale for the receiver.
        """
        # HA_VOL * (MAX VOL / 100) * MAX_RECEIVER_VOL
        await self.async_command(
            f"{self.zone}.volume={int(volume * (self.max_volume / 100) * self.receiver_max_volume)}"
        )

    async def async_volume_up(self) -> None:
        """Increase volume by 1 step."""
        await self.async_command(f"{self.zone}.volume=level-up")

    async def async_volume_down(self) -> None:
        """Decrease volume by 1 step."""
        await self.async_command(f"{self.zone}.volume=level-down")

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute (true) or unmute (false) media player."""
        if mute:
            await self.async_command(f"{self.zone}.muting=on")
        else:
            await self.async_command(f"{self.zone}.muting=off")

    async def async_turn_on(self) -> None:
        """Turn the media player on."""
        await self.async_command(f"{self.zone}.power=on")

    async def async_turn_off(self) -> None:
        """Turn the media player off."""
        await self.async_command(f"{self.zone}.power=standby")

    async def async_select_source(self, source: str) -> None:
        """Set the input source."""
        reverse_sources = reverse_mapping(self.sources)
        if source in self.source_list:
            source = reverse_sources[source]
        await self.async_command(f"{self.zone}.selector={source}")

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """Switch the sound mode of the entity."""
        reverse_sounds = reverse_mapping(self.sounds)
        sound_mode = reverse_sounds[sound_mode]
        await self.async_command(f"{self.zone}.listening-mode={sound_mode}")
