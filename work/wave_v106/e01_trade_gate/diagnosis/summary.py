"""完成24結果の小JSONだけを読み、安定性と5寄与を先に整理する。"""

import numpy as np

import tools


def run() -> None:
    """
    機能: 根の金融完了通知後だけ保存24条件の中央値・活動・上位3除外を算定する。
    引数: なし。
    返り値: None。大型入力・台帳・金融再生を呼ばず新証跡へ保存する。
    """
    value,sha=tools.read(tools.SOURCE/'finance/結果.json');assert value['全合格']
    assert value['新gateengine']==792 and value['新政策会計']==1584 and value['新基準政策会計']==66
    results={};both_share=both_top3=both_median=0
    for cfg in value['configs']:
        id=cfg['id'];case=value['results'][id];results[id]={}
        for symbol in ('TOPIX','NK225'):
            rows=[r for r in case['rows'] if r['symbol']==symbol];assert len(rows)==33
            total=case['symbols'][symbol];active=[r for r in rows if r['親数']]
            positive=sorted((r for r in rows if r['収支']>0),key=lambda r:r['収支'],reverse=True)
            remaining=[r for r in rows if r['session'] not in {z['session'] for z in positive[:3]}]
            results[id][symbol]=dict(利益=total['利益'],損失=total['損失'],収支=total['収支'],
                金額利益割合=total['利益割合'],決済親数=total['親数'],勝ち親=total['勝ち親'],負け親=total['負け親'],
                平均利益=total['平均利益'],平均損失=total['平均損失'],平均損益比=total['平均損益比'],
                活動場=len(active),黒字場=sum(r['収支']>0 for r in rows),赤字場=sum(r['収支']<0 for r in rows),
                無取引場=33-len(active),全33中央値=float(np.median([r['収支'] for r in rows])),
                活動場中央値=float(np.median([r['収支'] for r in active])) if active else None,
                上位3黒字場=[dict(session=r['session'],収支=r['収支']) for r in positive[:3]],
                上位3黒字場除外収支=sum(r['収支'] for r in remaining),
                最悪場=min(rows,key=lambda r:r['収支'])['session'],最悪場収支=min(r['収支'] for r in rows),
                全33の5寄与=value['diagnosis'][id][symbol])
        both_share+=all((results[id][s]['金額利益割合'] or 0)>=.8 for s in results[id])
        both_top3+=all(results[id][s]['上位3黒字場除外収支']>0 for s in results[id])
        both_median+=all(results[id][s]['全33中央値']>0 for s in results[id])
    proof=dict(全合格=True,scope='固定24条件・既知33場・TOPIX5/NK10枚。無取引は勝ちなし。',
        両商品金額利益80達成条件数=both_share,両商品上位3黒字場除外黒字条件数=both_top3,
        両商品全場中央値黒字条件数=both_median,results=results,
        source=dict(path='work/wave_v106/e01_trade_gate/finance/結果.json',sha256=sha),
        台帳読取=0,入力cache読取=0,新金融=0,原NPZ=0,API=0,
        買売別='詳細診断で実親台帳全数から別算定する。この概要では未読。')
    print(tools.write('全24の安定性と5寄与の小結.json',proof),flush=True)


if __name__=='__main__':run()
