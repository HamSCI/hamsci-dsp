"""hamsci_dsp.ionosphere.space_weather — F10.7/Kp/Ap indices service.

Moved from hf-timestd (split design §5.2) with two DI changes:
* no `/var/lib/timestd` default — `cache_dir=None` uses a temp dir, and
  the timing client's shim supplies its own path;
* the HTTP session is injected (`session=`); without one the service
  simply reports nothing fetchable (the network layer stays with the
  caller — hamsci-dsp gains no `requests` dependency).

Parse tests are ported verbatim from hf-timestd tests/test_external_data.py.
"""
import pytest

from hamsci_dsp.ionosphere.space_weather import SpaceWeatherService


@pytest.fixture()
def svc(tmp_path):
    return SpaceWeatherService(cache_dir=str(tmp_path))


class TestParse:
    def test_swpc_summary(self, svc):
        svc._get_json = lambda url: [{"flux": 128, "time_tag": "2026-06-12T20:00:00"}]
        r = svc._fetch_f107_swpc_summary()
        assert r[0] == 128.0
        assert r[2] == "swpc:summary"

    def test_swpc_summary_rejects_garbage(self, svc):
        svc._get_json = lambda url: [{"flux": 99999, "time_tag": "x"}]
        assert svc._fetch_f107_swpc_summary() is None

    def test_swpc_dsd_last_row(self, svc):
        dsd = (":Product: daily-solar-indices.txt\n"
               "# header\n"
               "2026 06 11  127     81      485\n"
               "2026 06 12  128    113      430\n")
        svc._get_text = lambda url: dsd
        r = svc._fetch_f107_swpc_dsd()
        assert r[0] == 128.0
        assert r[2] == "swpc:dsd"

    def test_swpc_planetary_kp_latest(self, svc):
        svc._get_json = lambda url: [
            {"time_tag": "2026-06-12T21:00:00", "Kp": 3.0, "a_running": 15},
            {"time_tag": "2026-06-13T00:00:00", "Kp": 4.0, "a_running": 22},
        ]
        kp, ap, t, src = svc._fetch_kp_ap_swpc()
        assert kp == 4.0   # latest by time_tag
        assert ap == 22.0
        assert src == "swpc:planetary-k"

    def test_gfz_fallback_last_non_null(self, svc):
        svc._get_json = lambda url: {
            "Kp": [2.0, 2.667, None],
            "datetime": ["2026-06-12T18:00:00Z", "2026-06-12T21:00:00Z",
                         "2026-06-13T00:00:00Z"],
        }
        kp, t, src = svc._fetch_kp_gfz()
        assert kp == 2.667
        assert src == "gfz"

    def test_getters_default_when_empty(self, svc):
        assert svc.get_f107(default=111.0) == 111.0
        assert svc.get_f107(default=None) is None


class TestDependencyInjection:
    def test_no_timestd_path_default(self, tmp_path, monkeypatch):
        import tempfile
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        svc = SpaceWeatherService()   # no cache_dir → temp, never /var/lib
        assert str(svc.cache_dir).startswith(str(tmp_path))

    def test_injected_session_is_used(self, tmp_path):
        class FakeResp:
            status_code = 200
            def json(self):
                return [{"flux": 128, "time_tag": "t"}]
        class FakeSession:
            def __init__(self):
                self.calls = []
            def get(self, url, timeout=None):
                self.calls.append(url)
                return FakeResp()
        s = FakeSession()
        svc = SpaceWeatherService(cache_dir=str(tmp_path), session=s)
        assert svc._fetch_f107_swpc_summary()[0] == 128.0
        assert s.calls  # the injected session carried the fetch

    def test_no_session_means_no_fetch_not_a_crash(self, tmp_path):
        svc = SpaceWeatherService(cache_dir=str(tmp_path))
        assert svc._get_json("http://example.invalid") is None
        assert svc._get_text("http://example.invalid") is None
