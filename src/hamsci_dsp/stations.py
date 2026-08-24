"""Frozen catalog of HF time-signal stations (the split's DI seam).

Pure station data — coordinates, broadcast frequencies, names — extracted
from hf-timestd ``core/wwv_constants.py`` (Issue 4.1: NIST/NRC-verified
values) per the split design §5.2.  Timing schedules, tone frequencies and
detector thresholds are deliberately NOT here; they belong to the signal
client that interprets them.

Engines take a ``catalog`` constructor argument defaulting to
``BUILTIN_CATALOG`` so a client can study any transmitter set without
editing library code.  Everything is frozen: station facts are data, not
state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

__all__ = ["Station", "StationCatalog", "BUILTIN_CATALOG"]


@dataclass(frozen=True)
class Station:
    name: str
    lat: float
    lon: float
    frequencies_mhz: Tuple[float, ...]
    description: str = ""

    @property
    def coordinates(self) -> Tuple[float, float]:
        """(lat, lon) — the tuple shape wwv_constants consumers read."""
        return (self.lat, self.lon)


@dataclass(frozen=True)
class StationCatalog:
    stations: Tuple[Station, ...]
    _by_name: Dict[str, Station] = field(
        init=False, repr=False, compare=False, default_factory=dict)

    def __post_init__(self) -> None:
        # Populate the lookup dict on the frozen instance.
        object.__setattr__(
            self, "_by_name", {s.name: s for s in self.stations})

    def get(self, name: str) -> Station:
        return self._by_name[name]

    def names(self) -> Tuple[str, ...]:
        return tuple(s.name for s in self.stations)

    def locations(self) -> Dict[str, Dict[str, object]]:
        """The exact ``STATION_LOCATIONS`` dict shape hf-timestd's
        ``wwv_constants`` has always exported — derivable one-liner-style
        so the back-compat re-export needs no translation code."""
        return {
            s.name: {"lat": s.lat, "lon": s.lon, "name": s.description}
            for s in self.stations
        }


BUILTIN_CATALOG = StationCatalog((
    Station(
        name="WWV", lat=40.6807, lon=-105.0407,
        frequencies_mhz=(2.5, 5.0, 10.0, 15.0, 20.0, 25.0),
        description="Fort Collins, CO, USA",
    ),
    Station(
        name="WWVH", lat=21.9872, lon=-159.7636,
        frequencies_mhz=(2.5, 5.0, 10.0, 15.0),   # NOT 20/25 MHz
        description="Kekaha, Kauai, HI, USA",
    ),
    Station(
        name="CHU", lat=45.2953, lon=-75.7544,
        frequencies_mhz=(3.33, 7.85, 14.67),
        description="Ottawa, ON, Canada",
    ),
    Station(
        name="BPM", lat=34.9489, lon=109.5430,
        frequencies_mhz=(2.5, 5.0, 10.0, 15.0),
        description="Pucheng, Shaanxi, China",
    ),
    Station(
        name="WWVB", lat=40.6776, lon=-105.0470,
        frequencies_mhz=(0.06,),
        description="Fort Collins, CO, USA (NIST 60 kHz LF)",
    ),
))
