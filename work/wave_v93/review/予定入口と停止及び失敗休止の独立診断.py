"""当時BBOの予定比、実停止証拠、失敗後休止を独立式と原板で診断する。"""

import math
from pathlib import Path

import numpy as np

import 共通独立読取 as R


def same(a: float, b: float) -> bool:
    """
    機能: 有限診断値又は双方未定義値の一致を検査する。
    引数: a/b (float)。
    返り値: bool は許容誤差1e-7以内又は双方NaNの一致。
    """
    return bool(np.isnan(a) and np.isnan(b) or np.isfinite(a) and np.isfinite(b) and abs(a - b) < 1e-7)


def proposal(record: dict, row: int, side: int, quantity: int, center: float,
             extreme: float, width: float, symbol: str) -> dict:
    """
    機能: 判断行までのBBO・中心・極値から予定距離比を独立算出する。
    引数: record (dict)、row/side/quantity (int)、center/extreme/width (float)、symbol (str)。
    返り値: dict は将来約定を参照しない予定値。
    """
    bid, ask = float(record['bid'][row]), float(record['ask'][row])
    entry, liquidation = (ask, bid) if side == 1 else (bid, ask)
    multiplier, fee_unit = (1000., 41.8) if symbol == 'TOPIX' else (10., 11.)
    fee = 2 * math.floor(quantity * fee_unit + 1e-8) / (quantity * multiplier)
    spread = ask - bid
    failure = extreme - side * record['tick']
    risk = side * (entry - failure)
    gain = side * (center - entry) - spread - fee
    proxy = min(risk, width + spread) + fee
    ratio = gain / proxy if proxy > 0 else np.nan
    return {'planned_entry': entry, 'planned_liquidation': liquidation, 'spread': spread,
            'fee_width': fee, 'planned_extreme_risk': risk, 'center_gain': gain,
            'risk_proxy': proxy, 'center_ratio': ratio, 'failure_line': failure,
            '深さu': side * (center - extreme) / width,
            '入口回復v': side * (entry - extreme) / width}


def gate_allowed(value: dict, width: float, tick: float, side: int, config: dict) -> bool:
    """
    機能: 事前固定した距離又はrhoゲートを、独立式で再評価する。
    引数: value/config (dict)、width/tick (float)、side (int)。
    返り値: bool は予定判断の採否。
    """
    accepted = True
    maximum = config['range_entry_max_risk_widths']
    minimum = config['range_entry_min_center_ratio']
    if maximum > 0:
        accepted = 0 < value['planned_extreme_risk'] <= maximum * width + tick * 1e-8
    if minimum > 0:
        accepted = (accepted and value['planned_extreme_risk'] > 0 and value['center_gain'] > 0
                    and value['risk_proxy'] > 0
                    and side * (value['planned_liquidation'] - value['failure_line']) > tick * 1e-8
                    and value['center_ratio'] >= minimum - 1e-12)
    return bool(accepted)


def gate_diagnosis(ident: str, ledgers: dict, config: dict, material: dict) -> tuple[list, list]:
    """
    機能: 全ゲート判断を当時気配へ照合し、受理と拒否の深さ・距離を診断する。
    引数: ident (str)、ledgers/config/material (dict)。
    返り値: tuple[list,list] は全ゲート及び全反発親の診断行。
    """
    gates, parents = [], []
    for key, ledger in sorted(ledgers.items()):
        record = material['prices'][key]
        qty = int(config['range_budget'] * (1 if key[1] == 'TOPIX' else 2))
        for event in ledger['events'][ledger['events'][:, 3] == 27]:
            row, side = int(event[0]), int(event[4])
            state = R.state_at(ledger, row)
            risk = R.state_at(ledger, row, 'risk')
            extreme = state['own_low' if side == 1 else 'own_high']
            value = proposal(record, row, side, qty, state['range_anchor'], extreme, state['width'], key[1])
            for name in ('planned_entry', 'planned_liquidation', 'spread', 'fee_width', 'planned_extreme_risk',
                         'center_gain', 'risk_proxy', 'center_ratio'):
                assert same(value[name], risk[name]), (ident, key, row, name, value[name], risk[name])
            accepted = gate_allowed(value, state['width'], record['tick'], side, config)
            assert int(event[11]) == risk['gate_accepted'] == int(accepted)
            assert risk['gate_row'] == row and risk['gate_side'] == side
            gates.append({'条件': ident, '場': key[0], '銘柄': key[1], '判断行': row,
                          '判断時刻': R.clock(record['time_s'][row]), '方向': side, '枚数': qty,
                          'エピソード': int(event[10]), '受理': accepted, '中心': state['range_anchor'],
                          '極値': extreme, '幅': state['width'], **value})
        diagnostics = ledger['range_parent_diagnostics']
        columns = ledger['range_parent_columns']
        assert len(columns) == 33 and diagnostics.shape[1] == 33
        trades = {int(t[0]): t for t in ledger['trades'] if t[1] == 1}
        assert len(diagnostics) == len(trades)
        for raw in diagnostics:
            value = dict(zip(columns, map(float, raw)))
            trade = trades[int(value['parent_id'])]
            row, side, quantity = int(value['decision_row']), int(value['side']), int(value['quantity'])
            extreme_row = int(value['extreme_row'])
            assert same(value['extreme'], (record['bid'][extreme_row] + record['ask'][extreme_row]) / 2)
            planned = proposal(record, row, side, quantity, value['center'], value['extreme'], value['width'], key[1])
            for name in ('planned_entry', 'planned_liquidation', 'spread', 'fee_width', 'planned_extreme_risk',
                         'center_gain', 'risk_proxy', 'center_ratio', 'failure_line'):
                assert same(value[name], planned[name]), (ident, key, row, name)
            assert value['entry_row'] == trade[2] and value['exit_row'] == trade[3]
            assert value['quantity'] == trade[5] and value['net'] == trade[11]
            assert same(value['actual_extreme_risk'], side * (trade[6] - value['failure_line']))
            target = value['center'] + side * config['range_center_target_offset'] * value['width'] \
                if config['range_target_kind'] != 'widths' else np.nan
            assert same(value['target_line'], target)
            exit_row = int(value['exit_decision_row'])
            assert exit_row > int(trade[2])
            quote = record['bid'][exit_row] if side == 1 else record['ask'][exit_row]
            width_hit = (bool(record['price_valid'][exit_row]) and
                         side * (record['price'][exit_row] - trade[6]) <= -config['stop_widths'] * value['width'])
            witness_hit = (bool(record['quote_valid'][exit_row]) and
                           side * (quote - value['failure_line']) <= record['tick'] * 1e-8)
            reason = int(trade[13])
            recorded_width = width_hit and config['range_stop_kind'] != 'witness_extreme' and reason in (6, 13, 14)
            recorded_witness = witness_hit and config['range_stop_kind'] != 'width' and reason in (6, 13, 14)
            assert bool(value['exit_width_flag']) == recorded_width
            assert bool(value['exit_witness_flag']) == recorded_witness
            assert bool(value['exit_target_flag']) == (reason in (5, 15))
            paused = config['range_failure_reentry_kind'] != 'legacy' and recorded_witness and trade[11] < 0
            assert bool(value['failure_pause_started']) == paused
            parents.append({'条件': ident, '場': key[0], '銘柄': key[1], '判断時刻': R.clock(record['time_s'][row]),
                            '返済判断時刻': R.clock(record['time_s'][exit_row]),
                            '実取得価格': float(trade[6]), '実返済価格': float(trade[7]),
                            '返済理由': ledger['reasons'][reason], **value,
                            '深さu': planned['深さu'], '入口回復v': planned['入口回復v']})
    return gates, parents


def raw_observation(key: tuple, grid_index: int, material: dict, config: dict) -> dict:
    """
    機能: N4専用rawの可観測性と往復述語及び実最古源時計を入力から独立算出する。
    引数: key (tuple)、grid_index (int)、material/config (dict)。
    返り値: dict はknown/raw/oldest及び両市場源時計。
    """
    g = grid_index
    known, low, inside = True, True, True
    clocks, sources, old_clocks = {}, {}, []
    session = material['grids'][key[0]]
    for symbol in R.SYMBOLS:
        market, record = session['markets'][symbol], material['prices'][key[0], symbol]
        current, window, bounds = market['current'], market['windows'][300], market['ranges'][180]
        source = int(current['index'][g])
        sources[symbol] = source
        clocks[symbol] = float(record['time_s'][source]) if 0 <= source < len(record['time_s']) else np.nan
        known &= bool(current['valid'][g] and window['source_valid'][g]
                      and np.isfinite(window['efficiency'][g]) and np.isfinite(window['total_variation'][g])
                      and window['total_variation'][g] > 0 and bounds['source_valid'][g]
                      and bounds['position_valid'][g] and np.isfinite(bounds['width'][g]) and bounds['width'][g] > 0
                      and np.isfinite(bounds['low'][g]) and np.isfinite(bounds['high'][g])
                      and np.isfinite(current['mid'][g]))
        low &= bool(window['efficiency'][g] <= config['low_er'])
        inside &= bool(bounds['low'][g] <= current['mid'][g] <= bounds['high'][g])
        for seconds in (30, 300):
            value = market['windows'][seconds]
            known &= bool(value['source_valid'][g] and np.isfinite(value['ret_bp'][g]))
        for history in (market['windows'][30], market['windows'][300], bounds):
            old = int(history['old'][g])
            old_clocks.append(float(record['time_s'][old]) if 0 <= old < len(record['time_s']) else np.nan)
    common = int(material['entries'][key[0]]['common'][g])
    oldest = float(np.min(old_clocks))
    return {'known': bool(known), 'raw': bool(known and low and inside and common == 0),
            'oldest': oldest, 'sources': sources, 'clocks': clocks, 'common': common}


def pauses(ident: str, ledger_sets: dict, config: dict, material: dict, control: str) -> list:
    """
    機能: N4の実損切りから解除又は場末までを記録し、区間内の対照新規を分類する。
    引数: ident/control (str)、ledger_sets/config/material (dict)。
    返り値: list[dict] は休止区間と対照機会。因果除外額は別の全経路差分を用いる。
    """
    output = []
    for key, ledger in ledger_sets[ident].items():
        record = material['prices'][key]
        events = ledger['events']
        starts, releases = events[events[:, 3] == 28], events[events[:, 3] == 30]
        mapped = R.published_grid(record, material['grids'][key[0]]['grid'])
        for event in starts:
            start = int(event[0])
            following = releases[releases[:, 0] > start]
            end = int(following[0, 0]) if len(following) else len(record['time_s']) - 1
            state = R.state_at(ledger, start, 'risk')
            assert state['failure_paused'] == 1 and state['failure_exit_row'] == start
            release_evidence = None
            if len(following):
                self_returned = (record['price_valid'][end] and record['quote_valid'][end]
                                 and abs(record['price'][end] - state['failure_center'])
                                 <= config['failure_center_fraction'] * state['failure_width'] + record['tick'] * 1e-8)
                peer_symbol = 'NK225' if key[1] == 'TOPIX' else 'TOPIX'
                g = int(mapped[end])
                peer = material['grids'][key[0]]['markets'][peer_symbol]['current']
                peer_record = material['prices'][key[0], peer_symbol]
                fresh = g >= 0 and record['time_s'][end] - material['grids'][key[0]]['grid'][g] <= 10.
                peer_source = int(peer['index'][g]) if fresh else -1
                peer_returned = bool(fresh and peer_source >= 0 and peer['valid'][g] and peer.get('q_valid', peer['valid'])[g]
                                     and peer_source > state['failure_exit_peer_source']
                                     and peer_record['time_s'][peer_source] > state['failure_exit_time']
                                     and abs(peer['mid'][g] - state['failure_peer_center'])
                                     <= config['failure_center_fraction'] * state['failure_peer_width'] + peer_record['tick'] * 1e-8)
                kind = config['range_failure_reentry_kind']
                if kind in ('return_self', 'return_both'):
                    assert self_returned and (kind != 'return_both' or peer_returned)
                    release_evidence = {'自己帰還': bool(self_returned), '同判断相手帰還': peer_returned,
                                        '相手公開源': peer_source,
                                        '相手原板時計': R.clock(peer_record['time_s'][peer_source]) if peer_source >= 0 else None,
                                        '自己のみ版は相手鮮度を要求しない': kind == 'return_self'}
                else:
                    assert fresh
                    false_events = events[(events[:, 3] == 29) & (events[:, 0] > start) & (events[:, 0] < end)]
                    assert len(false_events) == 1
                    false_row = int(false_events[0, 0])
                    false_grid = int(mapped[false_row])
                    false, true = raw_observation(key, false_grid, material, config), raw_observation(key, g, material, config)
                    assert false['known'] and not false['raw'] and true['known'] and true['raw']
                    assert false['oldest'] > state['failure_exit_time'] and true['oldest'] > state['failure_exit_time']
                    assert g > false_grid
                    for symbol in R.SYMBOLS:
                        exit_source = state['failure_exit_own_source' if symbol == key[1] else 'failure_exit_peer_source']
                        assert false['sources'][symbol] > exit_source and true['sources'][symbol] > false['sources'][symbol]
                        assert false['clocks'][symbol] > state['failure_exit_time'] and true['clocks'][symbol] > state['failure_exit_time']
                    release_evidence = {'有効False行': false_row, '有効False時刻': R.clock(record['time_s'][false_row]),
                                        'False入力': false, 'True入力': true,
                                        '元mode2確認': '全件独立状態監査で照合。ここではrawの入力と全窓時計を独立照合。'}
            range_orders = ledger['orders'][(ledger['orders'][:, 3] == 1) & (ledger['orders'][:, 7] == 1)]
            assert not np.any((range_orders[:, 1] >= start) & (range_orders[:, 1] <= end))
            alternatives = ledger_sets[control][key]['trades']
            alternatives = alternatives[(alternatives[:, 1] == 1) & (alternatives[:, 15] > start) & (alternatives[:, 15] <= end)]
            output.append({'条件': ident, '場': key[0], '銘柄': key[1], '開始行': start, '終了行': end,
                           '開始時刻': R.clock(record['time_s'][start]), '終了時刻': R.clock(record['time_s'][end]),
                           '休止秒': float(record['time_s'][end] - record['time_s'][start]), '場末まで未解除': not len(following),
                           '旧失敗中心': state['failure_center'], '旧相手中心': state['failure_peer_center'],
                           '解除の独立入力証拠': release_evidence,
                           '対照': control, '区間内に対照が発注した親会計': R.totals(alternatives),
                           '対照と反発数量が異なる': config['range_budget'] != (10 if control in ('C02', 'C06') else 2),
                           '注意': '区間内の対照親は候補機会の診断。全経路で因果的に消えた親の額とは同一でない。小枠S02/S03の対照C06は全枠なので数量差も持つ。'})
    return output


def distribution(rows: list, field: str) -> dict:
    """
    機能: 事後診断群の有限値の分布を表示する。
    引数: rows (list[dict])、field (str)。
    返り値: dict は件数・最小・中央値・90%点・最大。
    """
    values = np.array([v[field] for v in rows if np.isfinite(v[field])])
    return {'件数': len(values), '最小': float(values.min()) if len(values) else None,
            '中央値': float(np.median(values)) if len(values) else None,
            '90%点': float(np.quantile(values, .9)) if len(values) else None,
            '最大': float(values.max()) if len(values) else None}


def main() -> None:
    """
    機能: 全正式完了の根許可後、予定入口と実停止及び休止の診断を保存する。
    引数: --根許可後 (bool)。
    返り値: None。新しい条件又は売買経路を再生しない。
    """
    R.permission()
    fixed, assembled = R.validate()
    data = R.module('予定値独立読取93', R.WORK / 'data.py')
    material = data.load_inputs()
    ledgers = {v['id']: R.load_ledgers(v['id']) for v in fixed['条件']}
    gate_rows, parent_rows, pause_rows, views = [], [], [], {}
    for config in fixed['条件']:
        ident = config['id']
        gates, parents = gate_diagnosis(ident, ledgers[ident], config, material)
        gate_rows.extend(gates)
        parent_rows.extend(parents)
        if config['range_failure_reentry_kind'] != 'legacy':
            pause_rows.extend(pauses(ident, ledgers, config, material, 'C06' if ident in ('C11', 'S02', 'S03') else 'C02'))
        views[ident] = {}
        for symbol in R.SYMBOLS:
            own = [v for v in gates if v['銘柄'] == symbol]
            accepted = [v for v in own if v['受理']]
            rejected = [v for v in own if not v['受理']]
            actual = [v for v in parents if v['銘柄'] == symbol]
            flags = {}
            for width_flag in (False, True):
                for witness_flag in (False, True):
                    group = [v for v in actual if bool(v['exit_width_flag']) == width_flag
                             and bool(v['exit_witness_flag']) == witness_flag]
                    flags[f'幅{int(width_flag)}_極値{int(witness_flag)}'] = {
                        '親': len(group), '利益親': sum(v['net'] > 0 for v in group),
                        '利益円': sum(max(v['net'], 0.) for v in group),
                        '損失円': -sum(min(v['net'], 0.) for v in group), '収支円': sum(v['net'] for v in group)}
            views[ident][symbol] = {'全gate': len(own), '受理': len(accepted), '拒否': len(rejected),
                                   '受理深さ': distribution(accepted, '深さu'), '拒否深さ': distribution(rejected, '深さu'),
                                   '受理予定比': distribution(accepted, 'center_ratio'), '拒否予定比': distribution(rejected, 'center_ratio'),
                                   '全親深さ': distribution(actual, '深さu'), '実停止証拠別会計': flags,
                                   '活動場': assembled['results'][ident]['periods']['全31'][symbol]['active_sessions']}
        print(f'{ident}: 当時予定値・全反発親停止証拠の独立診断', flush=True)
    # ----------------------------------------
    # 拒否例は成績順位で選ばず、条件と場名と当時行の固定順で20例を原本同seq照合する。
    rejected = sorted((v for v in gate_rows if not v['受理']), key=lambda v: (v['条件'], v['場'], v['銘柄'], v['判断行']))[:20]
    wanted = {}
    for value in rejected:
        key = value['場'], value['銘柄']
        record = material['prices'][key]
        mapped = R.published_grid(record, material['grids'][key[0]]['grid'])
        value['原板'] = R.point(key, value['判断行'], material, mapped, wanted)
    proofs = R.attach_raw(wanted)
    R.save('全16条件の予定入口と停止証拠及び失敗休止の独立診断.json', {
        '全合格': True, '条件数': 16, '口座': 992, '商品別診断': views,
        '全gate判断': gate_rows, '全反発親': parent_rows, 'N4全休止': pause_rows,
        '拒否20例の当時原板': rejected, '原本同seq照合': proofs,
        '注意': ['予定rhoと実PF・実勝負比を混同しない。深い逸脱の選択はドリフトへ逆張りすることもある。',
                 '幅と極値の異なる価格基準を保持。停止線での約定保証としない。',
                 '潜在状態の全件独立復元・未来不変検査は監査担当が別途行う。'],
        '計算コードSHA256': R.digest(Path(__file__)), **R.provenance()})
    print('予定入口と停止証拠及び失敗休止の独立診断を保存しました', flush=True)


if __name__ == '__main__':
    main()
