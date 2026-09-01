#!/usr/bin/env python3
"""A retired station must cost nothing — not cycles, not predictions.

CHU ceased transmitting, and `stations.py` records that with `active=False`
while deliberately keeping the catalogue entry so archived measurements naming
CHU still resolve. But the propagation tables carried their own duplicate
copies of the station list, so CHU kept being predicted on every rebuild of
the arrival matrix: three frequencies (3.33, 7.85, 14.67 MHz) x a full
propagation solve, once per minute, forever, for a transmitter that is off
the air.

The guard below is the point of this file. Removing CHU by hand fixes today;
asserting that NO inactive station appears in any propagation table is what
stops the next retirement going half-done.
"""

import pytest

from hamsci_dsp.stations import BUILTIN_CATALOG


def _inactive_names():
    active = {s.name for s in BUILTIN_CATALOG.active_stations()}
    return {s.name for s in BUILTIN_CATALOG.stations} - active


def test_the_catalogue_still_knows_chu_so_archives_resolve():
    """Retirement must not delete history."""
    assert BUILTIN_CATALOG.get("CHU") is not None
    assert BUILTIN_CATALOG.get("CHU").active is False
    assert "CHU" in _inactive_names()


@pytest.mark.parametrize("table_name", [
    "STATION_LOCATIONS", "STATION_FREQUENCIES",
    "STATION_MIN_UNCERTAINTY_3SIGMA_MS",
])
def test_arrival_matrix_tables_exclude_inactive_stations(table_name):
    from hamsci_dsp.propagation import arrival_matrix

    table = getattr(arrival_matrix, table_name)
    leaked = _inactive_names() & set(table)
    assert not leaked, (
        f"arrival_matrix.{table_name} still lists {sorted(leaked)}; "
        f"every entry costs a propagation solve per minute")


def test_mode_solver_locations_exclude_inactive_stations():
    from hamsci_dsp.propagation import mode_solver

    leaked = _inactive_names() & set(mode_solver.STATION_LOCATIONS)
    assert not leaked, f"mode_solver.STATION_LOCATIONS still lists {sorted(leaked)}"


def test_the_matrix_predicts_nothing_for_a_retired_station():
    """The observable that matters: no arrival is computed for CHU."""
    from datetime import datetime, timezone

    from hamsci_dsp.propagation.arrival_matrix import ArrivalPatternMatrix

    apm = ArrivalPatternMatrix(receiver_lat=38.9187497, receiver_lon=-92.1277207)
    matrix = apm.get_expected_arrivals(
        datetime(2026, 8, 31, 17, 19, tzinfo=timezone.utc))

    for freq in (3.33, 7.85, 14.67):
        assert matrix.get_arrival("CHU", freq) is None
    assert not matrix.get_station_arrivals("CHU")


def test_no_distance_is_computed_to_a_retired_station():
    from hamsci_dsp.propagation.arrival_matrix import ArrivalPatternMatrix

    apm = ArrivalPatternMatrix(receiver_lat=38.9187497, receiver_lon=-92.1277207)
    leaked = _inactive_names() & set(apm.great_circle_distances)
    assert not leaked, (
        f"great_circle_distances still carries {sorted(leaked)}")
