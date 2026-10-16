"""損失診断の分母・気配費用・時刻・未知保存・数量差を小人工だけで確認する。"""

import copy
import reader


def fixture(quantity: int=10, reason: int=141) -> dict:
    """
    機能: 初期spreadで赤字になる完結一親の小診断を作る。
    引数: quantity/reason(int) は実枚数と返済理由。
    返り値: dict は実親相当の人工。実素材/金融/公開会計を読まない。
    """
    fee=quantity*209//5;net=-.5*quantity*1000-2*fee
    entry=dict(row=2,source_row=1,raw_seq=12,source_raw_seq=11,price_time_s=1728838810.,source_price_time_s=1728838809.,
        price=100.5,quantity=quantity,fee_yen=fee,reason=90,bid=100.,ask=100.5,source_bid=100.,source_ask=100.5,source_normal=True)
    exit=dict(entry,row=4,source_row=3,raw_seq=14,source_raw_seq=13,price_time_s=1728838812.,source_price_time_s=1728838811.,price=100.,reason=reason)
    point=dict(row=2,raw_seq=12,price_time_s=1728838810.,bid=100.,ask=100.5,parent_liquidation_yen=net,hindsight_only=True)
    best=dict(point,row=3,parent_liquidation_yen=100.)
    return dict(session='人工0',symbol='TOPIX',parent=0,side=1,entry=entry,exits=[exit],entry_quantity=quantity,
        net_yen=net,fees_yen=2*fee,published_price_cap=101.,published_direction_votes=2,published_balance=.5,
        parent_stop_yen=100.5*quantity*1000*.00125,target_yen=100.5*quantity*1000*.005,
        worst_parent_liquidation_yen=net,best_parent_liquidation_yen=100.,liquidation_side_mae_price=-.5,
        first_parent_liquidation_argmin=point,first_parent_liquidation_argmax=best)


def run() -> None:
    """
    機能: 票帯・重複タグ・初期気配料・unknownと半/全量対応を独立小人工で確認する。
    引数: なし。
    返り値: None。診断sourceに拘束した人工証跡を新規保存する。
    """
    source=reader.sources();count=0;config={'exit_id':'TARGET'}
    for votes,band in ((2,'2票'),(3,'3〜4票'),(4,'3〜4票'),(5,'5〜9票'),(9,'5〜9票'),(10,'10票以上'),(None,'未保存')):
        assert reader.vote_band(votes)==band;count+=1
    p=fixture();out=reader.profile(p,config)
    assert out['入口FAK価格内'] and out['初回料込即時全返済見積損失円']==5836
    assert out['初期気配費用で親損失線到達'] and out['初期気配差からの追加逆行値幅']==0
    assert '費用後黒字を返して赤字' in out['観測タグ'] and out['事後ピークから最終netへ返した額']==5936;count+=5
    assert out['entry']['price_time_s_JST'].endswith('+09:00');count+=1
    broken=copy.deepcopy(p);broken['entry']['source_bid']=None;broken['entry']['source_ask']=None;broken['entry']['source_normal']=False
    assert reader.profile(broken,config)['公開時気配差'] is None;count+=1
    trail=reader.profile(p,{'exit_id':'TRAIL'});assert trail['有効純利益目標円'] is None and trail['事後ピーク目標比'] is None;count+=2
    quiet=reader.profile(fixture(reason=92),config);assert '予定静観による終了' in quiet['観測タグ'];count+=1
    group=reader.grouped([p,dict(p,net_yen=100.)],config)
    assert group['全実親数']==2 and group['利益親']==group['損失親']==1 and group['票帯']['2票']['親数']==2;count+=3
    # ----------------------------------------
    # 同公開親の料差だけの場合と実返済行が変わる場合を区別する。
    profiles={}
    for exit_id in ('GU','TARGET','TRAIL','PARTIAL'):
        for qtyname,q in (('HALF',5),('FULL',10)):
            cid='E01_SCALE_SELECTED_'+qtyname+'_'+exit_id;profiles[cid]=[fixture(q)]
    data={'actual_parent_diagnostics':profiles};paired=reader.half_full(data)
    assert all(v['共通公開親']==1 and v['非比例親数']==0 for k,v in paired.items() if k.startswith('TOPIX'));count+=4
    profiles['E01_SCALE_SELECTED_FULL_TARGET'][0]['exits'][0]['row']=5
    changed=reader.half_full(data)['TOPIX|TARGET'];assert changed['非比例親数']==1 and not changed['具体例'][0]['同返済行理由'];count+=2
    assert source==reader.sources()
    reader.write('小射影診断の人工検査.json',dict(全合格=True,検査=count,診断source_SHA256=source,
        金融=0,結果読取=0,公開会計読取=0,原input=0,台帳=0,API=0))
    print('診断小人工合格 '+str(count)+'検査。結果/入力/台帳読取0。')


if __name__=='__main__':run()
