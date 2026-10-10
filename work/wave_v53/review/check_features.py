"""特徴計算の現在足除外・確定時刻・場内初期化を独立検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK))
from features import build_account, completed_bars, add_swings, rsi_wilder, rolling_complete, vwap_series, load_inputs_only


def fixture(n: int = 45) -> tuple:
    """機能: 毎分三つの中値からなる監査用原本を作る。

    引数: n(int)。返り値: 入力と板の組(tuple[dict,dict])。
    """
    times = np.array([60*k+s for k in range(n+1) for s in (0, 30, 59)], float)
    mid = np.array([100+k*.1+d for k in range(n+1) for d in (0., .4, 0.)])
    seq = np.arange(len(times), dtype=np.int64)+1
    ready = dict(start=0., limit=float(60*n), session='合成', symbol='TOPIX', seq=seq, time_s=times, last=mid.copy(), atr=np.full(len(times), 999.))
    quotes = dict(seq=seq, time_s=times, mid=mid, bid=mid-.05, ask=mid+.05)
    return ready, quotes


def main() -> None:
    """機能: 手計算例・全口座時系列不変条件・未来改変を照合する。

    引数: なし。返り値: なし(None)。損益は参照しない。
    """
    allblocks = pickle.loads((TASK.parent/'wave_v52/measurement/features.pkl').read_bytes())
    empty = next(iter(allblocks.values())).iloc[:0].copy()
    checks = []
    ready, quote = fixture()
    frame = build_account(ready, quote, empty)
    assert len(frame) == 45 and frame.seq.iloc[0] == 4
    assert frame.source_last_seq.iloc[0] == 3 and frame.close.iloc[0] == 100
    assert frame.ema8.iloc[0] == 100 and frame.ema21.iloc[0] == 100
    assert np.isnan(frame.atr5.iloc[18]) and np.isclose(frame.atr5.iloc[19], (.8+.9*3)/4)
    assert np.isnan(frame.atr1.iloc[12]) and np.isclose(frame.atr1.iloc[13], (.4+.5*13)/14)
    checks.append('初足から独立初期化し、1分14本・5分4本の完了前にATRを公開しない')

    changed = {k: v.copy() for k,v in quote.items()}
    changed['mid'][-3:] = [1., 100000., 90000.]
    pd.testing.assert_frame_equal(completed_bars(ready, quote, 60), completed_bars(ready, changed, 60))
    altered_ready = ready.copy()
    altered_ready['atr'] = np.full(len(ready['seq']), .001)
    pd.testing.assert_frame_equal(frame, build_account(altered_ready, quote, empty))
    checks.append('現在の未完足と旧キャッシュATRを改変しても確定足の指標は不変')

    ready2, quote2 = fixture()
    quote2['mid'][61] = 10000.
    altered = build_account(ready2, quote2, empty)
    assert altered.high.iloc[20] == 10000. and np.isclose(altered.prior20_high.iloc[20], 102.3)
    assert altered.prior20_high.iloc[21] == 10000.
    assert frame.or30_high.iloc[:29].isna().all()
    assert np.isclose(frame.or30_high.iloc[29], 103.3) and frame.or30_high.iloc[29:].nunique() == 1
    gap = frame.iloc[list(range(20))+list(range(21, len(frame)))].reset_index(drop=True)
    assert not rolling_complete(gap, 20, True)[20]
    checks.append('現在足を支持抵抗から除き、開始30分の公開後固定と欠落分の拒否を確認')

    swing = pd.DataFrame(dict(bar_start=np.arange(5)*60., time_s=np.arange(1,6)*60., seq=np.arange(1,6)*3,
                              high=[1,2,5,3,2], low=[0,-1,-4,-2,-1]))
    add_swings(swing)
    assert swing.swing_high.iloc[:4].isna().all() and swing.swing_low.iloc[:4].isna().all()
    assert swing.swing_high.iloc[4] == 5 and swing.swing_low.iloc[4] == -4
    assert swing.swing_high_time.iloc[4] == 120 and swing.swing_high_confirmed_time.iloc[4] == 300
    assert swing.swing_high_confirmed_seq.iloc[4] == 15
    assert rsi_wilder(np.arange(20, dtype=float))[14] == 100
    assert rsi_wilder(np.ones(20))[14] == 50
    checks.append('山谷は右二本が確定するまで非公開、RSI初期値を手計算照合')

    block = pd.DataFrame(dict(time_s=[1,2,3,4,5], continuity_resets=[0,0,1,0,0], volume_resets=[0,0,0,1,0],
                             unavailable_volume_events=[0]*5, source_volume_delta=[0,10,5,100,2], source_last=[100,110,140,999,120]))
    vw = vwap_series(block, 0.)
    np.testing.assert_allclose(vw['vwap_proxy'], [np.nan,110,120,np.nan,120], equal_nan=True)
    np.testing.assert_allclose(vw['cum_volume'], [0,10,15,0,2])
    assert list(vw['vwap_discontinuity_count']) == [0,0,1,1,1]
    assert list(vw['vwap_reset_count']) == [0,0,0,1,1]
    checks.append('VWAP代理は初回累積を持ち込まず、出来高リセットと板不連続を区別')

    inputs = load_inputs_only()
    quotes = pickle.loads((TASK.parent/'wave_v52/measurement/quotes.pkl').read_bytes())
    saved = pickle.loads((TASK/'特徴.pkl').read_bytes())
    count = 0
    for key, f in saved.items():
        assert (f.source_last_seq < f.seq).all() and (f.source_last_time < f.time_s).all()
        assert (f.bar_start+60 <= f.time_s).all()
        assert (f.bar_start >= inputs[key]['start']).all()
        for side in ('high','low'):
            valid = f[f[f'swing_{side}_confirmed_seq'].notna()]
            assert (valid[f'swing_{side}_confirmed_seq'] <= valid.seq).all()
            assert (valid[f'swing_{side}_confirmed_time'] <= valid.time_s).all()
            assert (valid[f'swing_{side}_time']+180 <= valid[f'swing_{side}_confirmed_time']).all()
        peers = f[f.peer_time_s.notna()]
        assert (peers.peer_time_s <= peers.time_s-60).all() and (peers.peer_age <= 60).all()
        for i in range(20, len(f)):
            past = f.iloc[i-20:i]
            if past.bar_start.iloc[-1]-past.bar_start.iloc[0] == 1140 and f.bar_start.iloc[i]-past.bar_start.iloc[-1] == 60:
                assert f.prior20_high.iloc[i] == past.high.max() and f.prior20_low.iloc[i] == past.low.min()
            else:
                assert np.isnan(f.prior20_high.iloc[i]) and np.isnan(f.prior20_low.iloc[i])
        count += len(f)
    checks.append(f'全46口座{count}行の確定時刻・山谷公開・相手遅延・支持抵抗を独立検算')

    futures = []
    keys = sorted(inputs)
    for key in [keys[i] for i in (0,1,22,23,44,45)]:
        source, original_quote, blocks = inputs[key], quotes[key], allblocks[key]
        cut = len(source['seq'])//2
        cutoff = source['seq'][cut-1]
        modified = {name: value.copy() if isinstance(value, np.ndarray) else value for name,value in source.items()}
        mq = {name: value.copy() for name,value in original_quote.items()}
        modified['last'][cut:] *= 2.5
        for name in ('mid','bid','ask'):
            mq[name][cut:] *= 3.
        mb = blocks.copy()
        future = mb.seq > cutoff
        for name in ('exec_buy','exec_sell','exec_unknown','source_volume_delta','source_last'):
            mb.loc[future,name] *= 10.
        actual = build_account(modified, mq, mb)
        actual = actual[actual.seq <= cutoff].reset_index(drop=True)
        expected = saved[key].loc[saved[key].seq <= cutoff, actual.columns].reset_index(drop=True)
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        futures.append(dict(セッション=key[0], 銘柄=key[1], 一致行数=len(actual)))
    checks.append('六口座の未来価格・未来板量を大幅改変しても過去の全特徴は不変')
    result = dict(合格=True, 検査=checks, 未来改変=futures, 実装SHA256=hashlib.sha256((TASK/'features.py').read_bytes()).hexdigest())
    (HERE/'特徴の独立検査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print('合格', len(checks), '全行', count, '未来改変', len(futures), flush=True)


if __name__ == '__main__':
    main()
