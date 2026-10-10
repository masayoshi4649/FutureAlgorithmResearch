"""入口確認四水準を事前固定し、旧28場と追加追試1場へ同じ規則を適用する。"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np

import core


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path: Path) -> str:
    """機能: 原素材と実装の内容指紋を求める。

    引数: path(Path)。返り値: SHA256の16進文字列(str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def save(name: str, value: object) -> None:
    """機能: 今作業の入口領域だけへJSONを保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    path = (HERE / name).resolve()
    assert path.is_relative_to(HERE)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf8')


def material() -> tuple:
    """機能: 旧56口座と追加2口座を重複なしで集める。

    引数: なし。返り値: 入力・特徴・旧六列入口・使用ファイル(tuple)。
    """
    paths = [ROOT / 'work/wave_v69/prepared/inputs.pkl',
             ROOT / 'work/wave_v69/prepared/features.pkl', ROOT / 'work/wave_v70/inputs/signals.pkl',
             HERE.parent / 'prepared/extra_inputs.pkl', HERE.parent / 'prepared/extra_features.pkl',
             HERE.parent / 'prepared/extra_base_signals.pkl']
    values = [pickle.loads(p.read_bytes()) for p in paths]
    inputs, features, base = values[:3]
    for old, new in zip((inputs, features, base), values[3:]):
        assert not set(old) & set(new)
        old.update(new)
    assert set(inputs) == set(features) == set(base) and len(inputs) == 58
    return inputs, features, base, paths


def artificial() -> dict:
    """機能: 同中値更新、往復、reset、OFI欠測、相手先頭選択を人工経路で検査する。

    引数: なし。返り値: 検査結果(dict)。市場損益は使わない。
    """
    n = 22
    t = np.arange(n, dtype=float)
    bid = np.arange(n, dtype=float) + 100.
    ask = bid + 1.
    mid = (bid + ask) / 2.
    ofi = np.full(n, 5.)
    valid, reset = np.ones(n, bool), np.zeros(n, bool)
    out = core.own_gates(t, bid, ask, mid, ofi, valid, reset, 1.)
    assert not out[0][0, 0, :4].any() and out[0][0, 0, 4:].all()
    assert not out[0][1, 0, :16].any() and out[0][1, 0, 16:].all()
    assert not out[0][:, 1].any()
    tests = ['4/16中値イベントの準備不足と両気配進行・OFI一致']
    flat = np.full(n, 100.)
    still = core.own_gates(t, flat, flat+1., flat+.5, ofi, valid, reset, 1.)
    assert not still[0].any()
    tests.append('板行数が増えても中値変更がなければ価格履歴は増えない')
    missing = ofi.copy()
    missing[-1] = np.nan
    unknown = core.own_gates(t, bid, ask, mid, missing, valid, reset, 1.)
    assert unknown[0][0, 0, -1] and not unknown[0][1, 0, -1]
    tests.append('OFI欠測はG2を不許可にしG1の価格確認と混同しない')
    rs = reset.copy()
    rs[-1] = True
    restarted = core.own_gates(t, bid, ask, mid, ofi, valid, rs, 1.)
    assert not restarted[0][:, :, -1].any()
    tests.append('reset行で過去イベント履歴を破棄する')
    cut = 13
    short = core.own_gates(t[:cut], bid[:cut], ask[:cut], mid[:cut], ofi[:cut], valid[:cut], reset[:cut], 1.)
    np.testing.assert_array_equal(short[0], out[0][:, :, :cut])
    mirror = core.own_gates(t, 400.-ask, 400.-bid, 400.-mid, -ofi, valid, reset, 1.)
    np.testing.assert_array_equal(mirror[0][:, 0], out[0][:, 1])
    np.testing.assert_array_equal(mirror[0][:, 1], out[0][:, 0])
    tests.append('自市場許可の途中切断と価格上下鏡像が一致する')
    pt = np.repeat(np.arange(101., dtype=float), 2)
    pb = 100. + pt
    pa = pb + 1.
    # ----------------------------------------
    # 同時計二行目を大幅改変しても先頭行の相手判定は変わらない。
    peer = core.peer_gates(np.array([100., 107.]), pt, pb, pa, np.ones(len(pt)),
                          np.ones(len(pt), bool), np.zeros(len(pt), bool), 1.)
    assert peer[1][0] == 198 and peer[2][0] == 199 and peer[3][0] == 138
    assert peer[0][0, 0] and not peer[0][:, 1].any()
    changed_pb = pb.copy()
    changed_pa = pa.copy()
    changed_pb[199] += 1000.
    changed_pa[199] += 1000.
    peer2 = core.peer_gates(np.array([100., 107.]), pt, changed_pb, changed_pa, np.ones(len(pt)),
                           np.ones(len(pt), bool), np.zeros(len(pt), bool), 1.)
    np.testing.assert_array_equal(peer[0], peer2[0])
    tests.append('相手同時計の先頭行選択と末尾改変非依存、古さ5秒超は不許可')
    return dict(全合格=True, 検査=tests)


def clipped(inputs: dict, features: dict, base: dict, finish: float) -> tuple:
    """機能: 共通代理時計の途中まで入力・特徴・候補を切断する。

    引数: inputs/features/base(dict)、finish(float)。返り値: 切断三辞書(tuple)。
    """
    out, frames, signals = {}, {}, {}
    for k, ready in inputs.items():
        count = int(np.searchsorted(ready['time_s'], finish, side='left'))
        n = len(ready['seq'])
        assert 0 < count <= n
        out[k] = {name: value[:count].copy() if isinstance(value, np.ndarray) and value.ndim and len(value)==n else value
                  for name, value in ready.items()}
        frames[k] = {name: value[:count].copy() if isinstance(value, np.ndarray) and value.ndim and len(value)==n else value
                     for name, value in features[k].items()}
        signals[k] = base[k][:, :count].copy()
    return out, frames, signals


def main() -> None:
    """機能: 入口規則を先に固定し、旧56一致と新58の因果検査・根拠を保存する。

    引数: なし。返り値: なし(None)。APIと損益ファイルを参照しない。
    """
    sys.dont_write_bytecode = True
    socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('通信は禁止されています'))
    socket.create_connection = socket.socket.connect
    assert not (HERE / 'signals.pkl').exists(), '入口確認の生成は完了済みです'
    inputs, features, base, paths = material()
    old_schedule_path = ROOT / 'work/wave_v70/inputs/schedule.pkl'
    old_schedule = pickle.loads(old_schedule_path.read_bytes())
    spec = dict(固定時刻=datetime.now(timezone.utc).isoformat(), 入口順序=core.SOURCES,
        確認順序=core.LEVELS, 配列順序='source_index*4+gate_level。signals 24行、schedule 24配列。',
        G0='旧六列入口をそのまま使用。旧28場56口座のsignalsとscheduleを完全一致検査。',
        G1='直近4中値イベント前から両気配が候補方向へ1ラージ呼値以上。120秒以内の連続有効板。現気配差2呼値以下。',
        G2='G1に加え直近16中値イベント前から中値が候補方向へ2ラージ呼値以上、純移動/総移動0.30以上、区間のraw最良OFI符号比が候補方向へ0.10以上。履歴120秒以内、OFI欠測区間は不許可。',
        G3='G2に加え相手を自市場代理時計-1秒以前へ接続。同じ時計の先頭板だけ採用、古さ5秒以内。相手30秒前端も先頭板、前端ずれ5秒以内。区間にreset/無効板/OFI欠測なし。両気配1相手呼値以上、OFI符号比0.05以上の同方向。',
        採点位置='候補当行の可否のみを判定。確認待ちを設けず、不許可候補を後日の好価格で復活しない。',
        自市場破棄='reset、無効板、2呼値超の気配差、時計逆行、120秒超の時計空白で中値履歴を破棄。',
        OFI='数量増減・価格移動からの最良板フロー。成行約定と取消・補充を識別していない。',
        時計限界='CurrentPriceTimeは最終約定時計であり受信時計ではない。相手G3は代理時計上の過去対応のみ。両銘柄の実受信順の完全因果同期は証明できない。',
        主選定='G1/G2は主選定対象、G3は同期参考として主選定から除外。G0は対照。',
        確度='直前の候補方向確認が増えることは確認できるが、将来の正答率改善は保証しない。活動減少・動き終盤の追随・誤方向の整合確認になる可能性も損益で検証する。',
        入力観察=dict(利用可能=list(next(iter(features.values())).keys()),
            旧28場='受信時計なし、最良量とOFI・補充回復代理はある。真のaggressor、注文取消、個別参加者、将来返済はない。'),
        対象=dict(全口座数=58, 全セッション数=29, 選定既知範囲='旧28場のみ', 追加追試='2026-10-09_Day・2銘柄。選定に使用しない。'),
        共通入口='v70と同じ親stop予約→次有効観測で成立→さらに次有効行fill。fill後3630秒は次親予約禁止。TTL120秒、開始300秒、limit-300秒まで。',
        trace列=core.TRACE_COLUMNS, API取得数=0, 実注文数=0, 損益参照=False,
        SHA256={str(p.relative_to(ROOT)).replace('\\','/'):digest(p) for p in
                [*paths,old_schedule_path,HERE/'core.py',Path(__file__)]})
    save('入口確認の事前固定.json', spec)
    save('入口確認の人工経路検査.json', artificial())
    full = core.build(inputs, features, base)
    audit, g0 = [], []
    for key in sorted(inputs):
        if key in old_schedule:
            for source in range(6):
                np.testing.assert_array_equal(full['signals'][key][source*4], base[key][source])
                np.testing.assert_array_equal(full['schedule'][key][source*4], old_schedule[key][source])
            g0.append(dict(session=key[0],symbol=key[1], 六系列旧signals完全一致=True, 六系列旧schedule完全一致=True))
    assert len(g0) == 56
    for session in sorted({k[0] for k in inputs}):
        keys = [(session,s) for s in ('TOPIX','NK225')]
        current = {k:inputs[k] for k in keys}
        fs = {k:features[k] for k in keys}
        bs = {k:base[k] for k in keys}
        start, end = max(r['time_s'][0] for r in current.values()), min(r['time_s'][-1] for r in current.values())
        finish = start + (end-start)*.53
        parts = clipped(current,fs,bs,finish)
        prefix = core.build(*parts)
        changed, future_features, future_base = {}, {}, {}
        for k in keys:
            r = dict(current[k])
            f = dict(fs[k])
            cutoff = int(np.searchsorted(r['time_s'],finish,side='left'))
            for name in ('bid','ask','mid'):
                f[name] = fs[k][name].copy()
                f[name][cutoff:] += 50.*r['tick']
            f['best_ofi'] = fs[k]['best_ofi'].copy()
            f['best_ofi'][cutoff:] *= -7.
            f['reset'] = fs[k]['reset'].copy()
            f['reset'][cutoff:] = True
            future_features[k] = f
            future_base[k] = bs[k].copy()
            future_base[k][:,cutoff:] *= -1
            changed[k] = r
        future = core.build(changed,future_features,future_base)
        for k in keys:
            count = len(parts[0][k]['seq'])
            np.testing.assert_array_equal(prefix['signals'][k],full['signals'][k][:,:count])
            np.testing.assert_array_equal(future['signals'][k][:,:count],full['signals'][k][:,:count])
            for j in range(24):
                actual = full['schedule'][k][j]
                before = actual[actual[:,0] < count]
                np.testing.assert_array_equal(prefix['schedule'][k][j],before)
                future_before = future['schedule'][k][j]
                np.testing.assert_array_equal(future_before[future_before[:,0] < count],before)
                assert np.all(actual[:,2] < actual[:,1]) and np.all(actual[:,1] < actual[:,0])
            audit.append(dict(session=k[0],symbol=k[1], 切断24系列一致=True, 未来変更24系列一致=True,
                予約成立約定行分離=True, 候補数={core.SOURCES[s]+'_'+core.LEVELS[g]:int(np.count_nonzero(full['signals'][k][s*4+g]))
                    for s in range(6) for g in range(4)},
                初回数={core.SOURCES[s]+'_'+core.LEVELS[g]:len(full['schedule'][k][s*4+g])
                    for s in range(6) for g in range(4)}))
        print(session,'24系列の切断・未来改変を照合',flush=True)
    for name in ('signals','schedule','trace','states'):
        (HERE / (name+'.pkl')).write_bytes(pickle.dumps(full[name],pickle.HIGHEST_PROTOCOL))
    save('入口確認の因果検査.json',dict(全合格=True,口座数=58,セッション数=29,旧G0一致=g0,検査=audit,
        API取得数=0,実注文数=0,損益参照=False,
        注意='G3は代理時計の途中切断一致であり実受信順を証明しない。主選定対象外。',
        出力SHA256={name+'.pkl':digest(HERE/(name+'.pkl')) for name in ('signals','schedule','trace','states')}))
    print('58口座×24入口確認を固定し旧G0と因果性を照合しました',flush=True)


if __name__ == '__main__':
    main()
