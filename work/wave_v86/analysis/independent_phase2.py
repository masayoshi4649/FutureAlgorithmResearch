"""黒字後限定の追加十条件を、元の待機と一律早期再参加へ独立比較する。"""
from pathlib import Path
import json
import pickle
import sys

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from independent import read,sha,extract,summarize,group_summary,entry_changes,delta

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
SECOND=WORK/'phase2'
ROOT=WORK.parents[1]
SYMBOLS=('TOPIX','NK225')



def added_after_profit(before,after,symbol):
    """
    機能: 元にない入口のうち、直前親組が黒字だった再参加を切り分ける。
    引数: before/after(list[dict])、symbol(str)。
    返り値: dict の親組会計。追加後の経路の二次的変化と区別する。
    """
    keys={(c['session'],c['entry'],c['direction']) for c in before if c['symbol']==symbol}
    previous={};selected=[];same=[]
    for cycle in sorted((c for c in after if c['symbol']==symbol),key=lambda c:(c['session'],c['entry'])):
        prior=previous.get(cycle['session'])
        key=cycle['session'],cycle['entry'],cycle['direction']
        if key not in keys and prior and prior['net']>1e-7:
            selected.append(cycle)
            if prior['direction']==cycle['direction']: same.append(cycle)
        previous[cycle['session']]=cycle
    return dict(直前黒字=summarize(selected),うち同じ方向=summarize(same))


def main():
    """
    機能: 別固定の全結果が揃った後に、親組黒字だけの再参加を商品別に照合する。
    引数: なし。
    返り値: None。売買再生・条件選定の変更は行わない。
    """
    fixed=read(SECOND/'事前固定.json')
    expected=[SECOND/m/'results'/(c['id']+'.json') for m in fixed['models'] for c in fixed['catalog']]
    missing=[p for p in expected if not p.exists()]
    if missing: raise RuntimeError('第二段階の全結果待ち: '+str(len(missing)))
    endpoint_source=ROOT/'work/wave_v85/analysis/方向偏り独立確認.json'
    old_regime=read(endpoint_source)
    assert old_regime['input_SHA256']==fixed['input_SHA256']
    endpoints={(r['session'],r['symbol']):r for r in old_regime['session_results'] if r['model']=='observed'}
    sums=[];regimes=[];comparisons=[];entries=[];targets=[];actions=[];sources={str(endpoint_source.relative_to(ROOT)):sha(endpoint_source)}
    for model in fixed['models']:
        cache={}
        for config in fixed['catalog']:
            ident=config['id'];exit_id=config['exit_id']
            ordinary='E01_G_U' if exit_id=='T0' else exit_id+'_S'
            rapid=exit_id+('_A1' if config['clock_id']=='P1' else '_A0')
            ids=((ident,SECOND),(ordinary,WORK),(rapid,WORK))
            for key,directory in ids:
                if key in cache: continue
                path=directory/model/'results'/(key+'.json');ledgerpath=directory/model/'ledgers'/(key+'.pkl')
                result=read(path)
                assert sha(ledgerpath)==result['ledger_SHA256']
                with ledgerpath.open('rb') as stream: ledger=pickle.load(stream)
                cycles=extract(ledger,result)
                cache[key]=(result,cycles,ledger)
                sources[str(path.relative_to(ROOT))]=sha(path)
                sources[str(ledgerpath.relative_to(ROOT))]=result['ledger_SHA256']
            result,cycles,ledger=cache[ident]
            for symbol in SYMBOLS:
                for period in ('前16','後14','全30'):
                    sessions=set(fixed[period])
                    local=[c for c in cycles if c['symbol']==symbol and c['session'] in sessions]
                    rows=[r for r in result['rows'] if r['symbol']==symbol and r['session'] in sessions]
                    value=group_summary(local,rows)
                    saved=result['periods'][period][symbol]
                    assert abs(value['net']-saved['net'])<1e-6
                    value.update(max_drawdown=saved['max_drawdown'],
                        net_to_drawdown=value['net']/saved['max_drawdown'] if saved['max_drawdown'] else None,
                        by_direction={str(side):summarize([c for c in local if c['direction']==side]) for side in (1,-1)})
                    sums.append(dict(model=model,id=ident,period=period,symbol=symbol,**value))
                    for label in ('上昇','下落','横ばい'):
                        names={name for name in sessions if endpoints[name,symbol]['regime']==label}
                        regimes.append(dict(model=model,id=ident,period=period,symbol=symbol,regime=label,
                            **group_summary([c for c in local if c['session'] in names],[r for r in rows if r['session'] in names])))
                    for before in (ordinary,rapid):
                        prior,priorcycles,_=cache[before]
                        previous=group_summary([c for c in priorcycles if c['symbol']==symbol and c['session'] in sessions],
                            [r for r in prior['rows'] if r['symbol']==symbol and r['session'] in sessions])
                        previous['max_drawdown']=prior['periods'][period][symbol]['max_drawdown']
                        comparisons.append(dict(model=model,before=before,after=ident,symbol=symbol,period=period,**delta(previous,value)))
                for before in (ordinary,rapid):
                    entries.append(dict(model=model,before=before,after=ident,symbol=symbol,
                        **entry_changes(cache[before][1],cycles,symbol),
                        利確直後の追加入口=added_after_profit(cache[before][1],cycles,symbol)))
                event_count=allowed=resets=0
                for (session,sym),account in ledger.items():
                    if sym!=symbol: continue
                    events=account['profit_reentry_events']
                    event_count+=len(events)
                    allowed+=sum(e[3]>0 for e in events)
                    resets+=len(account['reentry_events'])
                    cy={c['campaign']:c for c in cycles if c['symbol']==symbol and c['session']==session}
                    assert len(events)==len(cy)
                    for event in events:
                        expected_net=cy[int(event[1])]['net']
                        assert abs(expected_net-event[2])<1e-6
                        assert bool(event[3])==(expected_net>1e-7)
                actions.append(dict(model=model,id=ident,symbol=symbol,親組終了数=event_count,
                    料金後黒字による早期許可数=int(allowed),実際の次観測リセット数=resets,
                    注記='場末の黒字全返済は許可と記録しても場末禁止により再新規しない。'))
                target='2026-09-24_Night'
                base=read(WORK/model/'results/E01_G_U.json')
                b={r['session']:r for r in base['rows'] if r['symbol']==symbol}
                a={r['session']:r for r in result['rows'] if r['symbol']==symbol}
                change={name:a[name]['net']-b[name]['net'] for name in b}
                targets.append(dict(model=model,id=ident,symbol=symbol,問題夜間収支=a[target]['net'],
                    問題夜間改善=change[target],全30改善=sum(change.values()),
                    他29改善=sum(v for k,v in change.items() if k!=target),改善場数=sum(v>0 for v in change.values()),
                    悪化場数=sum(v<0 for v in change.values())))
    # ----------------------------------------
    # 第一段階の候補も残し、追加十条件だけの一位を全体一位とは呼ばない。
    first=read(HERE/'独立解釈.json')
    all_summaries=first['商品別期間成績']+sums
    lookup={(r['model'],r['id'],r['period'],r['symbol']):r for r in all_summaries}
    ranks={};dominates={}
    for model in fixed['models']:
        ids=sorted({r['id'] for r in all_summaries if r['model']==model})
        positive=[ident for ident in ids if all(lookup[model,ident,'全30',s]['net']>0 for s in SYMBOLS)]
        ranks[model]=sorted(positive,key=lambda ident:min(lookup[model,ident,'全30',s]['net_to_drawdown'] for s in SYMBOLS),reverse=True)
        dominates[model]=[ident for ident in ids if ident!='E01_G_U' and all(
            lookup[model,ident,'全30',s]['net']>=lookup[model,'E01_G_U','全30',s]['net'] and
            lookup[model,ident,'全30',s]['profit_share']>=lookup[model,'E01_G_U','全30',s]['profit_share'] and
            lookup[model,ident,'全30',s]['positive_sessions']>=lookup[model,'E01_G_U','全30',s]['positive_sessions'] and
            lookup[model,ident,'全30',s]['max_drawdown']<=lookup[model,'E01_G_U','全30',s]['max_drawdown'] for s in SYMBOLS)]
    out=dict(新再生=False,条件変更=False,全会計照合=True,
        注記=['第1段階20条件を保持し、黒字の親組だけ再参加を早める別固定10条件。',
             '全30場は既知。前16/後14の区分を未見と呼ばず、収支下落比順位も事後比較。',
             '上昇下落分類は始終現在値±0.1%の事後説明。入口・出口や手法切替には使わない。',
             '同じ入口の照合は原本新規行と方向に基づく。追加組と消失組の説明を完全な因果分解とは呼ばない。'],
        期間別=sums,相場別=regimes,差分=comparisons,入口追加消失=entries,実発動=actions,
        問題夜間と全体=targets,全30条件の参考順位=ranks,両商品四指標同時改善=dominates,
        入力SHA256=sources,解析コードSHA256=sha(Path(__file__)))
    out['簡潔な解釈']=['料金後黒字の全返済だけに早期再準備を限定しても、全30条件の両商品共通の収支/最大下落の首位は元E01_G_Uだった。', 'T2_P1ではT2_Sと共通するTOPIX118組・NK225123組の損益が完全一致。追加入口のTOPIX305組は552457円赤字、NK225272組は325340円赤字。', 'その追加入口は手数料前でもTOPIX425000円、NK225265500円の赤字で、手数料だけが主因ではない。', '追加入口の平均利益は平均損失を下回る。TOPIXは12575円対14344円、NK225は5176円対6227円。狭い出口で再参加を増やすと、反発を待ってから入る入口と損切りの組合せが追加区間の小さな順行を回収しきれていない。最後の説明は価格経路の詳細分析ではなく損益構造からの推察。', 'P1とP0の優劣も一方向ではない。観測T2はTOPIXではP1が良いがNK225ではP0が良い。両商品共通の改善条件にはなっていない。', '今回の固定した入口・出口五系統・60秒又は0秒の利確後再準備で、元を両商品共通に上回る安定改善は得られなかった。利確後再参加という考え方一般が無効だとまでは言えない。']
    (HERE/'利確後限定の独立解釈.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    for model in fixed['models']:
        print(model,'全30参考上位',ranks[model][:5],'両商品四指標改善',dominates[model],flush=True)
        ids=list(dict.fromkeys(['T3_P1','T3_P0']+ranks[model][:3]))
        for ident in ids:
            for symbol in SYMBOLS:
                row=lookup[model,ident,'全30',symbol]
                print(ident,symbol,{k:row[k] for k in ('net','profit','loss','fees','cycles','positive_sessions','max_drawdown')},flush=True)


if __name__=='__main__': main()
