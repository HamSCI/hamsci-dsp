"""hamsci_dsp.ionosphere.ionex — IONEX GIM parser (moved from hf-timestd).

Split design §5.2: `ionex_parser` moves to hamsci-dsp verbatim (stdlib +
numpy only).  The synthetic-file test here is new coverage — the parser
previously had only ownership/caching tests in its consumer.
"""
from datetime import datetime

import pytest

from hamsci_dsp.ionosphere.ionex import IONEXParser

# A minimal, well-formed IONEX file: 2.5°-lat / 5°-lon grid over a tiny
# span, two epochs two hours apart, constant TEC per map (10.0 and 20.0
# TECU — IONEX stores 0.1-TECU integers).
_HEADER = """\
     1.0            IONOSPHERE MAPS     GPS                 IONEX VERSION / TYPE
    87.5 -87.5  -2.5                                        LAT1 / LAT2 / DLAT
  -180.0 180.0   5.0                                        LON1 / LON2 / DLON
                                                            END OF HEADER
"""


def _tec_map(epoch: str, tec_units: int) -> str:
    lines = [f"     1                                                      START OF TEC MAP\n",
             f"  {epoch}                        EPOCH OF CURRENT MAP\n"]
    lat = 87.5
    while lat >= -87.5:
        lines.append(
            f"  {lat:6.1f}-180.0 180.0   5.0 450.0                        LAT/LON1/LON2/DLON/H\n")
        row = ("%5d" % tec_units) * 16
        for _ in range(5):   # 73 lon points → 5 lines of 16 (last partial ok)
            lines.append(row + "\n")
        lat -= 2.5
    lines.append("     1                                                      END OF TEC MAP\n")
    return "".join(lines)


@pytest.fixture()
def ionex_file(tmp_path):
    p = tmp_path / "IGS0OPSFIN_20260740000_01D_02H_GIM.INX"
    p.write_text(
        _HEADER
        + _tec_map("2026     3    15    12     0     0", 100)   # 10.0 TECU
        + _tec_map("2026     3    15    14     0     0", 200))  # 20.0 TECU
    return p


class TestParse:
    def test_two_maps_parsed(self, ionex_file):
        p = IONEXParser(ionex_file)
        assert len(p.maps) == 2

    def test_interpolates_constant_map(self, ionex_file):
        p = IONEXParser(ionex_file)
        v = p.interpolate(40.0, -95.0, datetime(2026, 3, 15, 12, 0, 0))
        assert v == pytest.approx(10.0, abs=0.2)

    def test_time_interpolation_between_epochs(self, ionex_file):
        p = IONEXParser(ionex_file)
        v = p.interpolate(40.0, -95.0, datetime(2026, 3, 15, 13, 0, 0))
        assert v == pytest.approx(15.0, abs=0.4)  # halfway 10 → 20 TECU

    def test_no_maps_returns_none(self, tmp_path):
        p = object.__new__(IONEXParser)
        p.maps = []
        assert p.interpolate(0.0, 0.0, datetime(2026, 1, 1)) is None
