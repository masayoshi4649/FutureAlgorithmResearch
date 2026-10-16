"""数量改修の独立会計から、改善の成否と料金・損失予算の限界を短くまとめる。"""

from diagnose import ROOT, HERE, read, save


def main():
    """
    機能: 固定主仮説と少枚数対照について、収支差の根拠を簡潔な日本語で保存する。
    引数: なし。
    返り値: None。後から成績の良い条件を主仮説に置き換えない。
    """
    source = read(HERE / '全11数量条件の縮小追加と床の独立分解_会計修正版.json')
    observed = source['モデル別']['observed']
    methods = {x['条件']: x for x in observed['全11条件']}
    comparisons = observed['部品を揃えた比較']
    all_entries_equal = True
    for model in source['モデル別'].values():
        for method in model['全11条件']:
            for product in method['期間別']['全30'].values():
                match = product['親組対応']
                all_entries_equal &= match['元組数'] == match['新組数'] == match['同入口数']
    assert all_entries_equal
    main_info = {}
    for symbol in ('TOPIX', 'NK225'):
        main = methods['A_D05_R']['期間別']['全30'][symbol]
        difference = next(x for x in comparisons if x['元'] == 'A_S2' and x['新'] == 'A_D05_R'
                          and x['商品'] == symbol and x['期間'] == '全30')
        parts = difference['同初回入口の対応']['内訳']
        main_info[symbol] = dict(観測全30=main['集計'],
            前16=methods['A_D05_R']['期間別']['前16'][symbol]['集計'],
            後14=methods['A_D05_R']['期間別']['後14'][symbol]['集計'],
            同初回少枚数S2との差=difference['差'],
            S2黒字親組で失った利益=-parts['同入口の旧黒字']['差額寄与'],
            S2赤字親組の改善=parts['同入口の旧赤字']['差額寄与'],
            追加後の予算超過={k: main['順行追加と予算超過'][k] for k in
                ('追加が実約定した親組数', '床発動親組数', '設定床目標を下回った全返済親組数', '設定床目標からの超過合計')})
    rows = []
    for method in observed['全11条件']:
        for symbol, value in method['期間別']['全30'].items():
            a = value['集計']
            rows.append(dict(条件=method['条件'], 商品=symbol, 収支=a['net'],
                利益金額割合=a['campaign_profit_share'], 最大下落=a['max_drawdown'],
                収支対最大下落=a['net'] / a['max_drawdown'] if a['max_drawdown'] else None,
                黒字場=a['positive_sessions'], 赤字場=a['negative_sessions']))
    save('数量配分と追加後床の独立解釈.json', dict(主仮説='A_D05_R', 全初回入口一致=all_entries_equal,
        結論=[
            '主仮説の少数開始・0.5ATR段階追加・初回予算床は、TOPIXを赤字にし、日経も追加なしの同初回枚数を下回った。共通の改善とは認められない。',
            '全11条件の初回入口は同じ。取引回数の増減や入口の選び直しではなく、保有中の数量と退出の変化を比較できる。',
            '初回枚数だけを減らすS1/S2は金額利益割合をほぼ維持し、利益と損失をともに縮小した。整数の半減枠があるため完全な比例ではないが、方向の確度を高めた結果ではない。',
            'S2から新床なし一括追加J1_Nへ変えると、TOPIXは212,132円悪化し、日経は25,856円改善。日経でも最大下落が64,048円増え、共通の安定改善ではなかった。',
            '一括追加へ初回予算床だけを加えたJ1_Rは、減らした損失より削った利益が大きく、TOPIX264,008円・日経102,000円収支を減らした。',
            '主仮説の予算超過はTOPIX8組・合計14,395円、日経8組・合計4,893円。実際の床飛越は存在するが、これだけでは悪化全体を説明できない。',
            'ゼロ床のD05_Zは追加に達した親組の多くを黒字で返したが、追加に達しなかった初回建玉の損失も含めると、全体の金額利益割合はTOPIX55.5%、日経53.0%。追加成功後だけで評価しない。',
            '指定線モデルでは主仮説が両商品黒字だが、観測価格モデルではTOPIX赤字。指定線で必ず返済できる仮定を、実際の観測で確認した成績へ読み替えられない。'],
        主仮説の独立根拠=main_info, 全11一覧=rows,
        限界='全30場は既知。親組床は次観測からの価格条件で損失上限の保証ではなく、勝ちそうな将来経路を知って枚数を増やした検証ではない。'))


if __name__ == '__main__':
    main()
