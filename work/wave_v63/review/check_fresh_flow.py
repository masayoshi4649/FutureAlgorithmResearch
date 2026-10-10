"""新時計・代金平均・待機対照の入口を独立した配列式で照合する。"""

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
BRANCH = HERE.parent/'fresh_flow'
COMMON = HERE.parent.parent/'wave_v60'


def main() -> None:
    """機能: 全入口の因果的配列構成と固定SHA、待機の意味を検査する。

    引数: なし。返り値: なし(None)。価格や売買条件を変更しない。
    """
    fixed = json.loads((BRANCH/'入口固定と因果照合.json').read_text(encoding='utf-8'))
    for name, expected in fixed['SHA'].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected
    for name in ('core.py', 'run.py'):
        assert (BRANCH/name).read_bytes() == (HERE.parent/'microstructure'/name).read_bytes()
    inputs = pickle.loads((COMMON/'inputs.pkl').read_bytes())
    features = pickle.loads((HERE.parent/'tick_features.pkl').read_bytes())
    signals = pickle.loads((BRANCH/'signals.pkl').read_bytes())
    totals = dict(口座=0, 系列=0, 入口=0, 遅延区間の不正又はresetを跨ぐ入口=0)
    for account, f in features.items():
        r = inputs[account]
        bid, ask, last, mean, volume, times, valid, reset = [f[k] for k in
            ('bid', 'ask', 'last', 'exec_mean_price', 'volume_delta', 'time_s', 'valid', 'reset')]
        tick = r['tick']
        guard = valid & ~reset & (ask-bid <= tick*1.001) & (times-r['start'] >= 300)
        guard[0] = False
        ld = np.where(last >= ask+tick*.999, 1, np.where(last <= bid-tick*.999, -1, 0))
        md = np.where((volume > 0) & np.isfinite(mean),
                      np.where(mean >= ask+tick*.999, 1, np.where(mean <= bid-tick*.999, -1, 0)), 0)
        fresh = np.r_[False, np.diff(times) > 0] & (volume > 0)
        deep = np.where((volume > 0) & np.isfinite(mean),
                        np.where(mean >= ask+tick*1.999, 1, np.where(mean <= bid-tick*1.999, -1, 0)), 0)
        bases = [np.where(fresh, ld, 0), md, np.where(fresh & (md == ld), ld, 0), np.where(~fresh, ld, 0), deep]
        invalid_prefix = np.r_[0, np.cumsum(~valid | reset)]
        for k, base in enumerate(bases):
            base = np.where(guard, base, 0)
            for j, delay in enumerate((0, 16, 64)):
                expected = base.copy() if not delay else np.r_[np.zeros(delay, dtype=int), base[:-delay]]
                expected = np.where(guard, expected, 0)
                np.testing.assert_array_equal(expected, signals[account][k*3+j])
                ix = np.flatnonzero(expected)
                if delay:
                    totals['遅延区間の不正又はresetを跨ぐ入口'] += int(np.count_nonzero(invalid_prefix[ix+1]-invalid_prefix[ix-delay+1]))
                totals['系列'] += 1
                totals['入口'] += len(ix)
        totals['口座'] += 1
    record = dict(合格=True, 件数=totals, 独立配列式で全入口一致=True, 既存監査済み売買器とバイト一致=True,
        現在以前の同銘柄データのみ=True, 現在市場API回数=0,
        解釈の限定=['新時計は最終約定時計の増加であり受信時刻や真の執行側ではない。',
                    '古い最終値対照は新時計かつ出来高増分という条件の不成立であり、年齢の測定ではない。',
                    '16/64更新待機は元方向を遅らせた対照。待機中の価格保持や連続した板品質を要求する持続性検知ではない。'])
    (HERE/'新約定代理入口の独立照合.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
