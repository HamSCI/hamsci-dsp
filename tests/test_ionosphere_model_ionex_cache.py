"""IonosphericModel's IONEX parser cache (moved with the engine, §5.2).

Ported from hf-timestd tests/unit/test_ionex_parser_module.py — the
cache-behavior half; the ownership/shim assertions stayed behind.
"""
from datetime import datetime, timezone

_TS = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)  # day-of-year 074
_IONEX_NAME = "IGS0OPSFIN_20260740000_01D_02H_GIM.INX.gz"


class _StubParser:
    """Stand-in for IONEXParser that counts how often it is constructed."""
    instances = 0

    def __init__(self, path):
        type(self).instances += 1
        self.path = path

    def interpolate(self, lat, lon, timestamp):
        return 17.5


def test_cache_hit_avoids_reparsing(monkeypatch, tmp_path):
    import hamsci_dsp.ionosphere.model as im
    _StubParser.instances = 0
    monkeypatch.setattr(im, 'IONEXParser', _StubParser)
    (tmp_path / _IONEX_NAME).write_text('')
    model = im.IonosphericModel(enable_iri=False, enable_calibration=False,
                                ionex_dir=tmp_path)

    first = model.get_ionex_vtec(40.0, -95.0, _TS)
    second = model.get_ionex_vtec(40.0, -95.0, _TS)
    assert first == second
    assert first[0] == 17.5
    assert _StubParser.instances == 1  # second call was a cache hit


def test_stale_cache_is_reparsed(monkeypatch, tmp_path):
    import hamsci_dsp.ionosphere.model as im
    _StubParser.instances = 0
    monkeypatch.setattr(im, 'IONEXParser', _StubParser)
    (tmp_path / _IONEX_NAME).write_text('')
    model = im.IonosphericModel(enable_iri=False, enable_calibration=False,
                                ionex_dir=tmp_path)
    model._ionex_cache_max_age = 0  # everything is immediately stale

    model.get_ionex_vtec(40.0, -95.0, _TS)
    model.get_ionex_vtec(40.0, -95.0, _TS)
    assert _StubParser.instances == 2  # max_age honoured -> re-parsed


def test_no_ionex_dir_disables_lookup():
    import hamsci_dsp.ionosphere.model as im
    model = im.IonosphericModel(enable_iri=False, enable_calibration=False)
    assert model.ionex_dir is None
    assert model.get_ionex_vtec(40.0, -95.0, _TS) is None or \
        model.get_ionex_vtec(40.0, -95.0, _TS)[0] is None
