"""Constants for the Onkyo integration."""

from typing import Final

# Domain
DOMAIN: Final = "onkyo"

# Configuration
CONF_RECEIVER_MAX_VOLUME: Final = "receiver_max_volume"
CONF_VOLUME_RESOLUTION: Final = "volume_resolution"
CONF_MAX_VOLUME: Final = "max_volume"
CONF_SOURCES: Final = "sources"

# Defaults
DEFAULT_NAME: Final = "Onkyo Receiver"
DEFAULT_RECEIVER_MAX_VOLUME: Final = 100
DEFAULT_VOLUME_RESOLUTION: Final = 80

# Volume resolution options (number of steps from min to max)
VOLUME_RESOLUTION_50: Final = 50   # Very old receivers
VOLUME_RESOLUTION_80: Final = 80   # Older Onkyo receivers
VOLUME_RESOLUTION_100: Final = 100 # Some models
VOLUME_RESOLUTION_200: Final = 200 # Newer Onkyo receivers

# Connection settings
CONNECTION_TIMEOUT: Final = 10  # seconds
RECONNECT_DELAY_BASE: Final = 1  # seconds
RECONNECT_DELAY_MAX: Final = 60  # seconds
COMMAND_DELAY: Final = 0.15  # seconds between commands

# Service names
SERVICE_SELECT_HDMI_OUTPUT: Final = "select_hdmi_output"

# Attributes
ATTR_HDMI_OUTPUT: Final = "hdmi_output"
ATTR_AUDIO_INFORMATION: Final = "audio_information"
ATTR_VIDEO_INFORMATION: Final = "video_information"
ATTR_PRESET: Final = "preset"

# HDMI Output options
HDMI_OUTPUT_OPTIONS: Final = [
    "no",
    "analog",
    "yes",
    "out",
    "out-sub",
    "sub",
    "hdbaset",
    "both",
    "up"
]

# Update intervals
UPDATE_INTERVAL: Final = 30  # seconds for polling when not using push

# Error messages
ERROR_CANNOT_CONNECT: Final = "cannot_connect"
ERROR_TIMEOUT: Final = "timeout"
ERROR_UNKNOWN: Final = "unknown"
ERROR_INVALID_HOST: Final = "invalid_host"
ERROR_NETWORK_ERROR: Final = "network_error"
