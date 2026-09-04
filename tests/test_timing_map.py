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
