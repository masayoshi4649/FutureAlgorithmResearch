"""固定幅の診断結果から、反転の仕組みと費用の影響を短文へまとめる。"""
from pathlib import Path
import json


HERE = Path(__file__).resolve().parent


def yen(value):
    """
    機能: 円額を符号付きで表示する。
    引数: value (float)。
    返り値: str の日本語表示。
    """
    return f'{value:+,.0f}円'


def main():
    """
    機能: 既存診断を根拠に短い因果解釈を追加し、再探索せず保存する。
    引数: なし。
    返り値: None。売買・代表選定・損益計算は変更しない。
    """
    data = json.loads((HERE / '同幅6手法の損失構造.json').read_text(encoding='utf-8'))
    models = {model: {r['config']['family']: r for r in methods} for model, methods in data['models'].items()}
    source = json.loads((HERE / '診断の短い要旨.json').read_text(encoding='utf-8'))
    reasons = []
    for symbol in ('TOPIX', 'NK225'):
        a = {f: models['main'][f]['symbols'][symbol]['periods']['対象'] for f in range(6)}
        ideal = models['ideal_fee'][3]['symbols'][symbol]
        stops = ideal['analysis']['返済理由']['1']
        trails = ideal['analysis']['返済理由']['3']
        reasons.append(dict(観点=f'{symbol}・順行へ変えるだけでは共通化しない',
            説明=f'同幅・同じ損切り1対利確3で入口だけ順行へ変えると、逆張り{yen(a[0]["net"])}から順行{yen(a[1]["net"])}へ、差は{yen(a[1]["net"] - a[0]["net"])}。方向の変更が一方の商品で良くても両商品の共通優位とは扱わない。'))
        reasons.append(dict(観点=f'{symbol}・返済後すぐ反転する回数の増加',
            説明=f'幅8呼値の追尾返済後に待機する場合は{a[2]["trades"]}脚、即ドテンは{a[3]["trades"]}脚。収支は{yen(a[3]["net"] - a[2]["net"])}悪化し、手数料は{a[3]["fees"] - a[2]["fees"]:,.0f}円増えた。待機を飛ばして反対方向へ参加しても、反対方向が続く根拠は追加されない。'))
        reasons.append(dict(観点=f'{symbol}・気配差ゼロの別再生でも価格経路の赤字が残る',
            説明=f'現在値必約定の即ドテンでも手数料前{yen(ideal["periods"]["対象"]["gross"])}。初期損切り{stops["脚数"]}脚の純損益{yen(stops["収支"])}を、追尾返済{trails["脚数"]}脚の合計{yen(trails["収支"])}が埋めていない。追尾返済のうち{trails["赤字脚"]}脚は赤字で、少し順行しても出口幅ほど戻れば建値を割る。'))
        reasons.append(dict(観点=f'{symbol}・反転を制限した既検証の結果',
            説明=f'追加1幅の反転確認は待機基準に対して{yen(a[4]["net"] - a[2]["net"])}、利益時だけ即ドテンは{yen(a[5]["net"] - a[2]["net"])}。双方で共通した黒字化ではなく、同じ幅の確認・制限だけで解決したとはいえない。'))
    reasons.append(dict(観点='値幅と約定の違い',
        説明='通常の同幅即ドテンは、TOPIX4ポイント・日経80ポイントが損切りの発動幅である。これは約定損失の保証上限ではない。2026-10-02ナイトの日経では37呼値の売買気配差がある原本行で売り69530→返済69900となり、74,440円を失った。CurrentPriceは同値69790、記録時計も同じであり、実時間0秒の取引とは断定しない。'))
    reasons.append(dict(観点='今回確かめた範囲と未確定部分',
        説明='固定幅8の即ドテンは通常・現在値必約定の双方で不振だった。極値から一定幅戻ることは前方向が弱まった事実であり、逆方向へ利益幅が続く証拠とは同じではない。気配差と料金は反転回数に応じて重くなり、価格経路自体の赤字も別再生で残った。他の幅・確認法全般が無効だという一般化は行わない。'))
    source['因果的な読み方'] = reasons
    source['代表変更なし'] = True
    source['未来経路は事後説明専用'] = True
    (HERE / '診断の短い要旨.json').write_text(json.dumps(source, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(完了=True, 因果解釈=len(reasons)), ensure_ascii=False))


if __name__ == '__main__':
    main()
