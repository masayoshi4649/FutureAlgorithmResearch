"""四判断価格上限・二支持源・二入口・二出口及び即時対照の34条件を集計する。"""

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
    機能: 全34条件の62口座を8期間へ集計し、選定時の指紋を保持する。
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
        f'四判断価格上限・二支持源・二入口・二出口と即時対照の34条件を全31既知場で比較。両商品で金額利益割合80%以上は{len(both80)}条件、活動基準を満たす両80%は{len(set(both80)&set(active))}条件でした。無取引は勝ちに数えていません。',
        f'損益前に固定した主 {fixed["主"]} は、TOPIX {main_values["TOPIX"]["net"]:+,.0f}円、日経 {main_values["NK225"]["net"]:+,.0f}円。金額利益割合は' + '・'.join(f'{main_values[s]["profit_share"]:.1%}' if main_values[s]['profit_share'] is not None else '取引なし' for s in catalog.SYMBOLS) + 'です。',
        f'前16で固定した参考 {selected["selected"]} は、全31でTOPIX {reference_values["TOPIX"]["net"]:+,.0f}円、日経 {reference_values["NK225"]["net"]:+,.0f}円。後15も既知期間の確認で、未知データでの成功ではありません。'
    ]
    notes = {
        '入口': '同じ旧J8候補と入口幅を保持し、両気配進行のみと1W押し後の半W回復を比較。旧条件が成立した時だけ、元候補から不利方向への価格差を上限なし・半W・1W・2Wで制限します。買いはask、売りはbidを使います。',
        '待機幅': '始値の0.1%を最低2呼値で切上げたWを入口専用尺度とし、出口の初期停止とは独立。半Wも呼値へ切上げます。',
        '支持再確認': 'L0は旧の300秒気配中値、L1は既存の独立300秒取引価格による同方向許可。正常な両市場と両買売気配各1呼値の進行も別に要求。待機32条件の時計は同じC1に固定し、元候補と旧の硬い反対取消は変更しません。',
        '取消': '待機は元候補から300秒。自己reset、気配不正、硬い二市場反対、場末の旧取消が価格上限より先。上限外の行は予約せず、同じ元候補・方向・幅・期限を保持して次行を確認します。期限を延長しません。',
        '価格上限': '方向付きの差 side×(判断quote−元候補quote) をK×W以下に制限。数学的上限を呼値へ不利に切り上げません。上限外でも局所押し回復の幾何は旧通り更新し、同じ候補で上限内へ戻れば旧条件を再確認できます。',
        '出口': '二出口とも初期停止は始値0.1%、常時追尾は0.4%。X1は通常30分で返済判断。X3は2S順行後に手数料込み建値床を加え、通常の保有期限なし。実新規から状態を開始し、両方ともセッション内で返済します。',
        '約定': '成立後の次正常自己気配で買ask・売bidへ仮想約定。今回の上限は発注判断価格の制限なので、その後の実約定価格は上限を超え得ます。超過を別に記録し、未来の実約定を見て判断を取消しません。待機中の順行は利益に計上せず、利益床は実新規価格から開始します。',
        '場内返済': '全34で保存上の運用区切り60秒前から返済を判断、保存終端で全返済。通常期限なしでも場を跨ぎません。実取引所終了時刻と運用区切りを混同しません。',
        '連鎖': '待機・保有・市場予約中の新候補は消費し後から復活しません。新規価格と時刻を変えると後続売買も変わるので、旧負けだけを除外した成績で代用しません。',
        '検証限界': '全31は既知データの再探索。価格時計は真受信時計ではなく、二市場の実際の受信順は保存データから証明できません。公表代理時刻の再生仮定内の因果検査と実際の配信順保証を分けます。前16選定・後15確認は未知性能ではなく、API取得・実注文は0。',
        '安定性': '最大合計収益より赤字頻度・平均最大赤字・下方偏差を重視。比較単位は全条件共通上限10/20枚と各場最初の正常価格の0.1%。活動減少と無取引も表示します。'
    }

    report = dict(全合格=True, 条件数=34, primary=fixed['主'], selected=selected['selected'], labels=catalog.labels(),
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
    print(json.dumps(dict(条件数=34, 両80=both80, 活動充足両80=report['活動充足の両80'],
                         主={s: summary(main_values[s]) for s in catalog.SYMBOLS},
                         参考={s: summary(reference_values[s]) for s in catalog.SYMBOLS},
                         診断上位=diagnostic[:8]), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
