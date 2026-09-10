# hamsci-dsp

Shared DSP / timing utilities for the [HamSCI](https://hamsci.org/) **sigmond**
SDR suite. This is the canonical home for code that several sigmond clients
otherwise carry as byte-identical copies.

It is an **importable library only** — no CLI, no systemd unit, no client
contract surface. Like `callhash` and `ka9q-python`, consumers pin it editable
from a sibling checkout so a `git pull` propagates with no reinstall:

```toml
# in a consumer's pyproject.toml
[tool.uv.sources]
hamsci-dsp = { path = "../hamsci-dsp", editable = true }
```

## Modules

| Module | What it provides | Deps |
|--------|------------------|------|
| `hamsci_dsp.timing` | `AuthorityReader` / `AuthoritySnapshot` read hf-timestd's `authority.json`. `acquire_anchor_utc` pins the one RTP→UTC anchor every recorder shares (pass `anchor_hint_utc` when re-mapping a fixed anchor). `AnchorUTC.timing_authority_applied` and `applied_state_for_anchors` build the contract §3 report; `write_applied_state` / `read_applied_state` carry it from the daemon to `inventory --json`. | stdlib |
| `hamsci_dsp.constants` | `C_M_S`, `K_TEC=40.3`, `R_EARTH_KM`, `TECU`. | stdlib |
| `hamsci_dsp.geometry` | great-circle distance / bearing / midpoint / destination (geographiclib), reflection geometry (elevation, hop path), Maidenhead grid ↔ lat/lon. | numpy, geographiclib |
| `hamsci_dsp.dsp` | canonical peak SNR (Rayleigh/​signed), robust noise floor, `CoherentStack` (slow-time range-Doppler), carrier→Doppler, FFT correlation. | numpy |
| `hamsci_dsp.propagation` | **path observables**: `carrier` (phase→dTEC, dTEC/dt), `oblique` (virtual height, equivalent vertical freq, MUF, obliquity), `scintillation` (S4, σφ — ITU-R P.531). | numpy |
| `hamsci_dsp.ionosphere` | solar position/zenith (dep-free) + `ionosphere_state` (IRI when available, parametric fallback). | numpy; `iono` extra → `iri2020` |
| `hamsci_dsp.raytrace` | `RaytraceEngine` — lazy PyLAP/PHaRLAP wrapper (advisory; no-op when absent). | `raytrace` extra → `pylap` (+ PHaRLAP) |

`timing`, `constants`, `geometry`, `dsp`, and `propagation` are extracted
math-identical from the clients (the `authority.json` schema is owned by
`hf-timestd/docs/METROLOGY.md §4.5.2`; the carrier-dTEC and oblique-inversion
physics from hf-timestd `carrier_tec.py`/`tec_geometry.py` and codar
`invert.py`/`scintillation.py`). `ionosphere`/`raytrace` carry optional heavy
deps and are gated behind extras.

### Extras

```bash
uv sync --extra dev                  # tests
uv pip install -e '.[iono]'          # IRI ionosphere model (needs gfortran)
uv pip install -e '.[raytrace]'      # PyLAP/PHaRLAP ray tracing (PHaRLAP staged separately)
uv pip install -e '.[geomag]'        # apexpy geomagnetic coordinates
```

### Consumers / de-duplication status

superdarn-sounder consumes `timing`, `geometry`, and `propagation`. The existing
clients (hf-timestd, codar-sounder, hf-tec, wspr-recorder) still carry local
copies of the extracted code (great-circle ×17 in hf-timestd, codar `invert`/
`scintillation`, hf-tec `detect`/`coherent`); they are migrated onto this library
**opportunistically** as each module is next touched.

## Development

```bash
uv sync --extra dev
uv run pytest
```

## Authors

- Michael Hauan (AC0G) — https://github.com/HamSCI/hamsci-dsp
- Part of [HamSCI](https://hamsci.org/).
