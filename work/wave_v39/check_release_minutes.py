"""同秒公開順・過去切断・未来改変で次研究の集約を検査する。"""

from pathlib import Path
import hashlib
import json
import pickle
import numpy as np
import pandas as pd
import release_minutes as minutes

HERE = Path(__file__).resolve().parent


def same(actual: dict, expected: dict, mask: np.ndarray | None = None) -> None:
    """機能: 切断しても、確定済みの全列が変わらないことを検査する。

    引数: actual/expected (dict)、mask (ndarray|None)。返り値: なし (None)。
    """
    assert actual.keys() == expected.keys()
    for name in actual:
        target = expected[name] if mask is None else expected[name][mask]
        np.testing.assert_array_equal(actual[name], target, err_msg=name)


def sliced(ready: dict, end: int) -> dict:
    """機能: 原本行対応列だけを途中で切断する。

    引数: ready (dict)、end (int) は排他末尾。返り値: 切断入力 (dict)。
    """
    n = len(ready['seq'])
    return {k:(v[:end].copy() if isinstance(v, np.ndarray) and v.shape and v.shape[0] == n else v)
        for k,v in ready.items()}


def main() -> None:
    """機能: 人工境界と全26入力の因果的な集約を照合する。

    引数: なし。返り値: なし (None)。売買損益の計算・API取得は行わない。
    """
    times = np.array([0,30,50,60,60,70,90,110,120,140,150,170,180,200], float)
    ready = dict(time_s=times, seq=np.arange(len(times)), start=0., atr=np.full(len(times), 2.))
    seq = np.array([1,3,4,6,8,10,12])
    frame = pd.DataFrame(dict(seq=seq, time_s=times[seq], source_time_s=times[seq]-1,
        source_last_seq=seq-1, valid_event_count=1, continuity_reset_count=0,
        ofi_signed=np.arange(1.,8.), ofi_abs=np.arange(1.,8.),
        source_mid_last=100.+np.arange(7), bid_qty=4., ask_qty=6., spread_ticks=1.))
    full = minutes.build(ready, frame)
    assert full['indices'].tolist() == [3,8,12]
    assert full['block_count'].tolist() == [2,3,2]
    assert full['signed'].tolist() == [3.,12.,13.]
    assert full['source_seq'].tolist() == [3,8,12]
    assert np.isclose(full['flow'][1], np.log1p(12/10))
    same(minutes.build(sliced(ready,4), frame), full, full['indices'] < 4)
    assert len(minutes.build(sliced(ready,1), frame)['indices']) == 0
    later = frame.copy()
    later.loc[later.seq > 3, 'ofi_signed'] *= -100
    same(minutes.build(sliced(ready,4), later), full, full['indices'] < 4)
    gap = frame.copy()
    gap.loc[gap.seq == 6, 'continuity_reset_count'] = 1
    assert not minutes.build(ready, gap)['valid'][1]
    # ----------------------------------------
    # 実入力で集約だけを生成し、収支や未来ラベルはまだ作らない。
    inputs_path = HERE.parent/'wave_v23/inputs.pkl'
    features_path = HERE.parent/'wave_v23/features_depth.pkl'
    inputs = pickle.loads(inputs_path.read_bytes())
    features = pickle.loads(features_path.read_bytes())
    assert len(inputs) == len(features) == 26 and inputs.keys() == features.keys()
    saved, proofs = {}, []
    for key, raw in sorted(inputs.items()):
        f = features[key]
        output = minutes.build(raw, f)
        saved[key] = output
        ends = sorted({1, max(2,int(len(raw['seq'])*.02)), int(len(raw['seq'])*.37), int(len(raw['seq'])*.73)})
        for end in ends:
            cutoff = raw['seq'][end-1]
            same(minutes.build(sliced(raw,end), f), output, output['seq'] <= cutoff)
            changed = f.copy()
            changed.loc[changed.seq > cutoff, ['ofi_signed','bid_qty','ask_qty']] *= -19
            same(minutes.build(sliced(raw,end), changed), output, output['seq'] <= cutoff)
        reflected = f.copy()
        reflected['ofi_signed'] *= -1
        reflected['source_mid_last'] = 2*float(f.source_mid_last.iloc[0])-f.source_mid_last
        reflected['bid_qty'], reflected['ask_qty'] = f.ask_qty.copy(), f.bid_qty.copy()
        mirror = minutes.build(raw, reflected)
        for name in ('flow','signed','change'):
            np.testing.assert_allclose(mirror[name], -output[name], equal_nan=True, rtol=1e-10, atol=1e-10)
        for name in ('valid','indices','seq','depth','block_count','bad_block_count'):
            np.testing.assert_array_equal(mirror[name], output[name])
        x,y,mask = minutes.model_rows(output)
        assert np.isfinite(x[mask]).all() and np.isfinite(y[mask]).all()
        proofs.append(dict(セッション=key[0], 銘柄=key[1], 分境界数=len(output['seq']),
            有効集約数=int(output['valid'].sum()), 有効学習組数=int(mask.sum()),
            過去切断数=len(ends), 未来改変数=len(ends), 価格反射一致=True))
    destination = HERE/'released_minutes.pkl'
    destination.write_bytes(pickle.dumps(saved, pickle.HIGHEST_PROTOCOL))
    paths = [inputs_path, features_path, Path(minutes.__file__), Path(__file__), destination]
    result = dict(全合格=True, 段階='集約確認だけ・売買未実施', 入力=proofs,
        API取得数=0, 現在保存物使用=False,
        SHA256={p.relative_to(HERE.parents[1]).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (HERE/'分公開の因果検査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(全合格=True, 入力数=len(proofs),
        全有効学習組数=sum(r['有効学習組数'] for r in proofs)), ensure_ascii=False))


if __name__ == '__main__':
    main()
