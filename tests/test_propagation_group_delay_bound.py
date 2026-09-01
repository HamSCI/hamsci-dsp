#!/usr/bin/env python3
"""The ionospheric group delay must stay physical near the reflection level.

`_integrate_group_delay` walks a straight ray up the electron-density
profile and accumulates ``(n_g - 1) ds``.  That integrand diverges as the
signal frequency approaches the local plasma frequency, because a real ray
refracts and turns instead of continuing straight.  Integrating into the
turning region therefore does not measure the ionosphere; it measures where
the altitude grid happened to land relative to the reflection height.

Observed on B4 2026-08-31 17:19Z, SHARED_10000, with foF2 near 9.97 MHz:
WWV came back at 9.03 ms against a great-circle free-space time of 3.74 ms,
and WWVH at 46.67 ms against 22.05 ms.  Both roughly doubled, and the doubling
tracked the band whose frequency sat just under foF2.  Those numbers set
``expected_sample``, so they anchor every ``timing_error_ms`` downstream.

Two properties pin the fix:
  1. refining the altitude grid must not move the answer, and
  2. a reflected sky-wave cannot arrive later than the free-space path to the
     highest virtual reflection height the F2 layer supports.
"""

import math

import numpy as np
import pytest

from hamsci_dsp.propagation.model import HFPropagationModel, C_LIGHT_M_S

# A generous upper bound on F2 virtual height at oblique incidence.  Real
# ionograms put h'F2 well below this even near the MUF.
MAX_VIRTUAL_HEIGHT_KM = 500.0
C_KM_PER_MS = C_LIGHT_M_S / 1e6


def chapman_profile(step_km, peak_km=300.0, scale_km=60.0, fo_mhz=10.0,
                    top_km=1000.0, bottom_km=80.0):
    """Alpha-Chapman layer whose critical frequency is exactly `fo_mhz`.

    Ne = fp^2 / 80.6 with fp in Hz gives the peak density for a chosen foF2,
    which is how the reflection condition in the integrator is expressed.
    """
    peak_ne = (fo_mhz * 1e6) ** 2 / 80.6
    alt = np.arange(bottom_km, top_km + step_km, step_km, dtype=float)
    z = (alt - peak_km) / scale_km
    ne = peak_ne * np.exp(0.5 * (1.0 - z - np.exp(-z)))
    return alt, ne


def group_path_ceiling_ms(ground_distance_km, n_hops, height_km=MAX_VIRTUAL_HEIGHT_KM):
    """Free-space time along `n_hops` reflections off a virtual height."""
    half_hop = ground_distance_km / (2.0 * n_hops)
    path_km = 2.0 * n_hops * math.hypot(half_hop, height_km)
    return path_km / C_KM_PER_MS


@pytest.fixture
def model():
    # AC0G / B4, Columbia MO — the station the corruption was measured on.
    return HFPropagationModel(
        receiver_lat=38.9187497, receiver_lon=-92.1277207, enable_realtime=False,
    )


class TestGroupDelayNearReflection:

    @pytest.mark.parametrize("frequency_mhz", [9.0, 9.5, 9.9])
    def test_group_delay_is_grid_independent(self, model, frequency_mhz):
        """Halving the altitude step must not move the delay.

        Below foF2 = 10 MHz the straight-ray integrand blows up in whichever
        cell sits just under the turning point, so a coarse grid and a fine
        grid disagree by however much that one cell happens to contribute.
        A delay that depends on the grid is a discretisation artifact.
        """
        coarse_alt, coarse_ne = chapman_profile(5.0)
        fine_alt, fine_ne = chapman_profile(1.0)

        coarse = model._integrate_group_delay(
            altitudes_km=coarse_alt, Ne_m3=coarse_ne,
            frequency_mhz=frequency_mhz, n_hops=1, elevation_deg=20.0)
        fine = model._integrate_group_delay(
            altitudes_km=fine_alt, Ne_m3=fine_ne,
            frequency_mhz=frequency_mhz, n_hops=1, elevation_deg=20.0)

        assert coarse == pytest.approx(fine, rel=0.10), (
            f"{frequency_mhz} MHz under foF2=10 MHz: coarse grid gives "
            f"{coarse:.3f} ms, fine grid {fine:.3f} ms — the answer is being "
            f"set by the altitude step, not by the ionosphere")

    def test_group_delay_below_virtual_height_ceiling(self, model):
        """A reflected ray cannot lag the path to the highest virtual height.

        Whatever the retardation near the turning point, the ray still comes
        back down; Breit-Tuve puts the group path at the free-space distance
        to the virtual reflection height, and h'F2 does not reach 500 km.
        """
        alt, ne = chapman_profile(5.0)
        # WWV -> B4, one F2 hop.
        ground_km, n_hops = 1122.5, 1
        geometric_ms = ground_km / C_KM_PER_MS
        ceiling_ms = group_path_ceiling_ms(ground_km, n_hops)

        iono_ms = model._integrate_group_delay(
            altitudes_km=alt, Ne_m3=ne, frequency_mhz=9.9,
            n_hops=n_hops, elevation_deg=20.0)

        assert geometric_ms + iono_ms <= ceiling_ms, (
            f"9.9 MHz just under foF2: total {geometric_ms + iono_ms:.2f} ms "
            f"exceeds the {ceiling_ms:.2f} ms ceiling for a 500 km virtual "
            f"height (iono term alone {iono_ms:.2f} ms)")

    def test_delay_does_not_double_approaching_fof2(self, model):
        """The delay must not spike as the band crosses under foF2.

        This is the shape of the live defect: 15 MHz sat above foF2 and came
        back sane, while 10 MHz sat just under it and doubled.
        """
        alt, ne = chapman_profile(5.0)
        kw = dict(altitudes_km=alt, Ne_m3=ne, n_hops=1, elevation_deg=20.0)

        well_above = model._integrate_group_delay(frequency_mhz=15.0, **kw)
        just_below = model._integrate_group_delay(frequency_mhz=9.9, **kw)

        assert just_below < 4.0 * well_above + 1.0, (
            f"crossing under foF2 multiplies the ionospheric term: "
            f"15 MHz -> {well_above:.3f} ms but 9.9 MHz -> {just_below:.3f} ms")
