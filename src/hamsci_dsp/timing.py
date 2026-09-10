"""AuthorityReader — reads /run/hf-timestd/authority.json published by
hf-timestd's authority manager. Consumer side of the schema v1 contract
documented in hf-timestd/docs/METROLOGY.md §4.5.2.

This is the **canonical shared home** for the reader.  It was extracted
verbatim from the byte-identical copies that hf-tec, codar-sounder,
psk-recorder, and wspr-recorder each carried; new clients (superdarn-sounder)
import it from here.  The existing clients are rewired onto this module as a
follow-up (their local copies remain wire-compatible in the meantime — the
JSON schema is unchanged).

Under the RTP-reference labeling invariant, a client labels each frame's start
time from the RTP sample counter (rtp_to_wallclock) plus this published offset.

Standalone fallback. sigmond clients must work without hf-timestd. In that case
``read()`` returns None and callers fall back to the system clock (ONCE, at
stream start) with a clear warning. The operator is responsible for ensuring
radiod's host has timing accurate enough that the frame label lands on a useful
UTC bin.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional

logger = logging.getLogger(__name__)

_SUPPORTED_SCHEMAS = {"v1"}

DEFAULT_PATH = Path("/run/hf-timestd/authority.json")
DEFAULT_FRESHNESS_SEC = 60.0


@dataclass
class AuthoritySnapshot:
    """One reading of authority.json. All fields map 1:1 to the published
    schema; see hf-timestd/docs/METROLOGY.md §4.5.2."""
    utc_published: datetime
    a_level: str
    t_level_active: Optional[str]
    t_level_available: List[str]
    t_level_witnesses: List[str]
    rtp_to_utc_offset_ns: Optional[int]
    sigma_ns: Optional[int]
    stations_contributing: List[str]
    last_transition_utc: Optional[str]
    disagreement_flags: List[str]
    governor_radiod: Optional[str] = None
    #: hf-timestd's host-clock verdict (additive v1 key, 2026-09-04):
    #: {"verdict": ok|suspect|fault|unwitnessed, "reason", "witnesses", "since_utc"}.
    #: None on producers older than that.  A sysclock-origin TimeMap bounds
    #: its u_epoch_ns by it (hamsci_dsp.timing_map.sysclock_map).
    host_clock: Optional[dict] = None

    @property
    def offset_usable(self) -> bool:
        """True iff the snapshot carries a concrete offset we can apply."""
        return (
            self.t_level_active is not None
            and self.rtp_to_utc_offset_ns is not None
        )

    @property
    def offset_seconds(self) -> float:
        """rtp_to_utc_offset_ns expressed as a float in seconds. Undefined
        when `offset_usable` is False."""
        return (self.rtp_to_utc_offset_ns or 0) / 1_000_000_000.0

    def to_timing_authority(
        self, client_radiod: Optional[str] = None,
    ) -> dict:
        """Canonical timing-provenance block for data records.

        Identical across all sigmond clients (wspr/psk/codar/hf-tec/
        superdarn): the single authoritative record of how a sample's UTC
        label was derived, sourced entirely from hf-timestd's adjudicated
        authority.json — never from a secondary status feed. See
        CLIENT-CONTRACT §18 / METROLOGY §4.5. Use
        standalone_timing_authority() when no snapshot is available
        (hf-timestd absent / stale)."""
        return {
            "source": "hf-timestd-authority",
            "schema": "v1",
            "a_level": self.a_level,
            "t_level_active": self.t_level_active,
            "t_level_witnesses": list(self.t_level_witnesses),
            "rtp_to_utc_offset_ns": self.rtp_to_utc_offset_ns,
            "sigma_ns": self.sigma_ns,
            "disagreement_flags": list(self.disagreement_flags),
            "governor_radiod": self.governor_radiod,
            "host_clock_verdict": (
                self.host_clock.get("verdict") if isinstance(self.host_clock, dict) else None
            ),
            "client_radiod": client_radiod,
            "authority_utc_published": self.utc_published.isoformat(),
        }


class AuthorityReader:
    """Atomic reader for /run/hf-timestd/authority.json.

    All error paths return None rather than raising, so callers can
    treat "file missing" identically to "hf-timestd not running."
    """

    def __init__(
        self,
        path: Path = DEFAULT_PATH,
        freshness_sec: float = DEFAULT_FRESHNESS_SEC,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.path = Path(path)
        self.freshness_sec = float(freshness_sec)
        self.now_fn = now_fn

    def read(self) -> Optional[AuthoritySnapshot]:
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("authority.json read error: %s", e)
            return None

        if data.get("schema") not in _SUPPORTED_SCHEMAS:
            logger.debug("authority.json unsupported schema: %r", data.get("schema"))
            return None

        try:
            pub = _parse_iso_z(str(data["utc_published"]))
        except (KeyError, TypeError, ValueError) as e:
            logger.debug("authority.json utc_published parse: %s", e)
            return None

        if (self.now_fn() - pub).total_seconds() > self.freshness_sec:
            return None

        try:
            return AuthoritySnapshot(
                utc_published=pub,
                a_level=str(data.get("a_level", "A1")),
                t_level_active=data.get("t_level_active"),
                t_level_available=list(data.get("t_level_available") or []),
                t_level_witnesses=list(data.get("t_level_witnesses") or []),
                rtp_to_utc_offset_ns=(
                    int(data["rtp_to_utc_offset_ns"])
                    if data.get("rtp_to_utc_offset_ns") is not None
                    else None
                ),
                sigma_ns=(
                    int(data["sigma_ns"])
                    if data.get("sigma_ns") is not None
                    else None
                ),
                stations_contributing=list(data.get("stations_contributing") or []),
                last_transition_utc=data.get("last_transition_utc"),
                disagreement_flags=list(data.get("disagreement_flags") or []),
                governor_radiod=(
                    str(data["governor_radiod"])
                    if data.get("governor_radiod")
                    else None
                ),
                host_clock=(
                    dict(data["host_clock"])
                    if isinstance(data.get("host_clock"), dict) else None
                ),
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.debug("authority.json field error: %s", e)
            return None


def standalone_timing_authority(
    client_radiod: Optional[str] = None,
) -> dict:
    """Canonical timing-provenance block when authority.json is
    unavailable (hf-timestd absent or stale) — the standalone fallback.
    Shape matches AuthoritySnapshot.to_timing_authority so the record key
    is uniform across both states and across all clients."""
    return {
        "source": "standalone-fallback",
        "schema": "v1",
        "a_level": None,
        "t_level_active": None,
        "t_level_witnesses": [],
        "rtp_to_utc_offset_ns": None,
        "sigma_ns": None,
        "disagreement_flags": [],
        "governor_radiod": None,
        "host_clock_verdict": None,
        "client_radiod": client_radiod,
        "authority_utc_published": None,
    }


def sysclock_timing_authority(
    tracking_csv: Optional[str] = None,
    run_chronyc: Optional[Callable[[], str]] = None,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    """Timing-provenance block for HOST-CLOCK instruments (sysclock frame).

    For clients whose instrument is not radiod-sampled (e.g. mag-recorder's
    RM3100 on USB-I2C) the RTP labelling invariant does not apply: samples
    are stamped from the system clock, and this block records what that
    clock was disciplined by at stamp time, so host-clock products carry
    the same annotated-timing provenance as RTP-frame records.

    The key set is a superset of AuthoritySnapshot.to_timing_authority():
    the shared keys stay so consumers can treat the block uniformly; the
    RTP-frame keys are present-but-null, and sysclock extras are added
    (timing_source, stratum, leap_status, system_time_offset_ns,
    rms_offset_ns).

    Sourced from ``chronyc -c tracking`` (14-field CSV). ``sigma_ns`` is
    chrony's worst-case error bound |offset| + root_dispersion +
    root_delay/2 — a hard bound, not a 1-sigma. ``t_level_active`` is
    "T4" whenever chrony reports itself synchronised (METROLOGY §4.5's
    sysclock tier: "system clock chronyed"); adjudicating anything finer
    is hf-timestd's job, not this helper's.

    tracking_csv   inject the CSV line directly (tests); otherwise
    run_chronyc    zero-arg callable returning the CSV (defaults to
                   invoking ``chronyc -c tracking``, 2 s timeout).
    All failure paths return the "sysclock-fallback" block — never raises.
    """
    fallback = {
        **standalone_timing_authority(),
        "source": "sysclock-fallback",
        "timing_source": None,
        "stratum": None,
        "leap_status": None,
        "system_time_offset_ns": None,
        "rms_offset_ns": None,
    }
    if tracking_csv is None:
        try:
            if run_chronyc is not None:
                tracking_csv = run_chronyc()
            else:
                import subprocess
                tracking_csv = subprocess.run(
                    ["chronyc", "-c", "tracking"],
                    capture_output=True, text=True, timeout=2.0, check=True,
                ).stdout
        except Exception as e:  # noqa: BLE001 - any failure means "no chrony"
            logger.debug("chronyc unavailable: %s", e)
            return fallback

    try:
        fields = tracking_csv.strip().splitlines()[0].split(",")
        # chronyc -c tracking: refid, refname, stratum, reftime, sysoffset,
        # lastoffset, rmsoffset, freq, residfreq, skew, rootdelay, rootdisp,
        # updateinterval, leap
        if len(fields) < 14:
            raise ValueError(f"expected 14 fields, got {len(fields)}")
        refname = fields[1]
        stratum = int(fields[2])
        sys_offset = float(fields[4])
        rms_offset = float(fields[6])
        root_delay = float(fields[10])
        root_disp = float(fields[11])
        leap = fields[13]
    except (ValueError, IndexError) as e:
        logger.debug("unparseable chronyc tracking output: %s", e)
        return fallback

    synchronised = leap == "Normal"
    return {
        **standalone_timing_authority(),
        "source": "chrony-sysclock",
        "t_level_active": "T4" if synchronised else None,
        "sigma_ns": (
            int((abs(sys_offset) + root_disp + root_delay / 2.0) * 1e9)
            if synchronised else None
        ),
        "authority_utc_published": now_fn().isoformat(),
        "timing_source": f"CHRONY_{refname}" if refname else "CHRONY",
        "stratum": stratum,
        "leap_status": leap,
        "system_time_offset_ns": int(sys_offset * 1e9),
        "rms_offset_ns": int(rms_offset * 1e9),
    }


@dataclass(frozen=True)
class AnchorUTC:
    """Result of :func:`acquire_anchor_utc` — the single RTP->UTC anchor a
    sigmond recorder pins once at stream start.

    utc             epoch seconds of the anchored RTP sample
    source          provenance of the value (see acquire_anchor_utc)
    offset_seconds  authority RTP->UTC offset applied (0.0 if none usable)
    offset_ns       raw published offset in ns (None if no usable authority)
    snapshot        the AuthoritySnapshot consulted (None if unavailable)
    rtp_referenced  True iff utc came from rtp_to_utc, not a wall-clock fallback
    """
    utc: float
    source: str
    offset_seconds: float
    offset_ns: Optional[int]
    snapshot: Optional[AuthoritySnapshot]
    rtp_referenced: bool

    @property
    def datetime(self) -> datetime:
        """The anchor as a tz-aware UTC datetime (codar/hf-tec/wspr want this)."""
        return datetime.fromtimestamp(self.utc, tz=timezone.utc)

    def timing_authority_applied(
        self,
        client_radiod: Optional[str] = None,
        now_fn: Optional[Callable[[], float]] = None,
    ) -> Optional[dict]:
        """The CLIENT-CONTRACT §3 ``timing_authority_applied`` block for a
        recorder whose labels ride THIS anchor — or None when they carry no
        authority correction (§18.5 amendment 2026-09-04: reading a snapshot
        is not applying it; only a corrected label reports populated).

        Built from the snapshot that actually corrected the label, never
        from a fresh read of authority.json — the two can differ, and the
        report describes the labels.  The five contract keys come first;
        the rest is additive provenance so a later reader can put this
        client's labels on the same timeline as its peers'.
        """
        if self.offset_ns is None or self.snapshot is None:
            return None
        snap = self.snapshot
        governor = getattr(snap, "governor_radiod", None)
        published = getattr(snap, "utc_published", None)
        age = None
        if isinstance(published, datetime):
            now = (now_fn or time.time)()
            age = now - published.timestamp()
        host_clock = getattr(snap, "host_clock", None)
        return {
            "source": f"hf-timestd@{governor}" if governor else "hf-timestd",
            "tier": getattr(snap, "t_level_active", None),
            "sigma_ns": getattr(snap, "sigma_ns", None),
            "snapshot_age_s": age,
            "radiod_id": client_radiod,
            "rtp_to_utc_offset_ns": self.offset_ns,
            "anchor_source": self.source,
            "anchor_utc": self.datetime.isoformat(),
            "host_clock_verdict": (
                host_clock.get("verdict") if isinstance(host_clock, dict) else None
            ),
            "authority_utc_published": (
                published.isoformat() if isinstance(published, datetime) else None
            ),
        }


def acquire_anchor_utc(
    first_rtp: Optional[int],
    channel_info,
    rtp_to_utc: Callable,
    *,
    authority_reader=None,
    snapshot: Optional[AuthoritySnapshot] = None,
    samples_behind: int = 0,
    sample_rate: int = 12000,
    now_fn: Optional[Callable[[], float]] = None,
    anchor_hint_utc: Optional[float] = None,
) -> AnchorUTC:
    """Pin one RTP timestamp to UTC — the canonical anchor every sigmond
    slot/frame recorder establishes once at stream start.

    Replaces the five hand-rolled ``_compute_anchor_utc`` /
    ``_anchor_utc_for`` / ``_acquire_reference_utc`` copies that had drifted
    apart (e.g. hf-tec compensated for dropped samples in its fallback while
    codar did not).  One implementation so an upstream timing fix lands once.

    Preferred path (``rtp_referenced=True``): ``rtp_to_utc(first_rtp,
    channel_info, wallclock_hint_sec=now+offset)`` plus the hf-timestd §18
    authority offset.  radiod's GPSDO-disciplined RTP counter is the time
    reference; the host clock is used only as a wrap-disambiguation hint
    (±period/2, hours-scale).  This is the METROLOGY §4.5 RTP-reference
    invariant.

    Fallback (``rtp_referenced=False``), when no RTP timestamp / channel_info
    is available or ``rtp_to_utc`` returns None: the host wall clock at
    ``now_fn()`` minus ``samples_behind/sample_rate`` — so the anchor names the
    FIRST sample the caller holds, not "now" — plus the authority offset if one
    is usable.

    ``rtp_to_utc`` is injected (pass ``ka9q.rtp_to_utc``; the deprecated
    ``rtp_to_wallclock`` alias works too) so this module keeps no ka9q
    dependency.  Provide either ``authority_reader`` (read here) or a pre-read
    ``snapshot``.

    ``source`` ∈ {``"rtp_to_utc+authority"``, ``"rtp_to_utc"``,
    ``"authority_on_wallclock"``, ``"wallclock_fallback"``}.

    ``anchor_hint_utc`` — the approximate UTC of ``first_rtp`` when the caller
    already knows it.  REQUIRED when re-mapping a FIXED anchor RTP taken long
    ago (the slide-follow re-pin every recorder does each tick): the wrap
    hint must lie within ±P/2 of the anchor's TRUE instant, P/2 = 49.7 h at
    12 kHz, and "now" leaves that window after two days of uptime.  AC0G-B4
    2026-09-08: the hint aliased, k flipped, the anchor's UTC jumped +99.42 h
    and 136 FT8 spots left the station labelled four days ahead.  Pass the
    UTC the anchor was first given.  Default: ``now_fn() + offset`` — correct
    only for an RTP that IS recent, i.e. the first anchor.
    """
    # Resolve at call time (not as a default arg) so ``time.time`` stays
    # patchable and an explicit now_fn still wins.
    if now_fn is None:
        now_fn = time.time
    if snapshot is None and authority_reader is not None:
        try:
            snapshot = authority_reader.read()
        except Exception as exc:  # noqa: BLE001 — never crash the audio path
            logger.warning("authority read failed at anchor: %s", exc)
            snapshot = None
    usable = snapshot is not None and snapshot.offset_usable
    # The schema publishes the integer; seconds derive from it here so any
    # snapshot carrying the published field will do.
    offset_ns = int(snapshot.rtp_to_utc_offset_ns) if usable else None
    offset_sec = offset_ns / 1_000_000_000.0 if usable else 0.0

    if first_rtp is not None and channel_info is not None:
        try:
            hint = (
                anchor_hint_utc if anchor_hint_utc is not None
                else now_fn() + offset_sec
            )
            utc_sec = rtp_to_utc(
                int(first_rtp) & 0xFFFFFFFF,
                channel_info,
                wallclock_hint_sec=hint,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("rtp_to_utc raised at anchor: %s", exc)
            utc_sec = None
        if utc_sec is not None:
            return AnchorUTC(
                utc=utc_sec + offset_sec,
                source="rtp_to_utc+authority" if usable else "rtp_to_utc",
                offset_seconds=offset_sec,
                offset_ns=offset_ns,
                snapshot=snapshot,
                rtp_referenced=True,
            )

    # Wall-clock fallback: name the FIRST held sample, apply the offset if any.
    utc = now_fn() - samples_behind / sample_rate + offset_sec
    return AnchorUTC(
        utc=utc,
        source="authority_on_wallclock" if usable else "wallclock_fallback",
        offset_seconds=offset_sec,
        offset_ns=offset_ns,
        snapshot=snapshot,
        rtp_referenced=False,
    )


def applied_state_for_anchors(
    anchors: Iterable[Optional[AnchorUTC]],
    client_radiod: Optional[str],
    now_fn: Optional[Callable[[], float]] = None,
) -> Optional[dict]:
    """One instance's §3 ``timing_authority_applied`` block from the anchors
    of all its channels (psk/meteor: one per ChannelSink; wspr: one per
    BandRecorder), or None.

    Populated iff at least one channel is anchored and every anchored
    channel's anchor carries the authority offset — CLIENT-CONTRACT §18.7:
    a mixed state stays legal but must be VISIBLE, so it reports null here,
    never an average.  Channels not yet anchored have no label to report
    and do not veto.  The block is the newest applied anchor's own report
    plus ``channels: {total, anchored, applied}`` so the reader can see how
    many labels it stands for.
    """
    anchors = list(anchors)
    anchored = [a for a in anchors if a is not None]
    applied = [a for a in anchored if a.offset_ns is not None]
    counts = {"total": len(anchors), "anchored": len(anchored), "applied": len(applied)}
    if not anchored or len(applied) != len(anchored):
        return None
    newest = max(applied, key=lambda a: a.utc)
    block = newest.timing_authority_applied(client_radiod=client_radiod, now_fn=now_fn)
    if block is None:
        return None
    block["channels"] = counts
    return block


APPLIED_STATE_SCHEMA = "applied-state/v1"
#: A recorder writes its applied block once a minute; an inventory read
#: older than this treats the instance as not applying anything (stopped).
DEFAULT_APPLIED_STATE_MAX_AGE_S = 300.0


def write_applied_state(
    path: Path,
    block: Optional[dict],
    now_fn: Optional[Callable[[], float]] = None,
) -> None:
    """Leave the ``timing_authority_applied`` block a running recorder is
    applying where its own ``inventory --json`` (a separate process) can
    find it.  ``None`` is written explicitly: present-and-fresh-and-null
    means "running in §18 default mode", absent means "not running".
    Atomic (tmp + rename); never raises into the audio path.
    """
    now = (now_fn or time.time)()
    payload = {
        "schema": APPLIED_STATE_SCHEMA,
        "written_epoch": now,
        "written_utc": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "timing_authority_applied": block,
    }
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning("applied-state write failed at %s: %s", path, exc)


def read_applied_state(
    path: Path,
    max_age_s: float = DEFAULT_APPLIED_STATE_MAX_AGE_S,
    now_fn: Optional[Callable[[], float]] = None,
) -> Optional[dict]:
    """The block :func:`write_applied_state` left, or None when the file is
    missing, unreadable, of another schema, older than ``max_age_s`` (the
    recorder stopped writing, so nothing is being applied), or null."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != APPLIED_STATE_SCHEMA:
        return None
    try:
        written = float(data["written_epoch"])
    except (KeyError, TypeError, ValueError):
        return None
    if (now_fn or time.time)() - written > max_age_s:
        return None
    block = data.get("timing_authority_applied")
    return dict(block) if isinstance(block, dict) else None


def _parse_iso_z(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1]
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
