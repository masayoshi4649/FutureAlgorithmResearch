"""新しい約定代理と現在気配の不一致を、未来行を使わず抽出する。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
from numba import njit


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
BASE = WORK.parent / 'wave_v60'
LABELS = ('新時計の最終値', '新出来高の平均値', '両方が一致', '古い最終値の対照', '平均値が二呼値離れる')


@njit(cache=True)
def signals(bid, ask, last, mean, volume, times, valid, reset, tick, start):
    """機能: 公開済み原本行だけで不一致を検知し、更新数の待機も行う。

    引数: 各観測(ndarray)、tick/start(float)。返り値: 5入口×3待機の方向(ndarray)。
    """
    n = len(bid)
    base = np.zeros((5, n), dtype=np.int8)
    out = np.zeros((15, n), dtype=np.int8)
    for i in range(1, n):
        if not valid[i] or reset[i] or ask[i] - bid[i] > tick * 1.001 or times[i] - start < 300:
            continue
        ld = 1 if last[i] >= ask[i] + tick * .999 else -1 if last[i] <= bid[i] - tick * .999 else 0
        md = 0
        if volume[i] > 0 and np.isfinite(mean[i]):
            md = 1 if mean[i] >= ask[i] + tick * .999 else -1 if mean[i] <= bid[i] - tick * .999 else 0
        fresh = times[i] > times[i - 1] and volume[i] > 0
        base[0, i] = ld if fresh else 0
        base[1, i] = md
        base[2, i] = ld if fresh and md == ld else 0
        base[3, i] = ld if not fresh else 0
        if volume[i] > 0 and np.isfinite(mean[i]):
            base[4, i] = 1 if mean[i] >= ask[i] + tick * 1.999 else -1 if mean[i] <= bid[i] - tick * 1.999 else 0
        for k in range(5):
            for d in range(3):
                delay = 0 if d == 0 else 16 if d == 1 else 64
                if i >= delay:
                    out[k * 3 + d, i] = base[k, i - delay]
    return out


def main() -> None:
    """機能: 入口・遅延対照・90条件を損益計算前に固定する。

    引数: なし。返り値: なし(None)。保存済み原本のみを読む。
    """
    assert not (HERE / 'signals.pkl').exists(), '既存入口を上書きしません'
    source = WORK / 'microstructure'
    for name in ('core.py', 'run.py'):
        (HERE / name).write_bytes((source / name).read_bytes())
    inputs = pickle.loads((BASE / 'inputs.pkl').read_bytes())
    features = pickle.loads((WORK / 'tick_features.pkl').read_bytes())
    output, audits = {}, []
    for key in sorted(inputs):
        f, ready = features[key], inputs[key]
        args = tuple(f[name] for name in ('bid', 'ask', 'last', 'exec_mean_price', 'volume_delta', 'time_s', 'valid', 'reset')) + (ready['tick'], ready['start'])
        signal = signals(*args)
        for cut in (len(f['bid']) // 3, len(f['bid']) // 2):
            short = signals(*(tuple(a[:cut] for a in args[:8]) + args[8:]))
            assert np.array_equal(short, signal[:, :cut])
        output[key] = signal
        audits.append(dict(セッション=key[0],銘柄=key[1],途中切断一致=True,信号数=[int(np.count_nonzero(s)) for s in signal]))
    (HERE / 'signals.pkl').write_bytes(pickle.dumps(output, protocol=pickle.HIGHEST_PROTOCOL))
    configs = []
    for k in range(5):
        for d, delay in enumerate((0, 16, 64)):
            for target, stop in ((4, 2), (8, 4), (16, 8)):
                for hold in (60, 600):
                    configs.append(dict(id=f'F4_N{k+1}_D{delay}_T{target}_S{stop}_H{hold}',signal=k*3+d,entry=LABELS[k],delay_rows=delay,
                        target=target,stop=stop,hold=hold,cooldown=60,protect=0,calibration=0,window=20,required_wins=19))
    destination = HERE / 'round4'
    destination.mkdir()
    (destination / '条件案.json').write_text(json.dumps(dict(conditions=configs), ensure_ascii=False, indent=2), encoding='utf-8')
    sha = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), HERE/'core.py', HERE/'run.py', HERE/'signals.pkl')}
    (HERE / '入口固定と因果照合.json').write_text(json.dumps(dict(時刻=datetime.now(timezone.utc).isoformat(),SHA=sha,合格=True,入口=LABELS,口座別=audits,
        仮説='新約定代理が現在気配を追い越す観測の後、気配が追随するか。古い最終値は負の対照。更新16/64行待ってから判断する入口で持続性を点検。',
        留意='CurrentPriceTimeは受信時計ではない。平均値は累積売買代金/出来高増分の代理。翌原本行ask買bid売、異銘柄時計は結合しない。遅延は原本更新数であり秒と等価ではない。',
        条件数=len(configs),ATR使用=False,現在API=0), ensure_ascii=False, indent=2), encoding='utf-8')
    print('新約定不一致15入口、90条件、100途中切断一致', flush=True)


if __name__ == '__main__':
    main()
