"""旧主案と連敗停止案の最大下落を、全玉の時価から分解する。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import pickle
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
V28 = HERE.parent / 'wave_v28'
V27 = HERE.parent / 'wave_v27'
sys.path.insert(0, str(V28))
import context_runner as previous


def stamp(value: float) -> str:
    """機能: 原本時刻を日本時間へ整形する。

    引数: value (float) はUNIX秒。返り値: 日時 (str)。
    """
    return datetime.fromtimestamp(float(value), ZoneInfo('Asia/Tokyo')).isoformat()


def audit(identifier: str, management: dict, inputs: dict, expected: dict) -> list[dict]:
    """機能: 二つの既知仕様の最大下落を再積分し、区間内の損益を全玉へ帰属する。

    引数: identifier (str)、management/inputs/expected (dict)。返り値: 銘柄別の分解 (list[dict])。
    新しい保護機構、現在データ、探索順位変更は使用しない。
    """
    direction = np.load(V27 / 'directions' / 'H019.npz')
    result = []
    for symbol in ('TOPIX', 'NK225'):
        offset, stacks, pieces, sources = 0., [], [], []
        for key, ready in sorted(inputs.items()):
            session, own_symbol = key
            if own_symbol != symbol:
                continue
            config = previous.managers.make_config(management, symbol, ready)
            replay = previous.engine.run(ready, direction[f'{session}|{symbol}'], config, detail=True)
            point = config['point_value']
            session_index = len(sources)
            sources.append((session, ready, replay))
            curve = replay['curve']
            stacks.append(np.column_stack((ready['time_s'], curve[:, 0] * point + offset,
                                           curve[:, 1] * point + offset,
                                           np.full(len(curve), session_index), np.arange(len(curve)))))
            for trade in replay['trades']:
                pieces.append((session, session_index, ready, trade, point))
            offset += replay['stats'][0] * point
        combined = np.concatenate(stacks)
        maximum = np.maximum.accumulate(np.maximum(combined[:, 1], 0.))
        valley = int(np.argmax(maximum - combined[:, 1]))
        peak = int(np.argmax(combined[:valley + 1, 1]))
        initial_peak = combined[peak, 1] < 0
        peak_equity = 0. if initial_peak else float(combined[peak, 1])
        peak_time = float(combined[0, 0] - 1 if initial_peak else combined[peak, 0])
        valley_time = float(combined[valley, 0])
        peak_boundary = (-1, -1) if initial_peak else tuple(map(int, combined[peak, 3:5]))
        valley_boundary = tuple(map(int, combined[valley, 3:5]))
        dd = peak_equity - float(combined[valley, 1])
        np.testing.assert_allclose(dd, expected[symbol]['drawdown_yen'], atol=1e-7)
        np.testing.assert_allclose(offset, expected[symbol]['net_yen'], atol=1e-7)
        parts, by_reason = [], defaultdict(float)
        for session, session_index, ready, trade, point in pieces:
            entry, exit_row = int(trade[6]), int(trade[7])
            entry_t, exit_t = float(ready['time_s'][entry]), float(ready['time_s'][exit_row])
            direction_value, qty, entry_price, exit_price = map(float, trade[2:6])

            def marked(boundary: tuple[int, int]) -> float:
                """機能: 特定境界までの一部返済単位の時価損益を計算する。

                引数: boundary (tuple[int,int]) はセッション順と原本行。返り値: 時価損益の円額 (float)。
                """
                if boundary < (session_index, entry):
                    return 0.
                if boundary >= (session_index, exit_row):
                    return direction_value * qty * (exit_price - entry_price) * point
                row = boundary[1]
                return direction_value * qty * (float(ready['last'][row]) - entry_price) * point

            change = marked(valley_boundary) - marked(peak_boundary)
            if not change:
                continue
            closed = (session_index, exit_row) <= valley_boundary
            reason = previous.engine.REASONS[int(trade[9])] if closed else '谷の時点では未返済'
            timing = '山の時点で保有' if (session_index, entry) <= peak_boundary < (session_index, exit_row) else '山の後に新規'
            by_reason[timing + '／' + reason] += change
            parts.append({'session': session, '方向': int(direction_value), '枚数': int(qty),
                          '新規': stamp(entry_t), '谷までに返済': closed,
                          '区間損益円': change, '帰属': timing, '返済分類': reason})
        total = sum(p['区間損益円'] for p in parts)
        np.testing.assert_allclose(total, -dd, atol=1e-6)
        realized_at_peak = 0. if initial_peak else float(combined[peak, 2])
        realized_delta = float(combined[valley, 2]) - realized_at_peak
        result.append({'手法': identifier, '銘柄': symbol, '山': stamp(peak_time), '谷': stamp(valley_time),
                       '最大下落円': dd, '山の累積時価円': peak_equity,
                       '谷の累積時価円': float(combined[valley, 1]),
                       '区間実現損益差円': realized_delta, '区間含み損益差円': -dd - realized_delta,
                       '全玉寄与合計円': total, '分類別寄与円': dict(by_reason),
                       '全玉寄与': sorted(parts, key=lambda p: p['区間損益円']),
                       '既存最大下落と収支一致': True})
    return result


def main() -> None:
    """機能: 旧２条件だけを再現し、最大下落の帰属を保存する。

    引数: なし。返り値: なし (None)。新しい保護条件の成績は読まない。
    """
    inputs = pickle.loads((HERE.parent / 'wave_v23' / 'inputs.pkl').read_bytes())
    fixed27 = previous.read(V27 / '探索条件の固定.json')
    fixed28 = previous.read(V28 / '探索条件の固定.json')
    c27 = previous.read(V27 / '全条件の期間集計.json.gz')
    c28 = previous.read(V28 / '全条件の期間集計.json.gz')
    rows = []
    for identifier, fixed, candidates in (('H019__D273', fixed27, c27), ('H019__J116', fixed28, c28)):
        expected = next(c for c in candidates if c['id'] == identifier)
        management = next(m for m in fixed['managers'] if m['id'] == expected['manager_id'])
        rows.extend(audit(identifier, management, inputs, expected['symbols']))
    output = {'対象': '旧主案と連敗停止を追加した既知条件だけ。新機構の損益は未計算。',
              '現在データ使用': False, 'API取得': 0, '結果': rows,
              '限界': '最大下落１区間の会計的帰属であり、将来の原因や新規保護の改善を証明しない。'}
    previous.save(HERE / '最大下落の帰属.json', output)
    lines = ['# 既知２条件の最大下落の帰属', '',
             '新機構の成績を見る前に、旧２条件の最大下落を注文と時価から分解した。現在データは不使用。', '',
             '| 手法 | 銘柄 | 山 | 谷 | 最大下落 | 実現差 | 含み差 |', '|---|---|---|---|---:|---:|---:|']
    for row in rows:
        lines.append(f"|{row['手法']}|{row['銘柄']}|{row['山']}|{row['谷']}|{row['最大下落円']:,.0f}|{row['区間実現損益差円']:+,.0f}|{row['区間含み損益差円']:+,.0f}|")
        print(json.dumps({k: v for k, v in row.items() if k not in ('全玉寄与',)}, ensure_ascii=False), flush=True)
    lines += ['', '各玉の寄与を全件足すと、最大下落のマイナス額と一致する。返済分類は谷までに決済した場合だけを用い、谷以後の返済理由を原因へ混ぜない。',
              '同じ時刻の複数原本行があるため、境界はセッション順と原本行で特定し、同時刻の後の行を混ぜない。全時価曲線・既存集計と一致することを必須とした。',
              '', '全玉の分類と寄与は [JSON](最大下落の帰属.json)。単一の下落区間の説明であり、同じ形が繰り返されるとの予測ではない。']
    (HERE / '最大下落の帰属.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
