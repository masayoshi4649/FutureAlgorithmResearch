"""凍結済み注文と特徴だけを照合し、時計・準備・追撃の実装を監査する。売買核は呼ばない。"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
import pickle
import sys
from zoneinfo import ZoneInfo
import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / 'work/aggressive140_20261024'
sys.path.insert(0, str(OLD))
import active140_v2 as active


def stamp(value):
    """
    機能: 保存された価格時計を日本時間で表示し、受信時計と混同しない。
    引数: value(float)はepoch。
    返り値: strはISO8601の価格時計表示。
    """
    return datetime.fromtimestamp(float(value), ZoneInfo('Asia/Tokyo')).isoformat()


def clean(value):
    """
    機能: 未測定値をJSONのnullへ変換する。
    引数: value(object)は入れ子の監査値。
    返り値: objectは有限数値とnullだけを持つ値。
    """
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    return None if isinstance(value, float) and not np.isfinite(value) else value


def first_clock(times, mask):
    """
    機能: 条件が最初に既知となった価格時計を返す。
    引数: times/mask(ndarray)は原行の時計と資格。
    返り値: str|Noneは時計表示又は未成立。
    """
    rows = np.flatnonzero(mask)
    return stamp(times[rows[0]]) if len(rows) else None


def order_audit(orders, ready, quote, features, method):
    """
    機能: 保存済み親の発注条件・原行順・初回玉の含み益到達を読み取る。
    引数: orders/features(ndarray)、ready/quote(dict)、method(str)は保存注文と当時特徴。
    返り値: list[dict]は親単位診断。入口や返済を再選択せず、未記録armRは復元しない。
    """
    times = ready['time_s']
    good = quote['quote_valid'] & np.isfinite(quote['bid']) & np.isfinite(quote['ask']) & (quote['bid'] > 0.) & (quote['ask'] > quote['bid'])
    result = []
    for parent in np.unique(orders[:, 2]) if len(orders) else []:
        rows = orders[orders[:, 2] == parent]
        first = rows[rows[:, 7] == 1][0]
        begin, decision, end = int(first[0]), int(first[1]), int(rows[-1, 0])
        side, price = int(first[3]), float(first[5])
        indexes = np.flatnonzero(good[begin:end+1])+begin
        liquidate = quote['bid'] if side > 0 else quote['ask']
        moves = side*(liquidate[indexes]-price)
        maxrow = indexes[int(np.argmax(moves))]
        # 現在Rと準備時の固定Rは別。保存列から分からない固定Rを補わない。
        f = features[decision]
        group_start = int(np.searchsorted(times, times[decision], side='left'))
        group_end = int(np.searchsorted(times, times[decision], side='right'))
        events = []
        for row in rows:
            i, d = int(row[0]), int(row[1])
            events.append(dict(raw_row=i, raw_seq=int(ready['seq'][i]), decision_row=d,
                decision_seq=int(ready['seq'][d]), clock=stamp(times[i]), decision_clock=stamp(times[d]),
                clock_delay_seconds=float(times[i]-times[d]), original_sequence_gap=int(ready['seq'][i]-ready['seq'][d]),
                side=int(row[3]), quantity=int(row[4]), price=float(row[5]), reason=int(row[6]),
                new=bool(row[7]), uid=int(row[8]), fee=float(row[9])))
        result.append(dict(method=method, parent=int(parent), is_active=parent >= 3_000_000,
            first_clock=stamp(times[begin]), direction=side, initial_price=price, initial_quantity=int(first[4]),
            new_quantity=int(rows[rows[:, 7] == 1, 4].sum()),
            decision_current_R=float(f[9]), fixed_setup_R=None,
            fixed_setup_R_reason='準備時arm_riskは保存注文に無い。判断行のRで代用していない。',
            decision_efficiency=float(f[2]), decision_band_upper=float(f[0]), decision_band_lower=float(f[1]),
            decision_change30=float(f[12]), decision_peer_change30=float(f[20]),
            initial_maximum_favorable_points=float(moves.max()), initial_maximum_adverse_points=float(moves.min()),
            initial_favorable_peak_clock=stamp(times[maxrow]),
            decision_same_clock_rows=group_end-group_start,
            decision_same_clock_position=decision-group_start, events=events))
    return result


def main():
    """
    機能: 追加3場の保存注文と非金融特徴を全件読み、実装監査資料を新規保存する。
    引数: なし。
    返り値: None。金融再生・API・原本変更を行わず、既存証拠の上書きを拒否する。
    """
    manifest = json.loads((OLD/'inputs/input_manifest.json').read_text(encoding='utf-8-sig'))
    records = []
    for item in manifest['packets']:
        path = ROOT/item['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']
        packet = pickle.loads(path.read_bytes())
        scene = packet['session']
        prepared = active.prepare(packet, 40)
        for symbol in ('NK225', 'TOPIX'):
            r, q, a = packet['inputs'][(scene, symbol)], packet['quotes'][(scene, symbol)], prepared[symbol]['features']
            t = r['time_s']
            valid = q['quote_valid'] & np.isfinite(q['bid']) & np.isfinite(q['ask']) & (q['bid'] > 0.) & (q['ask'] > q['bid'])
            own_known = valid & np.isfinite(a[:, :14]).all(axis=1)
            both_known = own_known & np.isfinite(a[:, 14:24]).all(axis=1)
            baseline = OLD/'new/measurement'/f'{symbol}_{scene}.npz'
            extra = OLD/'round2_new/measurement'/f'{symbol}_{scene}.npz'
            with np.load(baseline) as saved:
                base = saved['B5'].copy()
                candidate = saved['C33'].copy() if symbol == 'TOPIX' else None
            if symbol == 'NK225':
                with np.load(extra) as saved:
                    candidate = saved['S36'].copy()
            records.append(dict(session=scene, symbol=symbol, rows=len(t), unique_price_clocks=len(np.unique(t)),
                repeated_price_clock_rows=int(np.count_nonzero(np.diff(t) == 0.)),
                price_clock_gaps_over_15_seconds=int(np.count_nonzero(np.diff(t) > 15.)),
                first_normal_bbo=first_clock(t, valid), first_published_atr=first_clock(t, np.isfinite(r['atr'])),
                first_own40_ready=first_clock(t, own_known), first_both40_ready=first_clock(t, both_known),
                start=stamp(r['start']), force_close=stamp(r['limit']),
                active_risk_budget_yen=float(2.*40.*r['tick']*(100. if symbol == 'NK225' else 1000.)),
                parents=order_audit(base, r, q, a, 'B5')+order_audit(candidate, r, q, a, 'C33' if symbol == 'TOPIX' else 'S36')))
    sources = ('active140_v2.py', 'run140_v2.py', 'round2_140.py')
    value = dict(records=records, source_sha256={s:hashlib.sha256((OLD/s).read_bytes()).hexdigest() for s in sources},
                 financial_replays=0, new_orders=0, API=0,
                 notes=['価格時計は受信時計ではない。時計差0秒は実遅延0秒を意味しない。',
                        'saved注文の採否・数量・約定・損益は変更していない。',
                        '当該3場は00140で既見。今後の改善に用いた場合は開発標本である。'])
    dest = HERE/'実装監査141.json'
    with dest.open('x', encoding='utf-8') as stream:
        json.dump(clean(value), stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(dict(sessions=3, symbol_sessions=len(records), financial_replays=0,
        active_parents=int(sum(p['is_active'] for r in records for p in r['parents']))), ensure_ascii=False))


if __name__ == '__main__':
    main()
