"""00165の保存会計と原板可用性を調べる。新しい売買は実行しない。"""

from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import math
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))


def sha(path: Path) -> str:
    """保存ファイルの内容指紋を求める。

    引数: path(Path)。返り値: SHA256文字列(str)。
    """
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def iso(at: float) -> str:
    """価格時計を日本時間へ表示変換する。

    引数: at(float)。返り値: 日本時間文字列(str)。
    """
    return datetime.fromtimestamp(at, JST).isoformat()


def dump(name: str, obj: object) -> None:
    """監査結果だけをUTF-8で保存する。

    引数: name(str)、obj(JSON変換可能)。返り値: None。
    """
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def snapshot(value: dict) -> dict:
    """保存時価断面に日本時間を付す。

    引数: value(dict)。返り値: 時刻付きコピー(dict)。
    """
    return dict(value, jst=iso(value['Time']))


def inventory(manifest: dict) -> dict:
    """既存入力のメタデータと保存場増分だけを照合する。

    引数: manifest(dict)。返り値: 指紋再利用と増分の根拠(dict)。
    """
    checked = []
    for scene in manifest['sessions']:
        for old in scene['fingerprints']:
            p = Path(old['path']); st = p.stat()
            equal = st.st_size == old['bytes'] and st.st_mtime_ns == old['mtime_ns']
            got = old['sha256'] if equal else sha(p)
            assert got == old['sha256'], ('既存原資料が変更', str(p))
            checked.append({'path': str(p), 'bytes': st.st_size, 'mtime_ns': st.st_mtime_ns,
                            'sha256': got, 'size_mtime_unchanged': equal,
                            'hash_read_this_run': not equal})
    old_sessions = {s['session'] for s in manifest['sessions']}
    markets = {}
    for ref in ['NK225', 'TOPIX']:
        base = ROOT.parent / 'JP_OSE_Data' / 'future' / ref
        ss = sorted(p for p in base.iterdir() if p.is_dir() and ('_Day' in p.name or '_Night' in p.name))
        markets[ref] = {'sessions': len(ss), 'days': sum(p.name.endswith('_Day') for p in ss),
                        'nights': sum(p.name.endswith('_Night') for p in ss),
                        'latest_day': max(p.name for p in ss if p.name.endswith('_Day')),
                        'latest_night': max(p.name for p in ss if p.name.endswith('_Night')),
                        'added': [{'session': p.name, 'qualified_for_this_study': False,
                                   'files': [{'path': str(q), 'bytes': q.stat().st_size,
                                              'mtime_ns': q.stat().st_mtime_ns}
                                             for q in sorted(p.iterdir()) if q.is_file()]}
                                  for p in ss if p.name not in old_sessions]}
    return {'created_at': datetime.now(JST).isoformat(), 'financial_replays': 0,
            'old_manifest': str(ROOT / 'work/research164/inputs164.json'),
            'old_manifest_sha256': sha(ROOT / 'work/research164/inputs164.json'),
            'existing_inputs': checked, 'markets': markets,
            'study_scope': '既存27完了Night。追加10/28Dayは今回金融入力に含めず終端資格を付けない。',
            'limitation': 'size/mtime一致の既存ファイルは既登録SHAを再利用。下記5夜NK225は別途全読SHA確認。'}


def accounting(scenes: list[dict]) -> tuple[dict, dict]:
    """旧U00の全保存約定を時間・親・玉に分けて読む。

    引数: scenes(list[dict])。返り値: 集計結果と各場ケース(dict,dict)。
    """
    cases = {}; rows = []; lots = []; by_hour = defaultdict(lambda: Counter())
    sources = []
    for s in scenes:
        sub = 'train_validation' if s['split'] in ['train', 'validation'] else 'confirmation'
        p = ROOT / 'work/research164/results' / sub / (s['session'] + '.json')
        d = json.loads(p.read_text(encoding='utf-8'))
        c = next(x for x in d['cases'] if x['config']['id'] == 'NK225_U164_00')
        cases[s['session']] = c
        sources.append({'path': str(p), 'sha256': sha(p)})
        risk = c['actual']['Risk']
        events = []
        for e in c['actual']['Events']:
            o = e['Order']; close = bool(o.get('Targets'))
            events.append({'index': e['FillIndex'], 'time': e['FillTime'], 'jst': iso(e['FillTime']),
                           'action': '返済' if close else '新規', 'side': o['Side'],
                           'qty_micro': o['Quantity'], 'price': e['Price'], 'gross': e['Gross'],
                           'owner': o['Owner'], 'parent': o['Parent'], 'reason': o['Reason'],
                           'decision_index': o['DecisionIndex'], 'decision_jst': iso(o['DecisionTime'])})
            if close:
                h = datetime.fromtimestamp(e['FillTime'], JST).strftime('%H')
                by_hour[h]['events'] += 1
                by_hour[h]['net'] += e['Gross']
                by_hour[h]['profit'] += max(0, e['Gross'])
                by_hour[h]['loss'] += max(0, -e['Gross'])
        rows.append({'session': s['session'], 'split': s['split'], 'net': c['actual']['Realized'],
                     'minimum_equity': risk['Minimum'], 'maximum_drawdown': risk['MaxDD'],
                     'peak': risk['Peak'], 'minimum_at': snapshot(risk['MinimumAt']),
                     'dd_from': snapshot(risk['DDFrom']), 'dd_to': snapshot(risk['DDTo']),
                     'peak_at': snapshot(risk['PeakAt']), 'events': events})
        for lid, lot in c['actual']['Lots'].items():
            exits = [e for e in c['actual']['Events'] if any(x['ID'] == lid for x in e['Order'].get('Targets') or [])]
            lots.append(dict(lot, session=s['session'], entry_jst=iso(lot['At']),
                             best_jst=iso(lot['BestAt']), worst_jst=iso(lot['WorstAt']),
                             exit_jst=iso(exits[-1]['FillTime']),
                             positive_then_loss=lot['Best'] > 0 and lot['Gross'] < 0))
    assert sum(r['net'] for r in rows) == 1100000
    return {'financial_replays': 0, 'method': 'NK225_U164_00', 'sessions': 27,
            'net': sum(r['net'] for r in rows), 'negative_sessions': sum(r['net'] < 0 for r in rows),
            'source_files': sources, 'rows': rows,
            'net_worst3': [r['session'] for r in sorted(rows, key=lambda r: r['net'])[:3]],
            'drawdown_worst5': [r['session'] for r in sorted(rows, key=lambda r: -r['maximum_drawdown'])[:5]],
            'close_clock_hour': dict(sorted(by_hour.items())), 'lots': lots,
            'limitations': ['全27夜は既知開発資料。これは保存会計の整理で新たな有効性確認ではない。',
                            '時間別収支は返済価格時計による帰属。そこで損失原因が発生したことを意味しない。',
                            'MFEは返済側気配と保存実建値との差。価格中値の順行幅とは別。']}, cases


def parse_clock(value: object) -> float | None:
    """保存文字列の時計を読み、未知を数値ゼロに置換しない。

    引数: value(object)。返り値: UNIX秒又はNone。
    """
    try:
        return datetime.fromisoformat(value).timestamp() if isinstance(value, str) else None
    except ValueError:
        return None


def scan(scene: dict, case: dict, picked_at: str) -> dict:
    """1夜の原板を全読し、保存約定対応と量・時計品質を集計する。

    引数: scene/case(dict)、picked_at(str)。返り値: 監査情報(dict)。
    """
    path = Path(scene['books']['NK225']); digest = hashlib.sha256()
    ledger = case['actual']; target_at = datetime.fromisoformat(picked_at).timestamp()
    lot = next(l for l in ledger['Lots'].values() if l['At'] == target_at and l['Owner'].endswith('/core'))
    all_events = ledger['Events']; events = [e for e in all_events if e['HoldID'] == lot['ID'] or
               any(t['ID'] == lot['ID'] for t in e['Order'].get('Targets') or [])]
    anchors = {e['FillIndex'] for e in all_events} | {e['Order']['DecisionIndex'] for e in all_events}
    selected_clock = [lot['At'], lot['BestAt'], lot['WorstAt']] + [e['FillTime'] for e in events]
    count = Counter(); index = -1; previous = scene['start']; rows = []; raw_extract = []
    exact = {}; last = None; valid_prev = None; prev_volume = None; keys = Counter()
    groups = {}; bucket = None; depth_presence = Counter(); pos = scene['us_open'] + 900
    with path.open('rb') as f:
        for physical, data in enumerate(f, 1):
            digest.update(data); count['physical'] += 1; obj = json.loads(data)
            if physical == 1:
                keys.update(obj.keys())
            at = parse_clock(obj.get('CurrentPriceTime'))
            if at is None: count['unknown_clock'] += 1; continue
            if at < scene['start'] or at > scene['end'] or at >= scene['cutoff']:
                count['outside'] += 1; continue
            if at < previous: count['clock_backwards'] += 1; continue
            price = float(obj.get('CurrentPrice') or 0)
            if not math.isfinite(price) or price <= 0:
                count['invalid_last'] += 1; continue
            previous = at; index += 1
            b = obj.get('Buy1') or {}; a = obj.get('Sell1') or {}
            bid, ask = float(b.get('Price') or 0), float(a.get('Price') or 0)
            bq, aq = float(b.get('Qty') or 0), float(a.get('Qty') or 0)
            ok = math.isfinite(bid) and math.isfinite(ask) and 0 < bid < ask
            tv = obj.get('TradingVolume'); vt = parse_clock(obj.get('TradingVolumeTime'))
            compact = {'index': index, 'line': physical, 'time': at, 'jst': iso(at),
                       'last': price, 'bid': bid, 'ask': ask, 'bid_qty': bq, 'ask_qty': aq,
                       'valid_bbo': ok, 'volume': tv, 'volume_time': vt,
                       'volume_jst': iso(vt) if vt is not None else None,
                       'buy': [[obj.get('Buy'+str(i), {}).get('Price'), obj.get('Buy'+str(i), {}).get('Qty')] for i in range(1, 11)],
                       'sell': [[obj.get('Sell'+str(i), {}).get('Price'), obj.get('Sell'+str(i), {}).get('Qty')] for i in range(1, 11)]}
            if index in anchors:
                exact[index] = compact
            if any(abs(at - t) <= 2 for t in selected_clock):
                raw_extract.append({'adopted_index': index, 'physical_line': physical, 'raw': obj})
            if at < pos:
                continue
            count['post_rows'] += 1
            count['post_normal_bbo' if ok else 'post_bad_bbo'] += 1
            count['volume_clock_known' if vt is not None else 'volume_clock_null'] += 1
            count['volume_clock_equals_price_clock'] += vt == at
            count['volume_clock_newer_than_price_clock'] += vt is not None and vt > at
            for depth in range(1, 11):
                for side in ['Buy', 'Sell']:
                    d = obj.get(side+str(depth)) or {}
                    if isinstance(d.get('Price'), (int, float)) and isinstance(d.get('Qty'), (int, float)):
                        depth_presence[side+str(depth)] += 1
            if last is not None:
                same = at == last['time']
                count['same_price_clock_row'] += same
                changed = (bid, ask) != (last['bid'], last['ask'])
                count['same_clock_bbo_changed'] += same and changed
                count['same_clock_quantity_changed'] += same and ((bq, aq) != (last['bid_qty'], last['ask_qty']))
                count['price_clock_gap_gt15'] += at - last['time'] > 15
                count['price_clock_gap_gt60'] += at - last['time'] > 60
                if isinstance(tv, (int, float)) and isinstance(last['volume'], (int, float)):
                    dv = tv - last['volume']
                    count['volume_increased'] += dv > 0
                    count['volume_decreased'] += dv < 0
                    count['volume_increased_same_price_clock'] += dv > 0 and same
                    count['volume_increased_same_volume_clock'] += dv > 0 and vt == last['volume_time']
                    count['volume_clock_advanced'] += vt is not None and last['volume_time'] is not None and vt > last['volume_time']
            if ok:
                if valid_prev is not None and index == valid_prev['index'] + 1:
                    for side in ['bid', 'ask']:
                        q = side+'_qty'; sameprice = compact[side] == valid_prev[side]
                        count[side+'_same_price_qty_up'] += sameprice and compact[q] > valid_prev[q]
                        count[side+'_same_price_qty_down'] += sameprice and compact[q] < valid_prev[q]
                valid_prev = compact
                rows.append(compact)
                if bucket is None or bucket['time'] != at:
                    if bucket is not None: groups[bucket['time']] = bucket
                    bucket = {'time': at, 'first': compact, 'last': compact, 'n': 1, 'mid_min': (bid+ask)/2, 'mid_max': (bid+ask)/2}
                else:
                    bucket['last'] = compact; bucket['n'] += 1
                    bucket['mid_min'] = min(bucket['mid_min'], (bid+ask)/2)
                    bucket['mid_max'] = max(bucket['mid_max'], (bid+ask)/2)
            last = compact
    if bucket is not None: groups[bucket['time']] = bucket
    expected = next(x['sha256'] for x in scene['fingerprints'] if Path(x['path']) == path)
    assert digest.hexdigest() == expected
    for e in all_events:
        q = exact[e['FillIndex']]
        assert (q['time'], q['bid'], q['ask']) == (e['FillTime'], e['Bid'], e['Ask'])
        assert e['Price'] == (q['ask'] if e['Order']['Side'] == 1 else q['bid'])
    # ----------------------------------------
    # 当時の入口、逆行極値、利益極値は事後診断点として分離する。
    point_rows = []
    event_by_index = {e['FillIndex']: e for e in events}
    for label, at, target_index in [('entry', lot['At'], lot['EntryIndex']),
                                   ('worst', lot['WorstAt'], None), ('best', lot['BestAt'], None)]:
        eligible = [q for q in rows if q['time'] == at and (target_index is None or q['index'] == target_index)]
        if target_index is None:
            gain = lambda q: lot['Side'] * ((q['bid'] if lot['Side'] == 1 else q['ask']) - lot['Entry'])
            wanted = lot['Worst'] if label == 'worst' else lot['Best']
            eligible = [q for q in eligible if gain(q) == wanted]
        anchor = eligible[0]
        windows = {}
        for h in [5, 15, 60, 120]:
            prior = [q for q in rows if q['index'] <= anchor['index'] and anchor['time']-h <= q['time'] <= anchor['time']]
            transitions = Counter()
            for x, y in zip(prior, prior[1:]):
                if y['index'] != x['index']+1: transitions['skipped_invalid_rows'] += 1; continue
                for side in ['bid', 'ask']:
                    delta = y[side]-x[side]
                    transitions[side+'_price_up'] += delta > 0
                    transitions[side+'_price_down'] += delta < 0
                    dq = y[side+'_qty']-x[side+'_qty']
                    transitions[side+'_same_price_qty_up'] += delta == 0 and dq > 0
                    transitions[side+'_same_price_qty_down'] += delta == 0 and dq < 0
            windows[str(h)] = {'normal_rows': len(prior), 'distinct_price_clocks': len({q['time'] for q in prior}),
                                'observed_span_seconds': anchor['time']-prior[0]['time'] if prior else None,
                                'mid_change': ((anchor['bid']+anchor['ask'])-(prior[0]['bid']+prior[0]['ask']))/2 if prior else None,
                                'volume_delta': anchor['volume']-prior[0]['volume'] if prior and isinstance(anchor['volume'], (int,float)) and isinstance(prior[0]['volume'], (int,float)) else None,
                                'transitions': dict(transitions)}
        point_rows.append({'kind': label, 'known_at_entry': label == 'entry', 'anchor': anchor, 'backward_windows': windows})
    graph_rows = []
    begin = lot['At'] - 120; finish = events[-1]['FillTime'] + 60
    for at, g in sorted(groups.items()):
        if begin <= at <= finish:
            graph_rows.append({'time': at, 'first': g['first'], 'last': g['last'], 'rows': g['n'],
                               'mid_min': g['mid_min'], 'mid_max': g['mid_max']})
    rawname = scene['session']+'_選定時刻の原行.jsonl'
    with (OUT / rawname).open('w', encoding='utf-8') as f:
        for q in raw_extract: f.write(json.dumps(q, ensure_ascii=False)+'\n')
    chartname = scene['session']+'_診断標本.json'
    prefix_end = min(lot['At']+900, max(lot['WorstAt']+90, lot['At']+180))
    initial_rows = [q for q in rows if lot['At']-60 <= q['time'] <= prefix_end]
    dump(chartname, {'session': scene['session'], 'lot': lot, 'events': events,
                     'points': point_rows, 'chart_rows': graph_rows, 'initial_rows': initial_rows,
                     'clock_note': '図の同価格時計の最初と末尾を両方保持。末尾は同時計最初の判断には利用できない。'})
    clocks = list(groups.values()); same_range = [g['mid_max']-g['mid_min'] for g in clocks]
    counts = dict(count)
    counts['distinct_normal_price_clocks'] = len(clocks)
    counts['same_clock_mid_range_gt0'] = sum(x > 0 for x in same_range)
    counts['same_clock_mid_range_max'] = max(same_range)
    return {'session': scene['session'], 'source': {'path': str(path), 'sha256': digest.hexdigest(), 'matches164': True},
            'counts': counts, 'depth_numeric_rows': dict(depth_presence), 'raw_top_keys': list(keys),
            'selected_lot': lot, 'selected_events': events, 'points': point_rows,
            'all_event_bbo_matches': len(all_events), 'extract': {'path': str(OUT/rawname), 'sha256': sha(OUT/rawname), 'rows': len(raw_extract)},
            'chart': {'path': str(OUT/chartname), 'sha256': sha(OUT/chartname)},
            'post_range': {'from': iso(pos), 'to': iso(scene['end'])}}


def main() -> None:
    """保存診断を実行し、原資料や登録済み成果を変更しない。

    引数: なし。返り値: None。
    """
    manifest = json.loads((ROOT/'work/research164/inputs164.json').read_text(encoding='utf-8'))
    OUT.mkdir(parents=True, exist_ok=True)
    inv = inventory(manifest); dump('保存資料の増分と同一性165.json', inv)
    scenes = [s for s in manifest['sessions'] if s['kind'] == 'Night']
    acc, cases = accounting(scenes); dump('U00の損失と回復の保存会計165.json', acc)
    selections = {'2026-09-21_Night': '2026-09-21T23:00:01+09:00',
                  '2026-10-13_Night': '2026-10-13T23:00:14+09:00',
                  '2026-10-26_Night': '2026-10-26T23:00:01+09:00',
                  '2026-10-02_Night': '2026-10-02T23:00:00+09:00',
                  '2026-10-14_Night': '2026-10-15T00:25:30+09:00'}
    results = []
    for s in scenes:
        if s['session'] in selections:
            a = scan(s, cases[s['session']], selections[s['session']]); results.append(a)
            print(s['session'], 'raw', a['counts']['physical'], 'exact', a['all_event_bbo_matches'], flush=True)
    dump('五夜の原板と時計の監査165.json', {'created_at': datetime.now(JST).isoformat(), 'financial_replays': 0,
                                      'selection': '赤字上位3夜と短期逆行から回復した2夜の事後診断。閾値の有効性評価ではない。',
                                      'rows': results})
    print('saved-accounting-and-raw-only: PASS', flush=True)


if __name__ == '__main__':
    main()
