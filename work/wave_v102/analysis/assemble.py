"""初回数量と固定予算増玉の20条件を、親と実建玉群の会計で集計する。"""

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
    result = {name: value[name] for name in names}
    result.update(cohort_profit=value['cohorts']['profit'],
                  cohort_loss=value['cohorts']['loss'],
                  cohort_profit_share=value['cohorts']['profit_share'])
    return result


def main() -> None:
    """
    機能: 全20条件の62口座を8期間へ集計し、選定時の指紋を保持する。
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
        and result['periods']['全31'][symbol]['profit_share'] >= .8
        and result['periods']['全31'][symbol]['cohorts']['profit_share'] is not None
        and result['periods']['全31'][symbol]['cohorts']['profit_share'] >= .8
        for symbol in catalog.SYMBOLS)]
    active = [ident for ident, result in results.items() if all(
        result['periods']['全31'][symbol]['campaigns'] >= 20
        and result['periods']['全31'][symbol]['active_sessions'] >= 8 for symbol in catalog.SYMBOLS)]
    positive = [ident for ident, result in results.items() if all(
        result['periods']['全31'][symbol]['all_sessions_profitable'] for symbol in catalog.SYMBOLS)]
    diagnostic = sorted(active, key=lambda ident: (
        -min(min(results[ident]['periods']['全31'][symbol]['profit_share'],
                 results[ident]['periods']['全31'][symbol]['cohorts']['profit_share'])
             for symbol in catalog.SYMBOLS), ident))
    stability_diagnostic = sorted(active, key=lambda ident: (
        max(results[ident]['stability']['全31'][symbol]['downside_rms_units'] for symbol in catalog.SYMBOLS),
        -min(results[ident]['stability']['全31'][symbol]['positive_session_rate'] for symbol in catalog.SYMBOLS),
        max(results[ident]['stability']['全31'][symbol]['worst_session_loss_units'] for symbol in catalog.SYMBOLS),
        -min(results[ident]['stability']['全31'][symbol]['active_net_q25_units'] for symbol in catalog.SYMBOLS),
        -min(min(results[ident]['periods']['全31'][symbol]['profit_share'],
                 results[ident]['periods']['全31'][symbol]['cohorts']['profit_share'])
             for symbol in catalog.SYMBOLS), ident))
    comparison_pairs = {config['id']: references(config) for config in fixed['条件']}
    main_values = results[fixed['主']]['periods']['全31']
    reference_values = results[selected['selected']]['periods']['全31']
    conclusion = [
        f'停止余裕と線据置の20条件を全31既知場で比較。親と実建玉群の両基準で両商品とも金額利益割合80%以上は{len(both80)}条件、活動基準を満たす両80%は{len(set(both80)&set(active))}条件でした。無取引は勝ちに数えていません。',
        f'損益前に固定した主 {fixed["主"]} は、TOPIX {main_values["TOPIX"]["net"]:+,.0f}円、日経 {main_values["NK225"]["net"]:+,.0f}円。金額利益割合は' + '・'.join(f'{main_values[s]["profit_share"]:.1%}' if main_values[s]['profit_share'] is not None else '取引なし' for s in catalog.SYMBOLS) + 'です。',
        f'前16で固定した参考 {selected["selected"]} は、全31でTOPIX {reference_values["TOPIX"]["net"]:+,.0f}円、日経 {reference_values["NK225"]["net"]:+,.0f}円。後15も既知期間の確認で、未知データでの成功ではありません。'
    ]
    notes = {
        "入口": "旧の両市場候補・現在L1支持・C1気配進行・元候補から1W価格制限を保持。新12は両商品とも初回絶対1枚。旧固定1枚・旧1/2呼値増玉と旧8/16枚固定を対照にします。",
        "途中": "B条件は実保有玉の順行利益が追加後の全量清算費用を支え、統合停止線まで初期Sの0.5/1/2倍の余裕がある時だけ倍増。最大はTOPIX8枚・日経16枚です。",
        "線政策": "T0は予算維持のため線を保護側へ更新可。T1は当該原行の通常更新後の旧線でplanned全量損失がR0内、かつactive費用床等を含む全統合planned線を寄せずに済む時だけ追加。初回や通常の追尾更新を変更しません。",
        "損失予算": "初回実約定の初期停止損失と往復費用をR0に固定。追加で予算を増やさず、実数量・加重建値・累計手数料から全玉停止線を計算します。成行なので実損失はR0を超え得ます。",
        "出口": "初回価格の初期停止と非緩和の追尾を保持。X1期限は初回約定から30分で追加による延長なし。X3は実保有玉の現在利益で費用床を起動し、一度起動したら追加で解除しません。全玉を場内で返します。",
        "約定": "追加も判断後の次正常自己気配で買ask・売bidへ仮想約定。悪い実約定を未来を見て取消したり、判断価格へ置換しません。返済が既に決まっていれば未約定追加を取消します。",
        "数量対照": "同じ初回1枚のG0と旧G1/G2を使い、停止余裕と線政策の効果を分離。損失額やRMSだけが小さくなっても方向予測の改善とは呼びません。活動黒字率、赤字平均最大、大勝ち除外収支も比較します。",
        "活動の反証": "T1は純数学の一方向例で初回追加に約7〜9S以上進む必要があり、強い通常追尾ではB三値が同時通過し得ます。活動縮小やG0との互換を安定収益成功としません。主はこの反証を受け新損益前にB1_T0へ変更し、T1は対照に残しました。",
        "会計": "親は全量返済単位、建玉群は各実新規の単位。全量返済料金は整数最大剰余法で配分し、同率は実約定作成順。親内相殺前の利益・損失を併記し、80%は両基準で判定します。",
        "場末": "新しい追加判断は保存運用区切り300秒前まで。既予約追加は60秒前又は初回期限・既存返済判断で取消。全実玉の返済を優先します。",
        "安定性": "共通上限TOPIX10枚・日経20枚と各場最初の正常価格0.1%を比較単位にします。小数量や無取引だけで安定した黒字としません。",
        "検証限界": "全31は既知データの再探索。前16の選択と後15の確認は未知性能ではありません。価格時計は真受信時計ではなく、実際の二市場受信順・ミニ/マイクロ固有の気配は未測定。API取得・実注文は0。"
    }
    report = dict(全合格=True, 条件数=20, primary=fixed['主'], selected=selected['selected'], labels=catalog.labels(),
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
    print(json.dumps(dict(条件数=20, 両80=both80, 活動充足両80=report['活動充足の両80'],
                         主={s: summary(main_values[s]) for s in catalog.SYMBOLS},
                         参考={s: summary(reference_values[s]) for s in catalog.SYMBOLS},
                         診断上位=diagnostic[:8]), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
