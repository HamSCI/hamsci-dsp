"""CounterMap: one channel's RTP counter mapped to radiod's input-sample index.

Since ka9q-radio e5f790dd every radiod channel starts its own RTP counter, so
two channels' RTP values never compare directly.  Each channel does report a
pair in its own status stream: INPUT_SAMPLES (radio_status.c:670, the value
`chan->filter.out.sample_index`) and RTP_TIMESNAP (radio_status.c:819, the
channel's RTP timestamp).  This module learns, from several such pairs, the
map from that channel's RTP to the absolute input-sample index, a coordinate
that every channel of one radiod run shares.

Assumption: the RTP-to-INPUT_SAMPLES offset convention holds equally for every
linear channel.  Task 3's live run tests that assumption.

Pure logic.  No clock reads, no I/O.  `input_epoch_gps_s` only names the radiod
run (gps_s - input_samples / f_in); it never carries timing.

RTP is a 32-bit counter, so `input_index` and `rolled_forward` reach only
half the range (2**31 samples, 24 h 51 m at 24 kHz) from `rtp_ref`.  A map held
longer must roll forward before it falls out of that reach.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Optional, Sequence

_MOD = 2**32


def _s32(x: int) -> int:
    """Signed 32-bit difference."""
    x &= 0xFFFFFFFF
    return x - _MOD if x >= 2**31 else x


@dataclass(frozen=True)
class CounterPoll:
    """One (INPUT_SAMPLES, RTP_TIMESNAP) status pair with its context."""
    rtp_timesnap: int
    input_samples: int
    filter_blocksize: int
    input_samprate: int
    output_samprate: int
    gps_time_ns: int


@dataclass(frozen=True)
class CounterMap:
    rtp_ref: int              # block-aligned RTP in this channel's counter
    input_ref: int            # radiod input-sample index at rtp_ref
    ilen: int                 # FILTER_BLOCKSIZE: input samples per block
    olen: int                 # output samples per block
    input_samprate: int
    input_epoch_gps_s: float  # least-late gps_s - input_samples/f_in; names the run
    n_agree: int

    @classmethod
    def from_polls(cls, polls: Sequence[CounterPoll],
                   min_agree: int = 3) -> Optional["CounterMap"]:
        if not polls:
            return None
        first = polls[0]
        ilen, f_in, f_out = first.filter_blocksize, first.input_samprate, first.output_samprate
        if ilen <= 0 or f_in <= 0 or f_out <= 0:
            return None
        num = f_out * ilen
        if num % f_in:
            return None
        olen = num // f_in
        if olen == 0:
            return None
        rtp0 = first.rtp_timesnap & 0xFFFFFFFF
        intercepts = []
        for p in polls:
            if (p.filter_blocksize, p.input_samprate, p.output_samprate) != (ilen, f_in, f_out):
                return None
            d = _s32(p.rtp_timesnap - rtp0)
            if d % olen:
                return None
            intercepts.append(p.input_samples - (d // olen) * ilen)
        value, count = Counter(intercepts).most_common(1)[0]
        if count < min_agree:
            return None
        epoch = min(p.gps_time_ns / 1e9 - p.input_samples / f_in
                    for p, i in zip(polls, intercepts) if i == value)
        return cls(rtp_ref=rtp0, input_ref=value, ilen=ilen, olen=olen,
                   input_samprate=f_in, input_epoch_gps_s=epoch, n_agree=count)

    def input_index(self, rtp: int) -> float:
        return self.input_ref + _s32((rtp & 0xFFFFFFFF) - self.rtp_ref) * self.ilen / self.olen

    def rolled_forward(self, rtp_now: int) -> "CounterMap":
        blocks = round(_s32((rtp_now & 0xFFFFFFFF) - self.rtp_ref) / self.olen)
        return CounterMap(
            rtp_ref=(self.rtp_ref + blocks * self.olen) % _MOD,
            input_ref=self.input_ref + blocks * self.ilen,
            ilen=self.ilen, olen=self.olen, input_samprate=self.input_samprate,
            input_epoch_gps_s=self.input_epoch_gps_s, n_agree=self.n_agree)

    def same_run(self, other: "CounterMap", tol_s: float = 0.5) -> bool:
        return ((self.ilen, self.olen, self.input_samprate)
                == (other.ilen, other.olen, other.input_samprate)
                and abs(self.input_epoch_gps_s - other.input_epoch_gps_s) <= tol_s)

    def intercept_blocks_from(self, other: "CounterMap") -> Optional[int]:
        """Whole blocks by which this map's index at its rtp_ref exceeds
        `other`'s; None for another run or a non-whole difference."""
        if not self.same_run(other):
            return None
        blocks = (self.input_index(self.rtp_ref) - other.input_index(self.rtp_ref)) / self.ilen
        whole = round(blocks)
        return whole if abs(blocks - whole) < 1e-6 else None

    def to_dict(self) -> dict:
        return {"rtp_ref": self.rtp_ref, "input_ref": self.input_ref,
                "ilen": self.ilen, "olen": self.olen,
                "input_samprate": self.input_samprate,
                "input_epoch_gps_s": self.input_epoch_gps_s,
                "n_agree": self.n_agree}

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> Optional["CounterMap"]:
        if not d:
            return None
        try:
            return cls(rtp_ref=int(d["rtp_ref"]), input_ref=int(d["input_ref"]),
                       ilen=int(d["ilen"]), olen=int(d["olen"]),
                       input_samprate=int(d["input_samprate"]),
                       input_epoch_gps_s=float(d["input_epoch_gps_s"]),
                       n_agree=int(d["n_agree"]))
        except (KeyError, TypeError, ValueError):
            return None
