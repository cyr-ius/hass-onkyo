"""The onkyo constants."""
DOMAIN = "onkyo"

ATTR_AUDIO_INFORMATION = "audio_information"
ATTR_HDMI_OUTPUT = "hdmi_output"
ATTR_PRESET = "preset"
ATTR_VIDEO_INFORMATION = "video_information"
ATTR_VIDEO_OUT = "video_out"
PLATFORMS = ["media_player"]
CONF_MAX_VOLUME = "max_volume"
CONF_RECEIVER_MAX_VOLUME = "receiver_max_volume"
CONF_SOURCES = "sources"
CONF_SOUNDS_MODE = "sounds_mode"
DEFAULT_NAME = "Onkyo Receiver"
DEFAULT_PLAYABLE_SOURCES = ("fm", "am", "tuner")
DEFAULT_RECEIVER_MAX_VOLUME = 80
SERVICE_SELECT_HDMI_OUTPUT = "select_hdmi_output"
SUPPORTED_MAX_VOLUME = 100
TIMEOUT_MESSAGE = "Timeout waiting for response."
UNKNOWN_MODEL = "unknown-model"
DEFAULT_SOURCES_SELECTED: list[str] = []
DEFAULT_SOUNDS_MODE_SELECTED: list[str] = []
ACCEPTED_VALUES = [
    "no",
    "analog",
    "yes",
    "out",
    "out-sub",
    "sub",
    "hdbaset",
    "both",
    "up",
]
