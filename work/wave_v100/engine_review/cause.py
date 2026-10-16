"""根の全31正式完了通知後だけ、保存台帳から価格上限の原因を候補単位で読む。"""

import argparse
from collections import Counter
from datetime import datetime
import gc
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
AUTHORIZED = False
PROBES = (dict(名前='TOPIXの元候補より高い新規', 場='2026-09-24_Night', 商品='TOPIX',
               候補quote=4063.5, 実新規=4080., 基準='P0_L1_C1_A7_X3'),
          dict(名前='日経の元候補と同値でも負けた新規', 場='2026-09-28_Day', 商品='NK225',
               候補quote=66660., 実新規=66660., 基準='P0_L1_C1_A7_X3'))
sys.dont_write_bytecode = True


def digest(path: Path) -> str:
    """
    機能: 大きな台帳又は原本を一定メモリーで指紋化する。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read(path: Path) -> object:
    """
    機能: 根の正式完了許可前には新結果や台帳を一切開かない。
    引数: path(Path)。
    返り値: objectはJSON又はpickle内容。新規の売買を呼ぶ経路はない。
    """
    assert AUTHORIZED, '根の全34・全31正式完了通知と明示flagが必要です'
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def stage_guard(notified: bool) -> dict:
    """
    機能: 明示許可と全34の前16・後15の保存完了を確認してから分析を許可する。
    引数: notified(bool)は根の全31完了通知後だけ指定するCLIflag。
    返り値: dictは事前固定。未完結果を読んで候補の仕様を変更しない。
    """
    global AUTHORIZED
    if not notified:
        raise RuntimeError('根の全31正式完了通知前は実行不可です。--root-all31-complete を許可後だけ指定してください')
    AUTHORIZED = True
    fixed = read(WORK / '事前固定.json')
    assert len(fixed['条件']) == 34 and len(fixed['全31']) == 31
    assert len(fixed['前16']) == 16 and len(fixed['後15']) == 15
    assert fixed['前16'] + fixed['後15'] == fixed['全31']
    ids = {value['id'] for value in fixed['条件']}
    for part in ('front', 'back'):
        assert {path.stem for path in (WORK / part / 'results').glob('*.json')} == ids, '未完の正式結果は分析しません'
        assert {path.stem for path in (WORK / part / 'ledgers').glob('*.pkl')} == ids, '未完の正式台帳は分析しません'
    for config in fixed['条件']:
        for part, period in (('front', '前16'), ('back', '後15')):
            result = read(WORK / part / 'results' / (config['id']+'.json'))
            assert result['config'] == config
            assert {(row['session'], row['symbol']) for row in result['rows']} == {
                (session, symbol) for session in fixed[period] for symbol in SYMBOLS}
            assert len(result['rows']) == len(fixed[period])*2
            assert result['ledger_SHA256'] == digest(WORK / part / 'ledgers' / (config['id']+'.pkl'))
    comparison = read(WORK / 'analysis/比較結果.json')
    assert comparison['全合格'] and comparison['条件数'] == 34
    assert comparison['sessions'] == fixed['全31'] and set(comparison['results']) == ids
    return fixed


def restore(ledger: dict) -> np.ndarray:
    """
    機能: 上限20列の疎状態を全原行へ独立復元し、保存SHAと照合する。
    引数: ledger(dict)は既存の1口座台帳。
    返り値: ndarray[float]は原行数×20。未知値はNaNのまま保持する。
    """
    changes = np.asarray(ledger['entry_cap_state_changes'], dtype=float)
    n = int(ledger['input_rows'])
    assert n > 0 and changes.ndim == 2 and changes.shape[1] == 21
    rows = changes[:, 0].astype(np.int64)
    assert np.array_equal(rows, changes[:, 0]) and rows[0] == 0 and rows[-1] == n-1
    assert np.all(np.diff(rows) > 0)
    trace = np.repeat(changes[:, 1:], np.diff(np.r_[rows, n]), axis=0)
    assert trace.shape == (n, 20)
    assert hashlib.sha256(trace.tobytes()).hexdigest() == ledger['entry_cap_state_SHA256']
    return trace


def named(row: np.ndarray, columns: list[str]) -> dict:
    """
    機能: 台帳の保存列名を用い、行を意味のある値へ変換する。
    引数: row(ndarray[float])、columns(list[str])。
    返り値: dict[str,float]。列番号を別台帳の番号と混同しない。
    """
    assert len(row) == len(columns)
    return dict(zip(columns, map(float, row)))


def episodes(ledger: dict, config: dict) -> dict:
    """
    機能: 拒否原行の多寡ではなく、元候補別の拒否・成立・取消と実約定をまとめる。
    引数: ledger/config(dict)。
    返り値: dictは候補seq/方向をkeyにした記録と集計。金融実行は行わない。
    """
    trace = restore(ledger)
    columns = ledger['entry_cap_state_columns']
    assert len(columns) == 20
    index = {name: columns.index(name) for name in columns}
    blocked_rows = np.flatnonzero(trace[:, index['cap_blocked']] == 1.)
    blocked = {}
    for candidate in np.unique(trace[blocked_rows, index['candidate_id']]).astype(int):
        rows = blocked_rows[trace[blocked_rows, index['candidate_id']] == candidate]
        blocked[candidate] = dict(拒否行数_参考=len(rows), 初回拒否原行=int(rows[0]),
            初回拒否時計=float(trace[rows[0], index['row_time']]),
            初回拒否判断quote=float(trace[rows[0], index['current_entry_quote']]),
            初回拒否不利幅=float(trace[rows[0], index['adverse_width']]),
            最後の拒否原行=int(rows[-1]))
    accepted, ignored, cancelled = {}, {}, {}
    for row in ledger['entry_wait_events']:
        value = named(row, ledger['entry_wait_event_columns'])
        code = int(value['code'])
        if code == 1:
            cid = int(value['state_candidate_id'])
            accepted[cid] = dict(元候補ID=cid, 元候補行=int(value['state_candidate_row']),
                元候補seq=int(value['state_candidate_seq']), 方向=int(value['state_side']),
                元候補時計=value['state_candidate_time'], 元候補quote=value['state_candidate_quote'],
                W=value['state_width'], 元deadline=value['state_deadline'])
        elif code == 2 and value['arriving_side'] != 0 and value['arriving_candidate_id'] > 0:
            ignored[int(value['observed_own_seq']), int(value['arriving_side'])] = dict(
                状態='元候補を消費して不参加', 原行=int(value['row']),
                理由=int(value['reason']), 代理時計=value['observed_own_time'])
        elif code == 3:
            cancelled[int(value['state_candidate_id'])] = dict(取消原行=int(value['row']),
                取消時計=value['observed_own_time'], 取消seq=int(value['observed_own_seq']),
                取消理由=int(value['reason']), 取消説明=ledger['entry_wait_reasons'][int(value['reason'])])
    trades = {int(row[0]): named(row, ledger['trade_columns']) for row in ledger['trades']}
    parents = {}
    cap_parents = {int(row[0]): named(row, ledger['entry_cap_parent_columns'])
                   for row in ledger['entry_cap_parent_diagnostics']}
    for row in ledger['entry_parent_diagnostics']:
        parent = named(row, ledger['entry_parent_columns'])
        cid, pid = int(parent['candidate_id']), int(parent['parent_id'])
        cap = cap_parents[pid]
        assert cap['candidate_quote'] == parent['candidate_quote'] and cap['width'] == parent['width']
        assert cap['trigger_adverse_width'] == parent['side']*(parent['trigger_quote']-parent['candidate_quote'])
        if config['entry_price_cap_multiple'] is not None:
            assert cap['cap_width'] == config['entry_price_cap_multiple']*parent['width']
            assert cap['trigger_adverse_width'] <= cap['cap_width'] and cap['trigger_inside_cap'] == 1.
            if np.isfinite(parent['fill_price']):
                assert cap['fill_adverse_width'] == parent['side']*(parent['fill_price']-parent['candidate_quote'])
                assert cap['fill_cap_excess'] == max(0., cap['fill_adverse_width']-cap['cap_width'])
        parents[cid] = dict(入口=parent, 上限と実約定=cap, 決済親=trades.get(pid))
        if cid not in accepted:
            assert int(config['entry_wait_kind']) == 0
            accepted[cid] = dict(元候補ID=cid, 元候補行=int(parent['candidate_row']),
                元候補seq=int(parent['candidate_seq']), 方向=int(parent['side']),
                元候補時計=parent['candidate_time'], 元候補quote=parent['candidate_quote'],
                W=parent['width'], 元deadline=None)
    result, reasons = {}, Counter()
    counts = Counter(受理候補数=len(accepted), 拒否候補数=len(blocked), 拒否行数_参考=len(blocked_rows),
                     拒否後判断成立=0, 拒否後未成立取消=0, 拒否後成立して市場予約取消=0,
                     判断成立=0, 実約定=0, 判断内で実約定上限超過=0)
    assert set(blocked) <= set(accepted)
    for cid, candidate in accepted.items():
        value = dict(candidate)
        value.update(blocked.get(cid, {}))
        value['上限による拒否経験'] = cid in blocked
        if cid in parents:
            value.update(parents[cid])
            value['状態'] = '判断成立・実約定' if value['決済親'] is not None else '判断成立・市場予約取消'
            counts['判断成立'] += 1
            counts['実約定'] += int(value['決済親'] is not None)
            if cid in blocked:
                assert value['入口']['trigger_row'] > value['初回拒否原行']
                counts['拒否後判断成立'] += 1
                counts['拒否後成立して市場予約取消'] += int(value['決済親'] is None)
            cap = value['上限と実約定']
            overshoot = config['entry_price_cap_multiple'] is not None and np.isfinite(cap['fill_cap_excess']) and cap['fill_cap_excess'] > 0
            counts['判断内で実約定上限超過'] += int(overshoot)
        else:
            assert cid in cancelled, ('完結した場で候補の終端が不明', config['id'], cid)
            value.update(cancelled[cid])
            value['状態'] = '判断未成立・取消'
            if cid in blocked:
                counts['拒否後未成立取消'] += 1
                reasons[value['取消説明']] += 1
        key = value['元候補seq'], value['方向']
        assert key not in result
        result[key] = value
    assert counts['拒否候補数'] == counts['拒否後判断成立']+counts['拒否後未成立取消']
    return dict(候補=result, 無視候補=ignored, 件数=dict(counts), 拒否後取消理由=dict(reasons))


def compare_origins(old: dict, new: dict, symbol: str) -> dict:
    """
    機能: 同じ元候補seq/方向で実現した親を比較し、建値・返済・費用差を分離する。
    引数: old/new(dict、候補集計)、symbol(str)。
    返り値: dict。消えた旧勝ち/旧負けは新条件の仮想損益として再利用しない。
    """
    old_filled = {key: value for key, value in old['候補'].items() if value.get('決済親') is not None}
    new_filled = {key: value for key, value in new['候補'].items() if value.get('決済親') is not None}
    common = old_filled.keys() & new_filled.keys()
    multiplier = 1000. if symbol == 'TOPIX' else 10.
    acquisition = repayment = fee_delta = common_net = 0.
    for key in common:
        a, b = old_filled[key]['決済親'], new_filled[key]['決済親']
        assert a['side'] == b['side'] and a['quantity'] == b['quantity']
        entry = -a['side']*a['quantity']*multiplier*(b['entry_price']-a['entry_price'])
        exit_value = a['side']*a['quantity']*multiplier*(b['exit_price']-a['exit_price'])
        fees = a['entry_fee']+a['exit_fee']-b['entry_fee']-b['exit_fee']
        assert abs(b['net']-a['net']-entry-exit_value-fees) < 1e-5
        acquisition += entry
        repayment += exit_value
        fee_delta += fees
        common_net += b['net']-a['net']
    missing = old_filled.keys()-new_filled.keys()
    return dict(同元候補で双方実約定=len(common), 旧勝ちの消失=sum(old_filled[key]['決済親']['net'] > 0 for key in missing),
        旧負けの消失=sum(old_filled[key]['決済親']['net'] < 0 for key in missing), 新固有実約定=len(new_filled.keys()-old_filled.keys()),
        共通親の取得差円=acquisition, 共通親の返済差円=repayment, 共通親の費用差円=fee_delta,
        共通親の実現純額差円=common_net)


def raw_points(path: Path, targets: set[int]) -> dict:
    """
    機能: 少数の元候補/判断/約定/返済の保存seqへ原JSONLを直接対応させる。
    引数: path(Path)、targets(set[int])は0始まりの保存行通番。
    返り値: dict[int,dict]。真受信時刻又は取引所sequenceを架空に補わない。
    """
    result = {}
    if not targets:
        return result
    with path.open('rb') as stream:
        for sequence, line in enumerate(stream):
            if sequence > max(targets):
                break
            if sequence not in targets:
                continue
            raw = json.loads(line)
            buy, sell = raw.get('Buy1') or {}, raw.get('Sell1') or {}
            result[sequence] = dict(保存seq=sequence, CurrentPrice=raw.get('CurrentPrice'),
                CurrentPriceTime=raw.get('CurrentPriceTime'), TradingVolume=raw.get('TradingVolume'),
                TradingVolumeTime=raw.get('TradingVolumeTime'), bid=buy.get('Price'), ask=sell.get('Price'),
                bid_qty=buy.get('Qty'), ask_qty=sell.get('Qty'), Buy1_Time=buy.get('Time'), Sell1_Time=sell.get('Time'),
                原行SHA256=hashlib.sha256(line).hexdigest())
    assert set(result) == targets
    return result


def attach_case_points(cases: list[dict], inputs: dict) -> list[dict]:
    """
    機能: 既存執行素材のseq/time/BBOと原JSONLを照合して少数事例へ添付する。
    引数: cases(list[dict])、inputs(dict[tuple,dict])は保存済み83の執行素材。
    返り値: list[dict]。新しい価格特徴又は売買結果は計算しない。
    """
    for case in cases:
        key = case['場'], case['商品']
        record = inputs[key]
        requests = set()
        for value in case['各条件'].values():
            if '元候補seq' not in value:
                continue
            rows = {'元候補': value['元候補行']}
            if '初回拒否原行' in value:
                rows['初回上限拒否'] = value['初回拒否原行']
            if '取消原行' in value:
                rows['待機取消'] = value['取消原行']
            if '入口' in value:
                rows['判断'] = int(value['入口']['trigger_row'])
            if value.get('決済親') is not None:
                rows['実新規'] = int(value['決済親']['entry_row'])
                rows['返済'] = int(value['決済親']['exit_row'])
            value['保存原板対応'] = {name: dict(執行行=row, 保存seq=int(record['seq'][row]),
                代理時計=float(record['time_s'][row]), bid=float(record['bid'][row]), ask=float(record['ask'][row]))
                for name, row in rows.items()}
            for point in value['保存原板対応'].values():
                requests.add(point['保存seq'])
        path = ROOT/'book'/case['商品']/(case['場']+'.jsonl')
        points = raw_points(path, requests)
        for value in case['各条件'].values():
            for point in value.get('保存原板対応', {}).values():
                raw = points[point['保存seq']]
                stamp = datetime.fromisoformat(raw['CurrentPriceTime']).timestamp()
                assert stamp == point['代理時計']
                assert raw['bid'] == point['bid'] and raw['ask'] == point['ask']
                point['原本'] = raw
        case['原本SHA256'] = digest(path)
    return cases


def clean(value: object) -> object:
    """
    機能: NaN等の診断不明をJSON nullへ変換して保存する。
    引数: value(object)。
    返り値: objectはJSON互換値。不明値を有効なゼロへ置換しない。
    """
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def main() -> None:
    """
    機能: 根許可と正式終端を確認した後だけ、元候補別拒否と実約定超過を保存する。
    引数: CLIの--root-all31-complete(bool)は根通知後のみ指定する。
    返り値: None。strategy/engine/研究実行器をimport又は呼出ししない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root-all31-complete', action='store_true')
    args = parser.parse_args()
    fixed = stage_guard(args.root_all31_complete)
    configs = fixed['条件']
    ordered = sorted(configs, key=lambda config: (config['entry_price_cap_multiple'] is not None, config['id']))
    baseline, collected, source_hashes = {}, {}, {}
    for config in ordered:
        ident = config['id']
        collected[ident] = {}
        for part, period in (('front', '前16'), ('back', '後15')):
            path = WORK/part/'ledgers'/(ident+'.pkl')
            records = read(path)
            assert set(records) == {(session, symbol) for session in fixed[period] for symbol in SYMBOLS}
            source_hashes[str(path.relative_to(ROOT))] = digest(path)
            for key, ledger in records.items():
                current = episodes(ledger, config)
                collected[ident][key] = current
                if config['entry_price_cap_multiple'] is None:
                    baseline[ident, key] = current
                else:
                    old = baseline['P0_'+config['previous_support_id'], key]
                    current['無制限同元候補比較'] = compare_origins(old, current, key[1])
            del records
            gc.collect()
        print(ident+': 元候補別拒否・成立・取消と実fillを読取', flush=True)

    # ----------------------------------------
    # 特定事例は全条件の同原seqへ結び、原本の少数該当行で時計とBBOを照合する。
    cases = []
    for probe in PROBES:
        key = probe['場'], probe['商品']
        possible = [(origin, value) for origin, value in collected[probe['基準']][key]['候補'].items()
                    if value['元候補quote'] == probe['候補quote'] and value.get('決済親') is not None
                    and value['決済親']['entry_price'] == probe['実新規']]
        assert len(possible) == 1, ('根から指定された事例を結果から別候補へ置換しません', probe, len(possible))
        origin, reference = possible[0]
        values = {}
        for config in configs:
            current = collected[config['id']][key]
            value = current['候補'].get(origin, current['無視候補'].get(origin, dict(状態='この元候補の受理記録なし')))
            if '元候補seq' not in value:
                value = dict({name: reference[name] for name in ('元候補行', '元候補seq', '方向',
                    '元候補時計', '元候補quote')}, **value)
            values[config['id']] = value
        cases.append(dict(probe, 元保存seq=origin[0], 方向=origin[1], 各条件=values))
    price_path = ROOT/'work/wave_v83/prepared/inputs.pkl'
    prices = read(price_path)
    cases = attach_case_points(cases, prices)
    del prices

    # ----------------------------------------
    # 全31の集計は候補件数を主とし、拒否raw行数や無取引を成功率へ置換しない。
    totals = {}
    for config in configs:
        ident = config['id']
        totals[ident] = {}
        for symbol in SYMBOLS:
            selected = [value for key, value in collected[ident].items() if key[1] == symbol]
            counts, reasons = Counter(), Counter()
            for value in selected:
                counts.update(value['件数'])
                reasons.update(value['拒否後取消理由'])
            totals[ident][symbol] = dict(件数=dict(counts), 拒否後取消理由=dict(reasons),
                セッション別={key[0]: dict(件数=value['件数'], 拒否後取消理由=value['拒否後取消理由'],
                    無制限同元候補比較=value.get('無制限同元候補比較')) for key, value in collected[ident].items() if key[1] == symbol},
                元候補別=[dict(場=key[0], **value) for key, session in collected[ident].items() if key[1] == symbol
                         for value in session['候補'].values()])
    source_hashes.update({str(path.relative_to(ROOT)): digest(path) for path in
        (Path(__file__), WORK/'事前固定.json', WORK/'analysis/比較結果.json', price_path, WORK/'engine.py', WORK/'strategy.py')})
    result = dict(全合格=True, 根の全31正式完了flag=True, 対象条件数=34, 対象口座数=2108,
        集計=totals, 具体原板事例=cases,
        説明='上限は発注判断だけ。判断時の上限合格と、予約後の次正常fillの超過を別計数。拒否raw行数ではなく元候補数を主に数える。全31既知で事後原因分析、売買変更なし。',
        時計の限界='保存seqは原JSONL行通番、CurrentPriceTimeは価格時計。真受信時計及び二市場共通受信順を証明しない。',
        新金融実行=0, 金融条件変更=0, API取得=0, 実注文=0, SHA256=source_hashes)
    destination = HERE/'全34の元候補別価格上限拒否と実約定超過及び二原板事例の原因.json'
    assert not destination.exists(), '既存原因証跡を上書きしません'
    destination.write_text(json.dumps(clean(result), ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print('原因分析保存: '+str(destination), flush=True)


if __name__ == '__main__':
    main()
