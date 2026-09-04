# TimeMap schema v2 Implementation Plan (hamsci-dsp)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the runtime carrier of `MEASUREMENT_MODEL.md` §8 — the `TimeMap` — and the `state` / `chain` records of `TIMING_PROVENANCE_MODEL.md` §3 into `hamsci_dsp.timing` as schema v2, pure and tested, so hf-timestd (producer) and hamsci-physics (consumer) build on one shape.

**Architecture:** One new module `hamsci_dsp/timing_map.py` holds frozen dataclasses (`BudgetTerm`, `Chain`, `TimeMap`), the two builders (`sysclock_map`, `native_anchor_map`), the composition law, and record (de)serialisation. `hamsci_dsp/timing.py` (schema v1 reader) gains one optional field, `host_clock`, read from authority.json. `hamsci_dsp/io/authority_snapshot_store.py` gains four flat columns for the host-clock verdict. No I/O in the new module; no behaviour change for existing v1 consumers.

**Tech Stack:** Python ≥3.10, dataclasses, pytest (`.venv/bin/python -m pytest tests -p no:cacheprovider`). No new dependencies.

**Spec:** `/home/mjh/hamsci/repos/hf-timestd/docs/design/TIMING_PROVENANCE_MODEL.md` (amended 2026-09-04) §3.1, §3.1.1, §3.2, §3.3, §3.4, §6 deliverable 1; `/home/mjh/hamsci/repos/hf-timestd/docs/design/MEASUREMENT_MODEL.md` §1, §3, §4, §5, §8, §9.

## Global Constraints

- Pure logic only in `timing_map.py`: no clock reads, no file I/O, no subprocess (spec §3 "the day can be replayed").
- Every uncertainty carries `k` and `p`; never a bare sigma (spec §3.1).
- Absence stays visible as absence: `origin: None`, `u_epoch_ns: None`, and a `reason` (MEASUREMENT_MODEL §9 invariant 3).
- A `BudgetTerm` states a value or a `disposition`; never neither (spec §3.2). A Type A term carries `measured_on` (spec §3.2).
- Dispositions: `declared`, `not_declared`, `cancels`, `historical`, `per_interval`, `excluded_by_convention` (spec §3.2, amended).
- Signed-32 RTP arithmetic identical to `hf_timestd.core.native_anchor.utc_ns_at_rtp` (MEASUREMENT_MODEL §8).
- Composition law: `u(t₀, t) = sqrt(u(t₀, t_reg)² + ((t − t_reg) · u(f_s)/f_s)²)` (MEASUREMENT_MODEL §4).
- Pair non-atomicity stand-in: p99 = 8 030 000 ns, Type A, `measured_on` 2026-08-16 AC0G-B4, disposition `historical` (spec §3.1.1).
- `u(f_s)/f_s` stand-ins: A1 disciplined 0.01 ppm; A0 undisciplined 2.0 ppm (MEASUREMENT_MODEL §2).
- Schema string for v2 records: `"v2"`. v1 reading unchanged; `_SUPPORTED_SCHEMAS` stays `{"v1"}` for authority.json.
- Commit on `main` (this repo's practice); messages end with the session trailer.
- Run tests as `cd /home/mjh/hamsci/repos/hamsci-dsp && .venv/bin/python -m pytest tests/<file> -p no:cacheprovider -q`.

---

## File map

| file | responsibility |
|---|---|
| `src/hamsci_dsp/timing_map.py` (create) | `BudgetTerm`, `Chain`, `TimeMap`, builders, composition law, records |
| `src/hamsci_dsp/timing.py` (modify L40-55, L137-162) | `AuthoritySnapshot.host_clock` |
| `src/hamsci_dsp/io/authority_snapshot_store.py` (modify COLUMNS, `_REAL_COLUMNS`) | four `host_clock_*` columns |
| `tests/test_timing_map.py` (create) | the module's tests, including the two station-day replays |
| `tests/test_timing.py` (modify) | `host_clock` read-through |
| `tests/test_authority_snapshot_store.py` (modify) | new columns round-trip |
| `docs/TIMING_MAP.md` (create) | the schema, one page, for consumers |

---

### Task 1: `BudgetTerm` and `Chain` with the disposition rule and RSS

**Files:**
- Create: `src/hamsci_dsp/timing_map.py`
- Test: `tests/test_timing_map.py`

**Interfaces:**
- Produces:
  - `BudgetTerm(term: str, type: Optional[str] = None, correction_ns: Optional[int] = None, u_ns: Optional[int] = None, method: str = "", disposition: Optional[str] = None, measured_on: Optional[dict] = None, spans: Optional[tuple[str, str]] = None)`; `.to_dict() -> dict`; `BudgetTerm.from_dict(d) -> BudgetTerm`; raises `ValueError` on an invalid term.
  - `Chain(id: str, measurand: str, measurand_plane: str, calibration_plane: str, traceability: dict, budget: tuple[BudgetTerm, ...], k: int = 2, inherited_from: Optional[dict] = None, custody_boundary: Optional[str] = None)`; `.u_combined_ns -> Optional[int]`; `.to_record() -> dict`; `Chain.from_record(d) -> Chain`.
  - Constants `DISPOSITIONS`, `SCHEMA = "v2"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_timing_map.py
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
    assert c.u_combined_ns == round(math.sqrt(200**2 + 1900**2 + 5000**2))  # 5352


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
    assert rec["u_combined_ns"] == 5352 and rec["k"] == 2
    assert Chain.from_record(rec) == c
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/mjh/hamsci/repos/hamsci-dsp && .venv/bin/python -m pytest tests/test_timing_map.py -p no:cacheprovider -q`
Expected: `ModuleNotFoundError: No module named 'hamsci_dsp.timing_map'`

- [ ] **Step 3: Write the minimal module**

```python
# src/hamsci_dsp/timing_map.py
"""TimeMap — the runtime carrier of the measurement model, schema v2.

MEASUREMENT_MODEL.md §1: for every data product the measurand reads the UTC
instant at which sample n was taken at the station's reference plane,

    t(n) = t0 + (n - n0) / f_s + sum(delta_i)

§8 asks for one value object that carries that model at runtime so every
consumer's arithmetic and every recorded `state` block descend from one
instance.  This module is that object, plus the `chain` record of
TIMING_PROVENANCE_MODEL.md §3.2 (the plane and the budget) and the two
builders every rung fills the shape with (§3.1, §3.1.1).

Pure logic.  No clock reads, no I/O.  The producer supplies the numbers and
the time, so a station's day can be replayed here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

SCHEMA = "v2"
_BILLION = 1_000_000_000

#: TIMING_PROVENANCE_MODEL §3.2.  A term states a value or one of these.
DISPOSITIONS = (
    "declared",                 # a value is stated and applies
    "not_declared",             # the station owes this term and has not supplied it
    "cancels",                  # considered, common to both paths, contributes nothing
    "historical",               # measured on a configuration the station no longer runs
    "per_interval",             # the value lives in every state block, not in the chain
    "excluded_by_convention",   # the declared plane keeps this term out of the measurand
)


@dataclass(frozen=True)
class BudgetTerm:
    """One row of a chain's budget (MEASUREMENT_MODEL §6: correction, its
    uncertainty, GUM type, method, disposition).  Silence never means zero."""

    term: str
    type: Optional[str] = None            # "A" | "B" | None (for `cancels`)
    correction_ns: Optional[int] = None
    u_ns: Optional[int] = None
    method: str = ""
    disposition: Optional[str] = None
    measured_on: Optional[dict] = None
    spans: Optional[Tuple[str, str]] = None

    def __post_init__(self) -> None:
        if self.type not in (None, "A", "B"):
            raise ValueError(f"{self.term}: type must be A, B or None, not {self.type!r}")
        if self.disposition is not None and self.disposition not in DISPOSITIONS:
            raise ValueError(f"{self.term}: unknown disposition {self.disposition!r}")
        states_value = self.correction_ns is not None or self.u_ns is not None
        if not states_value and self.disposition is None:
            raise ValueError(f"{self.term}: a term states a value or a disposition, never neither")
        if self.type == "A" and self.u_ns is not None and self.measured_on is None:
            raise ValueError(f"{self.term}: a Type A term carries measured_on (build and date)")
        if self.spans is not None:
            object.__setattr__(self, "spans", tuple(self.spans))

    def to_dict(self) -> dict:
        d: dict = {"term": self.term}
        if self.type is not None:
            d["type"] = self.type
        if self.correction_ns is not None:
            d["correction_ns"] = int(self.correction_ns)
        if self.u_ns is not None:
            d["u_ns"] = int(self.u_ns)
        if self.disposition is not None:
            d["disposition"] = self.disposition
        if self.measured_on is not None:
            d["measured_on"] = dict(self.measured_on)
        if self.spans is not None:
            d["spans"] = list(self.spans)
        d["method"] = self.method
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "BudgetTerm":
        spans = d.get("spans")
        return cls(
            term=str(d["term"]),
            type=d.get("type"),
            correction_ns=(int(d["correction_ns"]) if d.get("correction_ns") is not None else None),
            u_ns=(int(d["u_ns"]) if d.get("u_ns") is not None else None),
            method=str(d.get("method", "")),
            disposition=d.get("disposition"),
            measured_on=(dict(d["measured_on"]) if d.get("measured_on") is not None else None),
            spans=(tuple(spans) if spans else None),
        )


@dataclass(frozen=True)
class Chain:
    """The plane and the budget (TIMING_PROVENANCE_MODEL §3.2)."""

    id: str
    measurand: str
    measurand_plane: str
    calibration_plane: str
    traceability: dict
    budget: Tuple[BudgetTerm, ...]
    k: int = 2
    inherited_from: Optional[dict] = None
    custody_boundary: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "budget", tuple(self.budget))

    @property
    def u_combined_ns(self) -> Optional[int]:
        """RSS of the terms that carry a u_ns — the uncertainty REMAINING
        after corrections.  None when any term lives per interval, because
        the chain then cannot state a single figure (spec §3.2)."""
        if any(t.disposition == "per_interval" for t in self.budget):
            return None
        us = [t.u_ns for t in self.budget if t.u_ns is not None]
        if not us:
            return None
        return int(round(math.sqrt(sum(float(u) ** 2 for u in us))))

    def to_record(self) -> dict:
        rec: dict = {
            "type": "chain",
            "schema": SCHEMA,
            "id": self.id,
            "measurand": self.measurand,
            "measurand_plane": self.measurand_plane,
            "calibration_plane": self.calibration_plane,
            "traceability": dict(self.traceability),
            "budget": [t.to_dict() for t in self.budget],
            "u_combined_ns": self.u_combined_ns,
            "k": int(self.k),
        }
        if self.inherited_from is not None:
            rec["inherited_from"] = dict(self.inherited_from)
        if self.custody_boundary is not None:
            rec["custody_boundary"] = self.custody_boundary
        return rec

    @classmethod
    def from_record(cls, rec: Mapping[str, Any]) -> "Chain":
        return cls(
            id=str(rec["id"]),
            measurand=str(rec["measurand"]),
            measurand_plane=str(rec["measurand_plane"]),
            calibration_plane=str(rec["calibration_plane"]),
            traceability=dict(rec.get("traceability") or {}),
            budget=tuple(BudgetTerm.from_dict(t) for t in rec.get("budget") or ()),
            k=int(rec.get("k", 2)),
            inherited_from=(dict(rec["inherited_from"]) if rec.get("inherited_from") else None),
            custody_boundary=rec.get("custody_boundary"),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/mjh/hamsci/repos/hamsci-dsp && .venv/bin/python -m pytest tests/test_timing_map.py -p no:cacheprovider -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
cd /home/mjh/hamsci/repos/hamsci-dsp
git add src/hamsci_dsp/timing_map.py tests/test_timing_map.py
git commit -m "timing_map: BudgetTerm and Chain -- a term states a value or a disposition, never neither

TIMING_PROVENANCE_MODEL §3.2 / MEASUREMENT_MODEL §6.  Six dispositions,
Type A needs measured_on, u_combined is the RSS of the terms that carry
a u_ns and None when one lives per interval.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 2: `TimeMap` — evaluate the measurand and age the uncertainty

**Files:**
- Modify: `src/hamsci_dsp/timing_map.py` (append)
- Test: `tests/test_timing_map.py` (append)

**Interfaces:**
- Produces:
  - `TimeMap(counter_space: str, counter_epoch_id: str, n0: Optional[int], t0_utc_ns: Optional[int], f_s_hz: int, chain: str, origin: Optional[str], u_epoch_ns: Optional[int], k: int, p: Optional[float], measured_at_utc_ns: int, stability_ns: Optional[int] = None, tau_s: Optional[float] = None, a_level: str = "A0", a_level_provenance: str = "assumed", measurand_plane: str = "", calibration_plane: str = "", reason: Optional[str] = None, engineering: Mapping[str, Any] = {})`
  - `.utc_ns_at(n: int) -> int` — raises `ValueError("no registration")` when `origin is None`.
  - `.u_epoch_ns_at(t_utc_ns: int) -> Optional[int]` — the composition law with `u(f_s)/f_s` from `a_level` (`RULER_PPM_STANDIN`).
  - `.to_state_record(t_utc_ns: int) -> dict` (spec §3.1 JSON, `type: "state"`, `schema: "v2"`, ISO `t`).
  - `TimeMap.from_state_record(rec) -> TimeMap`.
  - `RULER_PPM_STANDIN = {"A1": 0.01, "A0": 2.0}`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_timing_map.py
from hamsci_dsp.timing_map import TimeMap, RULER_PPM_STANDIN

T0 = 1_788_537_251_999_997_458          # 2026-09-04T16:04:11.999997458Z


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
    assert rec["t"] == "2026-09-04T16:04:11.999997Z"
    for key in ("counter_space", "counter_epoch_id", "n0", "t0_utc_ns", "f_s_hz",
                "chain", "origin", "u_epoch_ns", "k", "p", "measured_at",
                "stability_ns", "tau_s", "a_level", "a_level_provenance",
                "measurand_plane", "calibration_plane", "engineering"):
        assert key in rec, key
    assert rec["engineering"]["judge_tier"] == "T6"
    assert "judge_tier" not in rec                    # the tier lives in engineering only
    assert TimeMap.from_state_record(rec) == m


from hamsci_dsp.timing_map import _BILLION  # noqa: E402  (test helper)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/mjh/hamsci/repos/hamsci-dsp && .venv/bin/python -m pytest tests/test_timing_map.py -p no:cacheprovider -q`
Expected: `ImportError: cannot import name 'TimeMap'`

- [ ] **Step 3: Write the minimal implementation**

```python
# append to src/hamsci_dsp/timing_map.py
from datetime import datetime, timezone

#: u(f_s)/f_s stand-ins by ruler state, ppm (MEASUREMENT_MODEL §2).  The
#: disciplined figure is 25x the value measured on AC0G-B4 (0.0004 ppm);
#: the undisciplined one is what a free-running TCXO does.
RULER_PPM_STANDIN = {"A1": 0.01, "A0": 2.0}


def _iso_z(utc_ns: int) -> str:
    dt = datetime.fromtimestamp(utc_ns / _BILLION, tz=timezone.utc)
    return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_iso_z_ns(s: str) -> int:
    if s.endswith("Z"):
        s = s[:-1]
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(round(dt.timestamp() * _BILLION))


@dataclass(frozen=True)
class TimeMap:
    """The registration in force, its ruler, and its uncertainty
    (MEASUREMENT_MODEL §8).  `to_state_record` is the §3.1 `state` block."""

    counter_space: str
    counter_epoch_id: str
    n0: Optional[int]
    t0_utc_ns: Optional[int]
    f_s_hz: int
    chain: str
    origin: Optional[str]                 # "native_anchor" | "sysclock" | None
    u_epoch_ns: Optional[int]             # standard uncertainty at measured_at
    k: int
    p: Optional[float]
    measured_at_utc_ns: int
    stability_ns: Optional[int] = None
    tau_s: Optional[float] = None
    a_level: str = "A0"
    a_level_provenance: str = "assumed"   # observed | attested | assumed
    measurand_plane: str = ""
    calibration_plane: str = ""
    reason: Optional[str] = None
    engineering: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.origin not in (None, "native_anchor", "sysclock"):
            raise ValueError(f"origin must be native_anchor, sysclock or None, not {self.origin!r}")
        if self.origin is not None and (self.n0 is None or self.t0_utc_ns is None):
            raise ValueError("a registration needs both n0 and t0_utc_ns")
        object.__setattr__(self, "engineering", dict(self.engineering))

    # --- the measurand ------------------------------------------------------

    def utc_ns_at(self, n: int) -> int:
        """t(n) = t0 + (n - n0) / f_s, with Karn's signed-32 difference.
        Corrections are already folded into t0 (MEASUREMENT_MODEL §1)."""
        if self.origin is None or self.n0 is None or self.t0_utc_ns is None:
            raise ValueError(f"no registration: {self.reason or 'origin is null'}")
        delta = (int(n) - int(self.n0)) & 0xFFFFFFFF
        if delta > 0x7FFFFFFF:
            delta -= 0x1_0000_0000
        return int(self.t0_utc_ns) + _BILLION * delta // int(self.f_s_hz)

    # --- the composition law -------------------------------------------------

    def u_epoch_ns_at(self, t_utc_ns: int) -> Optional[int]:
        """u(t0, t) = sqrt(u(t0, t_reg)^2 + ((t - t_reg) * u(f_s)/f_s)^2)
        (MEASUREMENT_MODEL §4).  None when there is no registration."""
        if self.u_epoch_ns is None:
            return None
        ppm = RULER_PPM_STANDIN.get(self.a_level, RULER_PPM_STANDIN["A0"])
        age_ns = abs(int(t_utc_ns) - int(self.measured_at_utc_ns))
        rate_term = age_ns * ppm * 1e-6
        return int(round(math.sqrt(float(self.u_epoch_ns) ** 2 + rate_term ** 2)))

    # --- the record ----------------------------------------------------------

    def to_state_record(self, t_utc_ns: int) -> dict:
        return {
            "t": _iso_z(t_utc_ns),
            "type": "state",
            "schema": SCHEMA,
            "chain": self.chain,
            "origin": self.origin,
            "counter_space": self.counter_space,
            "counter_epoch_id": self.counter_epoch_id,
            "n0": self.n0,
            "t0_utc_ns": self.t0_utc_ns,
            "f_s_hz": int(self.f_s_hz),
            "u_epoch_ns": self.u_epoch_ns,
            "k": int(self.k),
            "p": self.p,
            "measured_at": _iso_z(self.measured_at_utc_ns),
            "stability_ns": self.stability_ns,
            "tau_s": self.tau_s,
            "a_level": self.a_level,
            "a_level_provenance": self.a_level_provenance,
            "measurand_plane": self.measurand_plane,
            "calibration_plane": self.calibration_plane,
            "reason": self.reason,
            "engineering": dict(self.engineering),
        }

    @classmethod
    def from_state_record(cls, rec: Mapping[str, Any]) -> "TimeMap":
        return cls(
            counter_space=str(rec["counter_space"]),
            counter_epoch_id=str(rec["counter_epoch_id"]),
            n0=(int(rec["n0"]) if rec.get("n0") is not None else None),
            t0_utc_ns=(int(rec["t0_utc_ns"]) if rec.get("t0_utc_ns") is not None else None),
            f_s_hz=int(rec["f_s_hz"]),
            chain=str(rec["chain"]),
            origin=rec.get("origin"),
            u_epoch_ns=(int(rec["u_epoch_ns"]) if rec.get("u_epoch_ns") is not None else None),
            k=int(rec.get("k", 1)),
            p=rec.get("p"),
            measured_at_utc_ns=_parse_iso_z_ns(str(rec["measured_at"])),
            stability_ns=(int(rec["stability_ns"]) if rec.get("stability_ns") is not None else None),
            tau_s=(float(rec["tau_s"]) if rec.get("tau_s") is not None else None),
            a_level=str(rec.get("a_level", "A0")),
            a_level_provenance=str(rec.get("a_level_provenance", "assumed")),
            measurand_plane=str(rec.get("measurand_plane", "")),
            calibration_plane=str(rec.get("calibration_plane", "")),
            reason=rec.get("reason"),
            engineering=dict(rec.get("engineering") or {}),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/mjh/hamsci/repos/hamsci-dsp && .venv/bin/python -m pytest tests/test_timing_map.py -p no:cacheprovider -q`
Expected: `15 passed`

- [ ] **Step 5: Commit**

```bash
cd /home/mjh/hamsci/repos/hamsci-dsp
git add src/hamsci_dsp/timing_map.py tests/test_timing_map.py
git commit -m "timing_map: TimeMap -- evaluate t(n) with the signed-32 difference, age u by the composition law, emit the state record

MEASUREMENT_MODEL §1, §4, §8; TIMING_PROVENANCE_MODEL §3.1.  The tier
appears only under engineering.  origin None refuses to label and says why.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 3: The two builders — every rung fills the shape

**Files:**
- Modify: `src/hamsci_dsp/timing_map.py` (append)
- Test: `tests/test_timing_map.py` (append)

**Interfaces:**
- Produces:
  - `PAIR_P99_NS_STANDIN = 8_030_000`; `PAYLOAD_CHAIN_ID = "payload-anchored@1"`; `SYSCLOCK_CHAIN_ID = "sysclock@1"`.
  - `host_clock_bound_ns(host_clock: Optional[Mapping]) -> Optional[int]` — largest witnessed disagreement in ns when verdict is `suspect` or `fault`, else None. Pair witnesses are ms, `lb1421` is s (spec §3.1 / HOST_CLOCK_INTEGRITY witness kinds).
  - `sysclock_map(*, counter_space, counter_epoch_id, gps_time_ns: int, rtp_timesnap: int, f_s_hz: int, measured_at_utc_ns: int, a_level: str, a_level_provenance: str, host_clock: Optional[Mapping] = None, pair_p99_ns: int = PAIR_P99_NS_STANDIN, engineering: Optional[Mapping] = None) -> TimeMap`
  - `native_anchor_map(*, counter_space, counter_epoch_id, anchor_rtp: int, anchor_utc_ns: int, sample_rate_hz: int, measured_at_utc_ns: int, sigma_ns: Optional[int], lock_credible: bool, a_level: str, a_level_provenance: str, host_clock: Optional[Mapping] = None, chain_id: str = PAYLOAD_CHAIN_ID, stability_ns: Optional[int] = None, tau_s: Optional[float] = None, engineering: Optional[Mapping] = None) -> TimeMap`
  - `null_map(*, counter_space, counter_epoch_id, f_s_hz, measured_at_utc_ns, reason: str, a_level="A0", a_level_provenance="assumed", engineering=None) -> TimeMap`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_timing_map.py
from hamsci_dsp.timing_map import (
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/mjh/hamsci/repos/hamsci-dsp && .venv/bin/python -m pytest tests/test_timing_map.py -p no:cacheprovider -q`
Expected: `ImportError: cannot import name 'PAIR_P99_NS_STANDIN'`

- [ ] **Step 3: Write the minimal implementation**

```python
# append to src/hamsci_dsp/timing_map.py

PAYLOAD_CHAIN_ID = "payload-anchored@1"
SYSCLOCK_CHAIN_ID = "sysclock@1"

#: TIMING_PROVENANCE_MODEL §3.1.1: the pair's measured non-atomicity, p99 over
#: 900 s on AC0G-B4's T6 channel, 2026-08-16.  A bound, so k = 1.  The
#: running-minimum estimator of MEASUREMENT_MODEL §6.2 replaces it.
PAIR_P99_NS_STANDIN = 8_030_000


def host_clock_bound_ns(host_clock: Optional[Mapping[str, Any]]) -> Optional[int]:
    """The largest witnessed host-clock disagreement, in ns, when the
    authority manager's verdict is suspect or fault; else None.

    Witness kinds follow hf_timestd.core.host_clock_integrity: pair_ms in
    milliseconds, gps_second_s in seconds, rate_ppm has no epoch meaning."""
    if not host_clock or host_clock.get("verdict") not in ("suspect", "fault"):
        return None
    worst = 0
    for w in (host_clock.get("witnesses") or {}).values():
        kind, value = w.get("kind"), w.get("value")
        if not isinstance(value, (int, float)):
            continue
        if kind == "pair_ms":
            worst = max(worst, int(round(abs(float(value)) * 1e6)))
        elif kind == "gps_second_s":
            worst = max(worst, int(round(abs(float(value)) * 1e9)))
    return worst or None


def _worst_witness_name(host_clock: Mapping[str, Any]) -> str:
    best, name = -1.0, "?"
    for n, w in (host_clock.get("witnesses") or {}).items():
        kind, value = w.get("kind"), w.get("value")
        if not isinstance(value, (int, float)):
            continue
        ns = abs(float(value)) * (1e6 if kind == "pair_ms" else 1e9 if kind == "gps_second_s" else 0)
        if ns > best:
            best, name = ns, n
    return name


def sysclock_map(
    *, counter_space: str, counter_epoch_id: str, gps_time_ns: int, rtp_timesnap: int,
    f_s_hz: int, measured_at_utc_ns: int, a_level: str, a_level_provenance: str,
    host_clock: Optional[Mapping[str, Any]] = None,
    pair_p99_ns: int = PAIR_P99_NS_STANDIN,
    engineering: Optional[Mapping[str, Any]] = None,
) -> TimeMap:
    """The registration a station with only radiod's pair can publish
    (TIMING_PROVENANCE_MODEL §3.1.1; MEASUREMENT_MODEL §8 "every rung fills
    this shape").  u_epoch_ns takes the larger of the pair's measured
    non-atomicity and the host-clock verdict's largest disagreement, and
    the reason names which governed."""
    eng = dict(engineering or {})
    eng["radiod_gps_time_ns"] = int(gps_time_ns)
    eng["radiod_rtp_timesnap"] = int(rtp_timesnap)
    if host_clock is not None:
        eng["host_clock"] = dict(host_clock)
    bound = host_clock_bound_ns(host_clock)
    if bound is not None and bound > int(pair_p99_ns):
        u, k, p = bound, 1, 1.0
        reason = (f"host_clock: {host_clock['verdict']} ({_worst_witness_name(host_clock)}) "
                  f"bounds the registration at {bound / 1e9:.3f} s")
    else:
        u, k, p = int(pair_p99_ns), 1, 0.99
        reason = "pair_non_atomicity p99 stand-in (MEASUREMENT_MODEL §6.2 estimator pending)"
    return TimeMap(
        counter_space=counter_space, counter_epoch_id=counter_epoch_id,
        n0=int(rtp_timesnap), t0_utc_ns=int(gps_time_ns), f_s_hz=int(f_s_hz),
        chain=SYSCLOCK_CHAIN_ID, origin="sysclock", u_epoch_ns=u, k=k, p=p,
        measured_at_utc_ns=int(measured_at_utc_ns),
        a_level=a_level, a_level_provenance=a_level_provenance,
        measurand_plane="radiod_rtp_timesnap", calibration_plane="host_system_clock",
        reason=reason, engineering=eng,
    )


def native_anchor_map(
    *, counter_space: str, counter_epoch_id: str, anchor_rtp: int, anchor_utc_ns: int,
    sample_rate_hz: int, measured_at_utc_ns: int, sigma_ns: Optional[int], lock_credible: bool,
    a_level: str, a_level_provenance: str,
    host_clock: Optional[Mapping[str, Any]] = None, chain_id: str = PAYLOAD_CHAIN_ID,
    stability_ns: Optional[int] = None, tau_s: Optional[float] = None,
    engineering: Optional[Mapping[str, Any]] = None,
) -> TimeMap:
    """The payload-anchored registration (TIMING_PROVENANCE_MODEL §3.1).

    MEASUREMENT_MODEL §6.4: a registration may not claim a precision its lock
    does not support.  A lock the credibility guards did not pass yields
    origin None with the reason, never a confident wrong edge."""
    eng = dict(engineering or {})
    eng["lock_credible"] = bool(lock_credible)
    if host_clock is not None:
        eng["host_clock"] = dict(host_clock)      # outside the measurand; recorded
    common = dict(
        counter_space=counter_space, counter_epoch_id=counter_epoch_id,
        f_s_hz=int(sample_rate_hz), chain=chain_id,
        measured_at_utc_ns=int(measured_at_utc_ns),
        stability_ns=stability_ns, tau_s=tau_s,
        a_level=a_level, a_level_provenance=a_level_provenance,
        measurand_plane="antenna_terminals", calibration_plane="ts1_injection_point",
        engineering=eng,
    )
    if not lock_credible:
        return TimeMap(n0=None, t0_utc_ns=None, origin=None, u_epoch_ns=None, k=1, p=None,
                       reason="lock_not_credible: the edge did not pass the credibility guards",
                       **common)
    if sigma_ns is None:
        return TimeMap(n0=None, t0_utc_ns=None, origin=None, u_epoch_ns=None, k=1, p=None,
                       reason="no uncertainty published for the anchor", **common)
    return TimeMap(n0=int(anchor_rtp) & 0xFFFFFFFF, t0_utc_ns=int(anchor_utc_ns),
                   origin="native_anchor", u_epoch_ns=int(sigma_ns), k=2, p=0.95,
                   reason=None, **common)


def null_map(
    *, counter_space: str, counter_epoch_id: str, f_s_hz: int, measured_at_utc_ns: int,
    reason: str, a_level: str = "A0", a_level_provenance: str = "assumed",
    engineering: Optional[Mapping[str, Any]] = None,
) -> TimeMap:
    """Absence, stated as absence (MEASUREMENT_MODEL §9 invariant 3)."""
    return TimeMap(
        counter_space=counter_space, counter_epoch_id=counter_epoch_id,
        n0=None, t0_utc_ns=None, f_s_hz=int(f_s_hz), chain="none", origin=None,
        u_epoch_ns=None, k=1, p=None, measured_at_utc_ns=int(measured_at_utc_ns),
        a_level=a_level, a_level_provenance=a_level_provenance,
        reason=reason, engineering=dict(engineering or {}),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/mjh/hamsci/repos/hamsci-dsp && .venv/bin/python -m pytest tests/test_timing_map.py -p no:cacheprovider -q`
Expected: `22 passed`

- [ ] **Step 5: Commit**

```bash
cd /home/mjh/hamsci/repos/hamsci-dsp
git add src/hamsci_dsp/timing_map.py tests/test_timing_map.py
git commit -m "timing_map: the two builders -- every rung fills the shape, the host clock bounds the sysclock registration, a bad lock registers nothing

TIMING_PROVENANCE_MODEL §3.1 / §3.1.1; MEASUREMENT_MODEL §6.4, §8, §9.
Replays: the record AC0G-B4 should have written at 15:00Z on 2026-09-04
reads u_epoch_ns 12.1 s, k 1, reason host_clock: fault (lb1421).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 4: `AuthoritySnapshot.host_clock` — the v1 reader carries the additive key

**Files:**
- Modify: `src/hamsci_dsp/timing.py:40-55` (dataclass) and `:137-162` (`read()`), `:70-94` (`to_timing_authority`)
- Test: `tests/test_timing.py` (append)

**Interfaces:**
- Produces: `AuthoritySnapshot.host_clock: Optional[dict] = None` (last field, keyword default so positional construction elsewhere still works); `to_timing_authority()` gains `"host_clock_verdict": <str|None>`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_timing.py
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/mjh/hamsci/repos/hamsci-dsp && .venv/bin/python -m pytest tests/test_timing.py -p no:cacheprovider -q -k host_clock`
Expected: `AttributeError: 'AuthoritySnapshot' object has no attribute 'host_clock'`

- [ ] **Step 3: Implement**

In `src/hamsci_dsp/timing.py`, add the field after `governor_radiod`:

```python
    governor_radiod: Optional[str] = None
    #: hf-timestd's host-clock verdict (additive v1 key, 2026-09-04):
    #: {"verdict": ok|suspect|fault|unwitnessed, "reason", "witnesses", "since_utc"}.
    #: None on producers older than that.  A sysclock-origin TimeMap bounds
    #: its u_epoch_ns by it (hamsci_dsp.timing_map.sysclock_map).
    host_clock: Optional[dict] = None
```

In `to_timing_authority()`, add after `"governor_radiod": self.governor_radiod,`:

```python
            "host_clock_verdict": (
                self.host_clock.get("verdict") if isinstance(self.host_clock, dict) else None
            ),
```

In `read()`, inside the `AuthoritySnapshot(...)` construction, add after the `governor_radiod=(...)` argument:

```python
                host_clock=(
                    dict(data["host_clock"])
                    if isinstance(data.get("host_clock"), dict) else None
                ),
```

In `standalone_timing_authority()` and the `fallback` dict of `sysclock_timing_authority()`, add `"host_clock_verdict": None,` after `"governor_radiod": None,` so the key set stays uniform.

- [ ] **Step 4: Run the whole timing test file**

Run: `cd /home/mjh/hamsci/repos/hamsci-dsp && .venv/bin/python -m pytest tests/test_timing.py -p no:cacheprovider -q`
Expected: all pass (existing tests assert key sets; if one asserts an exact dict of `to_timing_authority()`, add `"host_clock_verdict": None` to its expected dict — the key is part of the uniform block now).

- [ ] **Step 5: Commit**

```bash
cd /home/mjh/hamsci/repos/hamsci-dsp
git add src/hamsci_dsp/timing.py tests/test_timing.py
git commit -m "timing: AuthoritySnapshot carries hf-timestd's host_clock verdict (additive v1 key)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 5: Authority history store — four host-clock columns

**Files:**
- Modify: `src/hamsci_dsp/io/authority_snapshot_store.py` (`COLUMNS` tuple end, `_REAL_COLUMNS`)
- Test: `tests/test_authority_snapshot_store.py` (append)

**Interfaces:**
- Produces columns: `host_clock_verdict` TEXT, `host_clock_since_utc` TEXT, `host_clock_t2_ms` REAL, `host_clock_lb1421_s` REAL. The producer (hf-timestd Plan B Task 1) writes exactly these keys.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_authority_snapshot_store.py
def test_host_clock_columns_round_trip(tmp_path):
    from hamsci_dsp.io.authority_snapshot_store import AuthoritySnapshotStore, COLUMNS
    for c in ("host_clock_verdict", "host_clock_since_utc", "host_clock_t2_ms", "host_clock_lb1421_s"):
        assert c in COLUMNS, c
    db = tmp_path / "authority_history.db"
    with AuthoritySnapshotStore(db) as store:
        store.insert({"utc_published": "2026-09-04T15:06:50.012628Z", "schema_version": "v1",
                      "host_clock_verdict": "fault", "host_clock_since_utc": "2026-09-04T02:47:12Z",
                      "host_clock_t2_ms": 11679.507, "host_clock_lb1421_s": -12.1})
    row = sqlite3.connect(db).execute(
        "SELECT host_clock_verdict, host_clock_since_utc, host_clock_t2_ms, host_clock_lb1421_s "
        "FROM authority_snapshot").fetchone()
    assert row == ("fault", "2026-09-04T02:47:12Z", 11679.507, -12.1)


def test_existing_db_gains_the_host_clock_columns_on_reopen(tmp_path):
    """A station's history DB predates the column; reopening migrates it."""
    from hamsci_dsp.io.authority_snapshot_store import AuthoritySnapshotStore
    db = tmp_path / "authority_history.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE authority_snapshot (utc_published TEXT NOT NULL PRIMARY KEY, schema_version INTEGER)")
    conn.commit(); conn.close()
    with AuthoritySnapshotStore(db) as store:
        store.insert({"utc_published": "2026-09-04T17:45:57Z", "host_clock_verdict": "suspect"})
    row = sqlite3.connect(db).execute(
        "SELECT host_clock_verdict FROM authority_snapshot").fetchone()
    assert row == ("suspect",)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /home/mjh/hamsci/repos/hamsci-dsp && .venv/bin/python -m pytest tests/test_authority_snapshot_store.py -p no:cacheprovider -q -k host_clock`
Expected: `AssertionError` on `"host_clock_verdict" in COLUMNS`

- [ ] **Step 3: Implement**

At the end of the `COLUMNS` tuple (after `"t6_fine_coarse_unverified",`), add:

```python
    # The host-clock verdict (hf-timestd host_clock_integrity, 2026-09-04):
    # the verdict, when the episode began, and the two epoch witnesses.
    # NULL on producers older than that.  On 2026-09-04 AC0G-B4 ran 11.6 s
    # slow for thirteen hours with nothing in this table saying so.
    "host_clock_verdict",
    "host_clock_since_utc",
    "host_clock_t2_ms",
    "host_clock_lb1421_s",
```

Add `"host_clock_t2_ms", "host_clock_lb1421_s",` to `_REAL_COLUMNS`. The existing `_migrate_missing_columns` adds them to an older DB.

- [ ] **Step 4: Run the store tests**

Run: `cd /home/mjh/hamsci/repos/hamsci-dsp && .venv/bin/python -m pytest tests/test_authority_snapshot_store.py -p no:cacheprovider -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
cd /home/mjh/hamsci/repos/hamsci-dsp
git add src/hamsci_dsp/io/authority_snapshot_store.py tests/test_authority_snapshot_store.py
git commit -m "authority_snapshot_store: four host_clock columns, migrated on reopen

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 6: Golden records and the one-page schema doc

**Files:**
- Create: `tests/golden/timing_state_b4_20260904T1610Z.json`, `tests/golden/timing_chain_payload_anchored_v1.json`
- Create: `docs/TIMING_MAP.md`
- Test: `tests/test_timing_map.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_timing_map.py
import json
from pathlib import Path

GOLDEN = Path(__file__).parent / "golden"


def test_golden_state_record_round_trips_byte_for_byte():
    rec = json.loads((GOLDEN / "timing_state_b4_20260904T1610Z.json").read_text())
    m = TimeMap.from_state_record(rec)
    again = m.to_state_record(_parse_t(rec["t"]))
    assert again == rec


def test_golden_chain_record_round_trips_byte_for_byte():
    rec = json.loads((GOLDEN / "timing_chain_payload_anchored_v1.json").read_text())
    assert Chain.from_record(rec).to_record() == rec


def _parse_t(s):
    from hamsci_dsp.timing_map import _parse_iso_z_ns
    return _parse_iso_z_ns(s)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /home/mjh/hamsci/repos/hamsci-dsp && .venv/bin/python -m pytest tests/test_timing_map.py -p no:cacheprovider -q -k golden`
Expected: `FileNotFoundError` for the golden file

- [ ] **Step 3: Write the golden files**

`tests/golden/timing_state_b4_20260904T1610Z.json` — generate it once from the builder so it is self-consistent, then commit the bytes:

```bash
cd /home/mjh/hamsci/repos/hamsci-dsp && mkdir -p tests/golden && .venv/bin/python - <<'EOF'
import json
from hamsci_dsp.timing_map import native_anchor_map, Chain, BudgetTerm
T0 = 1_788_537_251_999_997_458
m = native_anchor_map(counter_space="AC0G-B4-status.local/T6_96000",
                      counter_epoch_id="r-2026-09-04T16:03:35Z",
                      anchor_rtp=2_150_319_213, anchor_utc_ns=T0, sample_rate_hz=96_000,
                      measured_at_utc_ns=T0, sigma_ns=4_093, lock_credible=True,
                      a_level="A1", a_level_provenance="observed",
                      host_clock={"verdict": "ok", "reason": "every witness agrees with the host clock",
                                  "witnesses": {"T2": {"kind": "pair_ms", "value": 11.2, "bound": 60.0, "exceeded": False},
                                                "lb1421": {"kind": "gps_second_s", "value": 0.823, "bound": 1.0, "exceeded": False}},
                                  "since_utc": None},
                      stability_ns=120, tau_s=60.0,
                      engineering={"judge_tier": "T6", "how": "seeded", "cross_checked": True,
                                   "radiod_gps_time_ns": 1_788_537_251_988_000_000,
                                   "radiod_rtp_timesnap": 2_150_318_060, "cn0_db_hz": 55.1, "rf_gain_db": 7.5})
open("tests/golden/timing_state_b4_20260904T1610Z.json", "w").write(
    json.dumps(m.to_state_record(T0 + 348_000_002_542), indent=1, sort_keys=True) + "\n")
c = Chain(id="payload-anchored@1",
          measurand="UTC instant at which sample n was taken, at the antenna terminals",
          measurand_plane="antenna_terminals", calibration_plane="ts1_injection_point",
          traceability={"claim": "UTC(USNO) via GPS", "qualified": True,
                        "qualification": "antenna-to-injector path not declared; receiver front end not characterised"},
          budget=(BudgetTerm("ts1_modulator_delay", type="B", correction_ns=0, u_ns=200,
                             method="designer statement, P. Elliott WB6CXC, 2026-08-30; standard injector mode"),
                  BudgetTerm("antenna_to_injector", type="B", disposition="not_declared",
                             spans=("antenna_terminals", "ts1_injection_point"),
                             method="feed, preamp and filter ahead of the injection point; station-specific"),
                  BudgetTerm("injector_to_receiver", disposition="cancels",
                             spans=("ts1_injection_point", "rx888_adc"),
                             method="identical path for signal and injected reference; cancels by construction"),
                  BudgetTerm("gnss_antenna_feed", type="B", disposition="not_declared",
                             method="cable length x velocity factor; a sign-known bias, not an uncertainty"),
                  BudgetTerm("anchor_origin_dispersion", type="A", correction_ns=0, u_ns=1900,
                             measured_on={"build": "pre-folding", "date": "2026-08-24"}, disposition="historical",
                             method="63 anchors over 4.5 h ACROSS RE-LOCKS; the folded build of 2026-08-29 removed the re-locks"),
                  BudgetTerm("edge_estimation", type="B", correction_ns=0, u_ns=5000,
                             method="conservative bound; becomes Type A computed from cn0_db_hz once the fine-stage sweep has run"),
                  BudgetTerm("filter_group_delay", type="B", disposition="excluded_by_convention",
                             method="labeling_convention = content: the channel filter's group delay is pipeline latency outside the measurand")),
          k=2)
open("tests/golden/timing_chain_payload_anchored_v1.json", "w").write(
    json.dumps(c.to_record(), indent=1, sort_keys=True) + "\n")
print("golden written")
EOF
```

Then write `docs/TIMING_MAP.md`: one page with (a) the measurand formula and the three fields a consumer needs (`n0`, `t0_utc_ns`, `f_s_hz`), (b) the composition law and `measured_at`, (c) the `origin` values and what `reason` means, (d) the rule "read `u_epoch_ns` and `stability_ns`, never `judge_tier`", (e) the `counter_epoch_id` rule, (f) the two golden records inline. Cite `TIMING_PROVENANCE_MODEL.md` §3.1/§3.1.1 and `MEASUREMENT_MODEL.md` §8 for the reasoning rather than repeating it.

- [ ] **Step 4: Run the whole suite**

Run: `cd /home/mjh/hamsci/repos/hamsci-dsp && .venv/bin/python -m pytest tests -p no:cacheprovider -q`
Expected: all pass, including the two golden tests

- [ ] **Step 5: Commit and push**

```bash
cd /home/mjh/hamsci/repos/hamsci-dsp
git add tests/golden docs/TIMING_MAP.md tests/test_timing_map.py
git commit -m "timing_map: golden state and chain records; TIMING_MAP.md for consumers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
git push origin main
```

---

## Self-review

**Spec coverage.** §3.1 fields → Task 2 (`to_state_record` keys) and Task 3 (builders fill `lock_credible`, `host_clock`); §3.1.1 sysclock registration → Task 3 (`sysclock_map`, both governing cases, k/p as the spec states); §3.2 terms, dispositions, `measured_on`, RSS, per-interval → Task 1; §3.3 composition law → Task 2 (`u_epoch_ns_at`); §3.4 tier under engineering → Task 2 test asserts `judge_tier` not top-level; §6 deliverable 1 → the whole plan; §7 absence → `null_map` and the not-credible / no-sigma paths; MEASUREMENT_MODEL §8 `TimeMap` fields → Task 2 (all named fields present); §9 invariant 3 → `reason` on every null map. Not in this plan, by design: producing the map (Plan B, hf-timestd) and reading it (Plan C, hamsci-physics).

**Placeholders.** None. Every step carries code or an exact command.

**Type consistency.** `host_clock` is a `Mapping` in the builders and a `dict` on `AuthoritySnapshot`; `TimeMap.engineering` is a `Mapping` normalised to `dict`; `Chain.budget` is a `tuple`; `u_epoch_ns`, `n0`, `t0_utc_ns` are `Optional[int]` throughout; column names in Task 5 match the keys Plan B writes.
