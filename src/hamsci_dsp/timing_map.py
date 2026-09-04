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


from datetime import datetime, timezone  # noqa: E402

#: u(f_s)/f_s stand-ins by ruler state, ppm (MEASUREMENT_MODEL §2).  The
#: disciplined figure is 25x the value measured on AC0G-B4 (0.0004 ppm);
#: the undisciplined one is what a free-running TCXO does.
RULER_PPM_STANDIN = {"A1": 0.01, "A0": 2.0}


def _iso_z(utc_ns: int) -> str:
    """ISO-8601 UTC with nine fractional digits.  The record's other times
    are integer nanoseconds; a microsecond string could not reproduce
    `measured_at` on the way back, and a state record must round-trip."""
    secs, frac = divmod(int(utc_ns), _BILLION)
    dt = datetime.fromtimestamp(secs, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{frac:09d}Z"


def _parse_iso_z_ns(s: str) -> int:
    """Inverse of _iso_z; also reads the shorter forms other writers use
    (no fraction, 3 or 6 digits, `+00:00` instead of `Z`)."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1]
    elif s.endswith("+00:00"):
        s = s[:-6]
    frac_ns = 0
    if "." in s:
        s, frac = s.split(".", 1)
        frac_ns = int((frac + "000000000")[:9])
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp()) * _BILLION + frac_ns


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
