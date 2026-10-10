"""既知2条件の最大下落を注文現金とFIFO在庫から独立に分解する。"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v23'
V27, V28 = HERE.parent / 'wave_v27', HERE.parent / 'wave_v28'
for folder in (OLD, V28):
    sys.path.insert(0, str(folder))
import engine_context
import managers


def read(path: Path) -> dict:
    """機能: 指定した旧仕様又は帰属結果だけを読む。

    引数: path (Path)。返り値: JSON内容 (dict)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def fingerprint(path: Path) -> str:
    """機能: 検査元の変更を検出する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fifo_change(orders: list[tuple], peak: tuple[int, int], valley: tuple[int, int], peak_price: float, valley_price: float, point: float) -> dict:
    """機能: 山までの在庫を復元し、その在庫と山後の新規の価値変化を分ける。

    引数: orders (list[tuple])、peak/valley (tuple[int,int])、peak_price/valley_price/point (float)。
    返り値: 全玉の分類別価値変化 (dict)。将来の返済台帳は用いない。
    """
    lots, changes = [], defaultdict(float)
    for boundary, order in orders:
        if boundary > valley:
            break
        _, _, campaign, side, quantity, price, reason, is_open = order
        session = boundary[0]
        if is_open:
            lots.append(dict(key=(session, int(campaign)), side=side, quantity=quantity,
                             price=price, kind='山の時点で保有' if boundary <= peak else '山の後に新規'))
        else:
            remainder = quantity
            for lot in lots:
                if lot['quantity'] <= 0 or lot['key'] != (session, int(campaign)) or lot['side'] != -side:
                    continue
                closed = min(remainder, lot['quantity'])
                if boundary > peak:
                    anchor = peak_price if lot['kind'] == '山の時点で保有' else lot['price']
                    changes[lot['kind'] + '／' + engine_context.REASONS[int(reason)]] += lot['side'] * closed * (price - anchor) * point
                lot['quantity'] -= closed
                remainder -= closed
                if remainder <= 0:
                    break
            assert remainder == 0, '返済する元在庫が不足'
    for lot in lots:
        if lot['quantity'] > 0:
            anchor = peak_price if lot['kind'] == '山の時点で保有' else lot['price']
            changes[lot['kind'] + '／谷の時点では未返済'] += lot['side'] * lot['quantity'] * (valley_price - anchor) * point
    return {key: value for key, value in changes.items() if abs(value) > 1e-8}


def inspect(identifier: str, management: dict, inputs: dict, state: dict, reported: dict) -> dict:
    """機能: 旧1条件を再生し、注文から復元した最大下落を原本行で照合する。

    引数: identifier (str)、management/inputs/state/reported (dict)。返り値: 2銘柄の独立検査記録 (dict)。
    """
    records = []
    for symbol in ('TOPIX', 'NK225'):
        rows, all_orders, offset, source = [], [], 0., []
        for key, ready in sorted(inputs.items()):
            if key[1] != symbol:
                continue
            session_number = len(source)
            source.append((key, ready))
            cfg = managers.make_config(management, symbol, ready)
            result = engine_context.run(ready, state[key], cfg, detail=True)
            count = len(ready['last'])
            cash_delta, inventory_delta = np.zeros(count), np.zeros(count)
            for order in result['orders']:
                row, side, quantity, price = int(order[0]), order[3], order[4], order[5]
                assert order[0] > order[1]
                cash_delta[row] -= side * quantity * price
                inventory_delta[row] += side * quantity
                all_orders.append(((session_number, row), order.copy()))
            cash, inventory = np.cumsum(cash_delta), np.cumsum(inventory_delta)
            equity = cash + inventory * ready['last']
            np.testing.assert_allclose(equity, result['curve'][:, 0], atol=1e-6, rtol=0)
            assert inventory[-1] == 0
            rows.append(np.column_stack((equity * cfg['point_value'] + offset,
                                         np.full(count, session_number), np.arange(count))))
            offset += cash[-1] * cfg['point_value']
        combined = np.concatenate(rows)
        highest = np.maximum.accumulate(np.maximum(combined[:, 0], 0.))
        valley_index = int(np.argmax(highest - combined[:, 0]))
        best = float(highest[valley_index])
        peak_index = int(np.argmax(combined[:valley_index + 1, 0])) if best > 0 else -1
        peak = tuple(map(int, combined[peak_index, 1:])) if peak_index >= 0 else (-1, -1)
        valley = tuple(map(int, combined[valley_index, 1:]))
        dd = best - float(combined[valley_index, 0])
        peak_price = float(source[peak[0]][1]['last'][peak[1]]) if peak_index >= 0 else 0.
        valley_price = float(source[valley[0]][1]['last'][valley[1]])
        parts = fifo_change(all_orders, peak, valley, peak_price, valley_price, cfg['point_value'])
        np.testing.assert_allclose(sum(parts.values()), -dd, atol=1e-6, rtol=0)
        expected = reported[(identifier, symbol)]
        np.testing.assert_allclose(dd, expected['最大下落円'], atol=1e-6, rtol=0)
        assert set(parts) == set(expected['分類別寄与円'])
        for name, value in parts.items():
            np.testing.assert_allclose(value, expected['分類別寄与円'][name], atol=1e-6, rtol=0)
        categories = {kind: float(sum(value for name, value in parts.items() if name.startswith(kind + '／')))
                      for kind in ('山の時点で保有', '山の後に新規')}
        boundaries = {}
        for name, boundary in (('山', peak), ('谷', valley)):
            key, data = source[boundary[0]]
            boundaries[name] = dict(session=key[0], 原本行=boundary[1], seq=int(data['seq'][boundary[1]]),
                                    time_s=float(data['time_s'][boundary[1]])) if boundary[0] >= 0 else None
        records.append(dict(手法=identifier, 銘柄=symbol, 最大下落円=dd, 分類別寄与円=parts,
                            二分類寄与円=categories, 境界=boundaries, 原本行数=len(combined),
                            注文からの時価再構築一致=True, 独立FIFO帰属一致=True))
    return records


def main() -> None:
    """機能: 新機構を一切実行せず既知2条件の帰属結果だけを独立検証する。

    引数: なし。返り値: なし (None)。API・現在データを用いない。
    """
    paths = [Path(__file__), HERE / 'drawdown_cause.py', HERE / '最大下落の帰属.json',
             OLD / 'inputs.pkl', V27 / 'directions/H019.npz', V27 / '探索条件の固定.json',
             V28 / '探索条件の固定.json', V28 / 'engine_context.py', OLD / 'managers.py']
    hashes = {str(path): fingerprint(path) for path in paths}
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    with np.load(V27 / 'directions/H019.npz') as archive:
        state = {key: archive['|'.join(key)] for key in inputs}
    rows = read(HERE / '最大下落の帰属.json')['結果']
    reported = {(row['手法'], row['銘柄']): row for row in rows}
    output = []
    for identifier, path in (('H019__D273', V27), ('H019__J116', V28)):
        management = next(m for m in read(path / '探索条件の固定.json')['managers'] if m['id'] == identifier.split('__')[1])
        output.extend(inspect(identifier, management, inputs, state, reported))
    assert hashes == {str(path): fingerprint(path) for path in paths}
    report = dict(独立一致=True, 方法='最終返済台帳を再利用せず、注文の現金・在庫とFIFOで山から谷を分解。',
                  結果=output, 新機構再生=False, 現在データ使用=False, API取得数=0, 参照SHA256=hashes)
    (HERE / 'drawdown_independent_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 最大下落の帰属・独立確認', '', '注文から現金・在庫・時価曲線を再構築し、山と谷を原本行順で特定した。返済台帳とは別にFIFOの在庫追跡で寄与を再計算した。', '',
             '|条件|銘柄|最大下落|山時点の玉の価値変化|山後新規の価値変化|', '|---|---|---:|---:|---:|']
    for row in output:
        category = row['二分類寄与円']
        lines.append(f'|{row["手法"]}|{row["銘柄"]}|{row["最大下落円"]:,.0f}|{category["山の時点で保有"]:+,.0f}|{category["山の後に新規"]:+,.0f}|')
    lines += ['', '4件とも根拠側の全分類と一致し、明確な会計上の欠陥は見つからなかった。TOPIXの最大下落は既存玉の返上だけでなく後続新規の損失も含むため、残玉保護だけを原因・解決策と断定できない。',
              '', 'これは既知の最大下落区間の会計的内訳であり、将来の原因や新保護の改善を示すものではない。新機構・現在データ・APIは未使用。', '']
    (HERE / 'drawdown_independent_audit.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(dict(独立一致=True, 結果=[{k: r[k] for k in ('手法', '銘柄', '最大下落円', '二分類寄与円')} for r in output]), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
