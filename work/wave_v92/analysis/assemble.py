"""前16と後15を全31既知場へ接続し、回復・停止・再参加の差を分ける。"""

import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
sys.path.insert(0, str(WORK))

import accounting
import catalog
import data
import research


def references(config: dict) -> list[str]:
    """
    機能: 変えた部品に対応する同じ執行又は同じ枚数の対照を選ぶ。
    引数: config(dict)。
    返り値: list[str]。複数変更の参考差は一軸の効果と分ける。
    """
    ident = config['id']
    if ident.startswith('I_'):
        return ['R_B25_C_TR', 'R_B25_C']
    if ident.startswith('M_R'):
        return ['J8', 'J10', 'M82']
    if ident == 'M_KS25':
        return ['J8', 'J10', 'M82']
    if ident.endswith('_ESTOP'):
        return [ident.removesuffix('_ESTOP'), 'R0_C']
    if ident == 'R_B25_C_TR':
        return ['R_B25_C']
    if ident == 'R_B25_C_W15':
        return ['R_B25_C']
    if ident.startswith('R_'):
        return ['R0_C', ident.removesuffix('_C')] if ident.endswith('_C') else ['R0']
    if ident in ('R0', 'R0_C'):
        return ['A_O'] if ident == 'R0' else ['R0']
    if ident == 'KS25_W15':
        return ['O10_F15_TR', 'KS25']
    if ident.endswith('_REL') or ident.endswith('_ALL'):
        return [ident.removesuffix('_REL').removesuffix('_ALL')]
    if ident.startswith('K'):
        return ['O10_F10_TR'] if ident == 'K0' else ['K0', 'O10_F10_TR']
    if ident == 'M82':
        return ['J8', 'J10']
    if ident == 'O10_TR':
        return ['O10']
    return []


def summary(value: dict) -> dict:
    """
    機能: 結果の比較に必要な金額・活動と下落を簡潔に取り出す。
    引数: value(dict、期間会計)。
    返り値: dict。商品別の短い要約。
    """
    names = ('profit', 'loss', 'net', 'profit_share', 'campaigns', 'active_sessions',
             'positive_sessions', 'losing_sessions', 'no_trade_sessions', 'payoff', 'equity_drawdown')
    return {name: value[name] for name in names}


def main() -> None:
    """
    機能: 全36条件の62口座を8期間へ集計し、選定時の指紋を保持する。
    引数: なし。
    返り値: None。新規の売買、選定の差替え、未知データの主張はしない。
    """
    fixed = research.read(WORK / '事前固定.json')
    research.validate(fixed)
    selected = research.read(WORK / '前16参考代表.json')
    assert selected['後15正式損益前選定'] and selected['全31既知']
    assert selected['固定SHA256'] == data.digest(WORK / '事前固定.json')
    for path, expected in selected['結果SHA256'].items():
        assert data.digest(research.ROOT / path) == expected
    periods = {name: fixed[name] for name in ('全31', '前16', '後15', '旧30', '後14', '追加1')}
    periods.update(デイ=[key for key in fixed['全31'] if key.endswith('_Day')],
                   ナイト=[key for key in fixed['全31'] if key.endswith('_Night')])
    results, fingerprints = {}, {}
    for config in fixed['条件']:
        ident = config['id']
        paths = [WORK / part / 'results' / (ident + '.json') for part in ('front', 'back')]
        front, back = [research.read(path) for path in paths]
        assert front['config'] == back['config'] == config
        rows = sorted(front['rows'] + back['rows'], key=lambda row: (row['session'], row['symbol']))
        assert len(rows) == 62
        assert {(row['session'], row['symbol']) for row in rows} == {
            (key, symbol) for key in fixed['全31'] for symbol in catalog.SYMBOLS}
        sums = {period: {symbol: accounting.aggregate(rows, symbol, sessions) for symbol in catalog.SYMBOLS}
                for period, sessions in periods.items()}
        assert sums['前16'] == front['periods']['前16'] and sums['後15'] == back['periods']['後15']
        results[ident] = dict(config=config, rows=rows, periods=sums)
        fingerprints.update({str(path.relative_to(research.ROOT)): data.digest(path) for path in paths})
    both80 = [ident for ident, result in results.items() if all(
        result['periods']['全31'][symbol]['profit_share'] is not None
        and result['periods']['全31'][symbol]['profit_share'] >= .8 for symbol in catalog.SYMBOLS)]
    active = [ident for ident, result in results.items() if all(
        result['periods']['全31'][symbol]['campaigns'] >= 20
        and result['periods']['全31'][symbol]['active_sessions'] >= 8 for symbol in catalog.SYMBOLS)]
    positive = [ident for ident, result in results.items() if all(
        result['periods']['全31'][symbol]['all_sessions_profitable'] for symbol in catalog.SYMBOLS)]
    diagnostic = sorted(active, key=lambda ident: (
        -min(results[ident]['periods']['全31'][symbol]['profit_share'] for symbol in catalog.SYMBOLS), ident))
    comparison_pairs = {config['id']: references(config) for config in fixed['条件']}
    main_values = results[fixed['主']]['periods']['全31']
    reference_values = results[selected['selected']]['periods']['全31']
    conclusion = [
        f'回復確認・極値停止・中心再参加の36条件を全31場で比較。両商品で金額利益割合80%以上は{len(both80)}条件、活動基準を満たす両80%は{len(set(both80)&set(active))}条件でした。無取引は勝ちに数えていません。',
        f'損益前に固定した主 {fixed["主"]} は、TOPIX {main_values["TOPIX"]["net"]:+,.0f}円、日経 {main_values["NK225"]["net"]:+,.0f}円。金額利益割合は' + '・'.join(f'{main_values[s]["profit_share"]:.1%}' if main_values[s]['profit_share'] is not None else '取引なし' for s in catalog.SYMBOLS) + 'です。',
        f'前16で固定した参考 {selected["selected"]} は、全31でTOPIX {reference_values["TOPIX"]["net"]:+,.0f}円、日経 {reference_values["NK225"]["net"]:+,.0f}円。後15も既知期間の確認で、未知データでの成功ではありません。'
    ]
    notes = {
        '回復': '下がっただけで買わず、準備から観測した中値の安値を離れて戻った時に買います。双方版は相手にも各自の幅の回復を要求。買う価格が高くなる不利益も、同じ成行の確認なし対照と比較します。',
        '停止': '極値停止版だけ、判断時までの観測安値の1呼値下を買いの失敗線に固定します。売りは対称。予定価格での約定は保証せず、線を越えた後の次有効気配で返済します。',
        '再参加': '黒字全返済後、旧中心を保持するだけの版と、中心帯へ帰還してから新たに離れるまで入らない版を分けました。RETURNは返済後の帰還と、その次の行以降の逸脱を要求します。',
        '配分': '8：2と16：4の枠を同時運転し、源ごとの実際の料金と全玉を評価します。MのJ8差は同じ追従枚数へ反発を足した差、J10差は同上限での置換、M82差は複数変更の参考差です。',
        '評価': '少数取引の80%や無取引を安定成功へ置き換えません。逃した利益と、新しい再参加で生まれた損失も含めて比較します。全31は既知、現在API取得・実注文は0回です。'
    }
    report = dict(全合格=True, 条件数=36, primary=fixed['主'], selected=selected['selected'],
                  全31既知=True, 新未見確認場数=0, catalog=fixed['条件'], sessions=fixed['全31'],
                  results=results, selection_proof=selected, both80=both80,
                  活動充足の両80=[ident for ident in both80 if ident in active], 両商品で全場黒字=positive,
                  後から悪い側利益割合で並べた診断順=diagnostic, comparison_pairs=comparison_pairs,
                  conclusion=conclusion, cause_notes=notes, 正式結果SHA256=fingerprints,
                  API取得=0, 実注文=0)
    research.save(HERE / '比較結果.json', report)
    print(json.dumps(dict(条件数=36, 両80=both80, 活動充足両80=report['活動充足の両80'],
                         主={s: summary(main_values[s]) for s in catalog.SYMBOLS},
                         参考={s: summary(reference_values[s]) for s in catalog.SYMBOLS},
                         診断上位=diagnostic[:8]), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
