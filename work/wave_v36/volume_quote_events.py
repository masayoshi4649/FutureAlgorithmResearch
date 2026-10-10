"""既知原本だけから、正の出来高増分とその時点の最良気配を価格別に保存する。"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LEGACY_PATH = ROOT / 'work/wave_v8/raw_features.py'
module_spec = importlib.util.spec_from_file_location('v36_raw_parser', LEGACY_PATH)
legacy = importlib.util.module_from_spec(module_spec)
sys.modules[module_spec.name] = legacy
module_spec.loader.exec_module(legacy)
FEATURES = ROOT / 'work/wave_v23/features_depth.pkl'
INPUTS = ROOT / 'work/wave_v23/inputs.pkl'
FLOAT_COLUMNS = ('prev_time_s', 'current_time_s', 'prev_volume_time_s', 'current_volume_time_s',
    'release_time_s', 'current_price', 'prev_price', 'bid', 'ask', 'bid_qty', 'ask_qty',
    'prev_bid', 'prev_ask', 'prev_bid_qty', 'prev_ask_qty', 'prev_volume', 'current_volume',
    'volume_delta', 'side_qty', 'volume_to_side_qty')
INT_COLUMNS = ('prev_seq', 'current_seq', 'release_seq', 'source_first_seq', 'source_last_seq', 'feature_row', 'side')
COLUMNS = [*INT_COLUMNS, *FLOAT_COLUMNS, 'stable']


def digest(path: Path) -> str:
    """機能: 原本又は成果をストリーム読取りしSHA256を求める。

    引数: path (Path)。返り値: 指紋 (str)。ファイルを書き換えない。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def save(path: Path, value: dict) -> None:
    """機能: 非有限値を拒否して日本語の監査JSONを保存する。

    引数: path (Path)、value (dict)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def read_json(path: Path) -> dict:
    """機能: UTF-8の固定資料を読み込む。

    引数: path (Path)。返り値: 内容 (dict)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def finite(value) -> float | None:
    """機能: 欠損や非有限値を0へ置換せず識別する。

    引数: value (object)。返り値: 有限値又はNone (float|None)。
    """
    try:
        result = float(value)
        return result if np.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def stamp(value) -> float | None:
    """機能: タイムゾーン付き公開時刻だけを秒へ変換する。

    引数: value (object)。返り値: 時刻秒又はNone (float|None)。
    """
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def table(records: list[dict]) -> pd.DataFrame:
    """機能: 空集合も同じ型の価格別イベント表へ整える。

    引数: records (list[dict])。返り値: 全固定列を持つ表 (DataFrame)。
    """
    result = pd.DataFrame.from_records(records, columns=COLUMNS)
    for column in INT_COLUMNS:
        result[column] = result[column].astype(np.int64)
    for column in FLOAT_COLUMNS:
        result[column] = result[column].astype(np.float64)
    result['stable'] = result.stable.astype(bool)
    return result


def extract(rows, frame: pd.DataFrame, session: str, max_rows: int | None = None,
            future_from: int | None = None) -> tuple[pd.DataFrame, dict]:
    """機能: 原本順の隣接行だけで出来高差を作り、既存特徴の解放前には使用しない。

    引数: rows (iterable[bytes|dict])、frame (DataFrame)、session (str)、
    max_rows (int|None) は排他的読取上限、future_from (int|None) は因果検査専用改変開始行。
    返り値: イベント表と除外理由別監査 (tuple[DataFrame,dict])。
    時刻又は累積量の逆行行を捨て履歴を解除する。次の有効行から差分を再準備する。
    """
    needed = ['source_first_seq', 'source_last_seq', 'seq', 'time_s', 'source_time_s']
    assert all(name in frame for name in needed)
    first = frame.source_first_seq.to_numpy(np.int64)
    last = frame.source_last_seq.to_numpy(np.int64)
    release = frame.seq.to_numpy(np.int64)
    release_time = frame.time_s.to_numpy(float)
    material_time = frame.source_time_s.to_numpy(float)
    assert np.all(first <= last) and np.all(last < release)
    assert np.all(first[1:] > last[:-1]) and np.all(np.diff(release) > 0)
    assert np.all(np.isfinite(release_time)) and np.all(material_time < release_time)
    start, end = (value.timestamp() for value in legacy.session_bounds(session))
    audit = Counter()
    previous = None
    last_time = last_volume_time = None
    index = 0
    records = []
    for seq, source in enumerate(rows):
        if max_rows is not None and seq >= max_rows:
            break
        audit['読取原本行数'] += 1
        raw = dict(source) if isinstance(source, dict) else json.loads(source)
        if future_from is not None and seq >= future_from:
            raw = dict(raw)
            raw['CurrentPrice'] = 999999.
            raw['TradingVolume'] = 9000000. + seq
            raw['Buy1'] = dict(Price=999990., Qty=999.)
            raw['Sell1'] = dict(Price=1000010., Qty=777.)
            # 未来の時刻・価格・板・出来高を同時に変え、過去の表が変わらないことを調べる。
            raw['CurrentPriceTime'] = '2099-01-01T00:00:00+09:00'
            raw['TradingVolumeTime'] = '2099-01-01T00:00:00+09:00'
        time_s, volume_time = stamp(raw.get('CurrentPriceTime')), stamp(raw.get('TradingVolumeTime'))
        if time_s is None or volume_time is None:
            audit['時刻欠損又は不正行数'] += 1
            previous = None
            continue
        reverse = ((last_time is not None and time_s < last_time)
                   or (last_volume_time is not None and volume_time < last_volume_time))
        last_time, last_volume_time = time_s, volume_time
        if reverse:
            audit['価格又は出来高時刻逆行行数'] += 1
            previous = None
            continue
        if not start <= time_s < end:
            audit['場外行数'] += 1
            previous = None
            continue
        current, reason = legacy.parse_snapshot(raw)
        if current is None:
            audit['板不正行数'] += 1
            audit['板不正理由:' + reason] += 1
            previous = None
            continue
        price, volume = finite(raw.get('CurrentPrice')), finite(raw.get('TradingVolume'))
        if price is None or price <= 0 or volume is None or volume < 0:
            audit['現在値又は累積出来高欠損不正行数'] += 1
            previous = None
            continue
        audit['有効原本行数'] += 1
        current_values = (seq, time_s, volume_time, current, price, volume)
        if previous is None:
            audit['差分準備行数'] += 1
            previous = current_values
            continue
        prior_seq, prior_time, prior_volume_time, prior, prior_price, prior_volume = previous
        assert prior_seq == seq - 1, '不正行を跨ぐ出来高差を禁止'
        delta = volume - prior_volume
        if delta < 0:
            audit['累積出来高逆行行数'] += 1
            previous = None
            continue
        previous = current_values
        if delta == 0:
            audit['出来高増分ゼロ行数'] += 1
            continue
        audit['正増分観測数'] += 1
        while index < len(frame) and seq > last[index]:
            index += 1
        if index >= len(frame) or seq < first[index]:
            audit['対応する既存解放区間なし'] += 1
            continue
        assert time_s == material_time[index], '既存素材ブロック時刻との不一致'
        if prior_volume_time > release_time[index] or volume_time > release_time[index]:
            audit['出来高時刻が固定解放より未来'] += 1
            continue
        side = 1 if price == current.ask else -1 if price == current.bid else 0
        quantity = current.ask_qty if side == 1 else current.bid_qty if side == -1 else 0.
        stable = (price == prior_price and current.bid == prior.bid and current.ask == prior.ask
                  and current.bid_qty == prior.bid_qty and current.ask_qty == prior.ask_qty)
        records.append(dict(prev_seq=prior_seq, current_seq=seq, release_seq=int(release[index]),
            source_first_seq=int(first[index]), source_last_seq=int(last[index]), feature_row=index, side=side,
            prev_time_s=prior_time, current_time_s=time_s, prev_volume_time_s=prior_volume_time,
            current_volume_time_s=volume_time, release_time_s=float(release_time[index]),
            current_price=price, prev_price=prior_price, bid=current.bid, ask=current.ask,
            bid_qty=current.bid_qty, ask_qty=current.ask_qty,
            prev_bid=prior.bid, prev_ask=prior.ask, prev_bid_qty=prior.bid_qty, prev_ask_qty=prior.ask_qty,
            prev_volume=prior_volume, current_volume=volume, volume_delta=delta, side_qty=quantity,
            volume_to_side_qty=delta / quantity if side else np.nan, stable=stable))
    result = table(records)
    unreleased = result.release_seq >= audit['読取原本行数']
    audit['末尾の未解放イベント除外数'] = int(unreleased.sum())
    result = result.loc[~unreleased].reset_index(drop=True)
    assert (result.prev_seq < result.current_seq).all()
    assert (result.current_seq <= result.source_last_seq).all()
    assert (result.source_first_seq <= result.current_seq).all()
    assert (result.current_seq < result.release_seq).all()
    assert (result.current_time_s < result.release_time_s).all()
    assert (result.prev_volume_time_s <= result.release_time_s).all()
    assert (result.current_volume_time_s <= result.release_time_s).all()
    assert result.current_seq.is_unique and (result.volume_delta > 0).all()
    assert np.isfinite(result.drop(columns=['volume_to_side_qty']).to_numpy(dtype=float)).all()
    assert result.volume_to_side_qty.isna().equals(result.side.eq(0))
    audit['保存イベント数'] = len(result)
    audit['安定イベント数'] = int(result.stable.sum())
    audit['側不明イベント数'] = int(result.side.eq(0).sum())
    audit['側不明かつ安定イベント数'] = int((result.side.eq(0) & result.stable).sum())
    return result, dict(audit)


def extract_path(path: Path, frame: pd.DataFrame, session: str, max_rows: int | None = None,
                 future_from: int | None = None) -> tuple[pd.DataFrame, dict]:
    """機能: 原本を開いて抽出し、原本は変更せず閉じる。

    引数: path (Path)、frame (DataFrame)、session (str)、max_rows/future_from (int|None)。
    返り値: イベント表と監査 (tuple[DataFrame,dict])。
    """
    with path.open('rb') as stream:
        return extract(stream, frame, session, max_rows, future_from)


def fixture() -> tuple[list[dict], pd.DataFrame]:
    """機能: 同秒複数観測・既知解放境界を持つ人工原本を作る。

    引数: なし。返り値: 人工原本と既存特徴に相当する解放表 (tuple[list,DataFrame])。
    """
    rows = []
    for seq in range(12):
        text = f'2026-09-21T09:00:{seq // 2:02d}+09:00'
        rows.append(dict(CurrentPrice=101., TradingVolume=100. + seq,
            CurrentPriceTime=text, TradingVolumeTime=text, Buy1=dict(Price=100., Qty=4.), Sell1=dict(Price=101., Qty=2.)))
    frame = pd.DataFrame([dict(source_first_seq=i, source_last_seq=i+1, seq=i+2,
        source_time_s=stamp(rows[i]['CurrentPriceTime']), time_s=stamp(rows[i+2]['CurrentPriceTime'])) for i in range(0, 10, 2)])
    return rows, frame


def self_test() -> dict:
    """機能: 側分類・解放・欠損と逆行解除・未来不変を人工原本で検算する。

    引数: なし。返り値: 検査名別の合格結果 (dict)。売買再生を行わない。
    """
    from copy import deepcopy
    rows, frame = fixture()
    full, _ = extract(rows, frame, '2026-09-21_Day')
    assert len(full) == 9 and full.stable.all() and full.side.eq(1).all()
    assert full.volume_to_side_qty.eq(.5).all()
    checks = {'安定売り気配側と現在数量比': True}
    for price, side in ((100., -1), (100.5, 0)):
        altered = deepcopy(rows)
        for row in altered:
            row['CurrentPrice'] = price
        value, _ = extract(altered, frame, '2026-09-21_Day')
        assert value.side.eq(side).all() and value.stable.all()
    checks['買い側と側不明を保持'] = True
    for cut in range(1, 13):
        expected = full.loc[full.release_seq < cut].reset_index(drop=True)
        prefix, _ = extract(rows, frame, '2026-09-21_Day', cut)
        changed, _ = extract(rows, frame, '2026-09-21_Day', future_from=cut)
        pd.testing.assert_frame_equal(prefix, expected)
        pd.testing.assert_frame_equal(changed.loc[changed.release_seq < cut].reset_index(drop=True), expected)
    checks['全12境界の接頭部と未来改変一致'] = True
    changes = {'板欠損': {'Buy1': {}}, 'ロック': {'Buy1': dict(Price=101., Qty=4.)},
        '交差': {'Buy1': dict(Price=102., Qty=4.)}, '現在値欠損': {'CurrentPrice': None},
        '出来高欠損': {'TradingVolume': None}, '出来高逆行': {'TradingVolume': 1.},
        '時刻欠損': {'TradingVolumeTime': None}, '価格時刻逆行': {'CurrentPriceTime': rows[0]['CurrentPriceTime']},
        '出来高時刻逆行': {'TradingVolumeTime': rows[0]['TradingVolumeTime']},
        '場外': {'CurrentPriceTime': '2026-09-21T08:00:00+09:00'}}
    for name, change in changes.items():
        altered = deepcopy(rows); altered[6].update(change)
        value, _ = extract(altered, frame, '2026-09-21_Day')
        assert not value.current_seq.isin([6, 7]).any(), name
        checks[name + 'を跨がない'] = True
    altered = deepcopy(rows); altered[4]['TradingVolumeTime'] = rows[10]['TradingVolumeTime']
    value, audit = extract(altered, frame, '2026-09-21_Day')
    assert not value.current_seq.eq(4).any() and audit['出来高時刻が固定解放より未来'] == 1
    checks['解放より未来の出来高時刻を拒否'] = True
    altered = deepcopy(rows); altered[4]['Sell1']['Qty'] = 3.
    value, _ = extract(altered, frame, '2026-09-21_Day')
    assert not value.loc[value.current_seq.isin([4, 5]), 'stable'].any()
    assert len(value) == len(full)
    checks['数量変化イベントを対照として保持'] = True
    return dict(全合格=True, 検査=checks, 検査数=len(checks), API取得数=0, 売買再生=False)


def freeze() -> dict:
    """機能: 全既知26原本・入力・抽出仕様を、全量抽出より前に固定する。

    引数: なし。返り値: 固定資料 (dict)。以前の入力指紋とも一致を要求する。
    """
    features = pickle.loads(FEATURES.read_bytes())
    inputs = pickle.loads(INPUTS.read_bytes())
    assert set(features) == set(inputs) and len(features) == 26
    prior = read_json(ROOT / 'work/wave_v35/input_causality_before_pnl.json')
    paths = [ROOT / 'book' / symbol / (session + '.jsonl') for session, symbol in features]
    raw_sha = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    assert all(prior['原本78SHA256'][name] == sha for name, sha in raw_sha.items())
    sources = [Path(__file__), LEGACY_PATH, FEATURES, INPUTS, HERE / 'volume_quote_selftest.json']
    value = dict(対象=[list(key) for key in features], 全入力数=26,
        出力='events.pkl: dict[(session,symbol)]→DataFrame。価格別の全正増分を保存。',
        列=COLUMNS, 比率欠測='側0のみvolume_to_side_qty=NaN。JSONへイベントの非有限値を出力しない。',
        時間境界='既存source_first/last内の原本のみ。current_seq<release_seq、両出来高時刻<=release_time。未解放末尾除外。',
        履歴解除='欠損・板不正・場外・時刻又は累積量の逆行行を捨て、次の有効行から差分を再準備する。',
        側='+1現在値=Sell1、-1現在値=Buy1、他0。区間全約定の売買主導側ではない。',
        安定='現在値、両側最良価格と数量が直前原本行と完全一致。可視減少やOFIを要求しない。',
        原本26SHA256=raw_sha, 参照SHA256={p.relative_to(ROOT).as_posix(): digest(p) for p in sources},
        接頭部='全26の解放行25%・65%位置を排他的原本切断。各境界より未来を同時改変し過去一致も確認。',
        新損益読取=False, 売買再生=False, API取得数=0, 現在保存物使用=False)
    path = HERE / 'volume_quote_fixed.json'
    if path.exists():
        assert read_json(path) == value
    else:
        save(path, value)
    return value


def worker(key: tuple, frame: pd.DataFrame) -> tuple:
    """機能: 1原本の全抽出と2境界の接頭部・未来改変を検査する。

    引数: key (tuple[str,str])、frame (DataFrame)。返り値: キー・表・監査 (tuple)。
    """
    session, symbol = key
    path = ROOT / 'book' / symbol / (session + '.jsonl')
    full, audit = extract_path(path, frame, session)
    checks = []
    for fraction in (.25, .65):
        cut = int(frame.seq.iloc[int(len(frame) * fraction)])
        prefix, _ = extract_path(path, frame, session, cut)
        future, _ = extract_path(path, frame, session, cut + 64, future_from=cut)
        expected = full.loc[full.release_seq < cut].reset_index(drop=True)
        pd.testing.assert_frame_equal(prefix, expected)
        pd.testing.assert_frame_equal(future.loc[future.release_seq < cut].reset_index(drop=True), expected)
        checks.append(dict(切断原本行=cut, 公開済イベント数=len(expected), 接頭部一致=True, 未来改変一致=True))
    return key, full, dict(session=session, symbol=symbol, **audit, 境界検査=checks)


def main() -> None:
    """機能: 事前固定後に全26のイベント表と因果・原本不変監査を保存する。

    引数: --prepare (bool)、--workers (int、2〜4)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    assert 2 <= args.workers <= 4
    synthetic = self_test()
    save(HERE / 'volume_quote_selftest.json', synthetic)
    fixed = freeze()
    if args.prepare:
        print('全26入力の抽出仕様と人工検査を損益前に固定。', flush=True)
        return
    features = pickle.loads(FEATURES.read_bytes())
    outputs, audits = {}, []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        tasks = {pool.submit(worker, key, frame): key for key, frame in features.items()}
        for task in as_completed(tasks):
            key, frame, audit = task.result()
            outputs[key] = frame; audits.append(audit)
            print(f'{len(outputs)}/26 {key}: {len(frame)} 件、接頭部/未来改変一致', flush=True)
    assert set(outputs) == set(features) and freeze() == fixed
    outputs = {key: outputs[key] for key in features}
    with (HERE / 'events.pkl').open('wb') as stream:
        pickle.dump(outputs, stream, protocol=pickle.HIGHEST_PROTOCOL)
    result = dict(全監査合格=True, 全入力数=26, 全イベント数=sum(len(v) for v in outputs.values()),
        接頭部検査数=52, 未来改変検査数=52, 人工検査=synthetic,
        各入力=sorted(audits, key=lambda r: (r['session'], r['symbol'])),
        固定SHA256=digest(HERE / 'volume_quote_fixed.json'), 出力SHA256=digest(HERE / 'events.pkl'),
        原本26SHA256=fixed['原本26SHA256'], 参照SHA256=fixed['参照SHA256'], 原本前後不変=True,
        新損益読取=False, 売買再生=False, API取得数=0, 現在保存物使用=False)
    save(HERE / 'volume_quote_audit.json', result)
    print({'全監査合格': True, '全イベント数': result['全イベント数']}, flush=True)


if __name__ == '__main__':
    main()
