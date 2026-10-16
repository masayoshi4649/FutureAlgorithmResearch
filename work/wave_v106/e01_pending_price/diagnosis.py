"""完成した実台帳同士で、永久取消の効果と取り逃しを時刻付きで検算する。"""

from datetime import datetime, timedelta, timezone
import gc

import numpy as np

import common
import data


def time_text(value: float) -> str:
    """
    機能: 価格代理時計を日本時間へ表示する。
    引数: value(float)は保存UTC秒。
    返り値: strは日時。受信時刻や実送信時刻とは呼ばない。
    """
    return datetime.fromtimestamp(value,timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S')


def same_orders(a: dict, b: dict) -> None:
    """
    機能: 取消が一度もなかった口座の全実注文・UID・料金・全行時価を旧基準と照合する。
    引数: a/b(dict)は同じ政策の新旧保存会計。
    返り値: None。同値でない場合は金融を再実行せず診断を停止する。
    """
    for name in ('orders','order_uids','order_fees'):
        np.testing.assert_array_equal(a[name],b[name],err_msg=name)
    np.testing.assert_allclose(a['equity_yen'],b['equity_yen'],atol=1e-5,rtol=1e-12)
    for name in ('利益','損失','収支','費用','親数','勝ち枚数','負け枚数'):
        assert np.isclose(a['summary'][name],b['summary'][name],atol=1e-5),name


def source_quote(q: dict, seq: int) -> dict:
    """
    機能: 同原seqに対応した正常BBOを値だけで抜き出す。
    引数: q(dict)、seq(int)は保存正常列と公表源原seq。
    返り値: dictは同一原行の日時・BBO。後続正常行へ差替えない。
    """
    row=int(np.searchsorted(q['seq'],seq));assert row<len(q['seq']) and int(q['seq'][row])==seq
    return dict(原seq=seq,価格時計=time_text(float(q['time_s'][row])),bid=float(q['bid'][row]),ask=float(q['ask'][row]))


def observation(account: dict, quotes: dict, symbol: str, row: int, window: int, role: str) -> dict:
    """
    機能: 保存取消時の自己またはstrictpast相手の価格端点系譜を復元する。
    引数: account/quotes(dict)、symbol/role(str)、row/window(int)は保存判断の位置。
    返り値: dictは方向・始終点の価格・年齢。後から公表源を選び直さない。
    """
    projection=account['windows'][str(window)][role];index=int(projection['public_index'][row])
    market=symbol if role=='own' else ('NK225' if symbol=='TOPIX' else 'TOPIX')
    value=account['source_windows'][market]['windows'][str(window)]
    assert index>=0 and value['unknown_reason'][index]==0 and not value['ambiguous'][index]
    return dict(direction=int(projection['direction'][row]),公表年齢秒=float(projection['age_seconds'][row]),
        終点=source_quote(quotes[market],int(value['source_raw_seq'][index])),
        基準=source_quote(quotes[market],int(value['reference_raw_seq'][index])),
        bidask変化呼値=[float(value['bid_change_ticks'][index]),float(value['ask_change_ticks'][index])])


def contributions(before: dict, after: dict) -> tuple[dict, list[int], list[int]]:
    """
    機能: 保存親の損益差を入口除外と共通出口及び新入口に分解する。
    引数: before/after(dict)は新旧完結会計。
    返り値: tuple[dict,list[int],list[int]]は5寄与と除外/追加親。
    """
    a={int(p['親']):p for p in before['parent']};b={int(p['親']):p for p in after['parent']}
    removed=sorted(a.keys()-b.keys());added=sorted(b.keys()-a.keys());common_keys=a.keys()&b.keys()
    avoid=sum(-a[k]['収支'] for k in removed if a[k]['収支']<0)
    missed=sum(a[k]['収支'] for k in removed if a[k]['収支']>0)
    exits=sum(b[k]['収支']-a[k]['収支'] for k in common_keys);new=sum(b[k]['収支'] for k in added)
    net=after['summary']['収支']-before['summary']['収支']
    assert np.isclose(net,avoid-missed+exits+new,atol=1e-5)
    return dict(収支変化=net,避けた基準損失=avoid,失った基準利益=missed,共通入口の出口変化=exits,
        新たな入口の収支=new),removed,added


def run() -> None:
    """
    機能: 完成792台帳を一度読んで、0取消同値・共通親・赤字11場・利益取り逃しを確認する。
    引数: なし。
    返り値: None。新金融再生0、旧source/数学不変更の診断証跡を保存する。
    """
    final=common.read(common.HERE/'finance/結果.json');assert final['全合格']
    inputfixed=common.read(common.HERE/'入力事前固定.json');daily_meta=common.read(common.ROOT/'work/wave_v106/e01_daily/finance/結果.json')
    wanted=inputfixed['quotes'];assert common.digest(common.ROOT/wanted['path'])==wanted['SHA256']
    quotes=common.read(common.ROOT/wanted['path'])
    red={s:[r['session'] for r in daily_meta['results']['E01_DAILY_P1_L8']['rows'] if r['symbol']==s and r['収支']<0]
        for s in ('TOPIX','NK225')}
    assert len(red['TOPIX'])==5 and len(red['NK225'])==6
    targets={c['id']: {(x['session'],x['symbol']):x for x in final['results'][c['id']]['ledgers']} for c in final['configs']}
    daily_sha={(x['session'],x['symbol']):x for x in daily_meta['results']['E01_DAILY_P1_L8']['ledgers']}
    checks=[];zero=[];red_cases={c['id']:[] for c in final['configs']};lost={c['id']:[] for c in final['configs']}
    all_delta={c['id']:[] for c in final['configs']};cancel_counts={c['id']:{s:0 for s in ('TOPIX','NK225')} for c in final['configs']}
    for session in final['sessions']:
        packet=data.load_session(session);session_q={s:quotes[session,s] for s in ('TOPIX','NK225')}
        for symbol in ('TOPIX','NK225'):
            relative=f'ledgers/L_D20_BBO/{session}_{symbol}.pkl.gz';path=common.REFERENCE/relative
            assert common.digest(path)==inputfixed['baseline'][relative];old_gu=common.read(path)
            old_daily_item=daily_sha[session,symbol];old_daily=common.read(common.ROOT/old_daily_item['path'])
            assert common.digest(common.ROOT/old_daily_item['path'])==old_daily_item['SHA256']
            account=packet['accounts'][symbol];q=session_q[symbol]
            for config in final['configs']:
                ident=config['id'];item=targets[ident][session,symbol];path=common.ROOT/item['path']
                assert common.digest(path)==item['SHA256'];new=common.read(path)
                before=old_gu if config['exit']=='GU' else old_daily
                control=new.get('control',{});end=control['判断行'] if control.get('発動') else len(q['seq'])-1
                actual=new['cancel_events'][new['cancel_events'][:,0]<=end]
                cancel_counts[ident][symbol]+=len(actual)
                if len(actual)==0:
                    same_orders(new,before);zero.append(dict(id=ident,session=session,symbol=symbol,全注文会計同値=True))
                difference,removed,added=contributions(before,new);all_delta[ident].append(dict(session=session,symbol=symbol,**difference))
                a={int(p['親']):p for p in before['parent']};b={int(p['親']):p for p in new['parent']}
                common_parents=a.keys()&b.keys();exits_exact=0
                for cid in common_parents:
                    old_entry=before['orders'][(before['orders'][:,2]==cid)&(before['orders'][:,7]==1)]
                    new_entry=new['orders'][(new['orders'][:,2]==cid)&(new['orders'][:,7]==1)]
                    np.testing.assert_array_equal(old_entry,new_entry)
                    old_exit=before['orders'][(before['orders'][:,2]==cid)&(before['orders'][:,7]==0)]
                    new_exit=new['orders'][(new['orders'][:,2]==cid)&(new['orders'][:,7]==0)]
                    if config['exit']=='GU':
                        np.testing.assert_array_equal(old_exit,new_exit)
                        assert a[cid]['費用']==b[cid]['費用'] and a[cid]['収支']==b[cid]['収支']
                        exits_exact+=1
                cancellations=[]
                for event in actual:
                    row,cid,source,side=map(int,(event[0],event[2],event[3],event[4]))
                    assert source<row and not np.any(new['orders'][(new['orders'][:,2]==cid)&(new['orders'][:,7]==1)])
                    info=dict(取消価格時計=time_text(float(q['time_s'][row])),取消原seq=int(q['seq'][row]),
                        公開価格時計=time_text(float(q['time_s'][source])),紙上親=cid,方向=side,指値=float(event[8]),
                        元比較親収支=a[cid]['収支'] if cid in a else None,
                        peer=observation(account,session_q,symbol,row,config['window_seconds'],'peer'))
                    if config['mode']=='P':
                        info['own']=observation(account,session_q,symbol,row,config['window_seconds'],'own')
                    else:
                        info['own_direction']=int(account['windows'][str(config['window_seconds'])]['own']['direction'][row])
                    cancellations.append(info)
                for cid in removed:
                    if a[cid]['収支']>0:
                        matched=[x for x in cancellations if x['紙上親']==cid]
                        old_entry=before['orders'][(before['orders'][:,2]==cid)&(before['orders'][:,7]==1)][0]
                        lost[ident].append(dict(session=session,symbol=symbol,紙上親=cid,失った基準利益=a[cid]['収支'],
                            元実新規時計=time_text(float(q['time_s'][int(old_entry[0])])),元実新規価格=float(old_entry[5]),
                            取消=matched,原因='待機取消' if matched else '変わった日次停止又は実保有スケジュール'))
                if session in red[symbol]:
                    surviving=[dict(親=cid,新規価格時計=time_text(float(q['time_s'][b[cid]['新規行']])),
                        方向=b[cid]['方向'],新規枚数=b[cid]['枚数'],収支=b[cid]['収支']) for cid in b]
                    red_cases[ident].append(dict(session=session,symbol=symbol,元P1L8収支=old_daily['summary']['収支'],
                        対応比較基準収支=before['summary']['収支'],新収支=new['summary']['収支'],
                        取消=cancellations,残った実親=surviving,除外比較親=removed,追加実親=added,寄与=difference,
                        日次停止=control,無取引を黒字としない=True))
                checks.append(dict(id=ident,session=session,symbol=symbol,共通親入口同値=len(common_parents),
                    GU共通親返済及び費用同値=exits_exact,取消後復活なし=len(actual),**{'5寄与合格':True},
                    日次停止後予定取消を活動に数えない=True))
                del new
            print(session+' 0取消同値・共通親・赤字場原因の保存比較完了',flush=True)
            del old_gu,old_daily
            gc.collect()
    assert len(checks)==792
    totals={i:{s:{field:sum(r[field] for r in all_delta[i] if r['symbol']==s) for field in
        ('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')}
        for s in ('TOPIX','NK225')} for i in all_delta}
    for i in totals:
        for s in totals[i]:
            for field,v in totals[i][s].items():
                assert np.isclose(v,final['diagnosis'][i][s][field],atol=1e-5)
    common.write(common.HERE/'finance/取消零の旧同値と初期赤字11場の診断.json',dict(全合格=True,
        口座検査=checks,**{'0取消旧注文会計同値':zero,'0取消同値口座数':len(zero)},
        初期P1L8赤字場=red,赤字場具体時刻=red_cases,実際の有効取消件数=cancel_counts,
        失った利益上位={i:sorted(v,key=lambda x:x['失った基準利益'],reverse=True)[:12] for i,v in lost.items()},
        全33の5寄与=totals,結果SHA256=common.digest(common.HERE/'finance/結果.json'),
        新金融再生=0,既新台帳読取=792,元GU実台帳読取=66,既P1L8台帳読取=66,
        新入力cache読取=33,Qpickle読取=1,原板再読取=0,API=0,
        限界='取消時刻はCurrentPriceTimeの価格代理時計。真の受信/送信時刻は未観測。数量・補充・経路TVを示す測定ではない。'))
    print('0取消旧同値・初期赤字11場・5寄与の診断完了',flush=True)


if __name__=='__main__':
    run()
