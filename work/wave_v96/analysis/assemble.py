"""旧入口固定の初期停止・利益床・保有期限18条件の保存会計を集計する。"""

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
    return catalog.references(config['id'])


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
    機能: 全18条件の62口座を8期間へ集計し、選定時の指紋を保持する。
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
    material = data.load_inputs(verify=False)
    records = {key: dict(record=value) for key, value in material['prices'].items()}
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
        stable = {period: research.stability(rows, config, records, sessions)
                  for period, sessions in periods.items()}
        assert stable['前16'] == front['stability'] and stable['後15'] == back['stability']
        results[ident] = dict(config=config, rows=rows, periods=sums, stability=stable)
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
    stability_diagnostic = sorted(active, key=lambda ident: (
        max(results[ident]['stability']['全31'][symbol]['downside_rms_units'] for symbol in catalog.SYMBOLS),
        -min(results[ident]['stability']['全31'][symbol]['positive_session_rate'] for symbol in catalog.SYMBOLS),
        max(results[ident]['stability']['全31'][symbol]['worst_session_loss_units'] for symbol in catalog.SYMBOLS),
        -min(results[ident]['stability']['全31'][symbol]['active_net_q25_units'] for symbol in catalog.SYMBOLS),
        -min(results[ident]['periods']['全31'][symbol]['profit_share'] for symbol in catalog.SYMBOLS), ident))
    comparison_pairs = {config['id']: references(config) for config in fixed['条件']}
    main_values = results[fixed['主']]['periods']['全31']
    reference_values = results[selected['selected']]['periods']['全31']
    conclusion = [
        f'初期停止3幅・順行後利益床3種類・通常期限2種類の18条件（経済的に14組）を全31既知場で比較。両商品で金額利益割合80%以上は{len(both80)}条件、活動基準を満たす両80%は{len(set(both80)&set(active))}条件でした。無取引は勝ちに数えていません。',
        f'損益前に固定した主 {fixed["主"]} は、TOPIX {main_values["TOPIX"]["net"]:+,.0f}円、日経 {main_values["NK225"]["net"]:+,.0f}円。金額利益割合は' + '・'.join(f'{main_values[s]["profit_share"]:.1%}' if main_values[s]['profit_share'] is not None else '取引なし' for s in catalog.SYMBOLS) + 'です。',
        f'前16で固定した参考 {selected["selected"]} は、全31でTOPIX {reference_values["TOPIX"]["net"]:+,.0f}円、日経 {reference_values["NK225"]["net"]:+,.0f}円。後15も既知期間の確認で、未知データでの成功ではありません。'
    ]
    notes = {'入口': '全18で旧J8の候補・旧J2許可・発火消費を固定。入口を結果に合わせて変えません。', '初期停止': '始値の0.1/0.2/0.4%を呼値化した幅を実建値から置きます。通常の追尾幅は始値0.4%のままです。', '利益保護': '実建値から返済側気配の最大順行が初期幅の2倍になった後、費用込み建値保護又は最大順行の半分の利益保護を追加。以前の停止線より不利へ動かしません。', '約定': '停止価格は保証ではありません。判断後の次正常気配で買ask・売bidに約定する代理を使い、呼値差と手数料を含みます。', '期限': '通常30分と通常期限なしを比較。期限なしでも旧運用の場末60秒前から返済判断し保存終端で全返済します。場を跨ぎません。', '重複対照': '初期0.4%では2幅順行した時点で既存追尾が追加利益床以上になるため、3保護モードの経済結果は期限ごと同じになる対照です。18表示条件のうち独立経済条件は14組です。', '連鎖': '早期返済は後続候補の保有・再参加状態も変えます。旧負けだけ除外した成績を、新手法の損益に代用しません。', '検証限界': '全31場は既に見たデータの再探索です。前16選定・後15確認も未知データでの成功とは呼びません。現在API取得と実注文は0です。', '安定性': '最大合計収益より、赤字頻度・平均赤字・最大赤字・下方偏差を重視。比較単位は全条件共通上限10/20枚と各場最初の正常価格の0.1%。無取引を勝ちに含めません。'}

    report = dict(全合格=True, 条件数=18, primary=fixed['主'], selected=selected['selected'], labels=catalog.labels(),
                  全31既知=True, 新未見確認場数=0, catalog=fixed['条件'], sessions=fixed['全31'],
                  results=results, selection_proof=selected, both80=both80,
                  活動充足の両80=[ident for ident in both80 if ident in active], 両商品で全場黒字=positive,
                  後から悪い側利益割合で並べた診断順=diagnostic, comparison_pairs=comparison_pairs,
                  安定性の事後診断順=stability_diagnostic,
                  安定性の事後診断注記='全31を見た診断順。前16参考を差し替えず、黒字・損小利大・利益80%の達成も別に判定。',
                  conclusion=conclusion, cause_notes=notes, 正式結果SHA256=fingerprints,
                  セッション安定性の事前評価=research.read(WORK / 'セッション安定性の事前評価.json'),
                  API取得=0, 実注文=0)
    research.save(HERE / '比較結果.json', report)
    print(json.dumps(dict(条件数=18, 両80=both80, 活動充足両80=report['活動充足の両80'],
                         主={s: summary(main_values[s]) for s in catalog.SYMBOLS},
                         参考={s: summary(reference_values[s]) for s in catalog.SYMBOLS},
                         診断上位=diagnostic[:8]), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
