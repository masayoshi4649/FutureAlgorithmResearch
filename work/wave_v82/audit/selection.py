"""元条件の前半だけを用いた3枠の順位と、反転入力の非破壊性を独立照合する。"""

from context import *


def independent_metrics(packet: dict) -> dict:
    """機能: 既存の場別会計から安定赤字と成行反転余地を再集計する。

    引数: packet(dict)。返り値: 商品別指標(dict)。主順位関数を呼ばない。
    """
    result={}
    for symbol in ['TOPIX','NK225']:
        rows=sorted([r for r in packet['rows'] if r['symbol']==symbol],key=lambda r:r['session'])
        net=np.array([r['net'] for r in rows]);cost=np.array([r['fees']+r['spread_drag'] for r in rows])
        profit=sum(r['profit'] for r in rows);loss=sum(r['loss'] for r in rows)
        middle=net+cost;inverse=-middle-cost
        result[symbol]=dict(n=sum(r['trades'] for r in rows),active=sum(r['trades']>0 for r in rows),
            losses=net<0,middle_losses=middle<0,inverse_wins=inverse>0,
            loss_share=loss/(profit+loss) if profit+loss else 0.,
            middle_ratio=-sum(middle)/max(1.,sum(cost)),worst=min(inverse/np.maximum(cost,1.)),
            inverse_ratio=sum(inverse)/max(1.,sum(cost)))
    return result


def independent_score(packet: dict, label: str) -> tuple:
    """機能: 事前文書の辞書順から独立した順位キーを組み立てる。

    引数: packet(dict)、label(str)。返り値: 辞書順順位(tuple)。
    """
    m=independent_metrics(packet);a,b=m['TOPIX'],m['NK225'];both=[a,b]
    enough=all(v['n']>=20 and v['active']>=8 for v in both)
    if label=='A':
        parts=[min(int(v['losses'].sum()) for v in both),int(np.sum(a['losses']&b['losses'])),
               min(v['loss_share'] for v in both),sum(v['loss_share'] for v in both)/2]
    elif label=='B':
        parts=[min(int(v['middle_losses'].sum()) for v in both),int(np.sum(a['middle_losses']&b['middle_losses'])),
               min(v['middle_ratio'] for v in both),sum(v['middle_ratio'] for v in both)/2]
    else:
        parts=[min(int(v['inverse_wins'].sum()) for v in both),int(np.sum(a['inverse_wins']&b['inverse_wins'])),
               min(v['worst'] for v in both),min(v['inverse_ratio'] for v in both)]
    return (enough,*parts,packet['config']['id'])


def main() -> None:
    """機能: 凍結指紋、全順位、前半限定、方向反転非破壊性を確かめる。

    引数: なし。返り値: なし(None)。検査結果は監査領域へ保存する。
    """
    frozen=load(WORK/'事前固定.json');rankings=load(WORK/'元前半の選定順位.json')
    for path,h in frozen['SHA256'].items():assert digest(ROOT/path)==h,path
    packets=[load(ROOT/p['path']) for p in frozen['parents']]
    assert len(packets)==188
    for packet in packets:
        assert {r['session'] for r in packet['rows']}==set(frozen['前16'])
        assert len(packet['rows'])==32
        assert packet['periods']['後14']['TOPIX']['trades']==0
        assert packet['periods']['後14']['NK225']['trades']==0
    common=[p for p in packets if not p['config']['solo']]
    assert len(common)==180
    winners=[];rankcount=0
    for label in ['A','B','C']:
        candidates=[p for p in common if label=='A' or p['config']['entry_mode']==0]
        order=sorted(candidates,key=lambda p:independent_score(p,label),reverse=True)
        assert [p['config']['id'] for p in order]==[r['id'] for r in rankings[label]]
        pair=next(p for p in frozen['pairs'] if p['label']==label)
        assert pair['parent_id']==order[0]['config']['id']
        assert list(independent_score(order[0],label))==pair['score']
        m=independent_metrics(order[0]);rankcount+=len(order)
        winners.append(dict(選定枠=label,元条件=pair['parent_id'],候補数=len(order),
            TOPIX全16赤字=bool(m['TOPIX']['losses'].all()),NK225全16赤字=bool(m['NK225']['losses'].all())))
    # ----------------------------------------
    # 実素材でgate適用後の反転と、共有入力を変更していないことを確かめる。
    material=research.previous.material();keys=sorted(material[0]);arraychecks=0
    probes=[p['config'] for p in common if p['config'].get('entry_gate')][:2]
    probes += [p['original'] for p in frozen['pairs']]
    for parent in probes:
        c=dict(parent,polarity=1)
        for key in [keys[0],keys[1],keys[-2],keys[-1]]:
            a=research.arguments(c,key,material,5)
            snapshots=[v.copy() if isinstance(v,np.ndarray) else v for v in a]
            b=research.arguments(dict(c,polarity=-1),key,material,5)
            again=research.arguments(c,key,material,5)
            for i,(x,y,z,t) in enumerate(zip(a,b,again,snapshots)):
                np.testing.assert_array_equal(x,t)
                np.testing.assert_array_equal(z,t)
                np.testing.assert_array_equal(y,-t if i in [7,26,32,33] else t)
                arraychecks+=3
    result=dict(合格=True,元条件数=188,共通選定候補=180,独立順位照合数=rankcount,
        固定代表=winners,指紋照合数=len(frozen['SHA256']),反転非破壊照合数=arraychecks,
        後14選定利用口座=0,事前固定SHA256=digest(WORK/'事前固定.json'),
        解釈='C枠は前半成行の反転後損益を恒等式で計算した探索であり、反転損益を一切知らず選んだ枠ではない。全30は既知。')
    save('前半限定選定と非破壊反転の独立監査.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
