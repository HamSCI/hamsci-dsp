"""CounterMap: one channel's RTP counter to radiod's input-sample index."""
import pytest

from hamsci_dsp.counter_map import CounterMap, CounterPoll

L, F_IN, F_OUT, OLEN = 1_296_000, 64_800_000, 24_000, 480
ND_K0 = (51, 51, 51, 51, 50)
EPOCH_GPS_S = 1_450_000_000.0


def rtp_at(block, k0, olen=OLEN):
    return (2**32 - olen + (block + 1 - k0) * olen) % 2**32


def poll(rtp, input_samples, f_out=F_OUT):
    gps_ns = int(round((EPOCH_GPS_S + input_samples / F_IN) * 1e9))
    return CounterPoll(rtp_timesnap=rtp, input_samples=input_samples,
                       filter_blocksize=L, input_samprate=F_IN,
                       output_samprate=f_out, gps_time_ns=gps_ns)


def polls_for(k0, blocks, f_out=F_OUT):
    olen = f_out * L // F_IN
    return [poll(rtp_at(b, k0, olen), b * L, f_out) for b in blocks]


def test_nd_origins_map_one_instant_to_one_index():
    maps = [CounterMap.from_polls(polls_for(k0, range(10_000, 10_005)))
            for k0 in ND_K0]
    for m, k0 in zip(maps, ND_K0):
        assert m.input_index(rtp_at(12_000, k0)) == pytest.approx(12_000 * L, abs=1e-6)
    # the defect itself: same instant, raw RTP one block apart
    assert (rtp_at(12_000, 50) - rtp_at(12_000, 51)) % 2**32 == OLEN


def test_torn_poll_is_outvoted():
    polls = polls_for(51, range(10_000, 10_005))
    good = CounterMap.from_polls(polls)
    p = polls[2]
    polls[2] = poll(p.rtp_timesnap, p.input_samples + L)
    m = CounterMap.from_polls(polls)
    assert m.input_ref == good.input_ref and m.n_agree == 4


def test_too_few_agreeing_polls_gives_none():
    polls = polls_for(51, range(10_000, 10_004))
    for i in (1, 3):
        polls[i] = poll(polls[i].rtp_timesnap, polls[i].input_samples + L)
    assert CounterMap.from_polls(polls, min_agree=3) is None


def test_input_index_is_continuous_across_the_rtp_wrap():
    rtp_ref = 2**32 - OLEN
    polls = [poll((rtp_ref + i * OLEN) % 2**32, 7 * L + i * L) for i in range(4)]
    m = CounterMap.from_polls(polls)
    assert m.rtp_ref == rtp_ref and m.input_ref == 7 * L
    for n in (1, 2, 3, 50):
        rtp = (rtp_ref + n * OLEN) % 2**32
        assert m.input_index(rtp) == 7 * L + n * L
    assert (rtp_ref + 2 * OLEN) % 2**32 <= OLEN        # really past the wrap


def test_rolled_forward_survives_thirty_hours():
    m = CounterMap.from_polls(polls_for(51, range(10_000, 10_005)))
    later = 10_000 + 30 * 3600 * 50          # 30 h of 20 ms blocks
    # A held map rolls as it goes; one jump of 30 h exceeds the signed-32 reach.
    rolled = m
    for hours in (10, 20, 30):
        b = 10_000 + hours * 3600 * 50
        rolled = rolled.rolled_forward(rtp_at(b, 51))
    assert rolled.input_index(rtp_at(later, 51)) == pytest.approx(later * L, abs=1e-6)
    assert abs(m.input_index(rtp_at(later, 51)) - later * L) > 1e9   # unrolled aliases


def test_non_integer_block_is_refused():
    # 22_051 Hz x 20 ms = 441.02 samples per block (22_050 would give exactly 441)
    polls = [poll(10_000 * 441 + i * 441, (10_000 + i) * L, f_out=22_051)
             for i in range(5)]
    assert CounterMap.from_polls(polls) is None


def test_poll_off_the_block_grid_is_refused():
    polls = polls_for(51, range(10_000, 10_005))
    polls[1] = poll(polls[1].rtp_timesnap + 1, polls[1].input_samples)
    assert CounterMap.from_polls(polls, min_agree=5) is None


def test_another_run_is_not_the_same_run():
    a = CounterMap.from_polls(polls_for(51, range(10_000, 10_005)))
    shifted = [poll(p.rtp_timesnap, p.input_samples) for p in polls_for(51, range(10_000, 10_005))]
    shifted = [CounterPoll(p.rtp_timesnap, p.input_samples, p.filter_blocksize,
                           p.input_samprate, p.output_samprate,
                           p.gps_time_ns + 3600 * 10**9) for p in shifted]
    b = CounterMap.from_polls(shifted)
    assert not a.same_run(b) and a.intercept_blocks_from(b) is None


def test_same_run_step_counts_blocks():
    a = CounterMap.from_polls(polls_for(51, range(10_000, 10_005)))
    # same RTP values, input_samples one block higher: the intercept moved +1 block
    b = CounterMap.from_polls([poll(p.rtp_timesnap, p.input_samples + L)
                               for p in polls_for(51, range(10_000, 10_005))])
    assert a.same_run(b) and b.intercept_blocks_from(a) == 1 and a.intercept_blocks_from(b) == -1
    assert a.intercept_blocks_from(a) == 0


def test_dict_round_trip():
    m = CounterMap.from_polls(polls_for(51, range(10_000, 10_005)))
    assert CounterMap.from_dict(m.to_dict()) == m and CounterMap.from_dict(None) is None
