"""旧候補後の9入口と4出口36条件の保存会計を集計する。"""

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
        f'旧候補後の9入口と4出口の36条件を全31既知場で比較。両商品で金額利益割合80%以上は{len(both80)}条件、活動基準を満たす両80%は{len(set(both80)&set(active))}条件でした。無取引は勝ちに数えていません。',
        f'損益前に固定した主 {fixed["主"]} は、TOPIX {main_values["TOPIX"]["net"]:+,.0f}円、日経 {main_values["NK225"]["net"]:+,.0f}円。金額利益割合は' + '・'.join(f'{main_values[s]["profit_share"]:.1%}' if main_values[s]['profit_share'] is not None else '取引なし' for s in catalog.SYMBOLS) + 'です。',
        f'前16で固定した参考 {selected["selected"]} は、全31でTOPIX {reference_values["TOPIX"]["net"]:+,.0f}円、日経 {reference_values["NK225"]["net"]:+,.0f}円。後15も既知期間の確認で、未知データでの成功ではありません。'
    ]
    notes = {
        '入口': '同じ旧J8候補から、即時・気配再進行・順行・追尾新規・押し回復を比較。押しは候補以後の局所有利極値から測り、旧即時建値より有利に入れる保証はありません。',
        '待機幅': '始値の0.1%を最低2呼値で切上げたWを入口専用尺度とし、出口の初期停止とは独立。半Wも呼値へ切上げます。',
        '支持再確認': '待機の発注時は密な旧J2同方向許可と現在正常な両市場を要求。A2以外の新待機は原行と公表相手の更新・両買売気配各1呼値の進行を要求。',
        '取消': '300秒期限、自己価格経路の断裂、両市場の既知5分方向が元方向と反対へ各3bp以上、場末で取消。片市場の弱化は待機を維持して発注だけ停止します。',
        '出口': '四出口は96の即時入口と同じ設計。X0初期0.4%30分、X1初期0.1%30分、X2初期0.2%と半利益保護30分、X3初期0.1%と費用床保護で通常期限なし。常時追尾は始値0.4%。',
        '約定': '新規成立又は返済判断後の次正常自己気配で買ask・売bidへ仮想約定。待機中の順行は利益に計上せず、建玉の利益床は実新規価格から再設定します。',
        '場内返済': '全36で場末60秒前から返済を判断、保存終端で全返済。通常期限なしでも場を跨ぎません。',
        '連鎖': '待機・保有・市場予約中の新候補は消費し後から復活しません。新規価格と時刻を変えると後続売買も変わるので、旧負けだけを除外した成績で代用しません。',
        '検証限界': '全31場は既知データの再探索。類似の新規追尾・二市場回復は既検証で、正確な再組合せを比較する調査です。前16選定・後15確認は未知成功ではなく、API取得・実注文は0。',
        '安定性': '最大合計収益より赤字頻度・平均最大赤字・下方偏差を重視。比較単位は全条件共通上限10/20枚と各場最初の正常価格の0.1%。活動減少と無取引も表示します。'
    }

    report = dict(全合格=True, 条件数=36, primary=fixed['主'], selected=selected['selected'], labels=catalog.labels(),
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
    print(json.dumps(dict(条件数=36, 両80=both80, 活動充足両80=report['活動充足の両80'],
                         主={s: summary(main_values[s]) for s in catalog.SYMBOLS},
                         参考={s: summary(reference_values[s]) for s in catalog.SYMBOLS},
                         診断上位=diagnostic[:8]), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
