"""各場の符号と中値損益を直接集計し、反転の結論が証拠を超えないか確認する。"""

from context import *


def summarize(packet: dict, sessions: list) -> dict:
    """機能: 商品別に毎場の赤黒、費用、中値、金額利益割合を求める。

    引数: packet(dict)、sessions(list)。返り値: 商品別要約(dict)。
    """
    out={}
    for symbol in ['TOPIX','NK225']:
        rows=[r for r in packet['rows'] if r['symbol']==symbol and r['session'] in sessions]
        profit=sum(r['profit'] for r in rows);loss=sum(r['loss'] for r in rows)
        net=sum(r['net'] for r in rows);cost=sum(r['spread_drag']+r['fees'] for r in rows)
        out[symbol]=dict(収支=net,利益=profit,損失=loss,金額利益割合=profit/(profit+loss) if profit+loss else None,
            黒字場数=sum(r['net']>0 for r in rows),赤字場数=sum(r['net']<0 for r in rows),
            活動場数=sum(r['trades']>0 for r in rows),全場数=len(rows),
            気配差料金=cost,中値経路=net+cost,決済組数=sum(r['trades'] for r in rows))
    return out


def main() -> None:
    """機能: 元188・反転188と固定3枠を独立集計して解釈上の限界を記録する。

    引数: なし。返り値: なし(None)。今後の代表を選び直す処理はしない。
    """
    fixed=load(WORK/'事前固定.json');initial=[];selected=[]
    for p in fixed['parents']:
        parent=load(ROOT/p['path']);reverse=load(WORK/'first/results'/f'R__{p["config"]["id"]}.json')
        f=summarize(parent,fixed['前16']);r=summarize(reverse,fixed['前16'])
        initial.append(dict(元両方全場赤字=all(v['赤字場数']==16 for v in f.values()),
            逆両方全場赤字=all(v['赤字場数']==16 for v in r.values()),
            逆両方全場黒字=all(v['黒字場数']==16 for v in r.values()),
            逆両方合計黒字=all(v['収支']>0 for v in r.values()),逆両方合計赤字=all(v['収支']<0 for v in r.values())))
    stable=[r for r in initial if r['元両方全場赤字']]
    checks=dict(元が両商品全16場赤字の条件数=len(stable),その逆も両商品全16場赤字=sum(r['逆両方全場赤字'] for r in stable),
        その逆が両商品合計黒字=sum(r['逆両方合計黒字'] for r in stable),
        その逆も両商品合計赤字=sum(r['逆両方合計赤字'] for r in stable),
        全逆188の両商品合計黒字=sum(r['逆両方合計黒字'] for r in initial),
        全逆188の両商品全16場黒字=sum(r['逆両方全場黒字'] for r in initial))
    assert list(checks.values())==[66,62,0,66,20,0],checks
    for pair in fixed['pairs']:
        record=dict(枠=pair['label'],元ID=pair['parent_id'],再生={})
        for delay in [0,1,5]:
            result={}
            for polarity in ['original','reverse']:
                packet=load(WORK/'final'/f'delay{delay}'/'results'/f'{pair[polarity]["id"]}.json')
                result[polarity]={name:summarize(packet,fixed[name]) for name in ['前16','後14','全30']}
            record['再生'][str(delay)]=result
        five=record['再生']['5']
        if pair['label'] in ['A','B']:
            assert all(v['赤字場数']==30 for side in five.values() for v in side['全30'].values())
        if pair['label']=='C':
            assert all(v['収支']>0 for v in five['reverse']['前16'].values())
            assert all(v['収支']<0 for v in five['reverse']['後14'].values())
            assert five['reverse']['全30']['TOPIX']['収支']==21480.
            assert five['reverse']['全30']['NK225']['収支']==-192800.
        selected.append(record)
    result=dict(合格=True,前半188照合=checks,固定3枠=selected,
        必須の解釈=[
            '費用に売買気配差と税込料金を含める。成行恒等式に判断から約定までの価格変化をもう一度控除しない。',
            '元で中値損益が赤字なら逆の中値損益は改善し得る。しかし実売買費用を超えなければ元逆とも赤字。',
            'AはM1なので元逆で不成立・回数・時計が変わる。Aの差を同一経路の恒等式だけでは説明しない。',
            'Cは前半で反転余地そのものから選んだ。前16黒字は選定資料内の結果であり、独立した予測成功ではない。',
            '20条件の反転前半黒字を無かったことにしない。反転一般の無効を証明したのではなく、固定代表の両商品安定黒字を確認できなかった。',
            '各商品の毎場の赤字・黒字を数え、両商品の円を足して良否を判定しない。全30は既知。'],
        事前固定SHA256=digest(WORK/'事前固定.json'))
    save('反転結果の独立集計と解釈監査.json',result)
    print(json.dumps(dict(合格=True,**checks),ensure_ascii=False))


if __name__=='__main__':main()
