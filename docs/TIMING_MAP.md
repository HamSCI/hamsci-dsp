# TimeMap — schema v2, for consumers

One page. The reasoning lives in `hf-timestd/docs/design/TIMING_PROVENANCE_MODEL.md`
§3.1, §3.1.1, §3.2 and `hf-timestd/docs/design/MEASUREMENT_MODEL.md` §1, §4, §8, §9.
The code is `hamsci_dsp.timing_map`.

## The measurand, and the three fields you need

Every product labels sample `n` with the UTC instant at which the station's
reference plane saw it:

    t(n) = t0_utc_ns + (n − n0) · 10⁹ / f_s_hz        (n − n0 as a signed 32-bit difference)

Read `n0`, `t0_utc_ns`, `f_s_hz` from the `state` record and call
`TimeMap.utc_ns_at(n)`. Corrections are already folded into `t0_utc_ns`; do
not add a group delay, a cable, or a tier offset of your own. The counter is
radiod's RTP timestamp; `counter_space` names whose counter and
`counter_epoch_id` changes whenever that counter restarts. A registration
from one epoch id never labels samples from another.

## The uncertainty, and how it ages

`u_epoch_ns` is the standard uncertainty of `t0` as of `measured_at`, with
its coverage factor `k` and probability `p` beside it. Never a bare sigma.
It ages by the composition law (MEASUREMENT_MODEL §4):

    u(t) = sqrt( u_epoch_ns² + ((t − measured_at) · u(f_s)/f_s)² )

`TimeMap.u_epoch_ns_at(t_utc_ns)` evaluates it; `u(f_s)/f_s` comes from
`a_level` (A1 disciplined 0.01 ppm, A0 undisciplined 2.0 ppm, stand-ins in
`RULER_PPM_STANDIN`). `stability_ns` at `tau_s` describes the ruler's
short-term behaviour and is what a consumer that differences two labels
should read.

## Read `u_epoch_ns` and `stability_ns`, never `judge_tier`

The tier (T6, T3, …) is engineering shorthand for how the registration was
obtained. It appears only under `engineering`. A consumer that branches on
it re-derives the model; branch on the uncertainty instead.

## `origin`, and what `reason` means

| `origin` | meaning | `chain` |
|---|---|---|
| `native_anchor` | a payload-anchored registration from the TS-1 edge | `payload-anchored@1` |
| `sysclock` | radiod's advertised pair, bounded by the host-clock verdict | `sysclock@1` |
| `null` | no registration; `n0`, `t0_utc_ns`, `u_epoch_ns` are null | `none` |

`reason` says why the record is what it is: which term governs the
uncertainty on a sysclock record, why a native-anchor record registered
nothing (`lock_not_credible`, no uncertainty published), or why a null
record is null. Absence is stated as absence; silence never means zero.

## `chain` records

A `chain` record names the measurand's plane, the calibration plane, the
traceability claim with its qualification, and the budget: one term per
effect with its GUM type, correction, uncertainty and method, or a
disposition (`declared`, `not_declared`, `cancels`, `historical`,
`per_interval`, `excluded_by_convention`). `u_combined_ns` is the RSS of
the terms that carry a `u_ns`, and null when a term lives per interval.

## Golden records

`tests/golden/timing_state_b4_20260904T1600Z.json` — the state record
AC0G-B4's T6 registration of 15:54:11.999997458Z would carry at 16:00:00Z:

```json
{
 "a_level": "A1",
 "a_level_provenance": "observed",
 "calibration_plane": "ts1_injection_point",
 "chain": "payload-anchored@1",
 "counter_epoch_id": "r-2026-09-04T15:53:35Z",
 "counter_space": "AC0G-B4-status.local/T6_96000",
 "engineering": {
  "cn0_db_hz": 55.1,
  "cross_checked": true,
  "host_clock": {
   "reason": "every witness agrees with the host clock",
   "since_utc": null,
   "verdict": "ok",
   "witnesses": {
    "T2": {
     "bound": 60.0,
     "exceeded": false,
     "kind": "pair_ms",
     "value": 11.2
    },
    "lb1421": {
     "bound": 1.0,
     "exceeded": false,
     "kind": "gps_second_s",
     "value": 0.823
    }
   }
  },
  "how": "seeded",
  "judge_tier": "T6",
  "lock_credible": true,
  "radiod_gps_time_ns": 1788537251988000000,
  "radiod_rtp_timesnap": 2150318060,
  "rf_gain_db": 7.5
 },
 "f_s_hz": 96000,
 "k": 2,
 "measurand_plane": "antenna_terminals",
 "measured_at": "2026-09-04T15:54:11.999997458Z",
 "n0": 2150319213,
 "origin": "native_anchor",
 "p": 0.95,
 "reason": null,
 "schema": "v2",
 "stability_ns": 120,
 "t": "2026-09-04T16:00:00.000000000Z",
 "t0_utc_ns": 1788537251999997458,
 "tau_s": 60.0,
 "type": "state",
 "u_epoch_ns": 4093
}
```

`tests/golden/timing_chain_payload_anchored_v1.json`:

```json
{
 "budget": [
  {
   "correction_ns": 0,
   "method": "designer statement, P. Elliott WB6CXC, 2026-08-30; standard injector mode",
   "term": "ts1_modulator_delay",
   "type": "B",
   "u_ns": 200
  },
  {
   "disposition": "not_declared",
   "method": "feed, preamp and filter ahead of the injection point; station-specific",
   "spans": [
    "antenna_terminals",
    "ts1_injection_point"
   ],
   "term": "antenna_to_injector",
   "type": "B"
  },
  {
   "disposition": "cancels",
   "method": "identical path for signal and injected reference; cancels by construction",
   "spans": [
    "ts1_injection_point",
    "rx888_adc"
   ],
   "term": "injector_to_receiver"
  },
  {
   "disposition": "not_declared",
   "method": "cable length x velocity factor; a sign-known bias, not an uncertainty",
   "term": "gnss_antenna_feed",
   "type": "B"
  },
  {
   "correction_ns": 0,
   "disposition": "historical",
   "measured_on": {
    "build": "pre-folding",
    "date": "2026-08-24"
   },
   "method": "63 anchors over 4.5 h ACROSS RE-LOCKS; the folded build of 2026-08-29 removed the re-locks",
   "term": "anchor_origin_dispersion",
   "type": "A",
   "u_ns": 1900
  },
  {
   "correction_ns": 0,
   "method": "conservative bound; becomes Type A computed from cn0_db_hz once the fine-stage sweep has run",
   "term": "edge_estimation",
   "type": "B",
   "u_ns": 5000
  },
  {
   "disposition": "excluded_by_convention",
   "method": "labeling_convention = content: the channel filter's group delay is pipeline latency outside the measurand",
   "term": "filter_group_delay",
   "type": "B"
  }
 ],
 "calibration_plane": "ts1_injection_point",
 "id": "payload-anchored@1",
 "k": 2,
 "measurand": "UTC instant at which sample n was taken, at the antenna terminals",
 "measurand_plane": "antenna_terminals",
 "schema": "v2",
 "traceability": {
  "claim": "UTC(USNO) via GPS",
  "qualification": "antenna-to-injector path not declared; receiver front end not characterised",
  "qualified": true
 },
 "type": "chain",
 "u_combined_ns": 5353
}
```

Both round-trip byte for byte through `TimeMap.from_state_record` /
`to_state_record` and `Chain.from_record` / `to_record`
(`tests/test_timing_map.py`). Times render as ISO-8601 UTC with nine
fractional digits so a record reproduces its nanosecond fields on the way
back; the parser also reads the shorter forms other writers use.
