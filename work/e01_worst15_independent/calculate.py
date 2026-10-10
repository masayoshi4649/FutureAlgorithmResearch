"""E01の注文を固定し、判断から15秒以内の不利な価格への置換を独立計算する。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JST = timezone(timedelta(hours=9))


def read_json(path: Path) -> object:
    """機能: 圧縮有無に応じてJSONを読み込む。

    引数: path(Path)。返り値: 読み込み内容(object)。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def stamp(value: float) -> str:
    """機能: 秒時刻を日本時間の文字列に変換する。

    引数: value(float)。返り値: 日時(str)。
    """
    return datetime.fromtimestamp(value, JST).isoformat()


def accounting(profits: list[float], quantities: list[int]) -> dict:
    """機能: 決済ごとの円損益から利益・損失・勝敗枚数を計算する。

    引数: profits(list[float])、quantities(list[int])。返り値: 集計(dict)。
    """
    values = np.asarray(profits, dtype=float)
    sizes = np.asarray(quantities, dtype=int)
    return dict(利益円=round(float(values[values > 0].sum()), 6),
                損失円=round(float(-values[values < 0].sum()), 6),
                収支円=round(float(values.sum()), 6),
                利益枚数=int(sizes[values > 0].sum()),
                損失枚数=int(sizes[values < 0].sum()),
                同値枚数=int(sizes[values == 0].sum()),
                決済枚数=int(sizes.sum()))


def aggregate(rows: list[dict]) -> dict:
    """機能: 同銘柄のセッション集計を加算する。

    引数: rows(list[dict])。返り値: 集計(dict)。
    """
    result = {}
    for kind in ('理想', '15秒最悪'):
        result[kind] = {key: round(sum(row[kind][key] for row in rows), 6)
                        for key in rows[0][kind]}
        result[kind]['黒字セッション数'] = sum(row[kind]['収支円'] > 0 for row in rows)
        result[kind]['赤字セッション数'] = sum(row[kind]['収支円'] < 0 for row in rows)
    for key in ('収支差円', '新規による差円', '返済による差円', '注文数', '改善注文数',
                '悪化注文数', '同値注文数', '15秒窓重複隣接組数', '最悪時刻逆転隣接組数',
                '窓末尾までデータ未到達注文数', 'セッション末尾で窓短縮注文数', '候補なし注文数'):
        result[key] = round(sum(row[key] for row in rows), 6)
    return result


def main() -> None:
    """機能: 全19セッションの注文と決済を独立再計算し監査資料を保存する。

    引数: なし。返り値: なし(None)。
    """
    input_paths = [ROOT / 'work/wave_v47/inputs.pkl',
                   ROOT / 'work/wave_v48/update_20260930/new_inputs.pkl',
                   ROOT / 'work/wave_v48/update_20261001/new_inputs.pkl']
    ledger_paths = [ROOT / 'work/wave_v49/early/ledgers/E01.json.gz']
    for name in read_json(ROOT / 'work/wave_v50/追加結果一覧.json'):
        directory = ROOT / 'work/wave_v50' / name
        input_paths.append(directory / 'new_inputs.pkl')
        ledger_paths.append(directory / 'ledgers/E01.json.gz')
    inputs, ledgers, hashes = {}, [], {}
    for path in input_paths:
        raw = path.read_bytes()
        values = pickle.loads(raw)
        assert not set(inputs).intersection(values)
        inputs.update(values)
        hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(raw).hexdigest()
    for path in ledger_paths:
        ledgers.extend(read_json(path))
        hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(ledgers) == len(inputs) == 38
    all_orders, all_trades, sessions = [], [], []
    for ledger in sorted(ledgers, key=lambda value: (value['session'], value['symbol'])):
        session, symbol = ledger['session'], ledger['symbol']
        source = inputs[session, symbol]
        seconds, prices, seqs = (np.asarray(source[key]) for key in ('time_s', 'last', 'seq'))
        close = source.get('session_close', source['limit'] + 600)
        multiplier = 1000 if symbol == 'TOPIX' else 10
        assert np.all(np.diff(seconds) >= 0)
        assert np.all(np.diff(seqs) > 0)
        assert np.all(np.isfinite(prices) & (prices > 0))
        orders = []
        lookup = {}
        used = defaultdict(int)
        for number, values in enumerate(ledger['orders']):
            row, source_row, group, side, qty, ideal, reason, opening = values
            row, source_row, group, side, qty, reason, opening = map(int, (row, source_row, group, side, qty, reason, opening))
            assert source_row < row
            start = seconds[row]
            end = min(start + 15, np.nextafter(close, -np.inf))
            indices = np.flatnonzero((seconds >= start) & (seconds <= end))
            indices = indices[indices >= row]
            assert len(indices) > 0
            chosen = int(indices[np.argmax(prices[indices]) if side == 1 else np.argmin(prices[indices])])
            worst = float(prices[chosen])
            difference = -side * qty * (worst - ideal) * multiplier
            record = dict(セッション=session, 銘柄=symbol, 注文番号=number,
                          組番号=group, 種類='新規' if opening else '返済',
                          売買='買い' if side == 1 else '売り', 枚数=qty,
                          条件成立行=row, 条件準備行=source_row,
                          条件成立原本連番=int(seqs[row]), 条件成立時刻=stamp(start),
                          条件成立秒=float(start), 窓末尾秒=float(end), 窓末尾時刻=stamp(end),
                          理想価格=ideal, 最悪価格=worst, 収支差円=difference,
                          最悪価格行=chosen, 最悪価格原本連番=int(seqs[chosen]),
                          最悪価格時刻=stamp(seconds[chosen]), 最悪価格秒=float(seconds[chosen]),
                          最悪時点まで秒=float(seconds[chosen] - start),
                          窓内有効行数=len(indices),
                          窓内最終観測秒=float(seconds[indices[-1]]),
                          窓内最終観測時刻=stamp(seconds[indices[-1]]),
                          窓内最大受信間隔秒=float(np.diff(seconds[indices]).max(initial=0)),
                          窓末尾までデータ到達=bool(seconds[-1] >= end),
                          セッション末尾で窓短縮=bool(end < start + 15), 理由コード=reason)
            key = row, group, side, opening
            assert key not in lookup
            lookup[key] = record
            orders.append(record)
        # ----------------------------------------
        # 決済単位で建値と返済値をそれぞれ対応注文の最悪値へ置き換える。
        profits, stressed, quantities = [], [], []
        trade_records = []
        for number, values in enumerate(ledger['trades']):
            group, _, direction, qty, entry, exit_price, entry_row, exit_row, _, reason, original = values
            group, direction, qty, entry_row, exit_row = map(int, (group, direction, qty, entry_row, exit_row))
            opening = lookup[entry_row, group, direction, 1]
            closing = lookup[exit_row, group, -direction, 0]
            assert entry == opening['理想価格'] and exit_price == closing['理想価格']
            assert abs(original - direction * qty * (exit_price - entry)) <= 1e-8
            used[entry_row, group, direction, 1] += qty
            used[exit_row, group, -direction, 0] += qty
            ideal_profit = original * multiplier
            stress_profit = direction * qty * (closing['最悪価格'] - opening['最悪価格']) * multiplier
            profits.append(ideal_profit)
            stressed.append(stress_profit)
            quantities.append(qty)
            trade_records.append(dict(セッション=session, 銘柄=symbol, 決済番号=number,
                                      組番号=group, 方向='ロング' if direction == 1 else 'ショート',
                                      枚数=qty, 新規注文番号=opening['注文番号'], 返済注文番号=closing['注文番号'],
                                      理想損益円=ideal_profit, 最悪損益円=stress_profit,
                                      収支差円=stress_profit - ideal_profit,
                                      新規最悪時点が返済判断後=opening['最悪価格行'] > closing['条件成立行'],
                                      新規最悪時点が返済最悪時点後=opening['最悪価格行'] > closing['最悪価格行']))
        assert set(used) == set(lookup)
        assert all(used[key] == record['枚数'] for key, record in lookup.items())
        ideal_account, worst_account = accounting(profits, quantities), accounting(stressed, quantities)
        difference = worst_account['収支円'] - ideal_account['収支円']
        entry_difference = sum(order['収支差円'] for order in orders if order['種類'] == '新規')
        exit_difference = sum(order['収支差円'] for order in orders if order['種類'] == '返済')
        assert abs(difference - entry_difference - exit_difference) < 1e-6
        pairs = list(zip(orders, orders[1:]))
        overlap = [(left['注文番号'], right['注文番号']) for left, right in pairs
                   if left['窓末尾秒'] >= right['条件成立秒']]
        reversed_time = [(left['注文番号'], right['注文番号']) for left, right in pairs
                         if left['最悪価格行'] > right['最悪価格行']]
        sessions.append(dict(セッション=session, 銘柄=symbol, 理想=ideal_account,
                             **{'15秒最悪': worst_account}, 収支差円=difference,
                             新規による差円=entry_difference, 返済による差円=exit_difference,
                             注文数=len(orders), 改善注文数=sum(order['収支差円'] > 0 for order in orders),
                             悪化注文数=sum(order['収支差円'] < 0 for order in orders),
                             同値注文数=sum(order['収支差円'] == 0 for order in orders),
                             候補なし注文数=0,
                             窓末尾までデータ未到達注文数=sum(not order['窓末尾までデータ到達'] for order in orders),
                             セッション末尾で窓短縮注文数=sum(order['セッション末尾で窓短縮'] for order in orders),
                             最悪時刻逆転隣接組数=len(reversed_time), 最悪時刻逆転隣接組=reversed_time,
                             **{'15秒窓重複隣接組数': len(overlap), '15秒窓重複隣接組': overlap}))
        all_orders.extend(orders)
        all_trades.extend(trade_records)
    # ----------------------------------------
    # 元レポートの全口座会計値と独立計算した理想値を照合する。
    report = read_json(ROOT / 'work/wave_v50/報告データ.json')
    reference = next(item for item in report['候補'] if item['spec']['id'] == 'E01')
    names = {'利益円': 'gross_profit_yen', '損失円': 'gross_loss_yen', '収支円': 'net_yen',
             '利益枚数': 'profit_units', '損失枚数': 'loss_units', '同値枚数': 'zero_units'}
    stored = {(row['session'], row['symbol']): row for row in reference['sessions']}
    for row in sessions:
        old = stored[row['セッション'], row['銘柄']]
        for key, field in names.items():
            assert abs(row['理想'][key] - old[field]) < 1e-6
    totals = {symbol: aggregate([row for row in sessions if row['銘柄'] == symbol])
              for symbol in ('TOPIX', 'NK225')}
    result = dict(全合格=True, 対象手法='E01', セッション数=19, 口座数=38,
                  起点='条件成立・発注判断の瞬間として保存約定行を採用',
                  窓='保存約定行から15秒以内。同秒の先行行とセッション終了以降を除外。',
                  価格='保存された大型先物の有効な現在値。理想指定価格は窓候補に足さない。',
                  約定方針='注文の時刻・方向・枚数・対応建玉は固定して価格だけ置換。',
                  市場データ取得数=0, 原本変更数=0, 入力SHA256=hashes,
                  注文数=len(all_orders), 決済明細数=len(all_trades), 合計=totals,
                  セッション別=sessions)
    for name, value in (('独立計算.json', result), ('注文明細.json', all_orders), ('決済明細.json', all_trades)):
        (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(全合格=True, 注文数=len(all_orders), 決済明細数=len(all_trades), 合計=totals), ensure_ascii=False))


if __name__ == '__main__':
    main()
