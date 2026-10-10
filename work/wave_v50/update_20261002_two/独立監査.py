"""追加二セッションの保存原本と再生入力を独立に照合する。"""

from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import pickle

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SESSIONS = ('2026-10-01_Night', '2026-10-02_Day')
JST = timezone(timedelta(hours=9))


def sha(path: Path) -> str:
    """機能: 原本を変更せず内容指紋を計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8388608):
            digest.update(block)
    return digest.hexdigest()


def bounds(session: str) -> tuple[float, float]:
    """機能: 既存再生器と同じ監視区間を独立に定める。

    引数: session(str)。返り値: 開始以上・終了未満の時刻(tuple[float,float])。
    """
    day, kind = session.split('_')
    date = datetime.fromisoformat(day).replace(tzinfo=JST)
    if kind == 'Day':
        return (date + timedelta(hours=8, minutes=45)).timestamp(), (date + timedelta(hours=15, minutes=40)).timestamp()
    return (date + timedelta(hours=17)).timestamp(), (date + timedelta(days=1, hours=5, minutes=55)).timestamp()


def iso(value: float | None) -> str | None:
    """機能: 秒時刻を日本時間の文字列へ変換する。

    引数: value(float|None)。返り値: 日本時間表記(str|None)。
    """
    return datetime.fromtimestamp(value, JST).isoformat() if value is not None else None


def positive(value: object) -> bool:
    """機能: 有限の正数を判定する。

    引数: value(object)。返り値: 判定値(bool)。
    """
    return isinstance(value, (float, int)) and math.isfinite(value) and value > 0


def raw_audit(session: str, symbol: str) -> tuple[dict, dict, np.ndarray]:
    """機能: 保存板を原本順に検査し、有効行と時間別OHLCを独立に再構築する。

    引数: session(str)、symbol(str)。返り値: 監査、足、有効観測(tuple[dict,dict,np.ndarray])。
    """
    start, end = bounds(session)
    path = ROOT / 'book' / symbol / (session + '.jsonl')
    counts, hashes, bars = Counter(), set(), {60: {}, 300: {}}
    observations = []
    previous = first = last = first_valid = last_valid = None
    price_low, price_high = math.inf, -math.inf
    max_gap = 0.0
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for sequence, line in enumerate(stream):
            digest.update(line)
            counts['原本行数'] += 1
            line_hash = hashlib.sha256(line).digest()
            counts['完全同一行の再出現数'] += line_hash in hashes
            hashes.add(line_hash)
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError):
                counts['JSON不正行数'] += 1
                continue
            counts['原本seq件数'] += 'seq' in row
            raw_time = row.get('CurrentPriceTime')
            if not raw_time:
                counts['時刻欠損行数'] += 1
                continue
            try:
                time = datetime.fromisoformat(raw_time).timestamp()
            except (ValueError, TypeError):
                counts['時刻不正行数'] += 1
                continue
            first = time if first is None else first
            last = time
            counts['時刻逆行数'] += previous is not None and time < previous
            counts['同時刻連続行数'] += previous is not None and time == previous
            previous = time
            if not start <= time < end:
                counts['対象時間外行数'] += 1
                continue
            counts['対象時間内行数'] += 1
            price = row.get('CurrentPrice')
            if not positive(price):
                counts['対象内価格不正行数'] += 1
                continue
            counts['対象内有限正価格行数'] += 1
            counts['返済期限以降の有限正価格行数'] += time >= end - 300
            price_low, price_high = min(price_low, price), max(price_high, price)
            for seconds, output in bars.items():
                bucket = int(time // seconds) * seconds
                if bucket not in output:
                    output[bucket] = [price, price, price, price]
                else:
                    values = output[bucket]
                    values[1], values[2], values[3] = max(values[1], price), min(values[2], price), price
            bid, ask = row.get('Buy1') or {}, row.get('Sell1') or {}
            if not all(positive(v) for v in (bid.get('Price'), ask.get('Price'), bid.get('Qty'), ask.get('Qty'))):
                counts['最良価格数量不正行数'] += 1
                continue
            if bid['Price'] >= ask['Price']:
                counts['ロック板行数' if bid['Price'] == ask['Price'] else '交差板行数'] += 1
                continue
            counts['有効板行数'] += 1
            counts['返済期限以降の有効板行数'] += time >= end - 300
            first_valid = time if first_valid is None else first_valid
            if last_valid is not None:
                max_gap = max(max_gap, time - last_valid)
            last_valid = time
            observations.append((sequence, time, price))
    return dict(対象=session, 銘柄=symbol, 原本=path.relative_to(ROOT).as_posix(), SHA256=digest.hexdigest(), バイト数=path.stat().st_size,
                **dict(counts), 最初の原本時刻=iso(first), 最後の原本時刻=iso(last), 最初の有効板時刻=iso(first_valid), 最後の有効板時刻=iso(last_valid),
                対象内安値=price_low, 対象内高値=price_high, 有効板の約定時刻最大間隔秒=max_gap,
                監視開始=iso(start), 監視終了未満=iso(end), 返済期限=iso(end-300),
                seq説明='原本物理行順の0始まり連番。時刻の並べ替えや重複排除を行わない。',
                返済期限以降の有効板あり=counts['返済期限以降の有効板行数'] > 0,
                最終5分区間の有効板あり=last_valid is not None and end-300 <= last_valid < end), bars, np.asarray(observations)


def candle_audit(session: str, symbol: str, seconds: int, raw: dict) -> dict:
    """機能: 保存足の完成性と価格整合性、約定時刻集計との差を調べる。

    引数: session/symbol(str)、seconds(int)、raw(dict)。返り値: 監査値(dict)。
    """
    start, end = bounds(session)
    path = ROOT / f'candle_{seconds//60}min' / symbol / (session + '.csv')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    times = [datetime.fromisoformat(row['time']).timestamp() for row in rows]
    prices = [[float(row[k]) for k in ('open', 'high', 'low', 'close')] for row in rows]
    common = [(values, raw[time]) for time, values in zip(times, prices) if time in raw]
    equal = sum(all(abs(a-b) < 1e-8 for a, b in zip(saved, rebuilt)) for saved, rebuilt in common)
    return dict(対象=session, 銘柄=symbol, 足=f'{seconds//60}分', 原本=path.relative_to(ROOT).as_posix(), SHA256=sha(path), 行数=len(rows),
                最初の時刻=rows[0]['time'], 最後の時刻=rows[-1]['time'], 未確定足数=sum(row['closed'].lower() != 'true' for row in rows),
                出来高未完備足数=sum(row['volume_complete'].lower() != 'true' for row in rows), 重複時刻数=len(times)-len(set(times)),
                時刻逆行数=sum(b < a for a, b in zip(times, times[1:])), 価格不正足数=sum(not all(positive(x) for x in p) for p in prices),
                OHLC不整合足数=sum(not lo <= min(op, cl) <= max(op, cl) <= hi for op, hi, lo, cl in prices),
                生時刻OHLC共通足数=len(common), 生時刻OHLC全一致足数=equal, 生時刻OHLC不一致足数=len(common)-equal,
                生監視区間外の保存足数=sum(not start <= t < end for t in times), 生区間内で保存足のみの数=sum(start <= t < end and t not in raw for t in times),
                最終区間の確定足あり=any(t == end-seconds and r['closed'].lower() == 'true' for t, r in zip(times, rows)),
                監視区間の無保存足数=len(set(range(int(start), int(end), seconds))-set(times)))


def run() -> dict:
    """機能: 追加12原本、旧17セッション、再生入力4配列組を独立に照合する。

    引数: なし。返り値: 統合監査結果(dict)。
    """
    old_paths = (ROOT / 'work/wave_v48/update_20261001/固定.json', ROOT / 'work/wave_v50/update_20261001_day/固定.json')
    old = {}
    for path in old_paths:
        for name, digest in json.loads(path.read_text(encoding='utf-8'))['原本SHA256'].items():
            assert name not in old or old[name] == digest
            old[name] = digest
    old_names = {Path(path).stem for path in old}
    assert len(old_names) == 17
    inventory = {}
    for folder in ('book', 'candle_1min', 'candle_5min'):
        for symbol in ('TOPIX', 'NK225'):
            names = {path.stem for path in (ROOT/folder/symbol).iterdir() if path.is_file()}
            inventory[f'{folder}/{symbol}'] = dict(セッション数=len(names), 追加=sorted(names-old_names), 不足=sorted(old_names-names))
    assert all(v['追加'] == list(SESSIONS) and not v['不足'] for v in inventory.values())
    input_path = HERE / 'new_inputs.pkl'
    inputs = pickle.loads(input_path.read_bytes())
    originals, candles, alignment = [], [], []
    for session in SESSIONS:
        for symbol in ('TOPIX', 'NK225'):
            result, bars, independent = raw_audit(session, symbol)
            originals.append(result)
            candles.extend(candle_audit(session, symbol, seconds, bars[seconds]) for seconds in (60, 300))
            ready = inputs[session, symbol]
            for number, key in enumerate(('seq', 'time_s', 'last')):
                np.testing.assert_array_equal(independent[:, number], ready[key])
            alignment.append(dict(対象=session, 銘柄=symbol, 独立原本全行と再生入力完全一致=True, 行数=len(independent), 比較列=['seq', 'time_s', 'last']))
            print(json.dumps(dict(対象=session, 銘柄=symbol, 原本行数=result['原本行数'], 有効板行数=result['有効板行数'], 再生入力完全一致=True), ensure_ascii=False), flush=True)
    # ----------------------------------------
    # 以前の原本を再度指紋化し、今回の増分以外が変化していないか確認する。
    fingerprints = []
    for path, expected in old.items():
        actual = sha(ROOT/path)
        fingerprints.append(dict(原本=path, 以前SHA256=expected, 現在SHA256=actual, 一致=actual == expected))
    checks = [all(v['一致'] for v in fingerprints),
              all(r['最終5分区間の有効板あり'] and r['返済期限以降の有効板あり'] for r in originals),
              all(not any(r.get(k, 0) for k in ('JSON不正行数', '時刻不正行数', '時刻逆行数', '対象内価格不正行数')) for r in originals),
              all(not any(r[k] for k in ('未確定足数', '重複時刻数', '時刻逆行数', '価格不正足数', 'OHLC不整合足数')) and r['最終区間の確定足あり'] for r in candles),
              len(alignment) == 4]
    result = dict(全合格=all(checks), 対象=list(SESSIONS), 保存一覧=inventory, 生原本=originals, 保存足=candles,
                  再生入力照合=alignment, 再生入力SHA256=sha(input_path),
                  旧17場原本照合=dict(参照=[p.relative_to(ROOT).as_posix() for p in old_paths], 件数=len(fingerprints), 全一致=all(v['一致'] for v in fingerprints), 詳細=fingerprints),
                  API追加取得数=0, 原本変更数=0,
                  完了判定='両市場・両追加場の保存足は全足確定し、監視終端の最後の1分・5分枠を覆う。返済期限はデイ15:35、ナイト05:50で、その後の有効板がある。約定のない分に足を補完しない。取引所の全約定を完全収集したとの主張はしない。',
                  時刻の制約='CurrentPriceTimeは約定時刻であり受信時刻ではない。最終約定が終端直前10秒以内であることは完成性の要件にしない。約定時刻の間隔はネットワーク中断の証拠ではない。',
                  因果性の前提='原本物理行順を保持し、信号には既存の確定足公開待機と同時刻ブロックの次時刻解放を使用する。生約定時刻集計と保存足のOHLC差は件数を開示し、原本を編集しない。')
    (HERE/'入力独立監査.json').write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    assert result['全合格'], result
    return result


if __name__ == '__main__':
    result = run()
    print(json.dumps(dict(全合格=result['全合格'], 対象=result['対象'], 旧原本全一致=result['旧17場原本照合']['全一致']), ensure_ascii=False))
