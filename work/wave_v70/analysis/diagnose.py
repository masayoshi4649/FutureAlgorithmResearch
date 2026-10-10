"""機能: 固定済みの代表管理を一組損益・終端費用・前半順位だけで診断する。"""

import json
import math
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SYMBOLS = ('TOPIX', 'NK225')


def load(path):
    """機能: 固定結果のJSONまたは台帳を読み取る。

    引数: path(Path)。返り値: dictの保存内容。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf-8'))


def periods(result):
    """機能: 前半・後半・全期間について一組評価の必要値を簡潔に抜き出す。

    引数: result(dict)。返り値: dictの期間別・銘柄別評価。
    """
    fields = ('net', 'campaign_profit', 'campaign_loss', 'campaigns', 'campaign_wins',
              'campaign_losses', 'campaign_win_rate', 'campaign_payoff', 'fees',
              'drawdown', 'max_campaign_loss', 'without_best_session')
    return {p: {s: {k: a[k] for k in fields} for s, a in rows.items()}
            for p, rows in result['periods'].items()}


def groups(ledger):
    """機能: 玉別決済を元玉と保険を含む入口一組へ合算する。

    引数: ledger(dict)は場銘柄ごとの台帳。返り値: dictの場銘柄組別集計。
    """
    result = {}
    for (session, symbol), data in ledger.items():
        orders, trades = data['orders'], data['trades']
        for cid in sorted(set(orders[:, 2].astype(int))):
            oo, tt = orders[orders[:, 2] == cid], trades[trades[:, 0] == cid]
            first = oo[(oo[:, 7] == 1) & (oo[:, 8] == 0)][0]
            final = oo[(oo[:, 7] == 0) & (oo[:, 8] == 0)][-1]
            cover_exits = oo[(oo[:, 7] == 0) & (oo[:, 8] == 1) & (oo[:, 6] == 8)]
            cover_batches = []
            for row in cover_exits:
                exits = tt[(tt[:, 2] == row[0]) & (tt[:, 11] == 1)]
                cover_batches.append(float(exits[:, 10].sum()))
            result[(session, symbol, cid)] = {
                'session': session, 'symbol': symbol, 'cid': int(cid),
                'net': float(tt[:, 10].sum()),
                'core_net': float(tt[tt[:, 11] == 0, 10].sum()),
                'cover_net': float(tt[tt[:, 11] == 1, 10].sum()),
                'side': int(first[3]), 'entry_i': int(first[0]), 'exit_i': int(final[0]),
                'core_exit_reason': int(final[6]),
                'cover_new_orders': int(((oo[:, 7] == 1) & (oo[:, 8] == 1)).sum()),
                'cover_profit_exit_batches': len(cover_batches),
                'cover_profit_exit_net': sum(cover_batches),
                'cover_profit_exit_negative_batches': sum(x < 0 for x in cover_batches),
            }
    return result


def sign(value):
    """機能: 一組損益の正負を日本語分類へ変換する。

    引数: value(float)。返り値: strの勝ち・負け・同値。
    """
    return '勝ち' if value > 0 else '負け' if value < 0 else '同値'


def compare_campaigns(candidate, baseline, symbol):
    """機能: 同入口一組の損益差・勝敗変化・説明用事例を集計する。

    引数: candidate/baseline(dict)、symbol(str)。返り値: dictの比較結果。
    """
    rows = []
    transitions = {}
    for key, a in candidate.items():
        if key[1] != symbol:
            continue
        b = baseline[key]
        transition = sign(b['net']) + '→' + sign(a['net'])
        transitions[transition] = transitions.get(transition, 0) + 1
        rows.append(dict(a, baseline_net=b['net'], delta=a['net'] - b['net']))
    rows.sort(key=lambda r: r['delta'])
    return {'一組数': len(rows), '改善組': sum(r['delta'] > 0 for r in rows),
            '悪化組': sum(r['delta'] < 0 for r in rows), '同額組': sum(r['delta'] == 0 for r in rows),
            '差額合計': sum(r['delta'] for r in rows), '勝敗変化': transitions,
            '改善最大3組': rows[-3:][::-1], '悪化最大3組': rows[:3]}


def compare_sessions(candidate, baseline, symbol):
    """機能: 場単位の改善・悪化を基準の同じ場へ照合する。

    引数: candidate/baseline(dict)、symbol(str)。返り値: dictの比較結果。
    """
    by_key = {(r['session'], r['symbol']): r for r in baseline['rows']}
    rows = [dict(session=a['session'], net=a['net'], baseline_net=by_key[(a['session'], symbol)]['net'],
                 delta=a['net'] - by_key[(a['session'], symbol)]['net'],
                 core_net=a['core_net'], cover_net=a['cover_net'])
            for a in candidate['rows'] if a['symbol'] == symbol]
    rows.sort(key=lambda r: r['delta'])
    return {'改善場': sum(r['delta'] > 0 for r in rows), '悪化場': sum(r['delta'] < 0 for r in rows),
            '同額場': sum(r['delta'] == 0 for r in rows),
            '改善最大3場': rows[-3:][::-1], '悪化最大3場': rows[:3]}


def hedge_identity(hedge_ledger, net_ledger, hedge_result, net_result):
    """機能: 最終保険の売買価格と枚数だけで両建て対照の全場差額を独立分解する。

    引数: hedge_ledger/net_ledger/hedge_result/net_result(dict)。
    返り値: dictの銘柄別気配差費用・追加料金・照合。
    """
    result = {}
    for symbol in SYMBOLS:
        value, rate = (1000., 41.8) if symbol == 'TOPIX' else (10., 11.)
        spread_total = fee_total = residual_total = 0
        sessions = []
        for key, data in hedge_ledger.items():
            if key[1] != symbol:
                continue
            oo = data['orders']
            spread = fee = residual = 0
            for core in oo[(oo[:, 7] == 0) & (oo[:, 8] == 0)]:
                cover = oo[(oo[:, 0] == core[0]) & (oo[:, 2] == core[2])
                           & (oo[:, 7] == 0) & (oo[:, 8] == 1)]
                h = int(cover[:, 4].sum())
                spread += sum(int(x[4]) * abs(x[5] - core[5]) * value for x in cover)
                fee += math.floor(int(core[4]) * rate + 1e-8)
                fee += sum(math.floor(int(x[4]) * rate + 1e-8) for x in cover)
                fee -= math.floor((int(core[4]) - h) * rate + 1e-8)
                residual += h
            actual = float(net_ledger[key]['trades'][:, 10].sum() - data['trades'][:, 10].sum())
            assert abs(actual - spread - fee) < 1e-6, (key, actual, spread, fee)
            paired = net_ledger[key]['paired_metadata']['終了群の理論節約合計円']
            assert abs(actual - paired) < 1e-6
            spread_total += spread
            fee_total += fee
            residual_total += residual
            sessions.append({'session': key[0], '気配差費用': spread, '追加料金': fee,
                             '差額': actual, '終端残保険延べ枚数': residual, '合格': True})
        net_delta = net_result['periods']['全28'][symbol]['net'] - hedge_result['periods']['全28'][symbol]['net']
        assert abs(net_delta - spread_total - fee_total) < 1e-6
        result[symbol] = {'両建てより縮小復帰が有利な金額': net_delta, '終端気配差費用': spread_total,
                          '終端追加手数料': fee_total, '終端残保険延べ枚数': residual_total,
                          '全28場一致': True, '場別': sessions}
    return result


def management_summary(candidate, baseline):
    """機能: 全期間の損失削減と平均勝負額・利益維持率を区別して集計する。

    引数: candidate/baseline(dict)。返り値: dictの銘柄別管理効果。
    """
    result = {}
    for symbol in SYMBOLS:
        a, b = candidate['periods']['全28'][symbol], baseline['periods']['全28'][symbol]
        result[symbol] = {
            '基準収支': b['net'], '改修収支': a['net'], '収支差': a['net'] - b['net'],
            '負組損失_基準': b['campaign_loss'], '負組損失_改修': a['campaign_loss'],
            '負組損失削減率': 1 - a['campaign_loss'] / b['campaign_loss'],
            '勝組利益_基準': b['campaign_profit'], '勝組利益_改修': a['campaign_profit'],
            '勝組利益維持率': a['campaign_profit'] / b['campaign_profit'],
            '負組数_基準': b['campaign_losses'], '負組数_改修': a['campaign_losses'],
            '平均負組_基準': b['campaign_loss'] / b['campaign_losses'],
            '平均負組_改修': a['campaign_loss'] / a['campaign_losses'],
            '平均勝組_基準': b['campaign_profit'] / b['campaign_wins'],
            '平均勝組_改修': a['campaign_profit'] / a['campaign_wins'],
            '一組勝率_基準': b['campaign_win_rate'], '一組勝率_改修': a['campaign_win_rate'],
            '平均勝負比_基準': b['campaign_payoff'], '平均勝負比_改修': a['campaign_payoff'],
            '最大一組損失_基準': b['max_campaign_loss'], '最大一組損失_改修': a['max_campaign_loss'],
            '最大ドローダウン_基準': b['drawdown'], '最大ドローダウン_改修': a['drawdown'],
            '前16収支': candidate['periods']['前16'][symbol]['net'],
            '後12収支': candidate['periods']['後12'][symbol]['net'],
        }
    return result


def main():
    """機能: 選定を変えずに固定代表と家族別前半首位の効果・限界を保存する。

    引数: なし。
    返り値: None。analysis内の管理の効果と限界.jsonへ保存する。
    """
    results = {p.stem: load(p) for p in (ROOT / 'results').glob('*.json')}
    selection = load(ROOT / '前半選定.json')
    ids = ('T2L0_H03', 'T2L0_N03', 'T2L0_B00', 'T1L1_R01', 'T1L1_B00')
    ledgers = {i: load(ROOT / 'ledgers' / (i + '.pkl')) for i in ids}
    campaigns = {i: groups(l) for i, l in ledgers.items()}
    control = load(ROOT / 'controls/results/T2L0_D32.json')
    control_groups = groups(load(ROOT / 'controls/ledgers/T2L0_D32.pkl'))
    hedge = {
        'id': 'T2L0_H03', '選定': '前16の物理保険首位。両銘柄とも前半改善未達、採用条件未達。',
        '一組比較': {s: compare_campaigns(campaigns['T2L0_H03'], campaigns['T2L0_B00'], s) for s in SYMBOLS},
        '場比較': {s: compare_sessions(results['T2L0_H03'], results['T2L0_B00'], s) for s in SYMBOLS},
        '管理集計': management_summary(results['T2L0_H03'], results['T2L0_B00']),
        '期間': periods(results['T2L0_H03']),
        '元玉保険分類': {},
        '切り分け注意': 'B00 stop16に対しH03 stop32/全玉損失枠32。基準差には保険と許容幅変更が混在。別固定の追加原因診断D32と比較して保険有無を分ける。採用再選定には用いない。',
        '同許容幅の保険なし対照': {
            'id': 'T2L0_D32',
            '性質': '192結果を見た後に別固定した診断対照。損失枠・利益枠・期限はH03と同一、保険のみなし。未見の選定検証とは呼ばない。',
            '期間': periods(control),
            '管理集計': management_summary(results['T2L0_H03'], control),
            '場比較': {s: compare_sessions(results['T2L0_H03'], control, s) for s in SYMBOLS},
            '一組比較': {s: compare_campaigns(campaigns['T2L0_H03'], control_groups, s) for s in SYMBOLS},
            '損益差の分解': {},
        },
        '代表事例': [],
    }
    for symbol in SYMBOLS:
        rows = [a for k, a in campaigns['T2L0_H03'].items() if k[1] == symbol]
        classifications = {
            '元玉負け_保険勝ち': lambda a: a['core_net'] < 0 and a['cover_net'] > 0,
            '元玉勝ち_保険負け': lambda a: a['core_net'] > 0 and a['cover_net'] < 0,
            '両方負け': lambda a: a['core_net'] < 0 and a['cover_net'] < 0,
            '両方勝ち': lambda a: a['core_net'] > 0 and a['cover_net'] > 0,
            '保険なし': lambda a: a['cover_new_orders'] == 0,
        }
        summaries = {}
        for name, predicate in classifications.items():
            selected = [a for a in rows if predicate(a)]
            summaries[name] = {'組数': len(selected), '元玉収支': sum(a['core_net'] for a in selected),
                               '保険収支': sum(a['cover_net'] for a in selected),
                               '一組収支': sum(a['net'] for a in selected),
                               '一組勝ち': sum(a['net'] > 0 for a in selected)}
        summaries['反転利確注文'] = {
            '注文群数': sum(a['cover_profit_exit_batches'] for a in rows),
            '実約定後赤字注文群数': sum(a['cover_profit_exit_negative_batches'] for a in rows),
            '注文群収支合計': sum(a['cover_profit_exit_net'] for a in rows),
            '注意': '保険合計の利確注文群で判定。FIFOの一部玉赤字を注文群赤字と混同しない。判断時黒字でも次行約定で赤字になり得る。',
        }
        hedge['元玉保険分類'][symbol] = summaries
        h, d = results['T2L0_H03']['periods']['全28'][symbol], control['periods']['全28'][symbol]
        decomposition = {'元玉終了価格変化の差額': h['core_net'] - d['net'],
                         '保険の収支': h['cover_net'], '全玉収支差': h['net'] - d['net']}
        assert abs(decomposition['全玉収支差'] - decomposition['元玉終了価格変化の差額']
                   - decomposition['保険の収支']) < 1e-6
        hedge['同許容幅の保険なし対照']['損益差の分解'][symbol] = decomposition
    for kind, key in (
        ('保険だけ反転利確して改善', ('2026-09-29_Day', 'TOPIX', 4)),
        ('元玉回復時に保険が赤字のまま残り悪化', ('2026-10-08_Day', 'TOPIX', 4)),
    ):
        a, d, n = campaigns['T2L0_H03'][key], control_groups[key], campaigns['T2L0_N03'][key]
        source_orders = ledgers['T2L0_H03'][key[:2]]['orders']
        oo = source_orders[source_orders[:, 2] == key[2]]
        event_orders = [{'fill_i': int(x[0]), 'decision_i': int(x[1]),
                         '売買': '買い' if x[3] == 1 else '売り', '枚数': int(x[4]),
                         '価格': float(x[5]), '理由番号': int(x[6]),
                         '区分': '新規' if x[7] == 1 else '返済',
                         '役割': '元玉' if x[8] == 0 else '保険'} for x in oo]
        hedge['代表事例'].append({'説明': kind, **a, '同幅無保険収支': d['net'],
                                  '同判断縮小復帰収支': n['net'],
                                  '保険の有無による差': a['net'] - d['net'], '注文列': event_orders})
    hedge['機械的ルールから読める弱点'] = [
        '保険の合計含み益が4ティック相当になってから反転4ティックを追跡し、判断時に往復料金を超える利益が必要。保険が含み損のまま元方向へ戻る局面では保険返済を起動しない。',
        'そのため元玉が回復しても保険の損失が残り、全返済時に回復利益を相殺する。損失保険の単独停止や、元方向再開確認による保険削減は今回未検証。',
        '保険利確後は全枚数の元玉へ戻るので、少し反発した後に再逆行する局面で元玉の損失負担が再び増える。再展開冷却・新高安要件は今回未検証。',
        'この弱点は実装条件からの説明であり、未検証の補正を足せば黒字になるという結論ではない。',
    ]
    ratchet = {
        'id': 'T1L1_R01', '思想': '順行4ティックから4ティック刻みで利益線を引上げ、反落で全返済。keep0なので線が極値と同値になる観測もあり、次観測が同値でも返済条件になる。',
        '管理集計': management_summary(results['T1L1_R01'], results['T1L1_B00']),
        '一組比較': {s: compare_campaigns(campaigns['T1L1_R01'], campaigns['T1L1_B00'], s) for s in SYMBOLS},
        '場比較': {s: compare_sessions(results['T1L1_R01'], results['T1L1_B00'], s) for s in SYMBOLS},
        '期間': periods(results['T1L1_R01']),
        '結論': '負組の回数と損失合計は減るが、残った平均負組は大きく、平均勝組は小さい。平均勝負比1未満・両銘柄合計赤字のため損小利大達成ではない。',
    }
    family_winners = {}
    for family, name in (('F', '持ち替え'), ('P', '分割利確'), ('T', '時間短縮'), ('Q', '全玉保護')):
        winner = next(i for i in selection['その他管理順位'] if results[i]['config']['manager'].startswith(family))
        r = results[winner]
        b = results[r['config']['source'] + '_B00']
        family_winners[name] = {'id': winner, '選定': '同じ前16順位の当家族先頭。全28で選び直していない。',
                                'config': r['config'], '期間': periods(r),
                                '管理集計': management_summary(r, b)}
    family_winners['持ち替え']['結論'] = 'TOPIXは収支を161,996円改善するがNKは42,420円悪化。両方全期間赤字。1回の方向変更が全ての再反転に耐えるとは言えない。'
    family_winners['分割利確']['結論'] = '損失合計を約23%減らすが勝利益も減る。平均勝負比は両方約0.40で、安定した損小利大にはならない。'
    family_winners['時間短縮']['結論'] = '負組損失合計は両方0.3%未満しか減らない。TOPIXの勝利益が減り315,000円悪化、NKは60,000円改善。時間だけで弱化を決める効果は両銘柄共通ではない。'
    family_winners['全玉保護']['結論'] = '平均勝負比は1.11/1.03、最大一組損失もほぼ半減するが、勝率約40%では勝利益が負損失を上回らず両方赤字。損小利大の比率だけでも利益は保証されない。'
    output = {
        '選定変更': False, '新管理条件の追加': False,
        '一括最大数量': {'TOPIXmini': 10, 'NK225micro': 20},
        '全玉時価と手数料を含む': True,
        'H03': hedge,
        'H03対N03の終端差額': hedge_identity(ledgers['T2L0_H03'], ledgers['T2L0_N03'],
                                          results['T2L0_H03'], results['T2L0_N03']),
        'R01': ratchet,
        '他技術の前半首位': family_winners,
        '今回の限界': [
            '全192条件は全28で両銘柄黒字0。前半で選んだ代表も採用条件未達。',
            '保存28場は前研究で既知。未来参照防止と事前固定をしても完全未見の外部検証とは呼ばない。',
            'ラージ気配でミニ/マイクロを仮想約定。実商品気配・板深度・部分約定・通信取消の競合は未検証。',
            '入口は同一時刻の一括満額。初回少量の順行追加、時価リスクに応じた連続枚数変更は今回未検証。',
            '保険は合計玉の一括反転トレール。各段玉の独立IFD/OCOと個別利確、再展開冷却・新高安要件は今回未検証。',
            '持ち替えは1組1回、反対の同入口信号と保険数量割合のみ。他の構造/板補充の転換判定は未検証。',
            '利益線のkeep0は段階的に含み益を早く確定する性質で、常に幅を残して長期波を保持する条件とは異なる。',
            '未検証があることは利益が出る根拠ではない。今回通らない条件は通らないと報告する。',
        ],
    }
    (HERE / '管理の効果と限界.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    brief = {'H03対N03差額': {s: {k: v for k, v in a.items() if k != '場別'}
                            for s, a in output['H03対N03の終端差額'].items()},
             'R01管理集計': ratchet['管理集計'], '他前半首位ID': {k: v['id'] for k, v in family_winners.items()},
        'H03同許容幅との差': hedge['同許容幅の保険なし対照']['損益差の分解'],
        'H03同許容幅で効いた場': hedge['同許容幅の保険なし対照']['場比較'],
        'H03同許容幅で効いた組': hedge['同許容幅の保険なし対照']['一組比較']}
    print(json.dumps(brief, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
