"""TimeMap schema v2 — the runtime carrier of MEASUREMENT_MODEL §8 and the
state / chain records of TIMING_PROVENANCE_MODEL §3."""
from __future__ import annotations

import math

import pytest

from hamsci_dsp.timing_map import BudgetTerm, Chain, DISPOSITIONS, SCHEMA


def test_schema_is_v2():
    assert SCHEMA == "v2"


def test_term_states_a_value_or_a_disposition_never_neither():
    BudgetTerm("ts1_modulator_delay", type="B", correction_ns=0, u_ns=200,
               method="designer statement, WB6CXC, 2026-08-30")
    BudgetTerm("antenna_to_injector", type="B", disposition="not_declared",
               method="station-specific")
    with pytest.raises(ValueError, match="value or a disposition"):
        BudgetTerm("mystery", type="B", method="nothing stated")


def test_type_a_term_needs_measured_on():
    with pytest.raises(ValueError, match="measured_on"):
        BudgetTerm("edge_estimation", type="A", correction_ns=0, u_ns=150,
                   method="repeatability")
    BudgetTerm("edge_estimation", type="A", correction_ns=0, u_ns=150,
               method="repeatability",
               measured_on={"build": "folded-2026-08-29", "date": "2026-08-29"})


def test_unknown_disposition_is_refused():
    with pytest.raises(ValueError, match="disposition"):
        BudgetTerm("x", type="B", disposition="maybe", method="")
    assert {"declared", "not_declared", "cancels", "historical",
            "per_interval", "excluded_by_convention"} == set(DISPOSITIONS)


def test_term_round_trips():
    t = BudgetTerm("gnss_antenna_feed", type="B", disposition="not_declared",
                   method="length x velocity factor; a sign-known bias")
    assert BudgetTerm.from_dict(t.to_dict()) == t


def _payload_chain():
    return Chain(
        id="payload-anchored@1",
        measurand="UTC instant at which sample n was taken, at the antenna terminals",
        measurand_plane="antenna_terminals",
        calibration_plane="ts1_injection_point",
        traceability={"claim": "UTC(USNO) via GPS", "qualified": True,
                      "qualification": "antenna-to-injector path not declared"},
        budget=(
            BudgetTerm("ts1_modulator_delay", type="B", correction_ns=0, u_ns=200,
                       method="designer statement, WB6CXC, 2026-08-30"),
            BudgetTerm("anchor_origin_dispersion", type="A", correction_ns=0, u_ns=1900,
                       method="63 anchors over 4.5 h", disposition="historical",
                       measured_on={"build": "pre-folding", "date": "2026-08-24"}),
            BudgetTerm("edge_estimation", type="B", correction_ns=0, u_ns=5000,
                       method="conservative bound until the fine-stage sweep runs"),
            BudgetTerm("antenna_to_injector", type="B", disposition="not_declared",
                       spans=("antenna_terminals", "ts1_injection_point"),
                       method="feed, preamp, filter; station-specific"),
            BudgetTerm("injector_to_receiver", disposition="cancels",
                       spans=("ts1_injection_point", "rx888_adc"),
                       method="identical path for signal and reference"),
            BudgetTerm("filter_group_delay", type="B", disposition="excluded_by_convention",
                       method="content convention: pipeline latency outside the measurand"),
        ),
    )


def test_u_combined_is_rss_of_the_terms_that_carry_u():
    c = _payload_chain()
    assert c.u_combined_ns == round(math.sqrt(200**2 + 1900**2 + 5000**2))  # 5353


def test_u_combined_is_none_when_a_term_is_per_interval():
    c = Chain(
        id="sysclock@1", measurand="UTC instant at radiod's advertised epoch",
        measurand_plane="radiod_rtp_timesnap", calibration_plane="host_system_clock",
        traceability={"claim": "UTC via the host clock's chrony reference", "qualified": True,
                      "qualification": "registration descends from the host clock"},
        budget=(
            BudgetTerm("pair_non_atomicity", type="A", correction_ns=0, u_ns=8_030_000,
                       method="p99, 900 s, 2026-08-16", disposition="historical",
                       measured_on={"build": "pre-anchor-inversion", "date": "2026-08-16"}),
            BudgetTerm("host_clock_discipline", type="A", disposition="per_interval",
                       method="largest witnessed disagreement, per state block"),
        ),
        k=1,
    )
    assert c.u_combined_ns is None


def test_chain_record_round_trips_and_names_its_type():
    c = _payload_chain()
    rec = c.to_record()
    assert rec["type"] == "chain" and rec["schema"] == "v2"
    assert rec["id"] == "payload-anchored@1"
    assert rec["u_combined_ns"] == 5353 and rec["k"] == 2
    assert Chain.from_record(rec) == c


from hamsci_dsp.timing_map import TimeMap, RULER_PPM_STANDIN  # noqa: E402

T0 = 1_788_537_251_999_997_458          # 2026-09-04T15:54:11.999997458Z (348.000002542 s before 16:00:00Z)


def _b4_map(**kw):
    base = dict(
        counter_space="AC0G-B4-status.local/T6_96000", counter_epoch_id="r-2026-09-04T16:03:35Z",
        n0=2_150_319_213, t0_utc_ns=T0, f_s_hz=96_000, chain="payload-anchored@1",
        origin="native_anchor", u_epoch_ns=1_500_000, k=2, p=0.95,
        measured_at_utc_ns=T0, stability_ns=120, tau_s=60.0,
        a_level="A1", a_level_provenance="observed",
        measurand_plane="antenna_terminals", calibration_plane="ts1_injection_point",
        engineering={"judge_tier": "T6", "lock_credible": True},
    )
    base.update(kw)
    return TimeMap(**base)


def test_utc_at_registration_sample_is_t0():
    assert _b4_map().utc_ns_at(2_150_319_213) == T0


def test_utc_advances_at_the_ruler_rate():
    m = _b4_map()
    assert m.utc_ns_at(2_150_319_213 + 96_000) == T0 + 1_000_000_000
    assert m.utc_ns_at(2_150_319_213 + 48) == T0 + 500_000


def test_utc_uses_signed_32_bit_difference_across_the_wrap():
    m = _b4_map(n0=0xFFFF_FFF0)
    # 32 samples later the counter has wrapped to 0x10
    assert m.utc_ns_at(0x10) == T0 + _BILLION * 32 // 96_000


def test_no_registration_refuses_to_label():
    m = _b4_map(origin=None, n0=None, t0_utc_ns=None, u_epoch_ns=None,
                reason="no anchor, no usable pair")
    with pytest.raises(ValueError, match="no registration"):
        m.utc_ns_at(5)


def test_uncertainty_ages_at_the_ruler_rate():
    m = _b4_map(u_epoch_ns=1_000)
    one_hour = T0 + 3600 * _BILLION
    # A1 stand-in 0.01 ppm: 3600 s * 0.01e-6 = 36 us
    expected = math.sqrt(1_000**2 + 36_000**2)
    assert m.u_epoch_ns_at(one_hour) == round(expected)
    assert m.u_epoch_ns_at(T0) == 1_000


def test_undisciplined_ruler_ages_faster():
    m = _b4_map(u_epoch_ns=1_000, a_level="A0", a_level_provenance="assumed")
    one_hour = T0 + 3600 * _BILLION
    # 2.0 ppm stand-in: 7.2 ms per hour
    assert m.u_epoch_ns_at(one_hour) == round(math.sqrt(1_000**2 + 7_200_000**2))
    assert RULER_PPM_STANDIN == {"A1": 0.01, "A0": 2.0}


def test_state_record_shape_and_round_trip():
    m = _b4_map()
    rec = m.to_state_record(T0)
    assert rec["type"] == "state" and rec["schema"] == "v2"
    assert rec["t"] == "2026-09-04T15:54:11.999997458Z"   # nine digits: the record round-trips
    for key in ("counter_space", "counter_epoch_id", "n0", "t0_utc_ns", "f_s_hz",
                "chain", "origin", "u_epoch_ns", "k", "p", "measured_at",
                "stability_ns", "tau_s", "a_level", "a_level_provenance",
                "measurand_plane", "calibration_plane", "engineering"):
        assert key in rec, key
    assert rec["engineering"]["judge_tier"] == "T6"
    assert "judge_tier" not in rec                    # the tier lives in engineering only
    assert TimeMap.from_state_record(rec) == m


from hamsci_dsp.timing_map import _BILLION  # noqa: E402  (test helper)


from hamsci_dsp.timing_map import (  # noqa: E402
    PAIR_P99_NS_STANDIN, host_clock_bound_ns, native_anchor_map, null_map, sysclock_map,
)

HC_OK = {"verdict": "ok", "reason": "every witness agrees", "witnesses": {
    "T2": {"kind": "pair_ms", "value": 11.2, "bound": 60.0, "exceeded": False}}}
HC_B4_1500Z = {"verdict": "fault", "reason": "T2 disagrees by 11679.5 ms (> 1000 ms)",
               "witnesses": {
                   "T2": {"kind": "pair_ms", "value": 11679.507, "bound": 60.0, "exceeded": True},
                   "lb1421": {"kind": "gps_second_s", "value": -12.1, "bound": 1.0, "exceeded": True}},
               "since_utc": "2026-09-04T02:47:12.000000Z"}


def test_host_clock_bound_takes_the_largest_disagreement_in_ns():
    assert host_clock_bound_ns(HC_B4_1500Z) == 12_100_000_000     # lb1421 -12.1 s wins
    assert host_clock_bound_ns(HC_OK) is None
    assert host_clock_bound_ns(None) is None
    assert host_clock_bound_ns({"verdict": "unwitnessed", "witnesses": {}}) is None


def test_sysclock_map_wears_the_pairs_measured_uncertainty_when_the_clock_is_ok():
    m = sysclock_map(counter_space="AC0G-ND-status.local/SHARED_10000", counter_epoch_id="r-1",
                     gps_time_ns=1_788_537_000_000_000_000, rtp_timesnap=123_456,
                     f_s_hz=24_000, measured_at_utc_ns=1_788_537_000_000_000_000,
                     a_level="A1", a_level_provenance="observed", host_clock=HC_OK)
    assert m.origin == "sysclock" and m.chain == "sysclock@1"
    assert (m.n0, m.t0_utc_ns) == (123_456, 1_788_537_000_000_000_000)
    assert m.u_epoch_ns == PAIR_P99_NS_STANDIN == 8_030_000
    assert (m.k, m.p) == (1, 0.99)
    assert "pair_non_atomicity" in m.reason
    assert m.engineering["host_clock"]["verdict"] == "ok"


def test_sysclock_map_on_b4_at_1500z_says_eleven_seconds():
    # The record that should have been written on AC0G-B4 at 15:00Z, 2026-09-04.
    m = sysclock_map(counter_space="AC0G-B4-status.local/SHARED_10000", counter_epoch_id="r-1",
                     gps_time_ns=1_788_534_000_000_000_000, rtp_timesnap=1,
                     f_s_hz=24_000, measured_at_utc_ns=1_788_534_000_000_000_000,
                     a_level="A1", a_level_provenance="observed", host_clock=HC_B4_1500Z)
    assert m.u_epoch_ns == 12_100_000_000
    assert (m.k, m.p) == (1, 1.0)
    assert "host_clock: fault" in m.reason and "lb1421" in m.reason


def test_native_anchor_map_carries_the_anchor_and_standard_uncertainty():
    m = native_anchor_map(counter_space="AC0G-B4-status.local/T6_96000", counter_epoch_id="r-1",
                          anchor_rtp=2_150_319_213, anchor_utc_ns=T0, sample_rate_hz=96_000,
                          measured_at_utc_ns=T0, sigma_ns=4_093, lock_credible=True,
                          a_level="A1", a_level_provenance="observed", host_clock=HC_OK,
                          engineering={"judge_tier": "T6"})
    assert m.origin == "native_anchor" and m.chain == "payload-anchored@1"
    assert m.u_epoch_ns == 4_093 and (m.k, m.p) == (2, 0.95)
    assert m.utc_ns_at(2_150_319_213) == T0
    assert m.engineering["lock_credible"] is True
    assert m.engineering["host_clock"]["verdict"] == "ok"   # outside the measurand, recorded


def test_native_anchor_map_refuses_a_lock_that_is_not_credible():
    # 2026-09-04 15:53Z: raw 158.474 ms accepted "as-is", the LB-1421 path shut.
    m = native_anchor_map(counter_space="AC0G-B4-status.local/T6_96000", counter_epoch_id="r-1",
                          anchor_rtp=1, anchor_utc_ns=T0, sample_rate_hz=96_000,
                          measured_at_utc_ns=T0, sigma_ns=4_000, lock_credible=False,
                          a_level="A1", a_level_provenance="observed")
    assert m.origin is None and m.u_epoch_ns is None
    assert "lock_not_credible" in m.reason
    assert m.engineering["lock_credible"] is False
    with pytest.raises(ValueError):
        m.utc_ns_at(1)


def test_native_anchor_without_sigma_is_not_a_registration():
    m = native_anchor_map(counter_space="x", counter_epoch_id="r", anchor_rtp=1, anchor_utc_ns=T0,
                          sample_rate_hz=96_000, measured_at_utc_ns=T0, sigma_ns=None,
                          lock_credible=True, a_level="A1", a_level_provenance="observed")
    assert m.origin is None and "no uncertainty" in m.reason


def test_null_map_states_its_reason():
    m = null_map(counter_space="x", counter_epoch_id="r", f_s_hz=24_000,
                 measured_at_utc_ns=T0, reason="no anchor, no usable pair")
    rec = m.to_state_record(T0)
    assert rec["origin"] is None and rec["u_epoch_ns"] is None
    assert rec["reason"] == "no anchor, no usable pair"


import json  # noqa: E402
from pathlib import Path  # noqa: E402

GOLDEN = Path(__file__).parent / "golden"


def _parse_t(s):
    from hamsci_dsp.timing_map import _parse_iso_z_ns
    return _parse_iso_z_ns(s)


def test_golden_state_record_round_trips_byte_for_byte():
    rec = json.loads((GOLDEN / "timing_state_b4_20260904T1600Z.json").read_text())
    m = TimeMap.from_state_record(rec)
    again = m.to_state_record(_parse_t(rec["t"]))
    assert again == rec


def test_golden_chain_record_round_trips_byte_for_byte():
    rec = json.loads((GOLDEN / "timing_chain_payload_anchored_v1.json").read_text())
    assert Chain.from_record(rec).to_record() == rec


def test_parse_iso_reads_the_shorter_forms_other_writers_use():
    from hamsci_dsp.timing_map import _parse_iso_z_ns
    base = 1_788_537_600 * _BILLION
    assert _parse_iso_z_ns("2026-09-04T16:00:00Z") == base
    assert _parse_iso_z_ns("2026-09-04T16:00:00.5Z") == base + 500_000_000
    assert _parse_iso_z_ns("2026-09-04T16:00:00.000001+00:00") == base + 1_000
    assert _parse_iso_z_ns("2026-09-04T16:00:00.000000001Z") == base + 1
