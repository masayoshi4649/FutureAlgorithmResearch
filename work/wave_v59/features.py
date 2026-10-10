"""場内の中値確定足と単純移動平均を、次の実観測行で公開する。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SETTINGS = (
    {'id': 'M1_3_10', 'seconds': 60, 'short': 3, 'long': 10},
    {'id': 'M1_5_20', 'seconds': 60, 'short': 5, 'long': 20},
    {'id': 'M1_10_40', 'seconds': 60, 'short': 10, 'long': 40},
    {'id': 'M5_3_10', 'seconds': 300, 'short': 3, 'long': 10},
)
INPUT_KEYS = ('time_s', 'seq', 'last', 'start', 'limit', 'symbol', 'session', 'tick')
QUOTE_KEYS = ('time_s', 'seq', 'bid', 'ask', 'mid')
NEW_SESSIONS = ('2026-10-06_Night', '2026-10-07_Day')


def load_inputs() -> tuple[dict, dict]:
    """機能: 旧23場の価格入力と気配だけを読み、原本行単位で一致を確認する。

    引数: なし。
    返り値: 場・銘柄をキーにした価格辞書と気配辞書(tuple[dict,dict])。
    売買結果、旧指標、板数量、補充特徴は参照しない。
    """
    inputs = pickle.loads((ROOT / 'work/wave_v55/clean_inputs.pkl').read_bytes())
    quotes = pickle.loads((ROOT / 'work/wave_v57/features.pkl').read_bytes())
    inputs = {key: {name: value[name] for name in INPUT_KEYS} for key, value in inputs.items()}
    quotes = {key: {name: value[name] for name in QUOTE_KEYS} for key, value in quotes.items()}
    assert len(inputs) == 46 and len(set(key[0] for key in inputs)) == 23
    assert set(inputs) == set(quotes)
    for key in inputs:
        verify_input(inputs[key], quotes[key])
    return inputs, quotes


def verify_input(ready: dict, quotes: dict) -> None:
    """機能: 同一原本行の時計・気配・中値と、単調な観測順を検査する。

    引数: ready(dict) は価格入力、quotes(dict) は許可した気配配列。
    返り値: なし(None)。不一致は例外とし、暗黙の補正は行わない。
    """
    assert np.array_equal(ready['seq'], quotes['seq'])
    assert np.array_equal(ready['time_s'], quotes['time_s'])
    assert len(ready['seq']) > 0 and np.all(np.diff(ready['seq']) > 0)
    assert np.all(np.diff(ready['time_s']) >= 0)
    assert np.isfinite(quotes['bid']).all() and np.isfinite(quotes['ask']).all()
    assert (quotes['bid'] > 0).all() and (quotes['ask'] > quotes['bid']).all()
    assert np.array_equal(quotes['mid'], (quotes['bid'] + quotes['ask']) / 2.)


def build_features(ready: dict, quotes: dict, setting: dict) -> pd.DataFrame:
    """機能: 空白足を明示した等間隔確定足から移動平均を作る。

    引数: ready(dict)、quotes(dict)、setting(dict) は足幅と短長期間。
    返り値: 実観測バケット切替の初行だけを持つ公開特徴表(pd.DataFrame)。
    空白足の値は直前終値据置。観測有無は別管理し、末尾未完了足は使用しない。
    """
    verify_input(ready, quotes)
    seconds, short, long = setting['seconds'], setting['short'], setting['long']
    times, seq = np.asarray(ready['time_s']), np.asarray(ready['seq'])
    buckets = np.floor(times / seconds).astype(np.int64)
    starts = np.r_[0, np.flatnonzero(np.diff(buckets)) + 1]
    end_index = np.r_[starts[1:] - 1, len(seq) - 1]
    grid = np.arange(int(np.floor(ready['start'] / seconds)), buckets[-1], dtype=np.int64)
    bars = pd.DataFrame(index=grid)
    actual = pd.DataFrame({
        'close': quotes['mid'][end_index], 'source_last_time': times[end_index],
        'source_last_seq': seq[end_index], 'source_count': end_index - starts + 1,
        'high': np.maximum.reduceat(quotes['mid'], starts),
        'low': np.minimum.reduceat(quotes['mid'], starts),
    }, index=buckets[starts])
    bars = bars.join(actual)
    bars['observed'] = bars['close'].notna()
    bars['source_count'] = bars['source_count'].fillna(0).astype(np.int64)
    for name in ('close', 'source_last_time', 'source_last_seq'):
        bars[name] = bars[name].ffill().astype(np.float64)
    for name in ('high', 'low'):
        bars[name] = bars[name].fillna(bars['close'])
    bars['sma_short'] = bars['close'].rolling(short, min_periods=short).mean()
    bars['sma_long'] = bars['close'].rolling(long, min_periods=long).mean()
    bars['std_long'] = bars['close'].rolling(long, min_periods=long).std(ddof=0)
    bars['prior_box_high'] = bars['high'].shift(1).rolling(long, min_periods=long).max()
    bars['prior_box_low'] = bars['low'].shift(1).rolling(long, min_periods=long).min()
    changes = bars['close'].diff().abs().rolling(long, min_periods=long).sum()
    displacement = (bars['close'] - bars['close'].shift(long)).abs()
    bars['er'] = (displacement / changes).where(changes.ne(0), 0.)
    bars['prior_move'] = bars['close'].shift(1) - bars['close'].shift(short + 1)
    bars['gap'] = bars['sma_short'] - bars['sma_long']
    bars['observed_count_long'] = bars['observed'].rolling(long, min_periods=long).sum()
    bars['observed_fraction_long'] = bars['observed_count_long'] / long
    bars['prior_box_observed_count'] = bars['observed'].shift(1).rolling(long, min_periods=long).sum()
    bars['prior_box_observed_fraction'] = bars['prior_box_observed_count'] / long
    bars['prior_move_start_observed'] = bars['observed'].shift(short + 1)
    for lag in (1, 2, 3):
        for name in ('close', 'sma_short', 'sma_long', 'gap', 'observed', 'std_long'):
            bars[f'{name}_lag{lag}'] = bars[name].shift(lag)

    # ----------------------------------------
    # 途中の空白足を同じ公開行で何度も判定せず、最新の完了足だけを公開する。
    published = starts[1:]
    previous_buckets = buckets[published] - 1
    frame = bars.reindex(previous_buckets).reset_index(names='source_bucket')
    frame['source_bar_start'] = previous_buckets * seconds
    frame['bar_start'] = frame['source_bar_start']
    frame['bar_end'] = frame['source_bar_start'] + seconds
    frame['ready_index'] = published
    frame['time_s'], frame['seq'] = times[published], seq[published]
    for name in ('bid', 'ask', 'mid'):
        frame[name] = quotes[name][published]
    frame['last'] = ready['last'][published]
    frame['session_open'] = float(ready['last'][0])
    frame['session_open_mid'] = float(quotes['mid'][0])
    frame['elapsed_s'] = frame['time_s'] - ready['start']
    frame['bar_age'] = frame['time_s'] - frame['source_last_time']
    frame['publication_delay'] = frame['time_s'] - frame['bar_end']
    frame['bar_seconds'] = seconds
    frame['short_period'], frame['long_period'] = short, long
    frame['latest_two_observed'] = frame['observed'].eq(True) & frame['observed_lag1'].eq(True)
    frame['latest_three_observed'] = frame['latest_two_observed'] & frame['observed_lag2'].eq(True)
    frame['can_trade'] = (
        frame['elapsed_s'].ge((long + 3) * seconds)
        & frame['observed_fraction_long'].ge(.8)
        & frame['latest_two_observed']
        & frame['bar_age'].between(0, seconds)
        & frame['publication_delay'].between(0, seconds)
        & frame[['sma_short', 'sma_long', 'sma_short_lag1', 'sma_long_lag1',
                  'sma_short_lag2', 'sma_long_lag2', 'sma_long_lag3',
                  'prior_box_high', 'prior_box_low', 'er', 'prior_move']].notna().all(axis=1)
    )
    assert (frame['source_last_seq'] < frame['seq']).all()
    assert (frame['source_last_time'] < frame['time_s']).all()
    assert (frame['bar_end'] <= frame['time_s']).all()
    return frame


def cut_inputs(ready: dict, quotes: dict, size: int) -> tuple[dict, dict]:
    """機能: 原本有効行の後半を除去し、途中時点までの入力を作る。

    引数: ready(dict)、quotes(dict)、size(int) は残す原本有効行数。
    返り値: 切断した価格入力と気配配列(tuple[dict,dict])。
    """
    partial = dict(ready)
    for name in ('seq', 'time_s', 'last'):
        partial[name] = ready[name][:size]
    return partial, {name: value[:size] for name, value in quotes.items()}


def audit_prefix(ready: dict, quotes: dict, setting: dict, frame: pd.DataFrame) -> dict:
    """機能: 入力切断と未来中値の改変で、既公開特徴が変わらないことを検査する。

    引数: ready(dict)、quotes(dict)、setting(dict)、frame(pd.DataFrame)。
    返り値: 検査数・準備可能行数を持つ証跡(dict)。利益は計算しない。
    """
    checks = []
    for size in sorted(set((1, max(1, len(ready['seq']) // 3), max(1, len(ready['seq']) * 3 // 4)))):
        partial, quote_part = cut_inputs(ready, quotes, size)
        actual = build_features(partial, quote_part, setting)
        expected = frame[frame['ready_index'] < size].reset_index(drop=True)
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        mutated = {name: value.copy() for name, value in quotes.items()}
        for name in ('bid', 'ask', 'mid'):
            mutated[name][size:] += 1234 * float(ready['tick'])
        full = build_features(ready, mutated, setting)
        pd.testing.assert_frame_equal(full[full['ready_index'] < size].reset_index(drop=True), expected, check_exact=True)
        checks.append({'入力行数': size, '公開行数': len(actual), '切断一致': True, '未来改変一致': True})
    valid = frame[frame['can_trade']]
    return {'設定': setting['id'], '公開行数': len(frame), '新規可能行数': len(valid),
            '初回新規可能経過秒': None if valid.empty else float(valid.iloc[0]['elapsed_s']), '因果検査': checks}


def sha256(path: Path) -> str:
    """機能: 指定した旧原本の内容ハッシュを計算する。

    引数: path(Path) は読取専用原本。
    返り値: SHA256文字列(str)。新しい2場は呼び出さない。
    """
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def check_inventory(keys: set[tuple]) -> dict:
    """機能: 旧46原本だけの SHA を照合し、追加場はファイル名だけ記録する。

    引数: keys(set[tuple]) は事前固定の旧口座キー。
    返り値: 一致記録と未読の追加ファイル名(dict)。追加原本の内容は開かない。
    """
    baseline = json.loads((ROOT / 'work/wave_v57/特徴監査.json').read_text(encoding='utf-8'))
    expected = {(row['セッション'], row['銘柄']): row['原本SHA256'] for row in baseline['原本別']}
    paths = {key: ROOT / 'book' / key[1] / f'{key[0]}.jsonl' for key in sorted(keys)}
    with ThreadPoolExecutor(max_workers=4) as pool:
        hashes = dict(zip(paths, pool.map(sha256, paths.values())))
    assert all(hashes[key] == expected[key] for key in keys)
    inventory = {(p.stem, p.parent.name) for p in (ROOT / 'book').glob('*/*.jsonl')}
    return {'旧原本数': len(keys), '旧原本SHA全一致': True,
            '旧原本': [{'セッション': key[0], '銘柄': key[1], 'SHA256': value} for key, value in hashes.items()],
            '追加未読原本': [{'セッション': key[0], '銘柄': key[1]} for key in sorted(inventory - keys)],
            '追加原本の内容読取数': 0}


def read_raw_input(key: tuple[str, str]) -> tuple[dict, dict, dict]:
    """機能: 指定した一原本から、旧入力と同じ最良気配有効条件で価格だけを抽出する。

    引数: key(tuple[str,str]) はセッションと銘柄。
    返り値: 価格入力・気配配列・読取監査(tuple[dict,dict,dict])。
    追加2場に対しては親からの実行通知後だけ呼び出す。板数量は有効性判定のみに使う。
    """
    session, symbol = key
    date_text, kind = session.rsplit('_', 1)
    day = datetime.fromisoformat(date_text).replace(tzinfo=timezone(timedelta(hours=9)))
    if kind == 'Day':
        start, end = day + timedelta(hours=8, minutes=45), day + timedelta(hours=15, minutes=40)
    elif kind == 'Night':
        start, end = day + timedelta(hours=17), day + timedelta(days=1, hours=5, minutes=55)
    else:
        raise ValueError(f'未知のセッション種別: {session}')
    path = ROOT / 'book' / symbol / f'{session}.jsonl'
    tick = {'TOPIX': .5, 'NK225': 10.}[symbol]
    rows, previous_time, digest, raw_count, missing, outside, invalid = [], None, hashlib.sha256(), 0, 0, 0, 0
    with path.open('rb') as stream:
        for seq, line in enumerate(stream):
            raw_count += 1
            digest.update(line)
            raw = json.loads(line)
            text = raw.get('CurrentPriceTime')
            if not text:
                missing += 1
                continue
            stamp = datetime.fromisoformat(text)
            if stamp.tzinfo is None:
                raise ValueError(f'タイムゾーンなし: {path}:{seq + 1}')
            if previous_time is not None and stamp < previous_time:
                raise ValueError(f'約定時計逆行: {path}:{seq + 1}')
            previous_time = stamp
            if not start <= stamp < end:
                outside += 1
                continue
            try:
                bid, ask = float(raw['Buy1']['Price']), float(raw['Sell1']['Price'])
                bid_qty, ask_qty = float(raw['Buy1']['Qty']), float(raw['Sell1']['Qty'])
                last = float(raw['CurrentPrice'])
            except (KeyError, TypeError, ValueError):
                invalid += 1
                continue
            if not all(np.isfinite(x) for x in (bid, ask, bid_qty, ask_qty)) or not (0 < bid < ask and bid_qty > 0 and ask_qty > 0):
                invalid += 1
                continue
            assert np.isfinite(last) and last > 0, (key, seq, '最終価格不正')
            rows.append((seq, stamp.timestamp(), last, bid, ask))
    values = np.asarray(rows, dtype=float).reshape(-1, 5)
    ready = dict(seq=values[:, 0].astype(np.int64), time_s=values[:, 1], last=values[:, 2],
                 start=start.timestamp(), limit=(end - timedelta(minutes=5)).timestamp(),
                 symbol=symbol, session=session, tick=tick)
    quotes = dict(seq=ready['seq'].copy(), time_s=ready['time_s'].copy(),
                  bid=values[:, 3], ask=values[:, 4], mid=(values[:, 3] + values[:, 4]) / 2.)
    verify_input(ready, quotes)
    audit = {'セッション': session, '銘柄': symbol, '原本SHA256': digest.hexdigest(),
             '原本行数': raw_count, '有効入力行数': len(values), '時刻欠測行数': missing,
             '対象外時間行数': outside, '最良気配不正行数': invalid,
             '最初の原本時計': float(ready['time_s'][0]), '最後の原本時計': float(ready['time_s'][-1])}
    return ready, quotes, audit


def read_new_inputs(authorized: bool = False) -> None:
    """機能: 親の実行通知後に限り、新2場を一度抽出し同じ特徴コードを適用する。

    引数: authorized(bool) は旧23場の集計完了と親の明示通知を受けた呼出側の指定。
    返り値: なし(None)。既存の holdout 出力があれば再読取を拒否する。
    """
    if not authorized:
        raise RuntimeError('旧23場集計完了と親の実行通知が必要です。追加原本は未読のままです。')
    destination = HERE / 'holdout'
    if (destination / 'inputs.pkl').exists():
        raise RuntimeError('確認用の入力は既に抽出済みです。原本を再読取しません。')
    inputs, quotes, features, audits, feature_audits = {}, {}, {}, [], []
    for session in NEW_SESSIONS:
        for symbol in ('TOPIX', 'NK225'):
            key = session, symbol
            ready, quote, audit = read_raw_input(key)
            inputs[key], quotes[key], features[key] = ready, quote, {}
            audits.append(audit)
            for setting in SETTINGS:
                frame = build_features(ready, quote, setting)
                features[key][setting['id']] = frame
                feature_audits.append({'セッション': session, '銘柄': symbol,
                                       **audit_prefix(ready, quote, setting, frame)})
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in (('inputs.pkl', inputs), ('quotes.pkl', quotes), ('features.pkl', features)):
        (destination / name).write_bytes(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
    evidence = {'合格': True, '親の実行通知後': True, '条件変更なし': True,
                '新2場の原本監査': audits, '新2場の特徴監査': feature_audits,
                'コードSHA256': sha256(Path(__file__))}
    (destination / '未読2場の入力抽出監査.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')


def main() -> None:
    """機能: 旧23場の4期間設定を生成し、公開順・因果性・原本一致を保存する。

    引数: なし。
    返り値: なし(None)。売買結果と追加2場の内容は読まない。
    """
    inputs, quotes = load_inputs()
    features, audits = {}, []
    for key, ready in inputs.items():
        features[key] = {}
        for setting in SETTINGS:
            frame = build_features(ready, quotes[key], setting)
            features[key][setting['id']] = frame
            audits.append({'セッション': key[0], '銘柄': key[1], **audit_prefix(ready, quotes[key], setting, frame)})
    inventory = check_inventory(set(inputs))
    (HERE / 'inputs.pkl').write_bytes(pickle.dumps(inputs, protocol=pickle.HIGHEST_PROTOCOL))
    (HERE / 'quotes.pkl').write_bytes(pickle.dumps(quotes, protocol=pickle.HIGHEST_PROTOCOL))
    (HERE / 'features.pkl').write_bytes(pickle.dumps(features, protocol=pickle.HIGHEST_PROTOCOL))
    (HERE / '原本照合と未読追加場.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
    evidence = {'合格': True, '口座数': len(features), '場数': 23, '設定数': len(SETTINGS),
                '特徴設定別監査': audits, '損益参照': False, '将来収益特徴': False, 'ATR使用': False,
                '公開': '次の実観測バケットの初原本行。空白をまたぐ場合も最新の完了足1行だけ公開。',
                '空白足': '直前の中値終値据置。実観測flagは偽のまま。',
                '新規準備': '場開始から(long+3)足分以上、long窓80%以上実観測、最新と前足実観測、元終値年齢<=1足幅。',
                '設定': SETTINGS, 'コードSHA256': sha256(Path(__file__))}
    (HERE / '特徴仕様と監査.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'合格': True, '口座数': len(features), '設定別数': len(audits), '追加原本未読数': len(inventory['追加未読原本'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
