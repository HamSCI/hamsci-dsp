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
