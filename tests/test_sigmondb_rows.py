"""The sigmondb chirp row, shared by codar-sounder now and chirp-recorder later.

The row is the contract between a station and sigmondb (design
tasks/chirp-registry/2026-11-12-codar-sigmondb-design.md): whichever program
writes it, a transmitter's history must run on unbroken.  These tests pin the
pieces that history keys on to what sigmondb already holds from the back-fill
(wsprdaemon-server sigmondb/backfill_codar.py).
"""
from datetime import datetime, timezone

import pytest

from hamsci_dsp import sigmondb_rows as sr


def test_group_key_matches_the_backfill_format():
    # backfill_codar._group_key: f"{centre_hz / 1e6:.4f} {rate_hz_per_s / 1e3:+.2f}"
    assert sr.group_key(4_463_000.0, -25_733.913) == "4.4630 -25.73"
    assert sr.group_key(13_487_500.0, -49_629.688) == "13.4875 -49.63"


def test_the_period_separates_radars_with_the_same_sweep_rate():
    # Troyer et al. 2025 Table 1: SCRZ sweeps 49.63 kHz at 4 Hz, the 13.5 MHz
    # group 99.26 kHz at 2 Hz -- both -198.5 kHz/s.
    scrz = sr.group_key(13_500_000.0, -49_630 * 4, period_s=0.25)
    estr = sr.group_key(13_500_000.0, -99_259 * 2, period_s=0.5)
    assert scrz != estr
    assert scrz == "13.5000 -198.52 0.25s"
    assert sr.group_key(4_463_000.0, -25_733.913, period_s=1.0) == "4.4630 -25.73"


def test_delay_is_the_phase_within_the_period_from_the_utc_second():
    # An arrival 0.25 s after 12:00:07 on a 1 s sweep sits 250 ms into its period.
    t = int(datetime(2026, 11, 12, 12, 0, 7, tzinfo=timezone.utc).timestamp()) * 10**9 + 250_000_123
    second, delay = sr.split_arrival(t, period_s=1.0)
    assert delay == 250_000_123                    # nanoseconds survive
    assert second == "2026-11-12T12:00:07Z"
    # A 0.5 s sweep folds 0.75 s past the second to 250 ms.
    assert sr.split_arrival(t + 500_000_000, period_s=0.5)[1] == 250_000_123


def test_a_float_epoch_is_refused():
    with pytest.raises(TypeError):
        sr.split_arrival(1.79e9, period_s=1.0)


def test_a_t6_arrival_carries_the_block_the_solver_counts():
    # sigmondb's ground-wave solver counts a row only when u_epoch_ns is set and <= 1000.
    p = sr.provenance("T6")
    assert p["origin"] == "t6_anchor" and p["u_epoch_ns"] == 230.0 and p["k"] == 2.0
    assert p["a_level_provenance"] == "assumed"


@pytest.mark.parametrize("tier", ["T3", "T4", None, ""])
def test_anything_but_t6_travels_with_the_null_block(tier):
    p = sr.provenance(tier)
    assert p["u_epoch_ns"] is None and p["origin"] == ""


def test_rows_hold_exactly_the_columns_in_order():
    a = sr.arrival_row(time="2026-11-12T12:00:07Z", reporter_id="KFS-MAIN",
                       group_key="4.4630 -25.73", centre_hz=4_463_000.0,
                       rate_hz_per_s=-25_733.913, delay_ns=250_000_000, level_db=21.0,
                       detector_version="codar-sounder/1", **sr.provenance("T6"))
    assert tuple(a) == sr.ARRIVAL_COLUMNS
    assert a["schema_version"] == sr.SCHEMA_VERSION and a["engineering"] == {}
    c = sr.capture_row(time="2026-11-12T12:00:00.000Z", reporter_id="KFS-MAIN",
                       centre_hz=4_463_000.0, rate_hz_per_s=-25_733.913, duration_s=60.0,
                       detector_version="codar-sounder/1", **sr.provenance(None))
    assert tuple(c) == sr.CAPTURE_COLUMNS


def test_an_unknown_column_is_refused():
    with pytest.raises(TypeError):
        sr.arrival_row(time="2026-11-12T12:00:07Z", reporter_id="X", bogus=1)


def test_a_gated_wideband_sweep_gets_its_own_group():
    # An ionosonde sweeping 2-30 MHz at 100 kHz/s: 280 s of every 300 s.
    key = sr.group_key(16_000_000.0, 100_000.0, period_s=300.0, sweep_s=280.0)
    assert key == "16.0000 +100.00 300s sweep280s"
    assert sr.group_key(16_000_000.0, 100_000.0, period_s=300.0, sweep_s=300.0) == \
        "16.0000 +100.00 300s"


def test_an_arrival_names_the_frequency_its_delay_belongs_to():
    a = sr.arrival_row(time="2026-11-12T12:00:07Z", reporter_id="X", freq_hz=7_150_000.0)
    assert a["freq_hz"] == 7_150_000.0
    assert sr.arrival_row(time="2026-11-12T12:00:07Z", reporter_id="X")["freq_hz"] is None
