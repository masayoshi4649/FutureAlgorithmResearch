"""保存された早期参加の時刻と損失箇所を、元板の気配へ戻って診断する。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import pickle

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JST = timezone(timedelta(hours=9))
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit_early_diagnosis')
import early139


def read(path):
    """
    機能: 保存資料を読む。
    引数: path(Path)は位置。
    返り値: dict又はlistは内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def stamp(value):
    """
    機能: 原価格時計を日本時間へ表示する。
    引数: value(float)はUNIX秒。
    返り値: strは日本時間の時分秒。
    """
    return datetime.fromtimestamp(float(value), JST).strftime('%H:%M:%S')


def close_reasons(orders, symbol):
    """
    機能: 新規費用を返済数量へ配賦して、出口理由ごとの費用後損益を集計する。
    引数: orders(ndarray)、symbol(str)は保存注文と銘柄。
    返り値: list[dict]は理由・初回追撃別の件数、枚数、費用前後。
    """
    multiplier = 100. if symbol == 'NK225' else 1000.
    tickets = {}
    groups = defaultdict(lambda: dict(orders=0, quantity=0, gross=0., fees=0., net=0.))
    for o in orders:
        pid, side, quantity, uid, fee = int(o[2]), int(o[3]), int(o[4]), int(o[8]), int(o[9])
        key = pid, uid
        if o[7]:
            tickets[key] = [quantity, float(o[5]), side, fee]
        else:
            ticket = tickets[key]
            opening = ticket[3] * quantity // ticket[0]
            ticket[3] -= opening
            ticket[0] -= quantity
            gain = ticket[2] * (o[5] - ticket[1]) * quantity * multiplier
            item = groups[(int(o[6]), '初回' if uid == 0 else '追撃')]
            item['orders'] += 1
            item['quantity'] += quantity
            item['gross'] += gain
            item['fees'] += opening + fee
            item['net'] += gain - opening - fee
    assert all(t[0] == t[3] == 0 for t in tickets.values())
    labels = {1391: '利益追尾', 1392: '損失幅到達', 1399: '早期窓終了'}
    return [dict(reason=reason, label=labels.get(reason, str(reason)), role=role, **value)
            for (reason, role), value in groups.items()]


def details(orders, parents, ready, raw, symbol):
    """
    機能: 保存注文の建値・初期R・当時支持と実際の値動きを玉別に記録する。
    引数: orders(ndarray)、parents(list[dict])、ready/raw(dict)、symbol(str)は保存結果と因果特徴。
    返り値: list[dict]は親の損益と各玉の当時気配・順逆行・退出後推移。
    """
    ts, quote = ready['time_s'], ready['quotes']
    risk_floor = 20. if symbol == 'NK225' else 1.
    result = []
    for parent in parents:
        pid = parent['id']
        rows = orders[orders[:, 2] == pid]
        first = rows[(rows[:, 7] == 1) & (rows[:, 8] == 0)][0]
        initial_decision = int(first[1])
        risk = max(risk_floor, ready['atr'][initial_decision])
        legs = []
        for uid in np.unique(rows[:, 8]).astype(int):
            part = rows[rows[:, 8] == uid]
            entry = part[part[:, 7] == 1][0]
            exits = part[part[:, 7] == 0]
            i, decision, side = int(entry[0]), int(entry[1]), int(entry[3])
            end = int(exits[-1, 0])
            mark = quote['bid'] if side > 0 else quote['ask']
            good = quote['quote_valid'][i:end + 1]
            moves = side * (mark[i:end + 1][good] - entry[5])
            lower = int(np.searchsorted(ts, ts[decision] - 300., side='left'))
            past = ready['price'][lower:decision + 1]
            past = past[np.isfinite(past)]
            width = float(np.max(past) - np.min(past)) if len(past) else 0.
            position = float((entry[5] - np.min(past)) / width) if side > 0 and width else float((np.max(past) - entry[5]) / width) if width else None
            future_end = int(np.searchsorted(ts, min(ts[end] + 300., ready['window_end']), side='right'))
            after = side * (mark[end:future_end] - entry[5])
            after = after[np.isfinite(after)]
            legnet = parent['legs'][str(uid)]
            m = ready['market'][decision]
            legs.append(dict(uid=int(uid), role='初回' if uid == 0 else '追撃',
                decision=stamp(ts[decision]), entry_time=stamp(ts[i]), entry_price=float(entry[5]), quantity=int(entry[4]),
                exit_time=stamp(ts[end]), exit_prices=[float(o[5]) for o in exits], reasons=[int(o[6]) for o in exits],
                duration_seconds=float(ts[end]-ts[i]), net=legnet['net'], gross=legnet['gross'], fees=legnet['fees'],
                R=float(risk), stop_width=float((1.5 if uid == 0 else 1.) * risk),
                maximum_favorable=float(np.max(moves)), maximum_adverse=float(np.min(moves)),
                prior5min_range=width, directional_position_in_prior5min=position,
                decision_bid=float(quote['bid'][decision]), decision_ask=float(quote['ask'][decision]),
                decision_raw_seq=int(raw['seq'][decision]), own30_R=float(side*m[4]), own120_R=float(side*m[5]),
                peer30_R=float(side*m[6]), peer120_R=float(side*m[7]),
                after_exit_5min_reached_entry=bool(len(after) and np.max(after) >= 0.),
                after_exit_5min_favorable=float(np.max(after)) if len(after) else None))
        result.append(dict(parent=pid, side=parent['side'], net=parent['net'], gross=parent['gross'], fees=parent['fees'],
                           entry_time=stamp(ts[int(first[0])]), exit_time=stamp(ts[int(rows[-1, 0])]), legs=legs))
    return result


def main():
    """
    機能: 全条件の参入時計、E01/E15の費用・役割・出口と最悪場を保存情報だけで集計する。
    引数: なし。
    返り値: None。新規金融判定は実行せず、入力特徴の非金融再構成だけを使用する。
    """
    results = read(HERE / 'early_results/結果.json')
    packets = read(HERE / 'manifest139.json')['packets'] + read(HERE / 'manifest139_extra.json')['packets']
    known = set(read(HERE / 'manifest139.json')['sessions'])
    cache = {(r['session'], r['symbol']): r for r in results['cache']}
    rows = {(r['session'], r['symbol'], r['method']): r for r in results['rows']}
    worst = []
    for symbol in ('NK225', 'TOPIX'):
        for method in ('E01', 'E15'):
            selected = [r for r in results['rows'] if r['symbol'] == symbol and r['method'] == method]
            worst += [(r['session'], symbol, method) for r in sorted(selected, key=lambda r:r['net'])[:3]]
    coverage = []
    reason_rows = []
    bad_cases = []
    for packetref in packets:
        scene = packetref['session']
        with Path(packetref['path']).open('rb') as stream:
            packet = pickle.load(stream)
        prepared = early139.prepare(packet) if any(w[0] == scene for w in worst) else None
        for symbol in ('NK225', 'TOPIX'):
            raw = packet['inputs'][(scene, symbol)]
            ts = raw['time_s']
            with np.load(ROOT / cache[(scene, symbol)]['path'], allow_pickle=False) as arrays:
                for method in arrays.files:
                    orders = arrays[method]
                    row = rows[(scene, symbol, method)]
                    initial = orders[(orders[:, 7] == 1) & (orders[:, 8] == 0) & (orders[:, 2] >= 20000)]
                    parents = [p for p in row['parents'] if p['id'] >= 20000]
                    first = float(ts[int(initial[0, 0])]) if len(initial) else None
                    coverage.append(dict(session=scene, symbol=symbol, method=method, kind=row['kind'],
                        scope='既知45場' if scene in known else '追加2場', early_parents=len(initial),
                        first_time=stamp(first) if first is not None else None,
                        first_minutes_after_start=(first-raw['start'])/60. if first is not None else None,
                        early_gross=sum(p['gross'] for p in parents), early_fees=sum(p['fees'] for p in parents),
                        early_net=sum(p['net'] for p in parents), total_net=row['net']))
                    if method in ('E01', 'E15'):
                        for r in close_reasons(orders, symbol):
                            reason_rows.append(dict(session=scene, symbol=symbol, method=method, kind=row['kind'], **r))
                    if (scene, symbol, method) in worst:
                        bad_cases.append(dict(session=scene, symbol=symbol, method=method, net=row['net'],
                            gross=row['gross'], fees=row['fees'], parents=details(orders, row['parents'], prepared[symbol], raw, symbol)))
        print(scene + ' 保存早期注文の時計・損失診断完了', flush=True)

    # ----------------------------------------
    # 無取引は初回時計の平均に埋め込まず、参入場数と分母を別に残す。
    groups = defaultdict(list)
    for row in coverage:
        for scope in (row['scope'], '全47場'):
            groups[(scope, row['symbol'], row['method'], row['kind'])].append(row)
    summary = []
    for (scope, symbol, method, kind), selected in groups.items():
        values = [r['first_minutes_after_start'] for r in selected if r['first_minutes_after_start'] is not None]
        summary.append(dict(scope=scope, symbol=symbol, method=method, kind=kind, sessions=len(selected),
            participating_sessions=len(values), early_parents=sum(r['early_parents'] for r in selected),
            first_minutes_min=float(np.min(values)) if values else None,
            first_minutes_median=float(np.median(values)) if values else None,
            first_minutes_max=float(np.max(values)) if values else None,
            early_gross=sum(r['early_gross'] for r in selected), early_fees=sum(r['early_fees'] for r in selected),
            early_net=sum(r['early_net'] for r in selected), total_net=sum(r['total_net'] for r in selected)))
    reasons = defaultdict(lambda:dict(orders=0, quantity=0, gross=0., fees=0., net=0.))
    for row in reason_rows:
        key = row['symbol'], row['method'], row['kind'], row['role'], row['label']
        for field in reasons[key]:
            reasons[key][field] += row[field]
    reason_summary = [dict(symbol=k[0], method=k[1], kind=k[2], role=k[3], reason=k[4], **v) for k,v in reasons.items()]
    report = dict(coverage=coverage, summary=summary, exit_summary=reason_summary, worst_sessions=bad_cases,
                  financial_replays=0, API=0, real_orders=0,
                  limitation='入口時点の値と返済後の推移を区別した事後診断。5分後の戻りは当時の売買条件には利用していない。')
    with (HERE / 'early_diagnosis139.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    lines = ['# 早期参加の保存会計と損失箇所', '', '金融再生0。E01/E15各々・銘柄別の最悪3場を調査。退出後5分の戻りは事後診断のみ。', '',
             '|手法|銘柄|時間帯|参入場/全場|初回中央値（開始後分）|費用前|費用|収支|', '|---|---|---|---:|---:|---:|---:|---:|']
    for row in summary:
        if row['scope'] == '全47場' and row['method'] in ('E01', 'E15'):
            lines.append(f"|{row['method']}|{row['symbol']}|{row['kind']}|{row['participating_sessions']}/{row['sessions']}|{row['first_minutes_median']:.1f}|{row['early_gross']:,.0f}|{row['early_fees']:,.0f}|{row['early_net']:,.0f}|")
    for case in bad_cases:
        lines += ['', f"## {case['method']} {case['symbol']} {case['session']}：{case['net']:,.0f}円", '',
                  '|親|方向|初回→最終返済|収支|最悪玉の理由|建値→返済|初期R|玉の最高順行|最低逆行|', '|---:|---|---|---:|---|---|---:|---:|---:|']
        for p in sorted(case['parents'], key=lambda p:p['net'])[:3]:
            leg=min(p['legs'], key=lambda l:l['net'])
            lines.append(f"|{p['parent']}|{'買' if p['side']>0 else '売'}|{p['entry_time']}→{p['exit_time']}|{p['net']:,.0f}|{leg['role']} {leg['reasons']}|{leg['entry_price']}→{leg['exit_prices']}|{leg['R']:.2f}|{leg['maximum_favorable']:.2f}|{leg['maximum_adverse']:.2f}|")
    (HERE / 'early_diagnosis139.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('早期診断保存完了', flush=True)


if __name__ == '__main__':
    main()
