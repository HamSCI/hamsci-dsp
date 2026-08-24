"""TEC geometric corrections — obliquity, pierce points, station paths.

Canonical home since the split (§5.2); ported from hf-timestd
``core/tec_geometry.py``, which was already delegating its math here
(geodesic distance/midpoint/elevation from :mod:`hamsci_dsp.geometry`,
thin-shell obliquity from :mod:`hamsci_dsp.propagation.oblique`).  The
one station-aware helper takes the frozen catalog by injection.
"""
from __future__ import annotations

import math
from typing import Dict, Tuple

from hamsci_dsp.geometry import (
    great_circle_km as _great_circle_km,
    midpoint as _midpoint,
    elevation_angle_deg as _elevation_angle_deg,
)
from hamsci_dsp.propagation.oblique import (
    slant_to_vertical_tec as _slant_to_vertical_tec,
)
from hamsci_dsp.stations import BUILTIN_CATALOG, StationCatalog

EARTH_RADIUS_KM = 6371.0
DEFAULT_IONO_HEIGHT_KM = 350.0

#: Historical dict shape (P-M6) — derived from the catalog, never copied.
STATIONS = BUILTIN_CATALOG.locations()

#: Maximum obliquity factor — matches the sibling cap in the propagation
#: model (M ≤ 10); past it the thin-shell approximation loses meaning.
MAX_OBLIQUITY_FACTOR = 10.0


def _validate_latlon(lat: float, lon: float, label: str) -> None:
    """Validate lat/lon are finite and within physical range."""
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValueError(f"{label}: non-finite coordinate (lat={lat!r}, lon={lon!r})")
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"{label}: lat {lat} out of [-90, 90] (deg)")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"{label}: lon {lon} out of [-180, 180] (deg)")


def calculate_midpoint(lat1: float, lon1: float,
                       lat2: float, lon2: float) -> Tuple[float, float]:
    """Geodesic (WGS-84) midpoint of the path between two points."""
    _validate_latlon(lat1, lon1, "calculate_midpoint p1")
    _validate_latlon(lat2, lon2, "calculate_midpoint p2")
    return _midpoint(lat1, lon1, lat2, lon2)


def great_circle_distance(lat1: float, lon1: float,
                          lat2: float, lon2: float) -> float:
    """Geodesic (WGS-84 ellipsoidal) distance in kilometers."""
    return _great_circle_km(lat1, lon1, lat2, lon2)


def calculate_elevation_angle(rx_lat: float, rx_lon: float,
                              tx_lat: float, tx_lon: float,
                              h_iono: float = DEFAULT_IONO_HEIGHT_KM) -> float:
    """Elevation to the single-hop reflection point (spherical Earth)."""
    distance_km = great_circle_distance(rx_lat, rx_lon, tx_lat, tx_lon)
    return _elevation_angle_deg(distance_km, h_iono)


def convert_slant_to_vertical(tec_slant: float, elevation_angle_deg: float,
                              h_iono: float = DEFAULT_IONO_HEIGHT_KM
                              ) -> Tuple[float, float]:
    """Slant TEC → (VTEC, obliquity factor), M capped at 10."""
    return _slant_to_vertical_tec(tec_slant, elevation_angle_deg,
                                  h_iono_km=h_iono)


def calculate_geometry_for_station(
    station: str,
    rx_lat: float,
    rx_lon: float,
    h_iono: float = DEFAULT_IONO_HEIGHT_KM,
    catalog: StationCatalog = BUILTIN_CATALOG,
) -> Dict:
    """All geometric parameters for a catalog station → receiver path."""
    try:
        tx = catalog.get(station)
    except KeyError:
        raise ValueError(f"Unknown station: {station}")
    mid_lat, mid_lon = calculate_midpoint(rx_lat, rx_lon, tx.lat, tx.lon)
    elevation_deg = calculate_elevation_angle(rx_lat, rx_lon, tx.lat, tx.lon,
                                              h_iono)
    distance_km = great_circle_distance(rx_lat, rx_lon, tx.lat, tx.lon)
    return {
        'midpoint_lat': mid_lat,
        'midpoint_lon': mid_lon,
        'elevation_deg': elevation_deg,
        'distance_km': distance_km,
        'tx_lat': tx.lat,
        'tx_lon': tx.lon,
    }
