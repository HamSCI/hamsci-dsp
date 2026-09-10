"""Tests for hamsci_dsp.timing.AuthorityReader.

Mirrors the behaviour the sibling clients (hf-tec / codar-sounder /
psk-recorder / wspr-recorder) rely on: all error paths return None rather
than raising, schema/freshness are enforced, and the provenance block shape
is stable.
"""
import json
from datetime import datetime, timedelta, timezone

from hamsci_dsp.timing import (
    AnchorUTC,
    AuthorityReader,
    AuthoritySnapshot,
    acquire_anchor_utc,
    standalone_timing_authority,
)

_NOW = datetime(2026, 6, 23, 12, 0, 0, tzinfo=timezone.utc)


def _write(tmp_path, payload):
    p = tmp_path / "authority.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _fresh_payload(**overrides):
    base = {
        "schema": "v1",
        "utc_published": _NOW.isoformat(),
        "a_level": "A1",
        "t_level_active": "T3",
        "t_level_available": ["T3", "T4"],
        "t_level_witnesses": ["WWV"],
        "rtp_to_utc_offset_ns": 1_500_000,
        "sigma_ns": 2000,
        "stations_contributing": ["WWV"],
        "last_transition_utc": _NOW.isoformat(),
        "disagreement_flags": [],
        "governor_radiod": "fhe-rx888",
    }
    base.update(overrides)
    return base


def test_reads_fresh_snapshot(tmp_path):
    p = _write(tmp_path, _fresh_payload())
    snap = AuthorityReader(path=p, now_fn=lambda: _NOW).read()
    assert snap is not None
    assert snap.offset_usable
    assert snap.rtp_to_utc_offset_ns == 1_500_000
    assert abs(snap.offset_seconds - 0.0015) < 1e-12
    block = snap.to_timing_authority(client_radiod="fhe-rx888")
    assert block["source"] == "hf-timestd-authority"
    assert block["client_radiod"] == "fhe-rx888"
    assert block["rtp_to_utc_offset_ns"] == 1_500_000


def test_missing_file_returns_none(tmp_path):
    snap = AuthorityReader(path=tmp_path / "nope.json", now_fn=lambda: _NOW).read()
    assert snap is None


def test_stale_snapshot_returns_none(tmp_path):
    p = _write(tmp_path, _fresh_payload())
    later = _NOW + timedelta(seconds=120)
    snap = AuthorityReader(path=p, freshness_sec=60.0, now_fn=lambda: later).read()
    assert snap is None


def test_unsupported_schema_returns_none(tmp_path):
    p = _write(tmp_path, _fresh_payload(schema="v999"))
    assert AuthorityReader(path=p, now_fn=lambda: _NOW).read() is None


def test_malformed_json_returns_none(tmp_path):
    p = tmp_path / "authority.json"
    p.write_text("{ not json", encoding="utf-8")
    assert AuthorityReader(path=p, now_fn=lambda: _NOW).read() is None


def test_offset_not_usable_when_absent(tmp_path):
    p = _write(tmp_path, _fresh_payload(t_level_active=None, rtp_to_utc_offset_ns=None))
    snap = AuthorityReader(path=p, now_fn=lambda: _NOW).read()
    assert snap is not None
    assert not snap.offset_usable


def test_negative_offset_handled(tmp_path):
    # A behind-real-time radiod yields a negative RTP->UTC offset; it must
    # round-trip with sign intact (clients add it to the anchor UTC).
    p = _write(tmp_path, _fresh_payload(rtp_to_utc_offset_ns=-1_234_567))
    snap = AuthorityReader(path=p, now_fn=lambda: _NOW).read()
    assert snap is not None
    assert snap.rtp_to_utc_offset_ns == -1_234_567
    assert abs(snap.offset_seconds - (-0.001234567)) < 1e-12


def test_governor_radiod_none_when_absent(tmp_path):
    payload = _fresh_payload()
    del payload["governor_radiod"]
    snap = AuthorityReader(path=_write(tmp_path, payload), now_fn=lambda: _NOW).read()
    assert snap is not None
    assert snap.governor_radiod is None


# ── acquire_anchor_utc ────────────────────────────────────────────────────

class _Snap:
    """Minimal AuthoritySnapshot stand-in (offset usable)."""
    def __init__(self, offset_ns=2_000_000):
        self.rtp_to_utc_offset_ns = offset_ns
        self.t_level_active = "T3"

    @property
    def offset_usable(self):
        return self.t_level_active is not None and self.rtp_to_utc_offset_ns is not None

    @property
    def offset_seconds(self):
        return (self.rtp_to_utc_offset_ns or 0) / 1e9


def _rtp_to_utc_ok(rtp, ci, wallclock_hint_sec=None):
    # Pretend radiod's RTP maps to a fixed GPS-true instant.
    return 1_700_000_000.0


def _rtp_to_utc_none(rtp, ci, wallclock_hint_sec=None):
    return None


def test_anchor_rtp_referenced_with_authority():
    a = acquire_anchor_utc(
        first_rtp=12345, channel_info=object(), rtp_to_utc=_rtp_to_utc_ok,
        snapshot=_Snap(offset_ns=2_000_000),  # +2 ms
    )
    assert a.rtp_referenced
    assert a.source == "rtp_to_utc+authority"
    assert abs(a.utc - (1_700_000_000.0 + 0.002)) < 1e-9
    assert a.offset_ns == 2_000_000


def test_anchor_rtp_referenced_no_authority():
    a = acquire_anchor_utc(
        first_rtp=12345, channel_info=object(), rtp_to_utc=_rtp_to_utc_ok,
        snapshot=None,
    )
    assert a.rtp_referenced
    assert a.source == "rtp_to_utc"
    assert a.utc == 1_700_000_000.0
    assert a.offset_seconds == 0.0


def test_anchor_falls_back_when_no_channel_info():
    # samples_behind names the first held sample, not "now".
    a = acquire_anchor_utc(
        first_rtp=None, channel_info=None, rtp_to_utc=_rtp_to_utc_ok,
        snapshot=None, samples_behind=2400, sample_rate=12000,
        now_fn=lambda: 1_700_000_500.0,
    )
    assert not a.rtp_referenced
    assert a.source == "wallclock_fallback"
    assert abs(a.utc - (1_700_000_500.0 - 0.2)) < 1e-9


def test_anchor_fallback_applies_authority_offset():
    a = acquire_anchor_utc(
        first_rtp=None, channel_info=None, rtp_to_utc=_rtp_to_utc_ok,
        snapshot=_Snap(offset_ns=5_000_000), now_fn=lambda: 1_700_000_500.0,
    )
    assert not a.rtp_referenced
    assert a.source == "authority_on_wallclock"
    assert abs(a.utc - (1_700_000_500.0 + 0.005)) < 1e-9


def test_anchor_falls_back_when_rtp_to_utc_returns_none():
    a = acquire_anchor_utc(
        first_rtp=12345, channel_info=object(), rtp_to_utc=_rtp_to_utc_none,
        snapshot=None, now_fn=lambda: 1_700_000_500.0,
    )
    assert not a.rtp_referenced
    assert a.source == "wallclock_fallback"
    assert a.utc == 1_700_000_500.0


def test_anchor_reads_injected_authority_reader():
    class _Reader:
        def read(self):
            return _Snap(offset_ns=1_000_000)
    a = acquire_anchor_utc(
        first_rtp=1, channel_info=object(), rtp_to_utc=_rtp_to_utc_ok,
        authority_reader=_Reader(),
    )
    assert a.source == "rtp_to_utc+authority"
    assert a.snapshot is not None


def test_anchor_survives_authority_reader_exception():
    class _BadReader:
        def read(self):
            raise RuntimeError("boom")
    a = acquire_anchor_utc(
        first_rtp=1, channel_info=object(), rtp_to_utc=_rtp_to_utc_ok,
        authority_reader=_BadReader(),
    )
    # Degrades to no-authority RTP path, never raises.
    assert a.rtp_referenced and a.source == "rtp_to_utc"


def test_anchor_datetime_property():
    a = acquire_anchor_utc(
        first_rtp=1, channel_info=object(), rtp_to_utc=_rtp_to_utc_ok, snapshot=None,
    )
    assert a.datetime.tzinfo is timezone.utc
    assert abs(a.datetime.timestamp() - 1_700_000_000.0) < 1e-6


def test_standalone_block_shape_matches():
    block = standalone_timing_authority(client_radiod="fhe-rx888")
    assert block["source"] == "standalone-fallback"
    assert block["rtp_to_utc_offset_ns"] is None
    assert block["client_radiod"] == "fhe-rx888"
    # Same keys as the live block so consumers can treat them uniformly.
    live_keys = {
        "source", "schema", "a_level", "t_level_active", "t_level_witnesses",
        "rtp_to_utc_offset_ns", "sigma_ns", "disagreement_flags",
        "governor_radiod", "host_clock_verdict", "client_radiod", "authority_utc_published",
    }
    assert set(block) == live_keys


# ---------------------------------------------------------------------------
# sysclock_timing_authority (host-clock instruments: mag-recorder etc.)
# ---------------------------------------------------------------------------

from hamsci_dsp.timing import sysclock_timing_authority

# chronyc -c tracking, captured on AC0G-B4 2026-08-10 (FUSE, stratum 1)
_B4_TRACKING = (
    "46555345,FUSE,1,1786391861.237280040,0.000008532,0.000001637,"
    "0.000003967,-82.096,0.000,0.004,0.001000000,0.000181586,32.0,Normal"
)


def test_sysclock_block_from_tracking_csv():
    block = sysclock_timing_authority(tracking_csv=_B4_TRACKING)
    assert block["source"] == "chrony-sysclock"
    assert block["timing_source"] == "CHRONY_FUSE"
    assert block["t_level_active"] == "T4"
    assert block["stratum"] == 1
    assert block["leap_status"] == "Normal"
    # max-error bound: |offset| + root_dispersion + root_delay/2
    expected_ns = int((0.000008532 + 0.000181586 + 0.001 / 2) * 1e9)
    assert abs(block["sigma_ns"] - expected_ns) <= 1
    assert block["system_time_offset_ns"] == 8532
    # RTP-frame keys present-but-null so the record key stays uniform.
    assert block["rtp_to_utc_offset_ns"] is None
    assert block["governor_radiod"] is None


def test_sysclock_block_key_superset_of_authority_block():
    live_keys = set(standalone_timing_authority())
    block = sysclock_timing_authority(tracking_csv=_B4_TRACKING)
    assert live_keys <= set(block)


def test_sysclock_not_synchronised():
    csv = _B4_TRACKING.replace(",Normal", ",Not synchronised").replace(
        "46555345,FUSE,1", "7F7F0101,,0"
    )
    block = sysclock_timing_authority(tracking_csv=csv)
    assert block["source"] == "chrony-sysclock"
    assert block["t_level_active"] is None
    assert block["sigma_ns"] is None
    assert block["leap_status"] == "Not synchronised"


def test_sysclock_malformed_csv_falls_back():
    block = sysclock_timing_authority(tracking_csv="not,a,tracking,line")
    assert block["source"] == "sysclock-fallback"
    assert block["t_level_active"] is None
    assert block["sigma_ns"] is None


def test_sysclock_chronyc_failure_falls_back():
    def _boom(*a, **k):
        raise OSError("chronyc missing")
    block = sysclock_timing_authority(run_chronyc=_boom)
    assert block["source"] == "sysclock-fallback"


def test_host_clock_block_reads_through_and_names_its_verdict(tmp_path):
    from hamsci_dsp.timing import AuthorityReader
    p = tmp_path / "authority.json"
    p.write_text(json.dumps({
        "schema": "v1", "utc_published": "2026-09-04T15:06:50.012628Z",
        "a_level": "A1", "t_level_active": "T6", "t_level_available": ["T6", "T3"],
        "t_level_witnesses": ["T3", "T2"], "rtp_to_utc_offset_ns": -334104997,
        "sigma_ns": 4205, "stations_contributing": [], "last_transition_utc": None,
        "disagreement_flags": ["T6<->T2:11679.507ms>60.000ms:advisory"],
        "host_clock": {"verdict": "fault", "reason": "T2 disagrees by 11679.5 ms (> 1000 ms)",
                       "witnesses": {"T2": {"kind": "pair_ms", "value": 11679.507,
                                            "bound": 60.0, "exceeded": True}},
                       "since_utc": "2026-09-04T02:47:12.000000Z"},
    }))
    now = datetime(2026, 9, 4, 15, 6, 55, tzinfo=timezone.utc)
    snap = AuthorityReader(path=p, now_fn=lambda: now).read()
    assert snap.host_clock["verdict"] == "fault"
    assert snap.to_timing_authority()["host_clock_verdict"] == "fault"


def test_absent_host_clock_block_is_none_not_an_error(tmp_path):
    from hamsci_dsp.timing import AuthorityReader
    p = tmp_path / "authority.json"
    p.write_text(json.dumps({
        "schema": "v1", "utc_published": "2026-09-04T15:06:50.012628Z",
        "a_level": "A1", "t_level_active": "T3", "t_level_available": ["T3"],
        "t_level_witnesses": [], "rtp_to_utc_offset_ns": 0, "sigma_ns": 1000,
        "stations_contributing": [], "last_transition_utc": None, "disagreement_flags": [],
    }))
    now = datetime(2026, 9, 4, 15, 6, 55, tzinfo=timezone.utc)
    snap = AuthorityReader(path=p, now_fn=lambda: now).read()
    assert snap.host_clock is None
    assert snap.to_timing_authority()["host_clock_verdict"] is None


# ── anchor_hint_utc: re-pinning a FIXED anchor RTP long after it was taken ──
#
# AC0G-B4 2026-09-08: psk/meteor re-map a fixed anchor RTP every tick with
# rtp_to_utc(..., hint=now).  The hint must lie within ±P/2 of the anchor's
# TRUE instant (P/2 = 49.7 h at 12 kHz); once the anchor is older than that,
# the wrap epoch k flips and the anchor's UTC jumps by one full period
# (+99.42 h).  136 FT8 spots left B4 labelled four days in the future.
# The caller that knows the anchor's UTC must be able to hand it over.

def _recording_rtp_to_utc(calls):
    def f(rtp, ci, wallclock_hint_sec=None):
        calls.append(wallclock_hint_sec)
        return 1_700_000_000.0
    return f


def test_anchor_hint_utc_is_passed_as_the_wrap_hint():
    calls = []
    acquire_anchor_utc(
        first_rtp=1, channel_info=object(), rtp_to_utc=_recording_rtp_to_utc(calls),
        snapshot=None, now_fn=lambda: 1_700_400_000.0,   # "now" is 4.6 days later
        anchor_hint_utc=1_700_000_000.0,
    )
    assert calls == [1_700_000_000.0]


def test_anchor_hint_utc_defaults_to_now_plus_offset():
    calls = []
    acquire_anchor_utc(
        first_rtp=1, channel_info=object(), rtp_to_utc=_recording_rtp_to_utc(calls),
        snapshot=_Snap(offset_ns=2_000_000), now_fn=lambda: 1_700_000_500.0,
    )
    assert calls == [1_700_000_500.002]


# ── AnchorUTC.timing_authority_applied — the §3 / §18.5 report ──────────

class _FullSnap(_Snap):
    """Snapshot stand-in carrying the fields the report needs."""
    def __init__(self, offset_ns=2_000_000, tier="T6", sigma_ns=4210,
                 governor="AC0G-B4-status.local", published=_NOW):
        super().__init__(offset_ns)
        self.t_level_active = tier
        self.sigma_ns = sigma_ns
        self.governor_radiod = governor
        self.utc_published = published
        self.host_clock = {"verdict": "ok"}


def test_applied_block_reports_the_snapshot_that_corrected_the_labels():
    a = acquire_anchor_utc(
        first_rtp=1, channel_info=object(), rtp_to_utc=_rtp_to_utc_ok,
        snapshot=_FullSnap(),
    )
    block = a.timing_authority_applied(
        client_radiod="AC0G-B4-status.local",
        now_fn=lambda: (_NOW + timedelta(seconds=4.2)).timestamp(),
    )
    # CLIENT-CONTRACT §3 keys, in the contract's own example shape.
    assert block["source"] == "hf-timestd@AC0G-B4-status.local"
    assert block["tier"] == "T6"
    assert block["sigma_ns"] == 4210
    assert abs(block["snapshot_age_s"] - 4.2) < 1e-6
    assert block["radiod_id"] == "AC0G-B4-status.local"
    # Additive provenance so a reader can align the labels later (§18.5).
    assert block["rtp_to_utc_offset_ns"] == 2_000_000
    assert block["anchor_source"] == "rtp_to_utc+authority"
    assert block["host_clock_verdict"] == "ok"


def test_applied_block_is_none_when_labels_carry_no_correction():
    # §18.5: "Fetching the snapshot ... does not count as applying it."
    a = acquire_anchor_utc(
        first_rtp=1, channel_info=object(), rtp_to_utc=_rtp_to_utc_ok, snapshot=None,
    )
    assert a.timing_authority_applied(client_radiod="x") is None


def test_applied_block_populated_on_the_wallclock_fallback_with_offset():
    # The offset WAS applied to the label, so the report says so, and the
    # anchor_source tells the reader the label is not RTP-referenced.
    a = acquire_anchor_utc(
        first_rtp=None, channel_info=None, rtp_to_utc=_rtp_to_utc_ok,
        snapshot=_FullSnap(), now_fn=lambda: _NOW.timestamp(),
    )
    block = a.timing_authority_applied(client_radiod="x", now_fn=lambda: _NOW.timestamp())
    assert block is not None
    assert block["anchor_source"] == "authority_on_wallclock"


# ── applied-state file: the daemon writes, `inventory --json` reads ──────
#
# The inventory command is a separate process from the recorder, so the
# recorder leaves the block it applied where the inventory can find it.

def test_applied_state_round_trips_through_a_file(tmp_path):
    from hamsci_dsp.timing import read_applied_state, write_applied_state
    p = tmp_path / "timing-authority.json"
    block = {"source": "hf-timestd@x", "tier": "T6", "sigma_ns": 1}
    write_applied_state(p, block, now_fn=lambda: 1000.0)
    assert read_applied_state(p, max_age_s=300.0, now_fn=lambda: 1100.0) == block


def test_applied_state_is_none_when_stale_missing_or_garbled(tmp_path):
    from hamsci_dsp.timing import read_applied_state, write_applied_state
    p = tmp_path / "timing-authority.json"
    assert read_applied_state(p, max_age_s=300.0, now_fn=lambda: 0.0) is None
    write_applied_state(p, {"tier": "T6"}, now_fn=lambda: 1000.0)
    # The recorder stopped writing: the instance is no longer applying anything.
    assert read_applied_state(p, max_age_s=300.0, now_fn=lambda: 1400.0) is None
    p.write_text("{not json", encoding="utf-8")
    assert read_applied_state(p, max_age_s=300.0, now_fn=lambda: 1000.0) is None


def test_applied_state_writes_null_as_an_explicit_not_applied(tmp_path):
    from hamsci_dsp.timing import read_applied_state, write_applied_state
    p = tmp_path / "timing-authority.json"
    write_applied_state(p, None, now_fn=lambda: 1000.0)
    # Present and fresh, and it says "default mode".
    assert read_applied_state(p, max_age_s=300.0, now_fn=lambda: 1001.0) is None
    assert json.loads(p.read_text())["timing_authority_applied"] is None


# ── applied_state_for_anchors — one instance, many channels, one report ──
#
# psk/meteor own one AnchorUTC per ChannelSink and wspr one per BandRecorder.
# The instance's labels ride the authority only when every anchored channel's
# do (§18.7: a mixed state must stay visible, never averaged away).

def _anchor_with(offset_ns, utc=1_700_000_500.0):
    snap = _FullSnap(offset_ns=offset_ns) if offset_ns is not None else None
    return AnchorUTC(
        utc=utc, source="rtp_to_utc+authority" if snap else "rtp_to_utc",
        offset_seconds=(offset_ns or 0) / 1e9, offset_ns=offset_ns,
        snapshot=snap, rtp_referenced=True,
    )


def test_aggregate_populated_when_every_anchored_channel_is_corrected():
    from hamsci_dsp.timing import applied_state_for_anchors
    block = applied_state_for_anchors(
        [_anchor_with(4_250_000), _anchor_with(4_250_000), None], client_radiod="rx",
    )
    assert block["tier"] == "T6"
    assert block["radiod_id"] == "rx"
    assert block["channels"] == {"total": 3, "anchored": 2, "applied": 2}


def test_aggregate_null_when_one_anchored_channel_lacks_the_correction():
    from hamsci_dsp.timing import applied_state_for_anchors
    assert applied_state_for_anchors(
        [_anchor_with(4_250_000), _anchor_with(None)], client_radiod="rx",
    ) is None


def test_aggregate_null_when_nothing_is_anchored():
    from hamsci_dsp.timing import applied_state_for_anchors
    assert applied_state_for_anchors([None, None], client_radiod="rx") is None


def test_aggregate_describes_the_newest_anchor():
    from hamsci_dsp.timing import applied_state_for_anchors
    block = applied_state_for_anchors(
        [_anchor_with(1_000, utc=100.0), _anchor_with(2_000, utc=200.0)], client_radiod="rx",
    )
    assert block["rtp_to_utc_offset_ns"] == 2_000


def test_anchor_needs_only_the_published_offset_field():
    # The schema publishes rtp_to_utc_offset_ns; offset_seconds is a
    # convenience on the dataclass.  Duck-typed snapshots (wspr's tests,
    # a future reader) carry only the published field.
    class _MinimalSnap:
        offset_usable = True
        rtp_to_utc_offset_ns = 2_000_000
    a = acquire_anchor_utc(
        first_rtp=1, channel_info=object(), rtp_to_utc=_rtp_to_utc_ok,
        snapshot=_MinimalSnap(),
    )
    assert a.source == "rtp_to_utc+authority"
    assert abs(a.utc - (1_700_000_000.0 + 0.002)) < 1e-9
    assert a.offset_seconds == 0.002
