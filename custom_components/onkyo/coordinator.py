"""onkyo coordinators."""

from __future__ import annotations

from datetime import timedelta
import logging

from typing import Any

from eiscp import eISCP as onkyo_rcv

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_AUDIO_INFORMATION,
    ATTR_HDMI_OUTPUT,
    ATTR_PRESET,
    ATTR_VIDEO_INFORMATION,
    CONF_MAX_VOLUME,
    CONF_RECEIVER_MAX_VOLUME,
    CONF_SOURCES,
    DOMAIN,
    ERROR_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=10)


class OnkyoUpdateCoordinator(DataUpdateCoordinator):
    """DataUpdateCoordinator base class for onkyo."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        hdmi_out_supported=True,
        audio_info_supported=True,
        video_info_supported=True,
    ) -> None:
        """Initialize onkyo DataUpdateCoordinator."""
        self.config_entry = config_entry
        self.hdmi_out_supported = hdmi_out_supported
        self.audio_info_supported = audio_info_supported
        self.video_info_supported = video_info_supported
        self.sources = config_entry.options[CONF_SOURCES]
        self.receiver_max_volume = config_entry.options[CONF_RECEIVER_MAX_VOLUME]
        self.max_volume = config_entry.options[CONF_MAX_VOLUME]
        self.receiver = onkyo_rcv(self.config_entry.data[CONF_HOST])
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)

    async def _async_update_data(self) -> dict:
        data = {}
        try:
            main = await self.async_fetch_data()
            data.update({"main": main})

            for zone in self._determine_zones(self.receiver):
                other = await self.async_fetch_data_zone(zone)
                data.update({zone: other})

        except Exception as error:
            _LOGGER.debug(error)
            raise UpdateFailed from error
        else:
            return data

    async def async_fetch_data(self) -> dict:
        """Fetch all data from api."""
        data: dict[str, Any] = {}
        attributes: dict[str, Any] = {}

        status = self.receiver.command("system-power query")
        if not status:
            return data
        if status[1] == "on":
            data.update({"pwstate": STATE_ON})
        else:
            data.update({"pwstate": STATE_OFF, "attributes": attributes})
            return data

        volume_raw = self.receiver.command("volume query")
        mute_raw = self.receiver.command("audio-muting query")
        current_source_raw = self.receiver.command("input-selector query")
        preset_raw = self.receiver.command("preset query")
        listening_mode_raw = self.receiver.command("listening-mode query")
        # If the following command is sent to a device with only one HDMI out,
        # the display shows 'Not Available'.
        # We avoid this by checking if HDMI out is supported
        if listening_mode_raw:
            sound_mode = self._parse_onkyo_payload(listening_mode_raw)[-1]
            data.update({"sound_mode": sound_mode})

        if self.hdmi_out_supported:
            hdmi_out_raw = self.receiver.command("hdmi-output-selector query")
        else:
            hdmi_out_raw = []

        if self.audio_info_supported:
            audio_information_raw = self.receiver.command("audio-information query")
            info_audio = self._parse_audio_information(audio_information_raw)
            attributes.update(info_audio)
        if self.video_info_supported:
            video_information_raw = self.receiver.command("video-information query")
            info_video = self._parse_video_information(video_information_raw)
            attributes.update(info_video)
        if not (volume_raw and mute_raw and current_source_raw):
            return data

        sources = self._parse_onkyo_payload(current_source_raw)
        for source in sources:
            if source in self.sources:
                current_source = self.sources[source]
                break
            current_source = "_".join(sources)

        data.update({"current_source": current_source})

        if preset_raw and current_source.lower() == "radio":
            attributes[ATTR_PRESET] = preset_raw[1]
        elif ATTR_PRESET in attributes:
            del attributes[ATTR_PRESET]

        muted = bool(mute_raw[1] == "on")
        data.update({"muted": muted})

        # AMP_VOL/MAX_RECEIVER_VOL*(MAX_VOL/100)
        volume = volume_raw[1] / (self.receiver_max_volume * self.max_volume / 100)
        data.update({"volume": volume})

        if not hdmi_out_raw:
            return data

        attributes[ATTR_HDMI_OUTPUT] = ",".join(hdmi_out_raw[1])
        if hdmi_out_raw[1] == "N/A":
            data.update({"hdmi_out_supported": False})

        data.update({"attributes": attributes})

        return data

    async def async_fetch_data_zone(self, zone) -> dict:
        """Fetch data zone."""
        data: dict[str, Any] = {}
        attributes: dict[str, Any] = {}

        status = self.receiver.command(f"{zone}.power=query")
        if not status:
            return data
        if status[1] == "on":
            data.update({"pwstate": STATE_ON})
        else:
            data.update({"pwstate": STATE_OFF, "attributes": attributes})
            return data

        volume_raw = self.receiver.command(f"{zone}.volume=query")
        mute_raw = self.receiver.command(f"{zone}.muting=query")
        current_source_raw = self.receiver.command(f"{zone}.selector=query")
        preset_raw = self.receiver.command(f"{zone}.preset=query")
        # If we received a source value, but not a volume value
        # it's likely this zone permanently does not support volume.
        if current_source_raw and not volume_raw:
            supports_volume = False

        if not (volume_raw and mute_raw and current_source_raw):
            return {}

        # It's possible for some players to have zones set to HDMI with
        # no sound control. In this case, the string `N/A` is returned.
        supports_volume = isinstance(volume_raw[1], (float, int))

        # eiscp can return string or tuple. Make everything tuples.
        if isinstance(current_source_raw[1], str):
            current_source_tuples = (current_source_raw[0], (current_source_raw[1],))
        else:
            current_source_tuples = current_source_raw

        for source in current_source_tuples[1]:
            if source in self.sources:
                current_source = self.sources[source]
                break
            current_source = "_".join(current_source_tuples[1])

        data.update({"current_source": current_source})

        muted = bool(mute_raw[1] == "on")
        data.update({"muted": muted})

        if preset_raw and current_source.lower() == "radio":
            attributes[ATTR_PRESET] = preset_raw[1]
        elif ATTR_PRESET in attributes:
            del attributes[ATTR_PRESET]

        if supports_volume:
            # AMP_VOL/MAX_RECEIVER_VOL*(MAX_VOL/100)
            volume = volume_raw[1] / self.receiver_max_volume * (self.max_volume / 100)
            data.update({"volume": volume})

        data.update({"attributes": attributes})
        return data

    def _parse_onkyo_payload(self, payload):
        """Parse a payload returned from the eiscp library."""
        if isinstance(payload, bool):
            # command not supported by the device
            return False

        if len(payload) < 2:
            # no value
            return None

        if isinstance(payload[1], str):
            return payload[1].split(",")

        return payload[1]

    def _parse_audio_information(self, audio_information_raw):
        if values := self._parse_onkyo_payload(audio_information_raw):
            info = {
                "format": self._tuple_get(values, 1),
                "input_frequency": self._tuple_get(values, 2),
                "input_channels": self._tuple_get(values, 3),
                "listening_mode": self._tuple_get(values, 4),
                "output_channels": self._tuple_get(values, 5),
                "output_frequency": self._tuple_get(values, 6),
            }
            return {ATTR_AUDIO_INFORMATION: info}
        return {}

    def _parse_video_information(self, video_information_raw):
        if values := self._parse_onkyo_payload(video_information_raw):
            info = {
                "input_resolution": self._tuple_get(values, 1),
                "input_color_schema": self._tuple_get(values, 2),
                "input_color_depth": self._tuple_get(values, 3),
                "output_resolution": self._tuple_get(values, 5),
                "output_color_schema": self._tuple_get(values, 6),
                "output_color_depth": self._tuple_get(values, 7),
                "picture_mode": self._tuple_get(values, 8),
            }
            return {ATTR_VIDEO_INFORMATION: info}
        return {}

    def _tuple_get(self, tup, index, default=None) -> tuple:
        """Return a tuple item at index or a default value if it doesn't exist."""
        return (tup[index : index + 1] or [default])[0]

    def _determine_zones(self, receiver) -> list[str]:
        """Determine what zones are available for the receiver."""
        out = []
        try:
            _LOGGER.debug("Checking for zone 2 capability")
            response = receiver.raw("ZPWQSTN")
            if response != "ZPWN/A":  # Zone 2 Available
                out.append("zone2")
            else:
                _LOGGER.debug("Zone 2 not available")
        except ValueError as error:
            if str(error) != ERROR_TIMEOUT:
                raise HomeAssistantError(error) from error
            _LOGGER.debug("Zone 2 timed out, assuming no functionality")

        try:
            _LOGGER.debug("Checking for zone 3 capability")
            response = receiver.raw("PW3QSTN")
            if response != "PW3N/A":
                out.append("zone3")
            else:
                _LOGGER.debug("Zone 3 not available")
        except ValueError as error:
            if str(error) != ERROR_TIMEOUT:
                raise HomeAssistantError(error) from error
            _LOGGER.debug("Zone 3 timed out, assuming no functionality")
        except AssertionError:
            _LOGGER.error("Zone 3 detection failed")

        return out
