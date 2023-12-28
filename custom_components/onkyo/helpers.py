"""Helpers to Onkyo media player."""
from eiscp.commands import COMMANDS


def build_sources_list() -> dict:
    """Retrieve default sources."""
    sources_list = {}
    for value in COMMANDS["main"]["SLI"]["values"].values():
        name = value["name"]
        desc = value["description"].replace("sets ", "")
        if isinstance(name, tuple):
            name = name[0]
        if name in ["07", "08", "09", "up", "down", "query"]:
            continue
        sources_list.update({name: desc})
    return sources_list


def build_sounds_mode_list() -> dict:
    """Retrieve sound mode list."""
    sounds_list = []
    for value in COMMANDS["main"]["LMD"]["values"].values():
        name = value["name"]
        if isinstance(name, tuple):
            name = name[-1]
        if name in ["up", "down", "query"]:
            continue
        sounds_list.append(name)
    sounds_list = list(set(sounds_list))
    sounds_list.sort()
    sounds_mode = {name: name.replace("-", " ").title() for name in sounds_list}
    return sounds_mode


def build_selected_dict(sources: list = None, sounds: list = None) -> dict[str, str]:
    """Return selected dictionary."""
    if sources:
        return {k: v for k, v in build_sources_list().items() if (k in sources)}
    if sounds:
        return {k: v for k, v in build_sounds_mode_list().items() if (k in sounds)}
    return {}


def reverse_mapping(ssdict) -> dict[str, str]:
    """Reverse dictionary."""
    return {v: k for k, v in ssdict.items()}
