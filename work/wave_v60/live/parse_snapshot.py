"""一回取得した原本のセッション・限月・気配を照合し、既知入力と同じ価格形式へ変換する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle
import re

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def expiry(name: str) -> str:
    """機能: 原本銘柄名の年/月から限月を読む。

    引数: name(str) はAPI原本のSymbolName。
    返り値: YYYYMM形式の文字列(str)。不明なら例外とし推測しない。
    """
    match = re.search(r'(?<!\d)(\d{2}|\d{4})/(\d{2})(?!\d)', name)
    if not match:
        raise ValueError(f'限月を確認できない銘柄名: {name}')
    year, month = map(int, match.groups())
    year = year + 2000 if year < 100 else year
    if not 1 <= month <= 12:
        raise ValueError('限月の月が不正です')
    return f'{year:04d}{month:02d}'


def save_baseline() -> None:
    """機能: 既知最終場の原本から契約IDと限月だけを、ネットワーク取得前に固定する。

    引数: なし。
    返り値: なし(None)。現在APIへアクセスしない。
    """
    inputs = pickle.loads((WORK / 'inputs.pkl').read_bytes())
    latest = max(key[0] for key in inputs)
    baseline = {'既知最終場': latest, '銘柄': {}}
    for code in ('TOPIX', 'NK225'):
        path = ROOT / 'book' / code / f'{latest}.jsonl'
        with path.open('rb') as stream:
            line = stream.readline()
        raw = json.loads(line)
        baseline['銘柄'][code] = {'symbol': str(raw['Symbol']), 'name': raw['SymbolName'],
                                    'expiry': expiry(raw['SymbolName']), '参照先': str(path),
                                    '先頭行SHA256': hashlib.sha256(line).hexdigest()}
    (HERE / '契約照合基準.json').write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding='utf-8')


def header(record: dict, name: str) -> str:
    """機能: 大文字小文字に依存せず、一意なHTTPヘッダーを読む。

    引数: record(dict) は取得記録、name(str) はヘッダー名。
    返り値: 一つの値(str)。欠測・複数値は例外とする。
    """
    matches = [value for key, value in record['headers'].items() if key.lower() == name.lower()]
    assert len(matches) == 1 and len(matches[0]) == 1, (name, matches)
    return matches[0][0]


def session_bounds(session: str) -> tuple[float, float]:
    """機能: 保存検証と同じ通常監視区間の開始と排他的終端を求める。

    引数: session(str) はYYYY-MM-DD_Day/Night。
    返り値: Unix秒の開始・通常終端(tuple[float,float])。
    """
    date, kind = session.rsplit('_', 1)
    day = datetime.fromisoformat(date).replace(tzinfo=timezone(timedelta(hours=9)))
    if kind == 'Day':
        return (day + timedelta(hours=8, minutes=45)).timestamp(), (day + timedelta(hours=15, minutes=40)).timestamp()
    if kind == 'Night':
        return (day + timedelta(hours=17)).timestamp(), (day + timedelta(days=1, hours=5, minutes=55)).timestamp()
    raise ValueError('未知のセッションです')


def parse_book(path: Path, code: str, session: str, cutoff: float, contract: dict) -> tuple[dict, dict, dict]:
    """機能: 取得済みJSONLを原本順で読み、銘柄契約と保存時計・最良気配を検査する。

    引数: path(Path)、code/session(str)、cutoff(float)、contract(dict) は固定済み限月情報。
    返り値: 共通ready/quotesと監査(tuple[dict,dict,dict])。空場も空配列のまま保持する。
    """
    start, end = session_bounds(session)
    rows, previous, digest = [], None, hashlib.sha256()
    missing = outside = invalid = count = 0
    symbols, months, names = set(), set(), set()
    with path.open('rb') as stream:
        for seq, line in enumerate(stream):
            digest.update(line)
            count += 1
            raw = json.loads(line)
            symbols.add(str(raw.get('Symbol', '')))
            names.add(raw.get('SymbolName', ''))
            months.add(expiry(raw.get('SymbolName', '')))
            text = raw.get('CurrentPriceTime')
            if not text:
                missing += 1
                continue
            time = datetime.fromisoformat(text)
            assert time.tzinfo is not None, 'タイムゾーン不明'
            stamp = time.timestamp()
            assert previous is None or stamp >= previous, '約定時計逆行'
            previous = stamp
            assert stamp <= cutoff, '共通取得上限より未来の約定時計'
            if not start <= stamp < end:
                outside += 1
                continue
            try:
                bid, ask = float(raw['Buy1']['Price']), float(raw['Sell1']['Price'])
                bid_qty, ask_qty = float(raw['Buy1']['Qty']), float(raw['Sell1']['Qty'])
            except (KeyError, TypeError, ValueError):
                invalid += 1
                continue
            if not all(np.isfinite(x) for x in (bid, ask, bid_qty, ask_qty)) or not (0 < bid < ask and bid_qty > 0 and ask_qty > 0):
                invalid += 1
                continue
            rows.append((seq, stamp, bid, ask))
    if count:
        assert symbols == {contract['symbol']} and months == {contract['expiry']}, '限月又は契約IDが既知資料と一致しません'
    data = np.asarray(rows, float).reshape(-1, 4)
    ready = dict(seq=data[:, 0].astype(np.int64), time_s=data[:, 1], start=start, limit=end - 300.,
                 symbol=code, session=session, tick=.5 if code == 'TOPIX' else 10.)
    quotes = dict(seq=ready['seq'].copy(), time_s=ready['time_s'].copy(), bid=data[:, 2], ask=data[:, 3],
                  mid=(data[:, 2] + data[:, 3]) / 2.)
    audit = {'セッション': session, '銘柄': code, '原本行数': count, '有効原本行数': len(data),
             '時刻欠測': missing, '場外観測': outside, '最良気配不正': invalid, '原本SHA256': digest.hexdigest(),
             '契約ID': sorted(symbols), '限月': sorted(months), '銘柄名': sorted(names), '最終値不使用': True,
             '原本上の限月確認済み': count > 0,
             '最後の保存時計': None if len(data) == 0 else float(data[-1, 1])}
    return ready, quotes, audit


def main() -> None:
    """機能: 状態・二原本のセッションを照合し、一回取得の共通キャッシュを作る。

    引数: なし。
    返り値: なし(None)。APIの追加取得は行わない。
    """
    manifest = json.loads((HERE / '取得記録.json').read_text(encoding='utf-8'))
    assert manifest['全応答成功'] and len(manifest['requests']) == 3
    status = json.loads((HERE / 'status.json').read_text(encoding='utf-8'))
    current = {row['code']: row for row in status['current'] if row['code'] in ('TOPIX', 'NK225')}
    assert set(current) == {'TOPIX', 'NK225'}
    books = {record['file'].removesuffix('.jsonl'): record for record in manifest['requests'][1:]}
    session_ids = {header(row, 'X-History-Session-Id') for row in books.values()}
    generations = {header(row, 'X-History-Generation') for row in books.values()}
    assert len(session_ids) == 1 and len(generations) == 1, '二原本のセッション又はgenerationが不一致'
    session = next(iter(session_ids))
    assert {row['sessionId'] for row in current.values()} == {session}, '状態と原本のセッションが不一致'
    baseline = json.loads((HERE / '契約照合基準.json').read_text(encoding='utf-8'))
    cutoff = datetime.fromisoformat(manifest['共通to'].replace('Z', '+00:00')).timestamp()
    inputs, quotes, audits = {}, {}, []
    for code in ('TOPIX', 'NK225'):
        assert header(books[code], 'X-History-Code') == code
        ready, quote, audit = parse_book(HERE / f'{code}.jsonl', code, session, cutoff, baseline['銘柄'][code])
        inputs[(session, code)], quotes[(session, code)] = ready, quote
        audits.append(audit)
    known = pickle.loads((WORK / 'inputs.pkl').read_bytes())
    duplicate = session in {key[0] for key in known}
    latest = max(key[0] for key in known)
    latest_date, latest_kind = latest.rsplit('_', 1)
    expected_next = (latest_date + '_Night' if latest_kind == 'Day' else
                     (datetime.fromisoformat(latest_date) + timedelta(days=1)).date().isoformat() + '_Day')
    continuation = session == expected_next
    for name, values in (('inputs.pkl', inputs), ('quotes.pkl', quotes)):
        (HERE / name).write_bytes(pickle.dumps(values, protocol=pickle.HIGHEST_PROTOCOL))
    report = {'合格': True, 'セッション': session, '既知セッションと重複': duplicate,
              '未見検証と呼べるか': not duplicate, '共通to': manifest['共通to'],
              'generation': next(iter(generations)), '口座別': audits,
              '週内継続の直近保存場': latest, '直後に必要なセッション': expected_next,
              '週内継続の連結が可能': continuation,
              '週内継続の注記': ('直前保存場の直後として連結可能' if continuation else
                             '重複又は未収録セッションを挟むため、週内継続の検証は不成立。空白中の売買を再現しない。'),
              '限界': '指標と約定にはラージ気配を使用。mini/micro実気配の代用であり、同じスプレッド・価格での約定は保証しない。'}
    (HERE / '現在原本の照合.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
