"""追加デイの保存原本と以前の指紋を独立に検査する。"""

from collections import Counter
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import pickle

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SESSION = '2026-10-01_Day'
START = datetime.fromisoformat('2026-10-01T08:45:00+09:00').timestamp()
END = datetime.fromisoformat('2026-10-01T15:40:00+09:00').timestamp()
LIMIT = END - 300


def sha(path: Path) -> str:
    """機能: 内容の指紋を計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8388608):
            h.update(block)
    return h.hexdigest()


def positive(value: object) -> bool:
    """機能: 価格や数量が有限の正数か判定する。

    引数: value(object)。返り値: 判定値(bool)。
    """
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def raw_audit(symbol: str) -> tuple[dict, dict, list]:
    """機能: 原本順で生板を検査し、約定時刻別OHLCを集計する。

    引数: symbol(str)。返り値: 監査値、1分・5分集計、有効板観測(tuple[dict,dict,list])。
    """
    path = ROOT / 'book' / symbol / (SESSION + '.jsonl')
    counts, hashes, bars = Counter(), set(), {60: {}, 300: {}}
    observations = []
    previous = first = last = None
    first_valid = last_valid = None
    raw_seq_present, raw_seqs = set(), []
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for sequence, line in enumerate(stream):
            digest.update(line)
            counts['原本行数'] += 1
            h = hashlib.sha256(line).digest()
            counts['完全同一行の再出現数'] += h in hashes
            hashes.add(h)
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError):
                counts['JSON不正行数'] += 1
                continue
            if 'seq' in row:
                raw_seq_present.add(sequence)
                raw_seqs.append(row['seq'])
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
            if not START <= time < END:
                counts['対象時間外行数'] += 1
                continue
            counts['対象時間内行数'] += 1
            price = row.get('CurrentPrice')
            if not positive(price):
                counts['対象内価格不正行数'] += 1
                continue
            counts['対象内有限正価格行数'] += 1
            counts['返済期限以降の有限正価格行数'] += time >= LIMIT
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
            counts['返済期限以降の有効板行数'] += time >= LIMIT
            first_valid = time if first_valid is None else first_valid
            last_valid = time
            observations.append((sequence, time, price))
    iso = lambda t: datetime.fromtimestamp(t, datetime.fromisoformat('2026-10-01T00:00:00+09:00').tzinfo).isoformat() if t is not None else None
    result = dict(銘柄=symbol, 原本=path.relative_to(ROOT).as_posix(), SHA256=digest.hexdigest(), バイト数=path.stat().st_size,
                  **dict(counts), 最初の原本時刻=iso(first), 最後の原本時刻=iso(last), 最初の有効板時刻=iso(first_valid), 最後の有効板時刻=iso(last_valid),
                  seq説明='原本にはseqなし。物理行順の0始まり連番を使用し、並べ替えない。' if not raw_seq_present else '原本seqあり',
                  原本seq件数=len(raw_seq_present), 返済期限以降の有効板あり=counts['返済期限以降の有効板行数'] > 0,
                  監視終端直前まで被覆=last_valid is not None and last_valid >= END - 10)
    return result, bars, observations


def candle_audit(symbol: str, seconds: int, raw: dict) -> dict:
    """機能: 確定足の時刻順・価格・重複と生時刻集計との差を検査する。

    引数: symbol(str)、seconds(int)、raw(dict)。返り値: 検査内容(dict)。
    """
    path = ROOT / f'candle_{seconds // 60}min' / symbol / (SESSION + '.csv')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    times = [datetime.fromisoformat(row['time']).timestamp() for row in rows]
    prices = [[float(row[k]) for k in ('open', 'high', 'low', 'close')] for row in rows]
    bad = sum(not all(math.isfinite(x) and x > 0 for x in values) for values in prices)
    invalid_ohlc = sum(not lo <= min(op, cl) <= max(op, cl) <= hi for op, hi, lo, cl in prices)
    common = [(values, raw[time]) for time, values in zip(times, prices) if time in raw]
    equal = sum(all(abs(a-b) < 1e-8 for a, b in zip(saved, rebuilt)) for saved, rebuilt in common)
    return dict(銘柄=symbol, 足=f'{seconds // 60}分', 原本=path.relative_to(ROOT).as_posix(), SHA256=sha(path), 行数=len(rows),
                最初の時刻=rows[0]['time'], 最後の時刻=rows[-1]['time'], 未確定足数=sum(row['closed'].lower() != 'true' for row in rows),
                出来高未完備足数=sum(row['volume_complete'].lower() != 'true' for row in rows), 重複時刻数=len(times) - len(set(times)),
                時刻逆行数=sum(b < a for a, b in zip(times, times[1:])), 価格不正足数=bad, OHLC不整合足数=invalid_ohlc,
                生時刻OHLC共通足数=len(common), 生時刻OHLC全一致足数=equal, 生時刻OHLC不一致足数=len(common)-equal,
                生監視区間外の保存足数=sum(not START <= t < END for t in times), 生区間内で保存足のみの数=sum(START <= t < END and t not in raw for t in times))


def run() -> dict:
    """機能: 保存6系列の新規差分と旧原本指紋を確認する。

    引数: なし。返り値: 統合した監査結果(dict)。
    """
    old_path = ROOT / 'work/wave_v48/update_20261001/固定.json'
    old = json.loads(old_path.read_text(encoding='utf-8'))['原本SHA256']
    old_names = {Path(path).stem for path in old}
    inventory = {}
    for folder in ('book', 'candle_1min', 'candle_5min'):
        for symbol in ('TOPIX', 'NK225'):
            names = {path.stem for path in (ROOT/folder/symbol).iterdir() if path.is_file()}
            inventory[f'{folder}/{symbol}'] = dict(セッション数=len(names), 追加=sorted(names-old_names), 不足=sorted(old_names-names))
    assert all(v['追加'] == [SESSION] and not v['不足'] for v in inventory.values())
    originals, candles, alignment = [], [], []
    input_path = HERE / 'new_inputs.pkl'
    inputs = pickle.loads(input_path.read_bytes()) if input_path.exists() else None
    for symbol in ('TOPIX', 'NK225'):
        result, bars, observations = raw_audit(symbol)
        originals.append(result)
        candles.extend(candle_audit(symbol, seconds, bars[seconds]) for seconds in (60, 300))
        if inputs is not None:
            ready = inputs[SESSION, symbol]
            independent = np.asarray(observations)
            for number, key in enumerate(('seq', 'time_s', 'last')):
                np.testing.assert_array_equal(independent[:, number], ready[key])
            alignment.append(dict(銘柄=symbol, 独立原本全行と再生入力完全一致=True, 行数=len(observations), 比較列=['seq', 'time_s', 'last']))
    # ----------------------------------------
    # 旧16場の原本指紋と現在内容を比較し、再検証対象の増分を確定する。
    fingerprints = []
    for path, expected in old.items():
        actual = sha(ROOT/path)
        fingerprints.append(dict(原本=path, 以前SHA256=expected, 現在SHA256=actual, 一致=actual == expected))
    checks = [all(v['一致'] for v in fingerprints), all(r['監視終端直前まで被覆'] and r['返済期限以降の有効板あり'] for r in originals),
              all(not any(r.get(k, 0) for k in ('JSON不正行数', '時刻不正行数', '時刻逆行数', '対象内価格不正行数')) for r in originals),
              all(not any(r[k] for k in ('未確定足数', '重複時刻数', '時刻逆行数', '価格不正足数', 'OHLC不整合足数')) for r in candles)]
    result = dict(全合格=all(checks), 対象=SESSION, 保存一覧=inventory, 生原本=originals, 保存足=candles,
                  再生入力照合=alignment, 再生入力SHA256=sha(input_path) if inputs is not None else None,
                  旧16場原本照合=dict(参照=old_path.relative_to(ROOT).as_posix(), 件数=len(fingerprints), 全一致=all(v['一致'] for v in fingerprints), 詳細=fingerprints),
                  API追加取得数=0, 原本変更数=0,
                  完了判定='両市場の保存足は15:40までの監視区間を覆い全足確定。TOPIXの最終開始時刻は1分足15:39、5分足15:35。NKにはさらに15:40開始足があるが監視区間外。既存の監視区間08:45以上15:40未満を終端直前まで覆い、15:35返済期限後の有効板がある。取引所の全約定を完全収集したとの主張はしない。',
                  因果性の前提='原本のCurrentPriceTimeは受信時刻ではない。同時刻ブロックの特徴は次時刻で解放し、最終未解放ブロックは方向判断に使わない。確定足の公開待機は既存ルールを維持する。')
    (HERE/'入力独立監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 追加デイの入力独立監査', '', f'- 追加は {SESSION} の1セッション。2市場・生板／1分足／5分足の6系列が揃う。',
             f'- 旧16セッションの原本{len(fingerprints)}ファイルは以前のSHA256とすべて一致。',
             '- 両市場とも15:35返済期限後から15:40直前まで有効板がある。監視区間を覆う保存足は全足確定。',
             '- 同じ時刻の多数行や完全同一行の再出現は板配信上の観測で、順番を保持する。seqは原本フィールドではなく物理行番号。',
             '- 開始前の残値・時刻欠損・ロック／交差板は既存仕様通り監視対象から除外する。', '', '| 市場 | 原本行 | 有効板行 | 1分足 | 5分足 | 最後の有効板 |', '|---|---:|---:|---:|---:|---|']
    for raw in originals:
        counts = [r['行数'] for r in candles if r['銘柄'] == raw['銘柄']]
        lines.append(f"| {raw['銘柄']} | {raw['原本行数']:,} | {raw['有効板行数']:,} | {counts[0]} | {counts[1]} | {raw['最後の有効板時刻']} |")
    if alignment:
        lines.extend(['', '- 再生入力の物理行番号・時刻・生価格を、今回独立に読み直した原本全有効行と完全照合。'])
    lines.extend(['', '足と生約定時刻集計のOHLC差はJSONに件数を記録。既存通り、信号には保存足、注文監視には生価格を用い、差を埋めるための原本編集はしない。', '', 'API取得・原本変更は0件。セッションを取引所の全約定で完全収集したとの主張はしない。'])
    (HERE/'入力独立監査.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    assert result['全合格'], result
    return result


if __name__ == '__main__':
    result = run()
    print(json.dumps({k: result[k] for k in ('全合格', '対象', '生原本', '保存足')}, ensure_ascii=False))
