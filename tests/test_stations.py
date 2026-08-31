"""hamsci_dsp.stations — the frozen HF time-station catalog (DI seam).

Split design §5.2: pure station data (coordinates, frequencies, names)
moves here from hf-timestd's ``wwv_constants``; engines take a
``catalog`` constructor argument defaulting to the built-in.  Timing
schedules and detector thresholds stay with the timing client.
"""
import dataclasses

import pytest

from hamsci_dsp.stations import Station, StationCatalog, BUILTIN_CATALOG


class TestBuiltinCatalog:
    def test_all_five_hf_time_stations_present(self):
        assert set(BUILTIN_CATALOG.names()) == {
            "WWV", "WWVH", "CHU", "BPM", "WWVB"}

    def test_coordinates_match_the_nist_nrc_values(self):
        # Verbatim from hf-timestd wwv_constants (Issue 4.1, NIST/NRC
        # verified) — these are physical facts, pinned exactly.
        assert BUILTIN_CATALOG.get("WWV").lat == pytest.approx(40.6807)
        assert BUILTIN_CATALOG.get("WWV").lon == pytest.approx(-105.0407)
        assert BUILTIN_CATALOG.get("WWVH").lat == pytest.approx(21.9872)
        assert BUILTIN_CATALOG.get("WWVH").lon == pytest.approx(-159.7636)
        assert BUILTIN_CATALOG.get("CHU").lat == pytest.approx(45.2953)
        assert BUILTIN_CATALOG.get("CHU").lon == pytest.approx(-75.7544)
        assert BUILTIN_CATALOG.get("BPM").lat == pytest.approx(34.9489)
        assert BUILTIN_CATALOG.get("BPM").lon == pytest.approx(109.5430)
        assert BUILTIN_CATALOG.get("WWVB").lat == pytest.approx(40.6776)
        assert BUILTIN_CATALOG.get("WWVB").lon == pytest.approx(-105.0470)

    def test_frequencies_mhz(self):
        assert BUILTIN_CATALOG.get("WWV").frequencies_mhz == (
            2.5, 5.0, 10.0, 15.0, 20.0, 25.0)
        assert BUILTIN_CATALOG.get("WWVH").frequencies_mhz == (
            2.5, 5.0, 10.0, 15.0)  # NOT 20/25 MHz
        assert BUILTIN_CATALOG.get("CHU").frequencies_mhz == (
            3.33, 7.85, 14.67)
        assert BUILTIN_CATALOG.get("BPM").frequencies_mhz == (
            2.5, 5.0, 10.0, 15.0)
        assert BUILTIN_CATALOG.get("WWVB").frequencies_mhz == (0.06,)

    def test_unknown_station_raises_keyerror(self):
        with pytest.raises(KeyError):
            BUILTIN_CATALOG.get("JJY")


class TestFrozenness:
    def test_station_is_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            BUILTIN_CATALOG.get("WWV").lat = 0.0

    def test_catalog_get_returns_consistent_identity(self):
        assert BUILTIN_CATALOG.get("WWV") is BUILTIN_CATALOG.get("WWV")


class TestBackCompatShapes:
    """The shapes existing hf-timestd consumers read (STATION_LOCATIONS
    dict, (lat, lon) coordinate tuples) must be derivable one-liner-style
    so `wwv_constants` can re-export without translation code."""

    def test_locations_dict_matches_wwv_constants_shape(self):
        loc = BUILTIN_CATALOG.locations()
        assert loc["WWV"]["lat"] == pytest.approx(40.6807)
        assert loc["WWV"]["lon"] == pytest.approx(-105.0407)
        assert isinstance(loc["BPM"]["name"], str) and "Pucheng" in loc["BPM"]["name"]

    def test_coordinates_tuple(self):
        assert BUILTIN_CATALOG.get("CHU").coordinates == (
            pytest.approx(45.2953), pytest.approx(-75.7544))

    def test_custom_catalog_construction(self):
        cat = StationCatalog((
            Station(name="TEST", lat=1.0, lon=2.0,
                    frequencies_mhz=(10.0,), description="unit test"),
        ))
        assert cat.get("TEST").lon == 2.0
        assert set(cat.names()) == {"TEST"}


class TestRetiredStations:
    """A station that has ceased transmitting must not be a candidate.

    CHU (NRC Ottawa) no longer exists, so nothing should predict a signal
    from it.  The entry is kept -- historical data referencing CHU must
    still resolve -- and marked inactive, so live calculations skip it
    while archives stay readable.
    """

    def test_chu_is_marked_inactive(self):
        from hamsci_dsp.stations import BUILTIN_CATALOG
        chu = BUILTIN_CATALOG.get("CHU")
        assert chu is not None, "the entry must survive for historical data"
        assert chu.active is False

    def test_the_operating_stations_are_active(self):
        from hamsci_dsp.stations import BUILTIN_CATALOG
        for name in ("WWV", "WWVH", "BPM"):
            assert BUILTIN_CATALOG.get(name).active is True

    def test_active_stations_excludes_chu(self):
        from hamsci_dsp.stations import BUILTIN_CATALOG
        names = {s.name for s in BUILTIN_CATALOG.active_stations()}
        assert "CHU" not in names
        assert {"WWV", "WWVH", "BPM"} <= names
