"""両市場の新規見送り条件を事前固定し、既存四方式の注文列から再生する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
import time

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V47 = ROOT / 'work/wave_v47'
sys.path.insert(0, str(V47))
import integrated_followup as followup

replay, integration = followup.replay, followup.integration
IDS = ('F50_NONE__E11', 'F50_NONE__E10', 'C01__E10', 'A0__E10')
NEW = '2026-09-30_Night'
INPUTS, FEATURES, MODELS = {}, {}, {}


def read(path: Path) -> object:
    """機能: 保存JSONを読む。

    引数: path(Path)。返り値: 保存値(object)。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def save(path: Path, value: object) -> None:
    """機能: 今作業領域だけへ保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)


def sha(path: Path) -> str:
    """機能: 内容指紋を返す。

    引数: path(Path)。返り値: 指紋(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def catalog() -> list[dict]:
    """機能: 損益を参照せず十三条件を構成する。

    引数: なし。返り値: 条件(list[dict])。
    """
    result = [dict(id='G00', name='元の条件', kind='none')]
    for number, window in enumerate((5, 15, 30), 1):
        result.append(dict(id=f'G{number:02}', name=f'{window}分の両市場逆向きを避ける', kind='opposed', window=window))
    for number, window in enumerate((5, 15, 30), 4):
        result.append(dict(id=f'G{number:02}', name=f'{window}分で片方でも入口と逆なら避ける', kind='against', window=window))
    for number, window, threshold in ((7, 5, .1), (8, 15, .25), (9, 30, .5)):
        result.append(dict(id=f'G{number:02}', name=f'両市場の{window}分変化が同方向{threshold}ATR超', kind='strong', window=window, threshold=threshold))
    result += [dict(id='G10', name='両市場のEMA開始条件を現在も満たす', kind='rearm'),
               dict(id='G11', name='両市場の長期EMA傾きが入口と逆なら避ける', kind='slow'),
               dict(id='G12', name='両市場の短期EMA傾きが現在も同方向', kind='fast')]
    return result


def freeze() -> dict:
    """機能: 新条件と注文の公開順を損益再生前に固定する。

    引数: なし。返り値: 固定書(dict)。
    """
    value = dict(条件=catalog(), 既存方式=list(IDS), 対象='旧15セッションと09/30Nightを別集計。再探索であり未見検証ではない。',
        変更='入口10列の先頭stateだけを条件不成立時に0へ変更。退出・途中判断・枚数・注文価格は不変。条件成立後は通常の新規準備を再開。',
        新規注文順='観測行iの許可は行iの計画更新に使い、行i+1以降の約定に有効。行i時点で逆行に変わっても既発注の前行計画は同じ行で約定し得る。未約定の取消も次行から有効。',
        再生='見送り後の新しい準備・約定・仮想基準運転・待機時間をすべて再生。元の負け取引だけを削除しない。',
        足='確定1分足の開始時刻+120秒から利用。相手銘柄はさらに60秒遅延。セッション毎にEMAを初期化。',
        窓='5/15/30分は公表時刻から実時間で遡り、その時点以前の最後の確定終値との差。未来補間なし。',
        ATR='既存の因果的ATRを足公開時刻へasof。銘柄ごとに正規化。',
        欠損='必要な窓・EMA・ATRが欠ける場合は入口を見送る。',
        閾値='逆向きだけ避ける条件は厳密な符号だけ。強い一致は5分0.1ATR/15分0.25ATR/30分0.5ATRで事前固定。',
        評価='旧15と問題Nightを別評価。初回件数、活動場数、利益損失収支、時価最大下落、1枚平均勝敗比、勝ち場数。完全ノートレードを有望にしない。',
        API取得数=0)
    path = HERE / '条件の事前固定.json'
    if path.exists():
        assert read(path) == value
    else:
        save(path, value)
    return value


def initialize() -> None:
    """機能: 保存32入力を集め、旧信号を同じ計算器で再生成する。

    引数: なし。返り値: なし(None)。
    """
    global INPUTS, FEATURES, MODELS
    integration.initialize()
    INPUTS = pickle.loads((V47 / 'inputs.pkl').read_bytes())
    FEATURES = pickle.loads((V47 / 'features_depth.pkl').read_bytes())
    for name in ('update_20260930', 'update_20261001'):
        folder = ROOT / 'work/wave_v48' / name
        more = pickle.loads((folder / 'new_inputs.pkl').read_bytes())
        assert not set(more) & set(INPUTS)
        INPUTS.update(more)
        FEATURES.update(pickle.loads((folder / 'new_features_depth.pkl').read_bytes()))
    assert len(INPUTS) == 32
    followup.INPUTS = INPUTS
    replay.INPUTS, replay.FEATURES = INPUTS, FEATURES
    replay.entry.set_root(ROOT)
    replay.mid.clear_cache()
    replay.MID = dict(entry=replay.entry.build(replay.entry.specification(), INPUTS, FEATURES))
    for code in ('B00', 'B01'):
        spec = next(s for s in replay.mid.catalog() if s['id'] == code)
        replay.MID[code] = replay.mid.build(spec, INPUTS, FEATURES)
    MODELS = {key: model(ready) for key, ready in INPUTS.items()}


def model(ready: dict) -> dict:
    """機能: 確定足から新規見送り用の因果指標を計算する。

    引数: ready(dict)。返り値: 公開時刻と指標(dict)。
    """
    bars = replay.entry.HIERARCHY.LEGACY._bars(ready)
    return model_from_bars(bars)


def model_from_bars(bars: dict) -> dict:
    """機能: 公開済み足を指標へ変換し、切断・反射監査でも同じ関数を使う。

    引数: bars(dict)。返り値: 公開時刻と指標(dict)。
    """
    stamps, close, atr = np.asarray(bars['time_s']), np.asarray(bars['close']), np.asarray(bars['atr'])
    fast = pd.Series(close).ewm(span=15, adjust=False, min_periods=15).mean()
    slow = pd.Series(close).ewm(span=60, adjust=False, min_periods=60).mean()
    result = dict(time_s=stamps, gap=(fast.to_numpy()-slow.to_numpy())/atr,
                  slow=slow.diff(3).to_numpy()/atr, fast=fast.diff(3).to_numpy()/atr)
    for window in (5, 15, 30):
        positions = np.searchsorted(stamps, stamps-window*60, side='right')-1
        old = np.full(len(close), np.nan)
        valid = positions >= 0
        old[valid] = close[positions[valid]]
        result[f'r{window}'] = (close-old)/atr
    return result


def expanded(key: tuple, models: dict, targets: np.ndarray) -> tuple[dict, dict]:
    """機能: 自銘柄と追加60秒遅延した相手銘柄を過去方向へ対応させる。

    引数: key(tuple)、models(dict)、targets(ndarray)。返り値: ownとpeer(tuple[dict,dict])。
    """
    outputs = []
    peer = key[0], 'NK225' if key[1] == 'TOPIX' else 'TOPIX'
    for selected, delay in ((key, 0), (peer, 60)):
        source = models[selected]
        positions = np.searchsorted(source['time_s']+delay, targets, side='right')-1
        output = dict(source_index=positions, release=np.full(len(targets), np.nan))
        valid = positions >= 0
        output['release'][valid] = source['time_s'][positions[valid]]+delay
        for field, values in source.items():
            if field == 'time_s':
                continue
            values = np.asarray(values)
            out = np.full(len(targets), np.nan)
            out[valid] = values[positions[valid]]
            output[field] = out
        assert np.all(output['release'][valid] <= targets[valid])
        outputs.append(output)
    return tuple(outputs)


def gate_mask(spec: dict, state: np.ndarray, own: dict, peer: dict) -> np.ndarray:
    """機能: 新規方向と公開指標だけで可否を決める。

    引数: spec(dict)、state(ndarray)、own/peer(dict)。返り値: 許可(ndarray[bool])。
    """
    kind = spec['kind']
    if kind == 'none':
        return np.ones(len(state), bool)
    if kind in ('opposed', 'against', 'strong'):
        a, b = own[f"r{spec['window']}"], peer[f"r{spec['window']}"]
        valid = np.isfinite(a) & np.isfinite(b)
        if kind == 'opposed':
            return valid & (a*b >= 0)
        if kind == 'against':
            return valid & (a*state >= 0) & (b*state >= 0)
        return valid & (a*state > spec['threshold']) & (b*state > spec['threshold'])
    if kind == 'rearm':
        return ((own['gap']*state > .15) & (peer['gap']*state > .15)
                & (own['slow']*state > .02) & (peer['slow']*state > .02))
    a, b = own[kind], peer[kind]
    if kind == 'slow':
        return np.isfinite(a) & np.isfinite(b) & (a*state >= 0) & (b*state >= 0)
    return np.isfinite(a) & np.isfinite(b) & (a*state > 0) & (b*state > 0)


def prior_ledgers(identifier: str) -> dict:
    """機能: 元四方式の全16場台帳を集める。

    引数: identifier(str)。返り値: キー別台帳(dict)。
    """
    records = []
    for folder in (V47/'exit_integration', V47/'integration_followup/new',
                   ROOT/'work/wave_v48/update_20260930', ROOT/'work/wave_v48/update_20261001'):
        records += read(folder/'ledgers'/(identifier+'.json.gz'))
    assert len(records) == 32
    return {(r['session'], r['symbol']): r for r in records}


def period(rows: list, series: dict, names: list, symbol: str) -> dict:
    """機能: 期間損益と取引頻度を固定会計器で集計する。

    引数: rows(list)、series(dict)、names(list)、symbol(str)。返り値: 統計(dict)。
    """
    output = followup.audit.statistics.period(rows, series, names, symbol, {'TOPIX':1000, 'NK225':10}[symbol])
    selected = [r for r in rows if r['session'] in names and r['symbol'] == symbol]
    output['active_sessions'] = sum(r.get('cycles', 0) > 0 for r in selected)
    output['initial_entries'] = sum(r.get('cycles', 0) for r in selected)
    return output


def evaluate(identifier: str, gate: dict, *, causal: bool) -> None:
    """機能: 一条件を全16場で注文単位から再生し保存する。

    引数: identifier(str)、gate(dict)、causal(bool)。返り値: なし(None)。
    """
    started = time.perf_counter()
    spec = next(s for s in followup.catalog('new') if s['id'] == identifier)
    old = prior_ledgers(identifier) if gate['id'] == 'G00' else None
    spec = deepcopy(spec)
    spec['id'] = identifier + '__' + gate['id']
    rows, ledgers, proofs, series = [], [], [], {}
    for key, ready in sorted(INPUTS.items()):
        columns, valid = replay.new_columns(spec, key)
        own, peer = expanded(key, MODELS, ready['time_s'])
        mask = gate_mask(gate, columns[0], own, peer)
        columns = (np.where(mask, columns[0], 0).astype(np.int8), *columns[1:])
        config = integration.config_for(spec, ready)
        for field in ('add_mode', 'hedge_ratio', 'reverse_mode', 'neutral_min', 'signal_exit', 'us_mode'):
            assert config[field] == 0, (field, config[field])
        row, ledger, proof, curve = followup.inspect_case(spec, key, columns, valid, causal and key[0] == NEW)
        # ----------------------------------------
        # 前行の成熟済み計画だけが入口許可の根拠。取消観測行を約定取消へ遡及しない。
        orders = np.asarray(ledger['orders'])
        initial = orders[(orders[:,7] == 1) & (orders[:,6] == 20)] if len(orders) else np.empty((0,8))
        for order in initial:
            fill, source, side = int(order[0]), int(order[1]), int(order[3])
            assert source < fill and columns[0][source] == side and mask[source]
        if old is not None:
            for field in ('result_fingerprints', 'shadow_fingerprints', 'scheduler_fingerprints'):
                assert ledger[field] == old[key][field], (identifier, key, field)
            proof['元全指紋一致'] = True
        proof.update(新規許可源全一致=True, 保有中state依存操作が無効=True,
                     非中立行数=int(np.count_nonzero(replay.MID['entry'][key])),
                     見送り行数=int(np.count_nonzero((replay.MID['entry'][key] != 0) & ~mask)))
        row['initial_entries'] = len(initial)
        row['active_session'] = bool(len(initial))
        rows.append(row); ledgers.append(ledger); proofs.append(proof); series[key] = curve
    names = sorted({k[0] for k in INPUTS})
    summary = dict(id=spec['id'], method=identifier, gate=gate, 全合格=True,
                   elapsed_seconds=time.perf_counter()-started, periods={})
    for label, sessions in (('旧15', [s for s in names if s != NEW]), ('問題Night', [NEW]), ('全16', names)):
        summary['periods'][label] = {}
        for symbol in ('TOPIX', 'NK225'):
            stats = period(rows, series, sessions, symbol)
            chosen = [r for r in rows if r['session'] in sessions and r['symbol'] == symbol]
            stats['initial_entries'] = sum(r['initial_entries'] for r in chosen)
            stats['active_sessions'] = sum(r['active_session'] for r in chosen)
            summary['periods'][label][symbol] = stats
    for folder, value, suffix in (('sessions', rows, '.json.gz'), ('ledgers', ledgers, '.json.gz'),
                                  ('audits', proofs, '.json.gz'), ('summaries', summary, '.json')):
        save(HERE/folder/(spec['id']+suffix), value)
    print(spec['id'] + ' 完了 ' + str(round(time.perf_counter()-started, 1))+'秒', flush=True)


def main() -> None:
    """機能: 指定方式の事前固定条件を全再生する。

    引数: コマンド行のmethod(str)、gates(str)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--method', default=IDS[0], choices=IDS)
    parser.add_argument('--gates', default='all')
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    freeze()
    if args.freeze:
        return
    initialize()
    chosen = catalog() if args.gates == 'all' else [g for g in catalog() if g['id'] in args.gates.split(',')]
    for gate in chosen:
        evaluate(args.method, gate, causal=True)


if __name__ == '__main__':
    main()
