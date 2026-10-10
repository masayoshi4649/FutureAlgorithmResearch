"""生板の途中打切り再抽出で、未来を除いた信号・建玉・清算価値を確認する。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

import catalog
import research
import signals

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
LIVE = OUT/'live'
_spec = importlib.util.spec_from_file_location('v11独立原本抽出', ROOT/'work/wave_v8/raw_features.py')
RAW = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = RAW
_spec.loader.exec_module(RAW)


def clean(value: object) -> object:
    """機能: 数値欠測を同一性比較できる形へ変換する。

    引数: value (object)。返り値: 欠測と配列を正規化した値 (object)。
    """
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    return None if isinstance(value, float) and not np.isfinite(value) else value


def selected_configs() -> list[dict]:
    """機能: 三思想の主条件と三脚・両建て返済の代表を選ぶ。

    引数: なし。返り値: 重複なしの監査対象設定 (list[dict])。
    """
    value = json.loads((OUT/'最終選択.json').read_text(encoding='utf-8'))
    selected = [row['採用']['方式'] for row in value['主選択'].values() if row['採用']]
    selected += [value['群別代表'][f'注文主導|{family}']['採用']['方式'] for family in ('O08', 'O09', 'O10')]
    mapping = {c['id']: c for c in catalog.configs()}
    return [mapping[key] for key in sorted(set(selected))]


def row_count(path: Path) -> int:
    """機能: 原本を書き換えずに総行数を数える。

    引数: path (Path)。返り値: 原本行数 (int)。
    """
    with path.open('rb') as stream:
        return sum(1 for _ in stream)


def liquidation_seq(ready: dict, rows: list[dict], seq: int) -> tuple[float, float]:
    """機能: 時刻ではなく原本行番号の境界で全脚を清算評価する。

    引数: ready (dict)、rows (list[dict])、seq (int)。返り値: 通常・倍費用の清算価値 (tuple[float,float])。
    同じCurrentPriceTimeでも境界の後続行は使わない。
    """
    index = int(np.searchsorted(ready['seq'], seq, side='right'))-1
    assert index >= 0 and ready['seq'][index] == seq
    ordinary = stressed = 0.
    tick, multiplier = ready['tick'], research.single.MULTIPLIERS[ready['symbol']]
    for row in rows:
        if row['entry_seq'] > seq:
            continue
        if row['closed'] and row['exit_seq'] <= seq:
            ordinary += row['net_points']*multiplier
            stressed += row['stress_points']*multiplier
        else:
            mark = ready['bid'][index] if row['side'] > 0 else ready['ask'][index]
            points = row['side']*(mark-row['entry_price'])-2*tick
            ordinary += points*multiplier
            stressed += (points-2*tick)*multiplier
    return ordinary, stressed


def check_cut(item: dict, path: Path, session: str, symbol: str, cut: int,
              conditions: list[dict]) -> dict:
    """機能: 原本を指定行で止め再抽出し、確定済み過去と末尾清算価値を照合する。

    引数: item (dict)、path (Path)、session/symbol (str)、cut (int)、conditions (list[dict])。
    返り値: 信号・状態・各方式の一致記録 (dict)。
    """
    quotes = []
    features, audit = RAW.extract_features(path, symbol, session, max_rows=cut, quotes=quotes)
    features = pd.read_csv(io.StringIO(features.to_csv(index=False)))
    frame = pd.DataFrame(quotes)
    tape = {column: frame[column].to_numpy() for column in frame}
    cutoff, last_seq = float(tape['time_s'][-1]), int(tape['seq'][-1])
    tape['atr'] = signals.atr_at(session, symbol, tape['time_s'], cutoff=cutoff)
    peer = item['peer_features'].loc[item['peer_features'].time_s+60 <= cutoff]
    events, _ = signals.build_events(session, symbol, features, peer, cutoff=cutoff)
    expected_events = item['events'].loc[item['events'].seq <= last_seq]
    assert clean(events.to_dict('records')) == clean(expected_events.to_dict('records')), (session, symbol, cut, '信号')
    z = signals.price_grid(session, symbol, cutoff)
    state = signals.state_at(tape, features, z)
    full_mask = item['tape']['seq'] <= last_seq
    assert np.array_equal(tape['seq'], item['tape']['seq'][full_mask])
    for key in ('time_s', 'bid', 'ask', 'bid_qty', 'ask_qty', 'atr'):
        assert np.allclose(tape[key], item['tape'][key][full_mask], equal_nan=True), (session, symbol, cut, key)
    for key, value in state.items():
        assert np.allclose(value, item['state'][key][full_mask], equal_nan=True), (session, symbol, cut, key)
    full = research.prepared_inputs({(session, symbol): item})[(session, symbol)]
    short = research.single.prepare(tape, events, session, symbol, state)
    results = []
    for config in conditions:
        full_row, full_raw, _ = research.run_one(full, config)
        full_trades = research.trade_records(full, config, full_raw)
        short_row, short_raw, curve = research.run_one(short, config)
        short_trades = research.trade_records(short, config, short_raw)
        observed = [row for row in short_trades if row['closed']]
        expected = [row for row in full_trades if row['closed'] and row['exit_seq'] <= last_seq]
        assert clean(observed) == clean(expected), (session, symbol, cut, config['id'], '確定売買')
        value, stress = liquidation_seq(full, full_trades, last_seq)
        assert np.isclose(value, curve[-1, 2]), (session, symbol, cut, config['id'], '清算価値')
        assert np.isclose(stress, curve[-1, 3]), (session, symbol, cut, config['id'], '倍費用清算価値')
        results.append(dict(方式=config['id'], 確定取引数=len(observed), 属性数=sum(len(row) for row in observed),
                            未返済数=short_row['未返済数'], 清算価値円=value, 全属性一致=True, 清算価値一致=True))
    return dict(セッション=session, 銘柄=symbol, 原本打切り行数=cut, 最終有効行=last_seq,
                打切り時刻=pd.Timestamp(cutoff, unit='s', tz='Asia/Tokyo').isoformat(),
                気配行数=len(tape['seq']), 信号数=len(events), 系統数=len(signals.profiles()),
                信号一致=True, 気配一致=True, 状態一致=True, 確定売買=results)


def historical() -> dict:
    """機能: 日中・夜間の原本２組を各３行境界で切断し再計算する。

    引数: なし。返り値: 完了監査 (dict)。
    """
    sessions = ['2026-09-22_Day', '2026-09-22_Night']
    inputs, configs = signals.load_inputs(sessions), selected_configs()
    results = []
    for (session, symbol), item in inputs.items():
        path = ROOT/'book'/symbol/f'{session}.jsonl'
        total = row_count(path)
        for fraction in (.3137, .6137, .9137):
            results.append(check_cut(item, path, session, symbol, int(total*fraction), configs))
        print(f'原本打切り３箇所が一致: {session} {symbol}', flush=True)
    value = dict(API要求数=0, 条件=[c['id'] for c in configs], 原本打切り回数=len(results),
                 信号系統数=len(signals.profiles()), 確定取引延べ照合数=sum(r['確定取引数'] for v in results for r in v['確定売買']),
                 確定属性延べ照合数=sum(r['属性数'] for v in results for r in v['確定売買']), 全件一致=True, 検査=results,
                 限界='延べ数は独立した取引機会数ではない。保存順の因果性であり、実受信時計・本番約定を保証しない。')
    research.save(OUT/'原本打切り監査.json', value)
    return value


def byte_prefix(old_path: Path, new_path: Path) -> dict:
    """機能: 旧原本が新原本の完全な先頭バイト列であることを検査する。

    引数: old_path/new_path (Path)。返り値: 一致長と終端同時刻の追加状況 (dict)。
    """
    digest = hashlib.sha256()
    with old_path.open('rb') as old, new_path.open('rb') as new:
        while block := old.read(1024*1024):
            digest.update(block)
            assert new.read(len(block)) == block, (old_path, 'バイト先頭不一致')
    old_lines = row_count(old_path)
    last = None
    with old_path.open(encoding='utf-8-sig') as old:
        for line in old:
            if line.strip():
                last = json.loads(line)
    trailing = 0
    with new_path.open(encoding='utf-8-sig') as new:
        for i, line in enumerate(new):
            if i < old_lines or not line.strip():
                continue
            row = json.loads(line)
            if row.get('CurrentPriceTime') == last.get('CurrentPriceTime'):
                trailing += 1
            else:
                break
    return dict(旧原本が完全な先頭バイト列=True, 旧原本バイト数=old_path.stat().st_size,
                旧原本行数=old_lines, 旧原本SHA256=digest.hexdigest(),
                旧末尾CurrentPriceTime=last.get('CurrentPriceTime'), 旧末尾と同じ時刻の追加行数=trailing)


def live() -> dict:
    """機能: 取得済み原本の中間切断と旧原本の継続性を通信せず確認する。

    引数: なし。返り値: 追加照合の原本監査 (dict)。
    """
    record = json.loads((LIVE/'取得記録.json').read_text(encoding='utf-8'))
    assert record['status'] == '取得と検査完了'
    frozen = json.loads((OUT/'現在照合_凍結記録.json').read_text(encoding='utf-8'))
    session = frozen['session']
    old_inputs = signals.load_inputs([session])
    configs = selected_configs()
    old_candle, old_feature = dict(signals.CANDLE_OVERRIDES), dict(signals.FEATURE_OVERRIDES)
    records, boundary_rows = [], []
    try:
        signals.CANDLE_OVERRIDES[session], signals.FEATURE_OVERRIDES[session] = LIVE, LIVE/'features'
        inputs = signals.load_inputs([session])
        middle = (pd.Timestamp(frozen['known_cutoff']).timestamp()+pd.Timestamp(record['cutoff']).timestamp())/2
        for (session, symbol), item in inputs.items():
            path = LIVE/'book'/symbol/f'{session}.jsonl'
            old_path = ROOT/'work/wave_v10/live/book'/symbol/f'{session}.jsonl'
            prefix = byte_prefix(old_path, path)
            cut = 0
            with path.open(encoding='utf-8-sig') as stream:
                for line in stream:
                    stamp = json.loads(line).get('CurrentPriceTime')
                    if stamp and pd.Timestamp(stamp).timestamp() >= middle:
                        break
                    cut += 1
            result = check_cut(item, path, session, symbol, cut, configs)

            # ----------------------------------------
            # 旧保存末尾までの確定売買と、旧末尾同時刻の追加観測の影響を区別する。
            old_item = old_inputs[(session, symbol)]
            old_ready = research.prepared_inputs({(session, symbol): old_item})[(session, symbol)]
            new_ready = research.prepared_inputs({(session, symbol): item})[(session, symbol)]
            old_last_seq = int(old_item['tape']['seq'][-1])
            old_changes = []
            mapping = {c['id']: c for c in catalog.configs()}
            for key in frozen['selected_ids']:
                config = mapping[key]
                _, old_raw, _ = research.run_one(old_ready, config)
                _, new_raw, _ = research.run_one(new_ready, config)
                old_rows = research.trade_records(old_ready, config, old_raw)
                new_rows = research.trade_records(new_ready, config, new_raw)
                confirmed = [row for row in old_rows if row['closed']]
                same_boundary = [row for row in new_rows if row['closed'] and row['exit_seq'] <= old_last_seq]
                assert clean(confirmed) == clean(same_boundary), (symbol, key, '既知確定売買')
                before = liquidation_seq(new_ready, new_rows, old_last_seq)
                after_old = liquidation_seq(old_ready, old_rows, old_last_seq)
                assert np.allclose(before, after_old), (symbol, key, '同一原本境界評価')
                boundary_time = pd.Timestamp(frozen['known_cutoff']).timestamp()
                proxy_index = int(np.searchsorted(new_ready['time_s'], boundary_time, side='left'))-1
                proxy_seq = int(new_ready['seq'][proxy_index])
                proxy_value = liquidation_seq(new_ready, new_rows, proxy_seq)
                final_value = liquidation_seq(new_ready, new_rows, int(new_ready['seq'][-1]))
                boundary_rows.append(dict(方式=key, 銘柄=symbol, セッション=session,
                                          旧保存最終行=old_last_seq, 時計境界最終行=proxy_seq,
                                          旧保存行境界清算価値円=before[0], 時計境界清算価値円=proxy_value[0],
                                          同時刻追加行の評価差円=proxy_value[0]-before[0],
                                          旧保存行からの全追加円=final_value[0]-before[0],
                                          時計境界からの追加円=final_value[0]-proxy_value[0],
                                          費用倍同時刻追加行の評価差円=proxy_value[1]-before[1],
                                          費用倍旧保存行からの全追加円=final_value[1]-before[1]))
                more_rows = [row for row in new_rows if row['closed'] and row['exit_seq'] > old_last_seq and row['exit_time_s'] < boundary_time]
                old_changes.append(dict(方式=key, 旧確定取引数=len(confirmed), 既知確定売買一致=True,
                                         同一原本境界清算一致=True, 追加された既知時計内返済数=len(more_rows)))
            records.append(dict(銘柄=symbol, 原本継続性=prefix, 中間原本切断=result, 既知区間照合=old_changes))
            print(f'追加原本の切断・旧バイト列・既知取引が一致: {symbol}', flush=True)
    finally:
        signals.CANDLE_OVERRIDES.clear()
        signals.CANDLE_OVERRIDES.update(old_candle)
        signals.FEATURE_OVERRIDES.clear()
        signals.FEATURE_OVERRIDES.update(old_feature)
    result = dict(API要求数=0, 全件一致=True, 検査=records,
                  終端の説明='同じCurrentPriceTimeの板更新が旧保存末尾の後に続く場合、時計が既知境界より前でも追加行は旧保存時点では未観測。旧原本行境界までの確定売買と清算価値を比較し、時計境界内の追加行による返済は別計数する。')
    research.save(OUT/'現在照合_原本打切り監査.json', result)
    pd.DataFrame(boundary_rows).to_csv(OUT/'現在照合_旧保存行境界の補足.csv', index=False, encoding='utf-8-sig')
    return result


def main() -> None:
    """機能: 過去原本または今回取得済み原本の監査を実行する。

    引数: CLI --live (bool)。返り値: なし (None)。ネットワーク要求なし。
    """
    parser = argparse.ArgumentParser(description='原本打切り監査・通信なし')
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    tracked = [Path(module.__file__) for module in (signals, research, research.single, research.orders, catalog, RAW)]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
    result = live() if args.live else historical()
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
    result.update(実装SHA256={str(Path(name).relative_to(ROOT)): value for name, value in before.items()},
                  監査中コード変更なし=True)
    research.save(OUT/('現在照合_原本打切り監査.json' if args.live else '原本打切り監査.json'), result)
    print(json.dumps(dict(全件一致=result['全件一致'], API要求数=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
