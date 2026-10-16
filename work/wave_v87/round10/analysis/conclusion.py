"""全親組恒等分解から、第十段階の効果と限界を短くまとめる。"""
from pathlib import Path
import json

HERE=Path(__file__).resolve().parent


def main():
    """
    機能: 固定主案と固定対照の差を読み、後付け選定をせず要点を保存する。
    引数: なし。
    返り値: None。
    """
    path=HERE/'実両建て差引終了抑止の料金と価格露出の全分解.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    periods=data['全条件期間'];free=data['同じ実経路の手数料ゼロ感度']
    primary={}
    for symbol in ('TOPIX','NK225'):
        base=periods['GU_G']['全30'][symbol];main=periods['C_H05_S25_F']['全30'][symbol]
        gross=periods['C_H05_S25_G']['全30'][symbol];netted=periods['C_H05_S25_N']['全30'][symbol]
        primary[symbol]=dict(同じ実行待ちのGU収支=base['net'],主案収支=main['net'],GUとの差=main['net']-base['net'],
            GU最大下落=base['max_drawdown'],主案最大下落=main['max_drawdown'],
            GU黒字セッション=base['positive_sessions'],主案黒字セッション=main['positive_sessions'],
            GU最悪セッション=base['worst_session'],主案最悪セッション=main['worst_session'],
            同じ保険でGからNの料金節約=gross['fees']-netted['fees'],
            同じ保険でNからFの料金節約=netted['fees']-main['fees'],
            GからFの料金前差=main['gross']-gross['gross'],
            金額利益割合=main['cycle_profit_share'],同じ実経路で料金ゼロの金額利益割合=free['C_H05_S25_F']['全30'][symbol]['料金ゼロ金額利益割合'],
            前16収支=periods['C_H05_S25_F']['前16'][symbol]['net'],後14収支=periods['C_H05_S25_F']['後14'][symbol]['net'],
            後14の最大利益場除外=periods['C_H05_S25_F']['後14'][symbol]['best_session_removed'])
    maximum={symbol:max(free[identifier]['全30'][symbol]['料金ゼロ金額利益割合'] for identifier in free) for symbol in ('TOPIX','NK225')}
    out=dict(
        結論='両建てを差引へ置き換える実行改善は成立するが、利益8割を作る改善ではない。主案は従来のリスク低減候補を小額の料金削減で補強する位置付け。',
        固定主案='C_H05_S25_F。元GUを仮想で保持し、0.5ATR順行時の反対保険0.25ATR停止を加え、実保有だけ差引へ写し、仮想元玉終了後は実目標ゼロ。',
        主案=primary,
        GからN='全240口座の各原本行で現金・差引枚数・料金前全玉時価が一致。元玉を減らす実返済、保険を外す際の元玉復帰という売買が必要なため、両建てをやめても通常の往復料の大部分は消えない。今回の差は同一行相殺と注文単位の切捨てだけ。',
        NからF='保険だけを残す実保有を次観測からなくす。元の仮想終了行iで即時に消した計算ではなく、実行後j〜kの露出差を全親組の価格寄与として照合。主案ではその価格寄与差はゼロで、改善はTOPIX2508円/NK1100円の料金差だけだった。',
        万能ではない例='C_H05_S50のF化ではTOPIXの料金を3762円減らす一方、観測間の有利な露出を捨てて料金前2500円を失う。損失を必ず避ける機構とは言えない。',
        別条件='C_H05_S50_Fは同じ実行待ちのGUよりTOPIX収支が124052円増え、NKは22590円減る。I_P00_R50_C1_FはTOPIXが128270円減り、NKが46946円増える。双方共通の収支優位へ変わったわけではない。',
        待ちの交絡='GU_IDEALは旧GUと完全一致。GU_G/N/Fは互いに同じ注文・経済列・料金・全行時価で、旧GUに対するTOPIX17500円増/NK400円減は追加観測待ちによる価格差。差引方式の効果へ混ぜない。',
        料金ゼロ上限=maximum,
        上限の解釈='全13の中で商品ごとに最も高い料金ゼロ比率でも80%に届かない。同じ注文経路で料金だけをなくす上限であり、別の入口や無料時の新たな売買を再探索した値ではない。金額を二商品で合算せず、利益脚だけを独立勝負にも数えていない。',
        証明範囲='全30は既知。現金・枚数・親組・料金・全原本行時価の恒等式を検証した。小型商品の実板約定、受信時計、実通信時間に対する優位は証明していない。',
        今後='この結果で新しい停止幅や源戦略をこっそり追加していない。予測や保険そのものが負ける機構を直さず、実行の整理だけで利益8割へ到達するという仮説は、この固定13条件では否定される。')
    (HERE/'実行層の改善と料金ゼロ限界の短い結論.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(主案=primary,全13の無料割合上限=maximum),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
