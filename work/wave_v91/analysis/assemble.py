"""追加場で再選定せず、凍結した38条件の全31場を商品別に集約する。"""

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


def compact(value: dict) -> dict:
    """
    機能: 比較に必要な金額、活動、損益比と最大下落を取り出す。
    引数: value(dict、期間会計)。
    返り値: dict。別商品を円合計にせず比較できる要約。
    """
    fields = ('profit', 'loss', 'net', 'profit_share', 'campaigns',
              'winning_lots', 'losing_lots', 'positive_sessions', 'losing_sessions',
              'no_trade_sessions', 'active_sessions', 'payoff', 'equity_drawdown')
    return {field: value[field] for field in fields}


def yen(value: float) -> str:
    """
    機能: 確定円額を簡潔な説明用の符号付き文字列へ変換する。
    引数: value(float)。
    返り値: str。符号と桁区切りを付けた円表示。
    """
    return f'{value:+,.0f}円'


def main() -> None:
    """
    機能: 旧30と一度実行した追加1を合わせ、7期間と部品の差を保存する。
    引数: なし。
    返り値: None。注文は再実行せず、参考代表と理論主も差替えない。
    """
    fixed = research.read(WORK / '事前固定.json')
    research.validate(fixed)
    selection = research.read(WORK / '前16参考代表.json')
    assert selection['追加Day完結損益前選定']
    assert selection['固定SHA256'] == data.digest(WORK / '事前固定.json')
    for name, expected in selection['結果SHA256'].items():
        assert data.digest(research.ROOT / name) == expected, name
    periods = {name: fixed[name] for name in ('全31', '旧30', '前16', '後14', '追加1')}
    periods.update(デイ=[s for s in fixed['全31'] if s.endswith('_Day')],
                   ナイト=[s for s in fixed['全31'] if s.endswith('_Night')])
    results, fingerprints = {}, {}
    for config in fixed['条件']:
        ident = config['id']
        old_path = WORK / 'results' / f'{ident}.json'
        extra_path = WORK / 'extra/results' / f'{ident}.json'
        old, extra = research.read(old_path), research.read(extra_path)
        assert old['config'] == extra['config'] == config
        assert len(old['rows']) == 60 and len(extra['rows']) == 2
        rows = sorted(old['rows'] + extra['rows'], key=lambda row: (row['session'], row['symbol']))
        assert {(r['session'], r['symbol']) for r in rows} == {
            (s, symbol) for s in fixed['全31'] for symbol in catalog.SYMBOLS}
        calculated = {name: {symbol: accounting.aggregate(rows, symbol, sessions)
                            for symbol in catalog.SYMBOLS} for name, sessions in periods.items()}
        assert all(calculated[name] == value for name, value in old['periods'].items())
        assert calculated['追加1'] == extra['periods']['追加1']
        results[ident] = dict(config=config, rows=rows, periods=calculated)
        for path in (old_path, extra_path):
            fingerprints[str(path.relative_to(research.ROOT))] = data.digest(path)
    # ----------------------------------------
    # 無取引の高い見かけ割合と活動を満たす成績を別に残し、全場黒字とも分ける。
    both80 = [ident for ident, r in results.items() if all(
        r['periods']['全31'][s]['profit_share'] is not None
        and r['periods']['全31'][s]['profit_share'] >= .8 for s in catalog.SYMBOLS)]
    active = [ident for ident, r in results.items() if all(
        r['periods']['全31'][s]['campaigns'] >= 20
        and r['periods']['全31'][s]['active_sessions'] >= 8 for s in catalog.SYMBOLS)]
    all_positive = [ident for ident, r in results.items() if all(
        r['periods']['全31'][s]['all_sessions_profitable'] for s in catalog.SYMBOLS)]
    ranked = sorted(active, key=lambda ident: (
        -min(results[ident]['periods']['全31'][s]['profit_share'] for s in catalog.SYMBOLS),
        ident))
    comparisons = {}
    for name, target, base in [
        ('反発2枠の追加', 'M82', 'J8'),
        ('追従の反対10秒返済', 'J8_XC10', 'J8'),
        ('双方の反対10秒返済', 'M82_XC10', 'M82'),
        ('反発の小幅利益保護', 'O10_TR', 'O10'),
        ('追従の保有期限解除', 'J8_HUNL', 'J8'),
        ('統合の保有期限解除', 'P_G82_HUNL', 'P_G82'),
        ('統合で追従にも反対返済', 'P_G82', 'P_G82_XR')]:
        comparisons[name] = dict(target=target, base=base, 商品={})
        for symbol in catalog.SYMBOLS:
            real = results[target]['periods']['全31'][symbol]
            baseline = results[base]['periods']['全31'][symbol]
            comparisons[name]['商品'][symbol] = dict(
                基準=compact(baseline), 改修=compact(real),
                収支差円=real['net']-baseline['net'],
                利益差円=real['profit']-baseline['profit'],
                損失差円=real['loss']-baseline['loss'],
                最大下落差円=real['equity_drawdown']-baseline['equity_drawdown'])
    primary, selected = fixed['主'], selection['selected']
    p = results[primary]['periods']
    r = results[selected]['periods']
    conclusion = [
        f'38条件を全31場で比較。両商品の金額利益割合80%以上は{len(both80)}条件、両商品で全場黒字は{len(all_positive)}条件でした。無取引は勝ちに数えていません。',
        f'事前固定の統合主 {primary} は、手数料後でTOPIX {yen(p["全31"]["TOPIX"]["net"])}、NK225 {yen(p["全31"]["NK225"]["net"])}。保有期限解除はNK225の損失を増やし、採用できません。',
        f'追加日を見ずに旧前16で固定した参考 {selected} は、全31場でTOPIX {yen(r["全31"]["TOPIX"]["net"])}、NK225 {yen(r["全31"]["NK225"]["net"])}。利益割合はそれぞれ{r["全31"]["TOPIX"]["profit_share"]:.1%}・{r["全31"]["NK225"]["profit_share"]:.1%}で、目標に届きません。',
        f'追加10月12日Dayだけでは、統合主はTOPIX無取引、NK225 {yen(p["追加1"]["NK225"]["net"])}。参考はTOPIX {yen(r["追加1"]["TOPIX"]["net"])}、NK225 {yen(r["追加1"]["NK225"]["net"])}で、両商品に共通する成功ではありません。',
        '狭い追跡利確は既存の勝ちを削り、早く降りた後の新規取引にも損失を増やしました。異なる性質の戦略でも、追加した戦略の損失が大きければ配分だけでは安定しません。',
        '旧30場は既知データの再探索で、追加1場だけが条件と参考を固定した後の確認です。次は、往復を準備した理由が崩れた証拠と、利益を残す再参加条件を分けて検証します。'
    ]
    notes = {
        '配分': '追従8枠・反発2枠（NK225は16・4枚）。貸出しはせず、親ごとの損益・料金・含み損を保持しました。反発は追従と逆の性質ですが、利益を生む理由が確認できることが配分の前提です。',
        '短い準備': '低い方向効率の判定だけで準備を毎回やり直すと、中央値8〜11秒で基準が更新され、指値まで価格が届きませんでした。今回は準備を保持する条件と、共同方向が出た時の解除を分けました。',
        '狭い利確': '旧30場の反発単独では、同一新規のTOPIX勝ち27親の利益を184万円削り、負け16親の救済は125.5万円でした。早期返済後の新固有450親も249.62万円の赤字。救済だけを見れば改善を誤認します。',
        '期限解除': '統合主のNK225では、旧30場の同一新規215親で30.08万円悪化。勝ちから負けへの変化13親と、元から負けた親の損拡大が原因です。反対を示す条件が揃うまで、誤った建玉を抱える場面が残りました。',
        '反対返済': 'ERが高いという入口条件を出口にも要求すると、反対方向へ動いても返済しません。出口ではERを外しましたが、共同300秒方向と短期30秒が揃わない反転はなお拾えず、逆に反対返済が元の勝ちを削ることもあります。',
        '約定': '判断後の次の有効ラージ気配で買ask・売bid。指値は有利な価格改善を含めます。追加5秒遅延なし。小商品の実板、注文待ち順位、通信受信時刻は未検証です。全場で未返済残高をゼロにしています。'
    }
    report = dict(全合格=True, 条件数=38, primary=primary, selected=selected,
                  catalog=fixed['条件'], sessions=fixed['全31'], results=results,
                  selection_proof=selection, both80=both80,
                  活動充足の両80=[ident for ident in both80 if ident in active],
                  両商品で全場黒字=all_positive,
                  後から全31の悪い側利益割合で並べた診断順=ranked,
                  比較=comparisons, conclusion=conclusion, cause_notes=notes,
                  正式結果SHA256=fingerprints, 現在API取得=0, 実注文=0)
    research.save(HERE / '比較結果.json', report)
    research.save(HERE / '判定と部品比較.json', {k: v for k, v in report.items()
                  if k not in ('results', 'catalog', '正式結果SHA256')})
    print(json.dumps(dict(条件数=38, 両80=both80, 両全場黒字=all_positive,
                         主={s: compact(p['全31'][s]) for s in catalog.SYMBOLS},
                         参考={s: compact(r['全31'][s]) for s in catalog.SYMBOLS},
                         診断上位=ranked[:8], 比較=comparisons), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
