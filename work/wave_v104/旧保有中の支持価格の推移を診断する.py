"""既に完結した旧C/R自己入口の保有経路を調べ、仮説と出口のずれを測る。"""

import gzip
import math
from pathlib import Path
import pickle

import numpy as np

import base


HERE = Path(__file__).resolve().parent
PREVIOUS = base.PREVIOUS


def first(mask: np.ndarray, begin: int) -> int | None:
    """
    機能: 診断対象の既知経路から最初の事象原行を得る。
    引数: mask(ndarray[bool])、begin(int)は事象列と起点。
    返り値: int|Noneは最初の正常行。売買判断や新しい約定価格には使わない。
    """
    rows = np.flatnonzero(mask)
    return begin+int(rows[0]) if len(rows) else None


def run() -> None:
    """
    機能: 旧128口座の実完結親について支持境界と順行の時系列を集計する。
    引数: なし。
    返り値: None。診断JSONのみを保存し、104金融を再生しない。
    """
    target = HERE/'旧自己入口の支持破れと順行の診断.json'
    assert not target.exists()
    proof = base.lineage()
    before = {str(path.relative_to(base.ROOT)): base.digest(path) for path in
        (Path(__file__), HERE/'数値設計案.json', HERE/'catalog.py')}
    prepared = base.load_prepared()
    loader = base.module('104診断の不変活動cache', PREVIOUS/'activity/data.py')
    results = {ident: base.read(PREVIOUS/'finance/results'/(ident+'.json'))
               for ident in ('C_OWN', 'R_OWN')}
    rows = []
    for session in proof['sessions']:
        payload = loader.load_session(session)
        for ident in ('C_OWN', 'R_OWN'):
            family = ident[0]
            for symbol in ('TOPIX', 'NK225'):
                item = results[ident]['ledgers'][session+'|'+symbol]
                path = base.ROOT/item['path']
                saved = path.read_bytes()
                import hashlib
                assert hashlib.sha256(saved).hexdigest() == item['SHA256']
                ledger = pickle.loads(gzip.decompress(saved))
                record = prepared[session, symbol]['record']
                signal = prepared[session, symbol]['signal']
                account = payload['accounts'][symbol]
                packet = account['packets'][family+'1']
                info = {value['parent_id']: value for value in ledger['raw_entry_diagnostics']}
                quote_valid = record['quote_valid']
                qok = (quote_valid & np.isfinite(record['bid']) & np.isfinite(record['ask'])
                       & (record['bid'] > 0) & (record['ask'] > record['bid']))
                tick, multiplier = record['tick'], 1000. if symbol == 'TOPIX' else 10.
                for parent in ledger['trades']:
                    ident_parent, side, quantity = int(parent[0]), int(parent[4]), int(parent[5])
                    fill, end, entry_price = int(parent[2]), int(parent[3]), float(parent[6])
                    metadata = info[ident_parent]
                    source = metadata['episode']['lineage'][0]['own']['last_event_index']
                    support = float(packet['events'][source, 15 if family == 'C' else 17])
                    assert np.isfinite(support)
                    liquidation = (record['bid'] if side == 1 else record['ask'])[fill:end+1]
                    valid = qok[fill:end+1]
                    direction_progress = side*(liquidation-entry_price)
                    activation = {}
                    for width in (1, 2, 4):
                        bound = support-side*width*tick
                        hit = first(valid & (side*(liquidation-bound) <= 1e-8), fill)
                        activation[str(width)] = None if hit is None else dict(row=hit,
                            raw_seq=int(record['seq'][hit]), time=float(record['time_s'][hit]),
                            seconds_after_fill=float(record['time_s'][hit]-record['time_s'][fill]),
                            net_liquidation=side*(float((record['bid'] if side == 1 else record['ask'])[hit])-entry_price)*quantity*multiplier-parent[8]-parent[9])
                    fee_width = math.ceil((parent[8]+parent[9])/(quantity*multiplier*tick)-1e-10)*tick
                    favourable = first(valid & (direction_progress >= fee_width+2*tick-1e-8), fill)
                    zero = first(valid & (direction_progress >= 0.-1e-8), fill)
                    outcome = '利益' if parent[11] > 1e-5 else '損失' if parent[11] < -1e-5 else '同値'
                    rows.append(dict(method=ident, session=session, symbol=symbol, parent_id=ident_parent,
                        outcome=outcome, net=float(parent[11]), entry_price=entry_price,
                        support_price=support, decision_raw_seq=metadata['decision_raw_seq'],
                        fill_raw_seq=metadata['fill_raw_seq'], initial_support_distance_ticks=side*(entry_price-support)/tick,
                        fill_time=float(record['time_s'][fill]), exit_time=float(record['time_s'][end]),
                        held_seconds=float(record['time_s'][end]-record['time_s'][fill]),
                        support_boundaries=activation, first_fee_plus2_row=favourable, first_nonnegative_price_row=zero,
                        first_fee_plus2_time=None if favourable is None else float(record['time_s'][favourable]),
                        mfe_ticks=float(np.max(direction_progress[valid])/tick) if valid.any() else None))
    totals = {}
    for ident in results:
        totals[ident] = {}
        for symbol in ('TOPIX', 'NK225'):
            account = [row for row in rows if row['method'] == ident and row['symbol'] == symbol]
            assert len(account) == results[ident]['periods']['全32'][symbol]['campaigns']
            totals[ident][symbol] = {}
            for outcome in ('利益', '損失', '同値'):
                chosen = [row for row in account if row['outcome'] == outcome]
                totals[ident][symbol][outcome] = dict(count=len(chosen), net=sum(row['net'] for row in chosen),
                    median_hold_seconds=float(np.median([row['held_seconds'] for row in chosen])) if chosen else None,
                    fee_plus2_reached=sum(row['first_fee_plus2_row'] is not None for row in chosen),
                    boundaries={str(width): dict(crossed=sum(row['support_boundaries'][str(width)] is not None for row in chosen),
                        crossed_before_fee_plus2=sum(row['support_boundaries'][str(width)] is not None and
                            (row['first_fee_plus2_row'] is None or row['support_boundaries'][str(width)]['row'] < row['first_fee_plus2_row']) for row in chosen),
                        first_at_fill=sum(row['support_boundaries'][str(width)] is not None and
                            row['support_boundaries'][str(width)]['seconds_after_fill'] == 0. for row in chosen))
                        for width in (1, 2, 4)})
    assert before == {name: base.digest(base.ROOT/name) for name in before}
    answer = dict(全合格=True, source_SHA256=before, 実完結親数=len(rows),
        旧口座数=128, activity一場読取回数=32, totals=totals, rows=rows,
        売買判断に診断ラベル使用=False, 新金融再生=0, API取得=0, 実注文=0,
        限界='既保有期間内の診断であり、境界で決済した反実仮想戦略の損益ではない。正常quoteの当時清算額から将来約定の収益を保証しない。'
    )
    import json
    target.write_text(json.dumps(answer, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print('旧完結'+str(len(rows))+'親の支持境界診断を保存。104金融0', flush=True)


if __name__ == '__main__':
    run()
