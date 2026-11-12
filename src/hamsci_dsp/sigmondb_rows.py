"""The sigmondb chirp row: one definition for every program that writes one.

sigmondb (wsprdaemon-server, package ``sigmondb``) keeps chirp receptions in two
tables, ``arrival`` and ``capture``.  Its ingest never asks which program wrote
a row, so the row forms the contract between a station and sigmondb.
codar-sounder writes these rows now; chirp-recorder writes the same rows once
radiod's de-chirp channel lands.  Both take the definition from here, so a
transmitter's history runs on unbroken across the change
(tasks/chirp-registry/2026-11-12-codar-sigmondb-design.md).

Three conventions carry that history, and the back-fill already fixed them
(wsprdaemon-server sigmondb/backfill_codar.py):

- ``group_key`` names a sweep group by centre frequency and sweep rate.
  sigmondb matches arrivals to transmitters centrally, by group.
- ``time`` holds the UTC second of the arrival and ``delay_ns`` its phase
  within the sweep period, on the station's own timing ruler.  A station
  never subtracts an offset it assumes for the transmitter; the offsets come
  out of the central analysis.
- the provenance block says what timed the arrival.  Only a T6 arrival gets
  the block sigmondb's solver counts (u_epoch_ns set and at most 1000 ns).

ARRIVAL_COLUMNS and CAPTURE_COLUMNS copy sigmondb's ddl.COLUMNS, less
``received_at``, which the server stamps.  hfdl-recorder keeps its own copy
(hfdl_recorder.timing.sigmondb_rows) for now; the two agree column for column.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional, Tuple

SCHEMA_VERSION = 1

# The T6 block: u_epoch_ns from T6's stated scatter (50-230 ns, the top of the
# range), k = 2, provenance "assumed" -- as the back-fill and HFDL write it.
U_EPOCH_NS = 230.0
K = 2.0
T6_ORIGIN = "t6_anchor"

ARRIVAL_COLUMNS = (
    "time", "reporter_id", "tx_id", "group_key", "centre_hz", "rate_hz_per_s", "delay_ns",
    "delay_sigma_ns", "level_db", "margin_db", "half_band_db", "clean_tag", "doppler_hz",
    "phase_rate", "carrier_phase_rad", "s4", "sigma_phi_rad", "detector_version",
    "schema_version", "u_epoch_ns", "k", "p", "a_level", "a_level_provenance",
    "counter_epoch_id", "origin", "engineering")
CAPTURE_COLUMNS = (
    "time", "reporter_id", "centre_hz", "rate_hz_per_s", "duration_s", "n_sweeps", "expected",
    "null_max_db", "null_median_db", "n_expected", "n_found", "detector_version", "ring_ref",
    "schema_version", "u_epoch_ns", "k", "p", "a_level", "a_level_provenance",
    "counter_epoch_id", "origin", "engineering")

_ARRIVAL_DEFAULTS = dict(
    time=None, reporter_id="", tx_id="", group_key="", centre_hz=0.0, rate_hz_per_s=0.0,
    delay_ns=0, delay_sigma_ns=None, level_db=0.0, margin_db=None, half_band_db=None,
    clean_tag="A", doppler_hz=None, phase_rate=None, carrier_phase_rad=None, s4=None,
    sigma_phi_rad=None, detector_version="", schema_version=SCHEMA_VERSION, engineering=None)
_CAPTURE_DEFAULTS = dict(
    time=None, reporter_id="", centre_hz=0.0, rate_hz_per_s=0.0, duration_s=0.0,
    n_sweeps=None, expected=None, null_max_db=None, null_median_db=None, n_expected=None,
    n_found=None, detector_version="", ring_ref="", schema_version=SCHEMA_VERSION,
    engineering=None)


def group_key(centre_hz: float, rate_hz_per_s: float) -> str:
    """The sweep group's name, as sigmondb's back-fill writes it."""
    return f"{centre_hz / 1e6:.4f} {rate_hz_per_s / 1e3:+.2f}"


def split_arrival(epoch_ns: int, period_s: float) -> Tuple[str, int]:
    """(UTC second as ISO text, delay_ns) for an arrival at ``epoch_ns``.

    Integer nanoseconds on purpose: a float epoch in seconds resolves only
    about 240 ns today, which would spoil a T6 delay.  The delay folds the
    arrival's phase into one sweep period, counted from the UTC epoch, so a
    1 s or 0.5 s sweep measures from the UTC second."""
    if not isinstance(epoch_ns, int):
        raise TypeError(f"epoch_ns must be an int, got {type(epoch_ns).__name__}")
    if not period_s > 0:
        raise ValueError(f"period_s must be positive, got {period_s!r}")
    second = epoch_ns // 1_000_000_000
    stamp = datetime.fromtimestamp(second, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return stamp, epoch_ns % round(period_s * 1e9)


def utc_iso_ms(epoch_s: float) -> str:
    """Millisecond ISO-8601 UTC text, for a capture's start."""
    t = datetime.fromtimestamp(round(epoch_s * 1000) / 1000, tz=timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def provenance(t_level: Optional[str], counter_epoch_id: str = "") -> dict:
    """The provenance block for an arrival timed by ``t_level``.

    T6 gets the assumed block the solver counts; anything else, the null
    block, so the row counts for hearing and physics but never for offsets."""
    if (t_level or "").upper() == "T6":
        return dict(u_epoch_ns=U_EPOCH_NS, k=K, p=None, a_level="",
                    a_level_provenance="assumed", counter_epoch_id=counter_epoch_id or "",
                    origin=T6_ORIGIN)
    return dict(u_epoch_ns=None, k=None, p=None, a_level="", a_level_provenance="",
                counter_epoch_id="", origin="")


def _row(columns, defaults, kw) -> dict:
    unknown = set(kw) - set(columns)
    if unknown:
        raise TypeError(f"not a column: {sorted(unknown)}")
    row = dict(defaults)
    row.update(provenance(None))
    row.update(kw)
    for key in ("engineering", "expected"):
        if key in columns and row.get(key) is None:
            row[key] = {}
    return {c: row[c] for c in columns}


def arrival_row(**kw) -> dict:
    """An arrival row: exactly ARRIVAL_COLUMNS, in order, defaults filled."""
    return _row(ARRIVAL_COLUMNS, _ARRIVAL_DEFAULTS, kw)


def capture_row(**kw) -> dict:
    """A capture row: exactly CAPTURE_COLUMNS, in order, defaults filled."""
    return _row(CAPTURE_COLUMNS, _CAPTURE_DEFAULTS, kw)
