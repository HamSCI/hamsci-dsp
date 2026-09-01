#!/usr/bin/env python3
"""One established coordinate per transmitter — and per antenna where published.

Station coordinates had drifted into eight definition sites across three
repos carrying five distinct latitudes for WWV, a 0.577 km spread worth
1.93 us of predicted delay.  `arrival_matrix` and `mode_solver` disagreed
about the same path while both were live.

The archaeology: 40.6781/-105.0469 came first; commit 33e0925 ("Address all
critique issues") CORRECTED it to NIST's published figure; the correction
reached one copy.  So the divergence was never two guesses — it was the right
answer and the superseded one, running side by side.

NIST publishes WWVH's antennas PER FREQUENCY, and each metrology channel is a
frequency, so a channel can use the antenna that actually radiates it.  NIST
publishes only a site coordinate for WWV, so WWV keeps one — an uncited
per-frequency table is not evidence, and putting one into the anchor of every
propagation delay would repeat the mistake this file exists to close.
"""

import pytest

from hamsci_dsp.geometry import great_circle_km
from hamsci_dsp.stations import BUILTIN_CATALOG


def _dms(d, m, s):
    return d + m / 60.0 + s / 3600.0


# NIST, "WWVH Antenna Coordinates" — https://tf.nist.gov/stations/wwvh.htm
NIST_WWVH = {
    2.5:  (_dms(21, 59, 20.9), -_dms(159, 45, 52.4)),
    5.0:  (_dms(21, 59, 10.8), -_dms(159, 45, 44.8)),
    10.0: (_dms(21, 59, 18.2), -_dms(159, 45, 51.3)),
    15.0: (_dms(21, 59, 15.3), -_dms(159, 45, 50.0)),
}


class TestProvenance:

    @pytest.mark.parametrize("name", ["WWV", "WWVH", "BPM"])
    def test_every_station_cites_where_its_position_came_from(self, name):
        """A coordinate nobody can re-check is a coordinate nobody should trust."""
        station = BUILTIN_CATALOG.get(name)
        assert station.source, f"{name} has no source citation"
        assert station.source_retrieved, f"{name} has no retrieval date"

    def test_wwv_matches_the_nist_published_site_coordinate(self):
        """40 deg 40' 50.5" N, 105 deg 02' 26.6" W — NIST."""
        nist = (_dms(40, 40, 50.5), -_dms(105, 2, 26.6))
        wwv = BUILTIN_CATALOG.get("WWV").coordinates
        metres = great_circle_km(*nist, *wwv) * 1000.0
        assert metres < 5.0, f"WWV is {metres:.1f} m from the NIST figure"


class TestPerFrequencyAntennas:

    @pytest.mark.parametrize("freq_mhz", sorted(NIST_WWVH))
    def test_wwvh_carries_the_nist_antenna_for_each_frequency(self, freq_mhz):
        got = BUILTIN_CATALOG.get("WWVH").antenna_for(freq_mhz)
        want = NIST_WWVH[freq_mhz]
        metres = great_circle_km(*want, *got) * 1000.0
        assert metres < 5.0, (
            f"WWVH {freq_mhz} MHz antenna is {metres:.1f} m from the NIST figure")

    def test_wwvh_antennas_are_genuinely_distinct(self):
        """If they all collapsed to the site point the resolver did nothing."""
        station = BUILTIN_CATALOG.get("WWVH")
        seen = {station.antenna_for(f) for f in NIST_WWVH}
        assert len(seen) == len(NIST_WWVH)

    def test_a_station_without_published_antennas_falls_back_to_its_site(self):
        """NIST publishes no per-frequency table for WWV; do not invent one."""
        wwv = BUILTIN_CATALOG.get("WWV")
        for freq in wwv.frequencies_mhz:
            assert wwv.antenna_for(freq) == wwv.coordinates

    def test_an_unpublished_frequency_falls_back_to_the_site(self):
        wwvh = BUILTIN_CATALOG.get("WWVH")
        assert wwvh.antenna_for(20.0) == wwvh.coordinates


class TestTheMatrixUsesThem:

    def test_distances_are_keyed_by_station_and_frequency(self):
        from hamsci_dsp.propagation.arrival_matrix import ArrivalPatternMatrix

        apm = ArrivalPatternMatrix(receiver_lat=38.9187497,
                                   receiver_lon=-92.1277207)
        d = {f: apm.distance_km("WWVH", f) for f in NIST_WWVH}
        assert len(set(d.values())) == len(NIST_WWVH), (
            "every WWVH frequency got the same distance — the matrix is still "
            "using one point per station")

    def test_a_site_only_station_gives_one_distance_across_its_band(self):
        from hamsci_dsp.propagation.arrival_matrix import ArrivalPatternMatrix

        apm = ArrivalPatternMatrix(receiver_lat=38.9187497,
                                   receiver_lon=-92.1277207)
        d = {f: apm.distance_km("WWV", f)
             for f in BUILTIN_CATALOG.get("WWV").frequencies_mhz}
        assert len(set(d.values())) == 1


class TestNoSecondTruth:
    """Every station table in this package must agree with the catalogue.

    Not a style rule.  `arrival_matrix` and `mode_solver` disagreed about
    where WWV is for months, both live, because each kept its own copy and a
    correction reached only one of them.  Comparing the tables catches that
    the day it reappears, without anyone having to notice.
    """

    def _catalogue(self, names):
        return {n: BUILTIN_CATALOG.get(n).coordinates for n in names}

    def test_arrival_matrix_agrees_with_the_catalogue(self):
        from hamsci_dsp.propagation.arrival_matrix import STATION_LOCATIONS

        assert STATION_LOCATIONS == self._catalogue(STATION_LOCATIONS)

    def test_mode_solver_agrees_with_the_catalogue(self):
        from hamsci_dsp.propagation.mode_solver import STATION_LOCATIONS

        assert STATION_LOCATIONS == self._catalogue(STATION_LOCATIONS)

    def test_raytrace_agrees_with_the_catalogue(self):
        from hamsci_dsp.raytrace import _STATION_LOCS

        for name, loc in _STATION_LOCS.items():
            want = BUILTIN_CATALOG.get(name)
            assert (loc["lat"], loc["lon"]) == want.coordinates, name

    def test_arrival_matrix_and_mode_solver_agree_with_each_other(self):
        from hamsci_dsp.propagation.arrival_matrix import STATION_LOCATIONS as A
        from hamsci_dsp.propagation.mode_solver import STATION_LOCATIONS as B

        shared = set(A) & set(B)
        assert shared, "no stations in common — the comparison proves nothing"
        assert {k: A[k] for k in shared} == {k: B[k] for k in shared}
