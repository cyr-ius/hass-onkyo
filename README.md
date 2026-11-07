# Onkyo Receiver

Custom Home Assistant integration for Onkyo network receivers, using the eISCP protocol.

## Features

- Media player entity: power, volume, mute, source and sound mode selection
- Automatic discovery of receivers via SSDP
- Configurable maximum volume and receiver volume scale
- Selection and renaming of the sources and sound modes shown in Home Assistant
- `onkyo.select_hdmi_output` service to choose the HDMI output

## Installation

### HACS

1. Add `https://github.com/cyr-ius/hass-onkyo` as a custom repository (category: integration).
2. Install **Onkyo Receiver** and restart Home Assistant.

### Manual

Copy `custom_components/onkyo` into your Home Assistant `custom_components` folder and restart.

## Configuration

Go to **Settings → Devices & services → Add integration → Onkyo**, or accept the discovered receiver.
Volume limits, sources and sound modes can be changed later from the integration options.

## Issues

Please report problems on the [issue tracker](https://github.com/cyr-ius/hass-onkyo/issues).
