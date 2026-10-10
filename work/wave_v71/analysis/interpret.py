"""機能: 事前選定の入口確認・幅拡大を、先着率と管理別損益へ独立分解する。"""

import json
import hashlib
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SYMBOLS = ('TOPIX', 'NK225')
PERIODS = ('前16', '後12', '全28', '追加1', '全29')


def load(path):
    """機能: 保存固定資料・結果・台帳だけを読む。

    引数: path(Path)。返り値: objectの保存内容。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf-8'))


def amount_summary(result):
    """機能: 手数料後の一組損益と元玉・保険内訳を期間別に抜き出す。

    引数: result(dict)。返り値: dictの5期間・2銘柄比較。
    """
    fields = ('net', 'campaigns', 'mean_net_ticks', 'campaign_profit', 'campaign_loss',
              'campaign_win_rate', 'campaign_payoff', 'core_net', 'cover_net',
              'fees', 'drawdown', 'max_campaign_loss', 'without_best_session', 'active_sessions')
    return {p: {s: {k: a[k] for k in fields} for s, a in result['periods'][p].items()} for p in PERIODS}


def management_difference(a, baseline):
    """機能: 合計改善と一組平均改善を分け、元玉・保険の差額を確認する。

    引数: a/baseline(dict)は期間銘柄会計。返り値: dictの差と組数比。
    """
    count_term = ((a['campaigns'] - baseline['campaigns']) * baseline['net'] / baseline['campaigns']
                  if baseline['campaigns'] else None)
    average_term = (a['net'] - baseline['net'] * a['campaigns'] / baseline['campaigns']
                    if baseline['campaigns'] else None)
    if count_term is not None:
        assert abs(a['net'] - baseline['net'] - count_term - average_term) < 1e-6
    return {'net_delta': a['net'] - baseline['net'],
            'mean_net_ticks_delta': a['mean_net_ticks'] - baseline['mean_net_ticks'],
            'entry_count_ratio': a['campaigns'] / baseline['campaigns'] if baseline['campaigns'] else None,
            'core_net_delta': a['core_net'] - baseline['core_net'],
            'cover_net_delta': a['cover_net'] - baseline['cover_net'],
            'fees_delta': a['fees'] - baseline['fees'],
            'baseline_count_scaled_net': baseline['net'] * a['campaigns'] / baseline['campaigns']
            if baseline['campaigns'] else None,
            'amount_above_count_scaled_baseline': a['net'] - baseline['net'] * a['campaigns'] / baseline['campaigns']
            if baseline['campaigns'] else None,
            '組数変化の線形分解項': count_term, '一組平均変化の線形分解項': average_term,
            '線形分解の注意': '金額×組数の恒等分解で、ランダムに取引を減らす実験や原因の独立性を仮定しない。'}


def cover_inventory(ledger, sessions, symbol):
    """機能: 保険の単独反転返済と終端残玉を注文単位で集計する。

    引数: ledger(dict)、sessions(list[str])、symbol(str)。返り値: dictの注文と玉の集計。
    FIFO明細数を注文回数に数えず、終端に残った利益・損失も全玉へ含める。
    """
    profitable_orders = terminal_orders = opened_quantity = terminal_quantity = 0
    covered_groups = no_profit_exit_groups = 0
    profit_exit_net = terminal_net = 0.0
    for (session, current_symbol), data in ledger.items():
        if session not in sessions or current_symbol != symbol:
            continue
        oo, tt = data['orders'], data['trades']
        new = oo[(oo[:, 8] == 1) & (oo[:, 7] == 1)]
        normal = oo[(oo[:, 8] == 1) & (oo[:, 7] == 0) & (oo[:, 6] == 8)]
        terminal = oo[(oo[:, 8] == 1) & (oo[:, 7] == 0) & (oo[:, 6] <= 6)]
        profitable_orders += len(normal)
        terminal_orders += len(terminal)
        opened_quantity += int(new[:, 4].sum())
        terminal_quantity += int(terminal[:, 4].sum())
        covered = set(new[:, 2].astype(int))
        covered_groups += len(covered)
        no_profit_exit_groups += len(covered - set(normal[:, 2].astype(int)))
        for order in normal:
            batch = tt[(tt[:, 0] == order[2]) & (tt[:, 2] == order[0]) & (tt[:, 11] == 1)]
            profit_exit_net += float(batch[:, 10].sum())
        for order in terminal:
            batch = tt[(tt[:, 0] == order[2]) & (tt[:, 2] == order[0]) & (tt[:, 11] == 1)]
            terminal_net += float(batch[:, 10].sum())
    return {'covered_campaigns': covered_groups, 'without_cover_profit_exit_campaigns': no_profit_exit_groups,
            'cover_profit_exit_orders': profitable_orders, 'cover_terminal_exit_orders': terminal_orders,
            'cover_new_lots_total': opened_quantity, 'cover_terminal_lots_total': terminal_quantity,
            'cover_profit_exit_net': profit_exit_net, 'cover_terminal_net': terminal_net}


def main():
    """機能: 新条件や選び直しを行わず、固定代表と全432の参考範囲を診断する。

    引数: なし。返り値: None。analysis/入口確認と幅拡大の効果と限界.jsonへ保存する。
    """
    fixed = load(ROOT / '事前固定.json')
    selection = load(ROOT / '前半選定.json')
    diagnostic = load(HERE / '入口方向の独立診断.json')
    results = {p.stem: load(p) for p in (ROOT / 'results').glob('*.json')}
    assert len(results) == 432
    source = results[selection['比較代表']]['config']['source']
    selected_gate = results[selection['比較代表']]['config']['gate_level']
    selected_width = results[selection['比較代表']]['config']['width_id']
    main_ids = [selection['基準']] + [r['id'] for r in selection['代表']]
    baseline = results[selection['基準']]
    main = {}
    for id in main_ids:
        r = results[id]
        main[id] = {'config': r['config'], '期間': amount_summary(r),
                    '基準との差': {p: {s: management_difference(r['periods'][p][s], baseline['periods'][p][s])
                                        for s in SYMBOLS} for p in PERIODS}}
    # ----------------------------------------
    # 幅を固定して入口正答を比較する。保険・幅に関係ない診断の同じ系列を用いる。
    confidence = {}
    for p in PERIODS:
        confidence[p] = {}
        for s in SYMBOLS:
            base = diagnostic['集計'][source + '_G0'][p][s]
            confirmed = diagnostic['集計'][source + '_G' + str(selected_gate)][p][s]
            confidence[p][s] = {'旧入口': base, '確認入口': confirmed,
                                 '入口数比': confirmed['8']['total'] / base['8']['total'] if base['8']['total'] else None,
                                 '先着率差': {str(level): confirmed[str(level)]['favorable_rate_all'] - base[str(level)]['favorable_rate_all']
                                            if confirmed[str(level)]['total'] and base[str(level)]['total'] else None
                                            for level in (8, 16)}}
    # ----------------------------------------
    # 元玉だけ・保険だけ・両方の幅を事前定義通りに比較し、全玉の費用を残す。
    width_effects = {}
    fixed_periods = {'前16': fixed['前16'], '後12': fixed['後12'], '全28': fixed['全セッション'],
                     '追加1': fixed['追加追試'], '全29': fixed['全セッション'] + fixed['追加追試']}
    for gate in (0, selected_gate):
        group = source + '_G' + str(gate)
        width_effects[group] = {}
        base = results[group + '_W0_H']
        for width in range(6):
            id = group + '_W' + str(width) + '_H'
            r = results[id]
            ledger = load(ROOT / 'ledgers' / (id + '.pkl'))
            width_effects[group]['W' + str(width)] = {
                'id': id, '幅名': r['config']['width_name'],
                '元玉幅': r['config']['trail'], '保険幅': r['config']['cover_trail'],
                '元玉開始': r['config']['activation'], '保険開始': r['config']['cover_activation'],
                '期間': amount_summary(r),
                'W0との差': {p: {s: management_difference(r['periods'][p][s], base['periods'][p][s])
                                  for s in SYMBOLS} for p in PERIODS},
                '保険注文と終端': {p: {s: cover_inventory(ledger, keys, s) for s in SYMBOLS}
                                     for p, keys in fixed_periods.items()},
            }
    # ----------------------------------------
    # 主選定外の少数黒字も隠さない。ただし全28の損益から採用条件を選び直さない。
    positive = []
    for id, r in sorted(results.items()):
        if all(r['periods']['全28'][s]['net'] > 0 for s in SYMBOLS):
            a = r['periods']['前16']
            positive.append({'id': id, 'method': r['config']['method'], 'gate': r['config']['gate_level'],
                             'source': r['config']['source'],
                             '前16最低数充足': all(a[s]['campaigns'] >= 20 and a[s]['active_sessions'] >= 8 for s in SYMBOLS),
                             '主選定対象': r['config']['method'] == 'H' and r['config']['gate_level'] in (1, 2)
                             and r['config']['width_id'] != 'W0', '期間': amount_summary(r)})
    schedule = load(ROOT / 'inputs/schedule.pkl')
    t3same = all(np.array_equal(v[2 * 4], v[2 * 4 + 1]) for v in schedule.values())
    example = results['T3L1_G1_W4_D']
    assert t3same
    positive_example = {
        'id': 'T3L1_G1_W4_D', '性質': '全28で黒字を確認した主選定外の少数参考例。採用条件ではない。',
        '全58口座でG0とG1の実入口列完全一致': t3same,
        'G1確認による新たな方向確度改善ではない': True,
        '期間': amount_summary(example),
        '入口診断': {p: diagnostic['集計']['T3L1_G1'][p] for p in PERIODS},
        '理由': ['前16のNKは6組・5活動場で最低数未達、収支も-38,640円。',
                 '全28のNKは14組と少ない。TOPIXは最大黒字場を除くと-74,260円。',
                 '追加DayはTOPIX1組+14,164円、NK無取引。NK無取引を勝ちに数えない。',
                 '元玉幅24・保険なしの結果で、保険トレール改善やG1の確認効果の証明にはならない。']}
    # ----------------------------------------
    # 入口確認や未使用の保険幅が違っても実売買が同じ場合を、独立な黒字例へ水増ししない。
    executed_groups = {}
    prior_sessions = set(fixed['全セッション'])
    for example_row in positive:
        id = example_row['id']
        ledger = load(ROOT / 'ledgers' / (id + '.pkl'))
        digest = hashlib.sha256()
        for key in sorted(ledger):
            if key[0] not in prior_sessions:
                continue
            digest.update(repr(key).encode('utf-8'))
            # 理由のラベルは外し、時刻・数量・価格・新規返済・役割の実売買を比較する。
            digest.update(ledger[key]['orders'][:, [0, 1, 2, 3, 4, 5, 7, 8]].tobytes())
        executed_groups.setdefault(digest.hexdigest(), []).append(id)
    output = {
        '選定': selection, '新条件追加': False, '結果を見た選び直し': False,
        'API取得': 0, '実注文': 0, '基準と3対照': main,
        '入口確度': confidence, '固定入口での幅効果': width_effects,
        '全432で両銘柄全28黒字の参考条件': positive,
        '黒字参考の集計': {'条件数': len(positive),
                          'G3代理時計を除く': sum(r['gate'] != 3 for r in positive),
                          '前16最低数を満たす': sum(r['前16最低数充足'] for r in positive),
                          '全てT3L1': all(r['source'] == 'T3L1' for r in positive),
                          '同じ実売買を束ねた群数': len(executed_groups),
                          '同じ実売買の群': list(executed_groups.values()),
                          '注意': '異なる実売買の群も同じ少数期間のため、独立した統計的証拠の数ではない。'},
        '少数黒字の代表説明': positive_example,
        '短い結論': [
            '主比較T2のG2は入口数を約70〜77%減らすが、全28の±8先着率はTOP44.5→42.1%、NK37.8→21.6%。方向確度が上がったとは言えない。',
            '主代表G2W2は合計赤字を縮小するが、1組平均の料金後呼値収支は旧G0W0より両方悪い。合計損失減を入口確度改善と呼ばない。',
            '保険幅4→8は、旧入口ではTOPを102,513円悪化・NKを170,790円改善。確認入口ではTOPを67,496円改善・NKを8,050円悪化。幅の共通優位はない。',
            '保険単独利確は幅4→8で旧入口TOP54→14回、NK75→26回へ減少。幅12ではTOP0回・NK3回。広い幅と利益限定条件のため残玉を終端まで持つ傾向が強くなる。',
            '追加Dayの主代表は+23,914/+13,010円だが1/2組。後12・全28とも両方赤字なので、この1場から安定性を結論しない。',
            '両銘柄黒字の参考例は存在するが全てT3L1の少数系列。G0とG1は同じ実入口列で、確認で増えた優位性ではない。',
        ],
        '限界': ['MFEは方向の利益限界で、先に逆行するかを無視する。先着と分離して報告する。',
                 'G2の残り観測時間中央値はNK約394分対G0約335分。MFEの拡大には入口の時刻・日中夜間の構成差も混在する。',
                 'G3は受信同期を証明できず主選定から除外。',
                 '保険の利益限定返済を維持したため、損失保険の独立停止・元方向再開で保険削減は未検証。',
                 'ラージ代理気配・次行約定で、実ミニ/マイクロ板・深さ・通信・部分約定は再現していない。',
                 '保存28場は既知。条件を固定しても完全未見の外部検証ではない。']}
    (HERE / '入口確認と幅拡大の効果と限界.json').write_text(
        json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'黒字参考集計': output['黒字参考の集計'], '短い結論': output['短い結論']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
