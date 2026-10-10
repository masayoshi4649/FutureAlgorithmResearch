"""既に固定したティック条件の結果だけから、赤字の会計構造を独立整理する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
REASONS = {'1': '当初逆指値', '2': 'トレーリング返済', '3': '保有期限',
           '4': '場内返済', '10': '新規逆指値', '11': '新規トレール'}


def read(path: Path) -> dict:
    """機能: 元の結果JSONを読み取り専用で読む。

    引数: path(Path)。返り値: 結果(dict)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def period_account(packet: dict, period: str, symbol: str, sessions: list[str]) -> dict:
    """機能: 結果会計と理由回数を再集計し、気配差と料金を分ける。

    引数: packet(dict)、period/symbol(str)、sessions(list[str])。
    返り値: 損失構造(dict)。注文固定の中値置換を実行可能な利益とは解釈しない。
    """
    rows = [r for r in packet['rows'] if r['symbol'] == symbol and r['session'] in sessions]
    base = packet['periods'][period][symbol]
    for field in ('profit', 'loss', 'net', 'gross', 'fees', 'wins', 'losses', 'trades', 'ideal_net'):
        assert abs(sum(r[field] for r in rows) - base[field]) < 1e-6
    assert abs(base['profit'] - base['loss'] - base['net']) < 1e-6
    assert abs(base['gross'] - base['fees'] - base['net']) < 1e-6
    reasons = {REASONS[k]: sum(r['reasons'][k] for r in rows) for k in REASONS}
    assert sum(reasons[k] for k in ('当初逆指値', 'トレーリング返済', '保有期限', '場内返済')) == base['trades']
    tick_value = 2500. if symbol == 'TOPIX' else 1000.
    count = base['trades']
    winning = base['wins']
    losing = base['losses']
    average_win = base['profit'] / winning if winning else None
    average_loss = base['loss'] / losing if losing else None
    required_win_rate = average_loss / (average_loss + average_win) if average_loss and average_win else None
    spread_difference = base['ideal_net'] - base['net']
    return dict(利益=base['profit'], 損失=base['loss'], 収支=base['net'], 手数料前収支=base['gross'],
        手数料=base['fees'], 中値へ価格だけ置換した収支=base['ideal_net'],
        気配差相当の価格差=spread_difference, 取引数=count, 勝ち数=winning, 負け数=losing,
        勝率=base['win_rate'], 平均勝ち=average_win, 平均負け=average_loss,
        平均勝負比=base['payoff'], この平均勝負比で必要な勝率=required_win_rate,
        一取引平均収支呼値=base['mean_net_ticks'],
        一取引平均気配差相当呼値=spread_difference / (count * tick_value) if count else None,
        一取引平均手数料呼値=base['fees'] / (count * tick_value) if count else None,
        一取引平均勝ち呼値=average_win / tick_value if average_win is not None else None,
        一取引平均負け呼値=average_loss / tick_value if average_loss is not None else None,
        返済理由回数=reasons, 活動場=base['active_sessions'], 黒字場=base['positive_sessions'],
        場数=base['sessions'], 活動場一場平均取引数=count / base['active_sessions'] if base['active_sessions'] else None,
        最大一取引損失=base['max_trade_loss'], 最大資産下落=base['drawdown'],
        最大黒字場除外後収支=base['without_best_session'],
        親予約=sum(r['parent_submitted'] for r in rows),
        親成立=sum(r['parent_triggered'] for r in rows),
        親取消=sum(r['parent_canceled'] for r in rows))


def main() -> None:
    """機能: 全192条件と固定選定4条件・少数黒字例を整理して新規JSONへ保存する。

    引数: なし。返り値: なし(None)。入口、出口、選定を変更せず結果だけを分析する。
    """
    fixed = read(WORK / '事前固定.json')
    selection = read(WORK / '機構別の前半選定.json')
    packets = [read(path) for path in sorted((WORK / 'results').glob('*.json'))]
    assert len(packets) == 192
    ids = [s['id'] for s in selection['選定']] + ['T3L1_E0_O16A8W8_H60']
    lookup = {p['config']['id']: p for p in packets}
    counts = {}
    for period in ('前16', '後12', '全28'):
        stats = {symbol: dict(気配約定で黒字=sum(p['periods'][period][symbol]['net'] > 0 for p in packets),
            中値置換で黒字=sum(p['periods'][period][symbol]['ideal_net'] > 0 for p in packets),
            手数料前でも赤字=sum(p['periods'][period][symbol]['gross'] < 0 for p in packets))
            for symbol in ('TOPIX', 'NK225')}
        stats['両銘柄'] = dict(気配約定で黒字=sum(all(p['periods'][period][s]['net'] > 0 for s in ('TOPIX', 'NK225')) for p in packets),
            中値置換で黒字=sum(all(p['periods'][period][s]['ideal_net'] > 0 for s in ('TOPIX', 'NK225')) for p in packets))
        counts[period] = stats
    details = {}
    for identifier in ids:
        packet = lookup[identifier]
        periods = {period: {symbol: period_account(packet, period, symbol, sessions)
            for symbol in ('TOPIX', 'NK225')} for period, sessions in
            (('前16', fixed['前16']), ('後12', fixed['後12']), ('全28', fixed['全セッション']))}
        family = packet['config']['family']
        if identifier == 'T3L1_E0_O16A8W8_H60':
            explanation = '強い表示補充後の反転は全28では唯一の両銘柄黒字だが、前16は両方赤字。全28の平均勝ち/平均負けは両方1未満で、最大黒字場を外すと両方赤字。少数例の事後発見で採用根拠には不足。'
        elif family == 1:
            explanation = '2/4呼値の戻り確認は、その後も戻りが続く保証にならなかった。勝率は約半分でも、平均勝ちが平均負けの約0.55～0.60倍。中値置換でも全28は両方赤字で、気配差だけでは説明できない。'
        elif family == 2:
            explanation = '押し戻し後に再開した局所運動は、気配差と往復料金を越える伸びが不足。約55%勝っても、平均勝ちが平均負けの約0.42～0.44倍。1場に多数回繰り返し、1回の小さい負期待値が蓄積。'
        elif family == 3:
            explanation = '標準の表示補充後の反転を新規トレールで待つ条件は、保有5分の期限返済がTOPIX973/1060、日経571/650を占める。勝率約37%で平均勝負比も1未満。TOPIXは中値置換なら黒字だが、気配差がその小さい優位を超える。保有30/60分へ延長した既存対照も両方赤字なので、短い期限だけが原因とはいえない。'
        else:
            explanation = '補充価格を突破してOFIも一致しても、大きな一方向の持続を十分には選別していない。勝率は約半分でも、平均勝ちが平均負けの約0.61～0.63倍。中値置換でも全28は両方赤字。'
        details[identifier] = dict(設定=packet['config'], 所見=explanation, 期間別=periods)
    record = dict(参照='固定192条件のresults/*.jsonと選定証跡のみ。新規条件追加、入口改変、選び直しなし。',
        条件数=192, 黒字条件数=counts, 代表条件=details,
        補充標準の期限だけを替えた既存対照={str(h):lookup[f'T3L0_E1_O16A8W8_H{h}']['periods']['全28'] for h in (5,30,60)},
        共通所見=[
            '全28で選定4条件の平均勝負比はTOPIX約0.44～0.90、日経約0.42～0.90。勝率だけを見れば50%以上の条件もあるが、勝ち1回より負け1回が大きい。',
            '代表4条件では気配差相当が1取引平均約1.38～1.55呼値、手数料が0.1672呼値(TOPIX5枚)または0.22呼値(日経10枚)。極短い中値運動を売買する場合、この負担を越える持続が必要。',
            '中値置換は同じ注文の価格感度であり、子条件や次の入口を再計算した無コストバックテストではない。',
            '当初逆指値が出たという理由だけで、入口から一度も順行しなかったとは断定できない。初期MFE、追跡開始到達、ギャップ等をJSONは保持していない。',
            '補充とOFIは表示量変化の観測であり、真の成行、取消、個別注文、買い手の消耗を識別していない。市場原理そのものの否定ではなく、今回の代理特徴と注文幅の組合せが不足している。'],
        原資料SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (WORK / '機構別の前半選定.json', WORK / '事前固定.json')})
    (HERE / '損失構造.json').write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(条件数=192,黒字条件数=counts,
        代表全28={i:{s:{k:v for k,v in d['期間別']['全28'][s].items() if k in
            ('収支','中値へ価格だけ置換した収支','取引数','勝率','平均勝負比','この平均勝負比で必要な勝率','返済理由回数',
             '一取引平均気配差相当呼値','最大黒字場除外後収支')} for s in ('TOPIX','NK225')}
            for i,d in details.items()}), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
