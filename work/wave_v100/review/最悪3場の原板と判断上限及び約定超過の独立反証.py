"""全31正式完了後に少数の経済原因だけを原本同seqへ照合する。"""

from pathlib import Path

import numpy as np

import 共通独立読取 as R
import 元候補対応と独立会計分解 as P
import 判断価格上限の独立診断 as C


def stability_leaders(results: dict) -> dict:
    """
    機能: 活動要件を通った全31の事後RMS順位を独立算出し原因確認の対象を選ぶ。
    引数: results(dict)。
    返り値: dict。主及び前16参考を変更せず、順位を未知性能の認定へ使わない。
    """
    pool = [ident for ident, result in results.items() if all(
        result['periods']['全31'][symbol]['campaigns'] >= 20
        and result['periods']['全31'][symbol]['active_sessions'] >= 8 for symbol in R.SYMBOLS)]
    def score(ident: str) -> tuple:
        """
        機能: 共通上限による下方偏差と活動黒字率等の事前固定順を使う。
        引数: ident(str)。
        返り値: tupleは事後の診断順序。
        """
        result = results[ident]
        stable = [result['stability']['全31'][symbol] for symbol in R.SYMBOLS]
        money = [result['periods']['全31'][symbol] for symbol in R.SYMBOLS]
        return (max(value['downside_rms_units'] for value in stable),
            -min(value['positive_session_rate'] for value in stable),
            max(value['worst_session_loss_units'] for value in stable),
            -min(value['active_net_q25_units'] for value in stable),
            -min(value['profit_share'] for value in money), ident)
    ranking = sorted(pool, key=score)
    return dict(活動充足条件=pool, 安定性事後順=ranking, 上位2参考=ranking[:2],
        採点={ident: score(ident) for ident in ranking[:2]},
        scope='全31既知の事後原因分類。前16選定又は事前主の差替えではない。')


def support_sources(key: tuple, ledger: dict, grid: int, material: dict, wanted: dict) -> dict:
    """
    機能: 実判断格子の独立LPと旧執行BBOを別源で原本へ対応させる。
    引数: key(tuple[str,str])、ledger/material/wanted(dict)、grid(int)。
    返り値: dict。格子の自己BBOと実判断行の自己BBOを同一視しない。
    """
    selected = ledger['entry_support_state_trace']
    selected = selected[selected[:, 0] == grid]
    assert len(selected) == 1
    values = P.named(selected[0], ledger['entry_support_columns'])
    result = dict(保存59支持列=values, 別源原板={})
    peer = 'NK225' if key[1] == 'TOPIX' else 'TOPIX'
    for prefix, symbol in (('own', key[1]), ('peer', peer)):
        source_key = key[0], symbol
        out = {}
        for name, validity in (('current', 'valid'), ('old300', 'endpoint_valid')):
            stem = prefix + '_lp_' + name + '_'
            index = int(values[stem + 'index'])
            if index >= 0 and values[stem + validity] == 1.:
                point = R.lp_point(source_key, index, material, wanted)
                assert point['原本seq'] == int(values[stem + 'raw_seq'])
                assert point['LastPrice'] == values[stem + 'value']
                out['独立LP_' + name] = point
        index = int(values[prefix + '_execution_bbo_index'])
        if index >= 0:
            point = R.raw_point(source_key, material['prices'][source_key], index, wanted)
            assert point['原本seq'] == int(values[prefix + '_execution_bbo_raw_seq'])
            out['格子の旧BBO'] = point
        result['別源原板'][symbol] = out
    return result


def parent_case(key: tuple, ledger: dict, parent_id: int, config: dict,
                material: dict, wanted: dict) -> dict:
    """
    機能: 代表親の候補・判断・新規・返済を原本に照合し上限と保有後変位を分ける。
    引数: key(tuple[str,str])、ledger/config/material/wanted(dict)、parent_id(int)。
    返り値: dict。事後MFE及び返済価格を未来の入口情報へ戻さない。
    """
    origin = P.origin_map(ledger, material['prices'][key])
    selected = [value for value in origin.values() if int(value['trade'][0]) == parent_id]
    assert len(selected) == 1
    value = selected[0]
    trade, d = value['trade'], value['entry']
    record = material['prices'][key]
    mapped = R.published_grid(record, material['trend_prices']['I3'][key[0]]['grid'])
    points = {}
    for label, row in (('元候補', d['candidate_row']), ('発注判断', d['trigger_row']),
                       ('実新規', d['fill_row']), ('返済判断', ledger['orders'][
                           (ledger['orders'][:, 2] == parent_id) & (ledger['orders'][:, 7] == 0)][0, 1]),
                       ('実返済', trade[3])):
        points[label] = R.point(key, int(row), material, mapped, wanted)
    side, entry, exit_row = int(trade[4]), int(trade[2]), int(trade[3])
    quote = record['bid'] if side == 1 else record['ask']
    eligible = record['quote_valid'][entry:exit_row + 1] & np.isfinite(quote[entry:exit_row + 1])
    progress = side * (quote[entry:exit_row + 1][eligible] - trade[6])
    valid_rows = np.arange(entry, exit_row + 1)[eligible]
    baseline = quote[entry]
    changed = valid_rows[side * (quote[valid_rows] - baseline) != 0.]
    first_change = int(changed[0]) if len(changed) else None
    first_direction = '順行' if first_change is not None and side * (quote[first_change] - baseline) > 0 \
        else '逆行' if first_change is not None else '変化なし'
    if first_change is not None:
        points['新規後最初の正常な清算気配変化'] = R.point(key, first_change, material, mapped, wanted)
    multiplier = 1000. if key[1] == 'TOPIX' else 10.
    fee_width = float(trade[8] + trade[9]) / (trade[5] * multiplier)
    fee_positive = valid_rows[progress > fee_width]
    first_positive = int(fee_positive[0]) if len(fee_positive) else None
    if first_positive is not None:
        points['最初に往復料金込み黒字となった正常気配'] = R.point(key, first_positive, material, mapped, wanted)
    reference = material['metadata']['references']['|'.join(key)]['ref_open']
    assert reference['known_from_i'] == 0
    initial = max(2, int(np.ceil(reference['value'] * config['trend_initial_stop_bp']
        / 10000. / record['tick'] - 1e-10))) * record['tick']
    cap = P.named(ledger['entry_cap_parent_diagnostics'][
        ledger['entry_cap_parent_diagnostics'][:, 0] == parent_id][0], ledger['entry_cap_parent_columns'])
    assert cap['trigger_adverse_width'] == side * (d['trigger_quote'] - d['candidate_quote'])
    assert cap['fill_adverse_width'] == side * (d['fill_price'] - d['candidate_quote'])
    peak = float(progress.max()) if len(progress) else None
    losing = trade[11] < -1e-5
    returned = bool(losing and first_positive is not None)
    width_returned = bool(losing and peak is not None and peak >= initial)
    chase_decision = bool(cap['trigger_adverse_width'] > d['width'])
    chase_fill = bool(cap['fill_adverse_width'] > d['width'])
    labels = []
    if losing:
        if chase_decision: labels.append('判断の候補比不利幅が1W超')
        elif chase_fill: labels.append('判断は1W以内でも実fillが1W超')
        else: labels.append('判断と実fillは候補比1W以内')
        labels.append('最初の正常清算気配変化は' + first_direction)
        labels.append('料金込み黒字へ一度進んだ後に赤字返済' if returned else '料金込み黒字へ一度も進まず赤字返済')
        if width_returned: labels.append('初期停止幅以上の順行を返して赤字返済')
    rejected = C.blocked_samples(ledger, int(d['candidate_id']))
    for row in rejected:
        row['原板'] = R.point(key, row['行'], material, mapped, wanted)
        saved = row['保存20列']
        assert saved['adverse_width'] == side * (record['ask' if side == 1 else 'bid'][row['行']] - d['candidate_quote'])
        assert saved['adverse_width'] > saved['cap_width']
    return dict(親=P.scalar_parent(key[0], value), 判定上限21列=cap, 代表上限拒否=rejected,
        実判断格子のLPとBBO別源=support_sources(key, ledger, int(d['trigger_grid']), material, wanted),
        原板=points, 実保有秒=float(record['time_s'][exit_row] - record['time_s'][entry]),
        正常気配での事後MFE=peak,
        正常気配での事後MAE=float(progress.min()) if len(progress) else None,
        初期停止幅=initial, 返済理由=ledger['reasons'][int(trade[13])],
        事後原因分類=dict(赤字親=losing, 最初の正常清算気配変化方向=first_direction,
            最初の変化行=first_change, 新規時清算気配と実建値の差=side * (baseline - trade[6]),
            往復費用相当幅=fee_width, 最初の料金込み黒字行=first_positive,
            料金込み黒字を返した=returned, 初期停止幅以上の順行を返した=width_returned,
            判断の候補比1W超=chase_decision, 実fillの候補比1W超=chase_fill, 分類=labels,
            scope='重複する事後分類。新規時のspreadによる清算損を最初の逆行と混同しない。'
                  '最初の方向は自己の次の異なる正常清算気配であり、真受信時間又は将来予測ではない。'),
        scope='代表原seqだけを直接照合。事後MFEは原因説明であり参加時確度の算定ではない。')


def brief(result: dict) -> dict:
    """
    機能: 金額利益比と赤字/黒字/活動及び最大利益日依存を商品別に要約する。
    引数: result(dict)は固定条件の正式集計。
    返り値: dict。無取引及び取引減少も表示し総益だけで改善と呼ばない。
    """
    answer = {}
    for symbol in R.SYMBOLS:
        money = result['periods']['全31'][symbol]
        stable = result['stability']['全31'][symbol]
        answer[symbol] = dict(収支円=money['net'], 利益円=money['profit'], 損失円=money['loss'],
            金額利益割合=money['profit_share'], 親=money['campaigns'], 活動場=money['active_sessions'],
            黒字場=money['positive_sessions'], 赤字場=money['losing_sessions'], 無取引場=money['no_trade_sessions'],
            最大利益日除外収支円=money['without_best_day']['net'],
            平均赤字円=stable['mean_losing_session_yen'], 最大赤字円=stable['worst_session_loss_yen'],
            共通上限単位下方偏差=stable['downside_rms_units'], 活動黒字率=stable['positive_session_rate'])
    return answer


def main() -> None:
    """
    機能: 主/P0/前16参考/事後RMS上位の最悪3赤字場及び上限差の代表を原板へ照合する。
    引数: --根許可後(bool)は全31正式終端後に必須。
    返り値: None。全raw時価又は潜在最初触発の重複監査をせず自担当reviewへ保存する。
    """
    R.permission()
    fixed, assembled = R.validate()
    accounting_path = R.HERE / '全34条件全31の独立親会計と安定性及びNoCap旧620対照一致.json'
    accounting = R.read(accounting_path)
    assert accounting['全合格'] and accounting['NoCap旧口座一致数'] == 620
    decomp_path = R.HERE / '全34判断価格上限と支持源及び即時の同候補建値差と固有経路の独立分解.json'
    decomp = R.read(decomp_path)
    assert decomp['全合格'] and decomp['根集計SHA256'] == R.digest(R.WORK / 'analysis/比較結果.json')
    leaders = stability_leaders(assembled['results'])
    assert leaders['安定性事後順'] == assembled['安定性の事後診断順']
    targets = list(dict.fromkeys([fixed['主'], 'P0_L1_C1_A1_X1', assembled['selected']]
        + leaders['上位2参考'] + ['A0_X1', 'A0_X3']))
    for ident in list(targets):
        if ident.startswith(('P05_', 'P1_', 'P2_')):
            control = 'P0_' + ident.split('_', 1)[1]
            if control not in targets: targets.append(control)
    material, wanted, output = R.material(), {}, {}
    requested, nonparticipants = {}, {}
    examples = {}
    for changed in targets:
        if changed.startswith(('A0_', 'P0_')): continue
        control = 'P0_' + changed.split('_', 1)[1]
        pair = control + '→' + changed
        evidence = decomp['比較'][pair]['期間別元候補対応']['全31']
        examples[pair] = {}
        for symbol in R.SYMBOLS:
            v = evidence[symbol]
            groups = dict(逃した元勝ち=sorted([row for row in v['元固有一覧'] if row['純額円'] > 0],
                key=lambda row: -row['純額円'])[:2],
                避けた元負け=sorted([row for row in v['元固有一覧'] if row['純額円'] < 0],
                    key=lambda row: row['純額円'])[:2],
                新固有負け=sorted([row for row in v['新固有一覧'] if row['純額円'] < 0],
                    key=lambda row: row['純額円'])[:2],
                同候補改善=v['改善上位例'][:2], 同候補悪化=v['悪化上位例'][:2],
                同候補建値又は返済が変化=sorted([row for row in v['同候補一覧']
                    if abs(row['建値差円']) > 1e-5 or abs(row['返済差円']) > 1e-5],
                    key=lambda row: -abs(row['建値差円']) - abs(row['返済差円']))[:2])
            examples[pair][symbol] = groups
            for label, rows in groups.items():
                for row in rows:
                    if label.startswith('同候補'):
                        references = ((control, row['元']), (changed, row['新']))
                    else:
                        references = ((changed if label == '新固有負け' else control, row),)
                    for ident, parent in references:
                        requested.setdefault(ident, {}).setdefault((parent['場'], symbol), set()).add(parent['親'])
                    if not label.startswith('同候補'):
                        other = control if label == '新固有負け' else changed
                        nonparticipants.setdefault(other, {}).setdefault((row['場'], symbol), set()).add(
                            (row['元候補ID'], row['元候補行'], row['方向']))
    configs = {config['id']: config for config in fixed['条件']}
    for ident in targets:
        ledger = R.load_ledgers(ident)
        result = assembled['results'][ident]
        worst, parents, exclusions = {}, {}, {}
        for symbol in R.SYMBOLS:
            red = sorted([row for row in result['rows'] if row['symbol'] == symbol and row['net'] < -1e-5],
                key=lambda row: (row['net'], row['session']))[:3]
            worst[symbol] = []
            for row in red:
                key = row['session'], symbol
                requested.setdefault(ident, {}).setdefault(key, set()).update(int(t[0]) for t in ledger[key]['trades'])
                worst[symbol].append(dict(場=row['session'], 収支円=row['net'], 利益円=row['profit'],
                    損失円=row['loss'], 親数=row['campaigns']))
        for key, ids in requested.get(ident, {}).items():
            parents['|'.join(key)] = {str(pid): parent_case(key, ledger[key], pid, configs[ident], material, wanted)
                for pid in sorted(ids)}
        for key, origins in nonparticipants.get(ident, {}).items():
            record = material['prices'][key]
            mapped = R.published_grid(record, material['trend_prices']['I3'][key[0]]['grid'])
            rows = []
            for candidate_id, candidate_row, side in sorted(origins):
                quote = record['ask' if side == 1 else 'bid']
                samples = C.blocked_samples(ledger[key], candidate_id)
                for sample in samples:
                    saved = sample['保存20列']
                    assert saved['candidate_quote'] == quote[candidate_row]
                    assert saved['adverse_width'] == side * (quote[sample['行']] - quote[candidate_row])
                    assert saved['adverse_width'] > saved['cap_width']
                    sample['原板'] = R.point(key, sample['行'], material, mapped, wanted)
                rows.append(dict(元候補ID=candidate_id, 方向=side,
                    元候補原板=R.point(key, candidate_row, material, mapped, wanted),
                    上限拒否代表=samples, 旧取消消費の保存根拠=P.exclusion_evidence(ledger[key], candidate_row, side),
                    scope='実親不参加の候補を原板へ確認。cap拒否が存在しない時は勝手にcap原因と断定しない。'))
            exclusions['|'.join(key)] = rows
        cause_counts = {}
        for symbol in R.SYMBOLS:
            sessions = [row['場'] for row in worst[symbol]]
            red_parents = [parent for session in sessions
                for parent in parents.get('|'.join((session, symbol)), {}).values()
                if parent['事後原因分類']['赤字親']]
            fields = ('料金込み黒字を返した', '初期停止幅以上の順行を返した', '判断の候補比1W超', '実fillの候補比1W超')
            cause_counts[symbol] = dict(対象='当該設定の最悪3赤字セッション内の全赤字親のみ',
                赤字親=len(red_parents),
                重複事後分類={field: sum(parent['事後原因分類'][field] for parent in red_parents) for field in fields},
                最初の正常清算気配変化={side: sum(parent['事後原因分類']['最初の正常清算気配変化方向'] == side
                    for parent in red_parents) for side in ('順行', '逆行', '変化なし')})
        output[ident] = dict(全31安定性と活動=brief(result), 最悪3赤字場=worst, 原板付き代表親=parents,
            最悪3場の赤字親原因集計=cause_counts,
            相手側の参加を失った候補の原板=exclusions)
        print(f'{ident}: 最悪3場と上限差の代表を原seqへ対応', flush=True)
        del ledger
    raw_proof = R.attach_raw(wanted)
    R.save('主とP0及び前16参考と事後RMS上位の最悪3場原板と判断約定上限の独立反証.json', dict(
        全合格=True, 主=fixed['主'], 主変更=False, 前16固定参考=assembled['selected'],
        参考事後差替え=False, 事後安定性対象=leaders, 原板診断対象=targets,
        条件別代表=output, 価格上限差の代表親選択=examples, 原本同seq照合=raw_proof,
        注意=['判断capを実指値約定上限へ置き換えない。cap外fillの親も正式会計へ含める。',
            '赤字額の縮小を黒字率や活動減少と分離する。無取引は勝ちでない。',
            '平均赤字及び最大赤字が減っても最大利益日除外や双方80%未達なら達成と認定しない。',
            'C1及び旧候補は固定。LP支持不明を実方向反転として読まない。',
            '代表原本と保存されたcap拒否を確認する範囲で、全潜在最初triggerは別監査担当。'],
        根拠SHA256={path.relative_to(R.ROOT).as_posix(): R.digest(path) for path in (accounting_path, decomp_path)},
        計算コードSHA256=R.digest(Path(__file__)), **R.provenance()))
    print('上限判断と約定超過及び安定性の少数原因を原本同seqで確認。新戦略再生0。', flush=True)


if __name__ == '__main__':
    main()
