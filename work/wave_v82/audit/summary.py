"""反転調査の独立監査の件数と最終指紋をまとめる。"""

from context import *


def main() -> None:
    """機能: 完了済み監査の件数を加算し、監査索引を保存する。

    引数: なし。返り値: なし(None)。未完了を合格扱いにしない。
    """
    names=['first','final_delay0','final_delay1','final_delay5','quality3']
    stages=[load(HERE/(n+'の全口座独立会計監査.json')) for n in names]
    assert all(r['合格'] for r in stages)
    totals={field:sum(r.get(field,0) for r in stages) for field in ['条件数','口座数','注文数','決済数',
        '会計照合項目','期間照合数','成行恒等式口座数','成行恒等式決済数',
        '元前半完全一致口座数','全再生一致口座数','全行清算時価SHA一致口座数']}
    proofs=['売買反転の人工境界と独立会計監査.json','前半限定選定と非破壊反転の独立監査.json',
        '全固定元逆ペアと三遅延の実注文未来監査.json','反転結果の独立集計と解釈監査.json',
        '公開HTMLの数値と解釈の独立監査.json']
    for name in proofs:assert load(HERE/name)['合格']
    frozen=load(WORK/'事前固定.json')
    for path,h in frozen['SHA256'].items():assert digest(ROOT/path)==h,path
    result=dict(合格=True,**totals,指紋最終一致数=len(frozen['SHA256']),
        個別証跡={n:digest(HERE/n) for n in proofs},
        保存領域='work/wave_v82/auditのみ。旧研究、売買エンジン、固定選定、原本データは変更しない。',
        限界='保存時計と約定代理の下で実装と会計を監査した。実受信遅延、ミニ/マイクロの約定順位、市場影響及び将来利益は証明しない。')
    save('監査総括.json',result)
    lines=['# 売買反転の独立監査','',
        f'全{totals["条件数"]}条件実行・{totals["口座数"]:,}口座・{totals["注文数"]:,}注文・{totals["決済数"]:,}決済を再会計し、全行清算時価の指紋も一致しました。',
        f'成行{totals["成行恒等式口座数"]:,}口座・{totals["成行恒等式決済数"]:,}決済で、元と反転の約定時計と組別恒等式を照合しました。',
        '', '元5秒の前16は旧81の96口座と完全一致。鮮度3秒の180口座は全再生も一致。未来切断・改変は116口座2,147地点で合格しました。',
        '', 'C枠は前半の反転余地を計算して選ぶ探索です。全30は既知であり、未知将来の証明とは扱いません。',
        '', '元が両商品全16場赤字だった66条件は、実反転後も全て両商品合計赤字でした。一方、逆188の前半では20条件が両商品合計黒字。反転一般の無効という結論にはしません。',
        '', '以下は全て合格の証跡です。', '']
    lines += [f'- [{name}]({name})' for name in proofs]
    lines += ['',result['限界'],'']
    (HERE/'README.md').write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='個別証跡'},ensure_ascii=False))


if __name__=='__main__':main()
