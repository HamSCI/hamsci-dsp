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
from typing import Dict, Mapping, Tuple

__all__ = ["Station", "StationCatalog", "BUILTIN_CATALOG"]


@dataclass(frozen=True)
class Station:
    name: str
    lat: float
    lon: float
    frequencies_mhz: Tuple[float, ...]
    description: str = ""
    #: Whether the station still transmits.  A ceased station stays in
    #: the catalogue so historical data referencing it keeps resolving,
    #: and is excluded from anything predicting a signal that could be
    #: received now.
    active: bool = True

    #: Where this station's position came from, and when it was read.  A
    #: coordinate nobody can re-check is a coordinate nobody should trust:
    #: WWV's position sat wrong in several tables for a long time precisely
    #: because no entry recorded what it was supposed to be.
    source: str = ""
    source_retrieved: str = ""

    #: Per-frequency transmitting antenna positions, {MHz: (lat, lon)}, for
    #: stations whose operator publishes them.  NIST does for WWVH, where the
    #: four antennas sit up to ~50 m apart along the path from Missouri.  It
    #: publishes only a site coordinate for WWV, so WWV has none here — an
    #: uncited per-frequency table is not evidence.
    antennas: Mapping[float, Tuple[float, float]] = field(default_factory=dict)

    @property
    def coordinates(self) -> Tuple[float, float]:
        """(lat, lon) — the tuple shape wwv_constants consumers read."""
        return (self.lat, self.lon)

    def antenna_for(self, frequency_mhz: float) -> Tuple[float, float]:
        """The antenna that actually radiates this frequency.

        Falls back to the site coordinate when the operator publishes no
        per-frequency position, or for a frequency outside the published
        set.  Every metrology channel is one frequency, so a channel can ask
        for the antenna it is actually listening to.
        """
        if not self.antennas:
            return self.coordinates
        f = float(frequency_mhz)
        if f in self.antennas:
            return self.antennas[f]
        for key, pos in self.antennas.items():
            if abs(key - f) < 1e-6:
                return pos
        return self.coordinates


@dataclass(frozen=True)
class StationCatalog:
    stations: Tuple[Station, ...]
    _by_name: Dict[str, Station] = field(
        init=False, repr=False, compare=False, default_factory=dict)

    def __post_init__(self) -> None:
        # Populate the lookup dict on the frozen instance.
        object.__setattr__(
            self, "_by_name", {s.name: s for s in self.stations})

    def active_stations(self) -> Tuple["Station", ...]:
        """Stations still transmitting — what any live prediction wants.

        ``get()`` deliberately still returns retired stations, so archived
        measurements naming them continue to resolve.
        """
        return tuple(s for s in self.stations if s.active)

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
        # NIST publishes 40 deg 40' 50.5" N, 105 deg 02' 26.6" W for the site.
        # This entry sits 2 m from that figure.  NIST does not publish a
        # per-frequency antenna table, so there is no `antennas` here.
        source="NIST, Radio Station WWV (site coordinate)",
        source_retrieved="2026-09-01",
    ),
    Station(
        name="WWVH", lat=21.9872, lon=-159.7636,
        frequencies_mhz=(2.5, 5.0, 10.0, 15.0),   # NOT 20/25 MHz
        description="Kekaha, Kauai, HI, USA",
        source="NIST, WWVH Antenna Coordinates (tf.nist.gov/stations/wwvh.htm)",
        source_retrieved="2026-09-01",
        # Each frequency radiates from its own antenna at Kokole Point.
        antennas={
            2.5: (21.98913888888889, -159.76455555555555),
            5.0: (21.986333333333334, -159.76244444444444),
            10.0: (21.98838888888889, -159.76425),
            15.0: (21.987583333333333, -159.76388888888889),
        },
    ),
    Station(
        name="CHU", lat=45.2953, lon=-75.7544,
        frequencies_mhz=(3.33, 7.85, 14.67),
        description="Ottawa, ON, Canada (ceased transmitting)",
        active=False,
    ),
    Station(
        name="BPM", lat=34.9489, lon=109.5430,
        frequencies_mhz=(2.5, 5.0, 10.0, 15.0),
        description="Pucheng, Shaanxi, China",
        # Published site coordinate 34 deg 56' 55.96" N, 109 deg 32' 34.93" E
        # (NTSC, Chinese Academy of Sciences); this entry is within 15 m.
        source="NTSC/CAS, BPM station (site coordinate)",
        source_retrieved="2026-09-01",
    ),
    Station(
        name="WWVB", lat=40.6776, lon=-105.0470,
        frequencies_mhz=(0.06,),
        description="Fort Collins, CO, USA (NIST 60 kHz LF)",
    ),
))
