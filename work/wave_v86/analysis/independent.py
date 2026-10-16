"""保存済み二十条件だけから、狭幅・再参加・方向偏りを独立に分解する。"""
from collections import defaultdict
from datetime import datetime,timezone,timedelta
from pathlib import Path
import hashlib
import json
import pickle

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
BASE='E01_G_U'
SYMBOLS=('TOPIX','NK225')
JST=timezone(timedelta(hours=9))


def read(path):
    """
    機能: 完了した保存JSONを読む。
    引数: path(Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: 読取資料を指紋化する。
    引数: path(Path)。
    返り値: str のSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(cycles):
    """
    機能: 部分決済を親組へまとめた料金後成績を集計する。
    引数: cycles(list[dict])。
    返り値: dict。赤字の絶対額を損失として持つ。
    """
    profit=sum(max(x['net'],0.) for x in cycles)
    loss=sum(max(-x['net'],0.) for x in cycles)
    wins=sum(x['net']>0 for x in cycles)
    losses=sum(x['net']<0 for x in cycles)
    return dict(cycles=len(cycles),wins=wins,losses=losses,profit=profit,loss=loss,
        net=profit-loss,gross=sum(x['gross'] for x in cycles),fees=sum(x['fees'] for x in cycles),
        profit_share=profit/(profit+loss) if profit+loss else None,
        average_win=profit/wins if wins else None,average_loss=loss/losses if losses else None,
        average_net=(profit-loss)/len(cycles) if cycles else None)


def extract(ledgers,result):
    """
    機能: 台帳から親組を再構成し、保存済み場別会計と照合する。
    引数: ledgers/result(dict)。
    返り値: list[dict] の親組。新たな売買再生を行わない。
    """
    output=[]
    for key,ledger in sorted(ledgers.items()):
        groups=defaultdict(list)
        for trade in ledger['net_trades']: groups[trade['組']].append(trade)
        local=[]
        for cid,trades in sorted(groups.items()):
            assert len({t['方向'] for t in trades})==1
            assert len({t['新規原本行'] for t in trades})==1
            local.append(dict(session=key[0],symbol=key[1],campaign=cid,direction=int(trades[0]['方向']),
                entry=int(trades[0]['新規原本行']),entry_time=float(trades[0]['新規時刻']),
                exit=max(int(t['返済原本行']) for t in trades),exit_time=max(float(t['返済時刻']) for t in trades),
                net=float(sum(t['収支'] for t in trades)),gross=float(sum(t['利益損失前'] for t in trades)),
                fees=float(sum(t['手数料'] for t in trades)),exit_reasons=sorted({int(t['理由']) for t in trades})))
        row=next(x for x in result['rows'] if (x['session'],x['symbol'])==key)
        total=summarize(local)
        for a,b in [('net','net'),('gross','gross'),('fees','fees'),('profit','cycle_profit'),('loss','cycle_loss'),('cycles','cycles')]:
            assert abs(total[a]-row[b])<1e-6,(key,a)
        output.extend(local)
    return output


def group_summary(cycles,rows):
    """
    機能: 取引休止を勝ちに含めず、場別の安定度を親組会計へ追加する。
    引数: cycles/rows(list[dict])。
    返り値: dict。
    """
    value=summarize(cycles)
    days=defaultdict(float)
    for row in rows: days[row['session'].split('_')[0]]+=row['net']
    value.update(session_count=len(rows),positive_sessions=sum(r['net']>0 for r in rows),
        negative_sessions=sum(r['net']<0 for r in rows),no_trade_sessions=sum(r['cycles']==0 for r in rows),
        best_session_removed=value['net']-max((r['net'] for r in rows),default=0.),
        worst_session=min((r['net'] for r in rows),default=0.),
        day_count=len(days),positive_days=sum(v>0 for v in days.values()),
        best_day_removed=value['net']-max(days.values(),default=0.))
    return value


def delta(before,after):
    """
    機能: 利益減少と損失削減を、同じ親組会計で分離する。
    引数: before/after(dict)。
    返り値: dict。収支変化=利益変化+損失削減。
    """
    fields=('net','gross','fees','cycles','positive_sessions','max_drawdown')
    out={key:after[key]-before[key] for key in fields if key in before and key in after}
    out.update(profit_change=after['profit']-before['profit'],loss_reduction=before['loss']-after['loss'])
    assert abs(out['net']-out['profit_change']-out['loss_reduction'])<1e-6
    assert abs(out['net']-(out['gross']-out['fees']))<1e-6
    return out


def entry_key(cycle):
    """
    機能: 同じ場の原本新規行と方向から、入口一致の識別子を作る。
    引数: cycle(dict)。
    返り値: tuple[str,str,int,int]。
    """
    return cycle['session'],cycle['symbol'],cycle['entry'],cycle['direction']


def entry_changes(before,after,symbol):
    """
    機能: 同一出口のSとAを入口行で照合し、追加・消失・共通組を分ける。
    引数: before/after(list[dict])、symbol(str)。
    返り値: dict。経路が変わるため完全な因果分解とは呼ばない。
    """
    left={entry_key(c):c for c in before if c['symbol']==symbol}
    right={entry_key(c):c for c in after if c['symbol']==symbol}
    common=left.keys()&right.keys();added=right.keys()-left.keys();removed=left.keys()-right.keys()
    previous={}
    repeated=[]
    for item in sorted(right.values(),key=lambda c:(c['session'],c['entry'])):
        prior=previous.get(item['session'])
        if entry_key(item) in added and prior and prior['net']<0 and prior['direction']==item['direction']:
            repeated.append(dict(item,previous_campaign=prior['campaign'],
                wait_seconds=item['entry_time']-prior['exit_time']))
        previous[item['session']]=item
    detail=dict(追加=summarize([right[k] for k in added]),消失=summarize([left[k] for k in removed]),
        共通変更前=summarize([left[k] for k in common]),共通変更後=summarize([right[k] for k in common]),
        追加のうち直前赤字と同方向=summarize(repeated),
        追加のうち手数料前も赤字=summarize([right[k] for k in added if right[k]['gross']<0]),
        追加のうち料金で赤字化=summarize([right[k] for k in added if right[k]['gross']>=0 and right[k]['net']<0]),
        追加最悪例=[dict(c,entry_jst=datetime.fromtimestamp(c['entry_time'],JST).isoformat(),
                          exit_jst=datetime.fromtimestamp(c['exit_time'],JST).isoformat())
                    for c in sorted((right[k] for k in added),key=lambda c:c['net'])[:3]])
    actual=sum(c['net'] for c in right.values())-sum(c['net'] for c in left.values())
    explained=detail['追加']['net']-detail['消失']['net']+detail['共通変更後']['net']-detail['共通変更前']['net']
    assert abs(actual-explained)<1e-6
    detail['差分会計一致']=True
    return detail


def main():
    """
    機能: 全結果の完成後、事前固定条件を変更せず部品効果と偏りを確認する。
    引数: なし。
    返り値: None。今回analysis領域へJSONだけを保存する。
    """
    fixed=read(WORK/'事前固定.json')
    identifiers=[c['id'] for c in fixed['catalog']]
    expected=[WORK/m/'results'/(i+'.json') for m in fixed['models'] for i in identifiers]
    missing=[str(p) for p in expected if not p.exists()]
    if missing: raise RuntimeError('全結果の完成待ち: '+str(len(missing))+'件')
    regime_path=ROOT/'work/wave_v85/analysis/方向偏り独立確認.json'
    regime_data=read(regime_path)
    assert regime_data['input_SHA256']==fixed['input_SHA256']
    endpoints={(r['session'],r['symbol']):r for r in regime_data['session_results'] if r['model']=='observed'}
    results={};cycles={};sources={str(regime_path.relative_to(ROOT)):sha(regime_path)}
    for model in fixed['models']:
        results[model]={};cycles[model]={}
        for ident in identifiers:
            path=WORK/model/'results'/(ident+'.json');ledger=WORK/model/'ledgers'/(ident+'.pkl')
            result=read(path)
            assert sha(ledger)==result['ledger_SHA256']
            with ledger.open('rb') as stream: source=pickle.load(stream)
            results[model][ident]=result
            cycles[model][ident]=extract(source,result)
            sources[str(path.relative_to(ROOT))]=sha(path)
            sources[str(ledger.relative_to(ROOT))]=result['ledger_SHA256']
    # ----------------------------------------
    # 期間、方向、場の事後分類を分け、全場平均だけで共通性を主張しない。
    summaries=[];market_groups=[]
    for model in fixed['models']:
        for ident in identifiers:
            result=results[model][ident];local=cycles[model][ident]
            for period in ('前16','後14','全30'):
                sessions=set(fixed[period])
                for symbol in SYMBOLS:
                    selected=[c for c in local if c['symbol']==symbol and c['session'] in sessions]
                    rows=[r for r in result['rows'] if r['symbol']==symbol and r['session'] in sessions]
                    value=group_summary(selected,rows)
                    saved=result['periods'][period][symbol]
                    for key in ('net','fees','gross','cycles','positive_sessions'): assert abs(value[key]-saved[key])<1e-6
                    value.update(max_drawdown=saved['max_drawdown'],
                        net_to_drawdown=value['net']/saved['max_drawdown'] if saved['max_drawdown'] else None,
                        by_direction={str(side):summarize([c for c in selected if c['direction']==side]) for side in (1,-1)})
                    summaries.append(dict(model=model,id=ident,period=period,symbol=symbol,**value))
                    for label in ('上昇','下落','横ばい'):
                        chosen={name for name in sessions if endpoints[name,symbol]['regime']==label}
                        market_groups.append(dict(model=model,id=ident,period=period,symbol=symbol,regime=label,
                            **group_summary([c for c in selected if c['session'] in chosen],[r for r in rows if r['session'] in chosen])))
    lookup={(r['model'],r['id'],r['period'],r['symbol']):r for r in summaries}
    mapping={(c['exit_id'],c['clock_id']):c['id'] for c in fixed['catalog']}
    comparisons=[];entry_analysis=[];target=[]
    for model in fixed['models']:
        pairs=[]
        for clock in ('S','A5','A1','A0'):
            for exit_id in ('T1','T2','T3','T4'):
                pairs.append(('同じ時計で出口変更',mapping['T0',clock],mapping[exit_id,clock]))
        for exit_id in ('T0','T1','T2','T3','T4'):
            for clock in ('A5','A1','A0'):
                before,after=mapping[exit_id,'S'],mapping[exit_id,clock]
                pairs.append(('同じ出口で再参加変更',before,after))
                for symbol in SYMBOLS:
                    entry_analysis.append(dict(model=model,before=before,after=after,symbol=symbol,
                        **entry_changes(cycles[model][before],cycles[model][after],symbol)))
        for kind,before,after in pairs:
            for period in ('前16','後14','全30'):
                for symbol in SYMBOLS:
                    a=lookup[model,before,period,symbol];b=lookup[model,after,period,symbol]
                    comparisons.append(dict(model=model,kind=kind,before=before,after=after,period=period,symbol=symbol,**delta(a,b)))
        # ----------------------------------------
        # 問題の夜間の改善と、それ以外29場の改善を切り分ける。
        for ident in identifiers:
            for symbol in SYMBOLS:
                before={r['session']:r for r in results[model][BASE]['rows'] if r['symbol']==symbol}
                after={r['session']:r for r in results[model][ident]['rows'] if r['symbol']==symbol}
                change={name:after[name]['net']-before[name]['net'] for name in before}
                name='2026-09-24_Night'
                target.append(dict(model=model,id=ident,symbol=symbol,
                    target_before=before[name]['net'],target_after=after[name]['net'],target_change=change[name],
                    total_change=sum(change.values()),other29_change=sum(v for k,v in change.items() if k!=name),
                    improved_sessions=sum(v>0 for v in change.values()),worsened_sessions=sum(v<0 for v in change.values()),
                    best_improvement=max(change,key=change.get),worst_deterioration=min(change,key=change.get)))
    ranks={};counts={}
    for model in fixed['models']:
        both=[ident for ident in identifiers if all(lookup[model,ident,'全30',s]['net']>0 for s in SYMBOLS)]
        ranks[model]=sorted(both,key=lambda ident:min(lookup[model,ident,'全30',s]['net_to_drawdown'] for s in SYMBOLS),reverse=True)
        dominates=[]
        for ident in identifiers:
            if ident==BASE: continue
            if all(lookup[model,ident,'全30',s]['net']>=lookup[model,BASE,'全30',s]['net']
                and lookup[model,ident,'全30',s]['profit_share']>=lookup[model,BASE,'全30',s]['profit_share']
                and lookup[model,ident,'全30',s]['positive_sessions']>=lookup[model,BASE,'全30',s]['positive_sessions']
                and lookup[model,ident,'全30',s]['max_drawdown']<=lookup[model,BASE,'全30',s]['max_drawdown'] for s in SYMBOLS): dominates.append(ident)
        counts[model]=dict(両商品合計黒字数=len(both),両商品四指標同時改善=dominates,
            前後半どちらも両商品黒字=[ident for ident in identifiers if all(lookup[model,ident,p,s]['net']>0 for p in ('前16','後14') for s in SYMBOLS)])
    output=dict(全会計照合=True,新再生=False,条件変更=False,
        注記=['全30場は既知。事後の収支下落比順位を、未知データで選ばれた最良と呼ばない。',
            '場の方向は旧診断と同じCurrentPrice始終差±0.1%。取引判断や手法切替には使わない。',
            '金額は親組の手数料後。部分利確脚を別の勝ち取引として数えない。商品間の円額は合算しない。',
            '再参加の追加・消失は新規原本行と方向による台帳比較。未来経路が変わるため因果分解や同じ波の比較とは断定しない。',
            '直前赤字と同方向の再参加は台帳事実。途中のEMAが常に同方向だったかまでは、この台帳集計から断定しない。'],
        商品別期間成績=summaries,事後相場分類=market_groups,部品差分=comparisons,
        入口追加消失=entry_analysis,問題夜間と全体=target,事前定義指標での参考順位=ranks,
        共通性の判定=counts,入力SHA256=sources,解析コードSHA256=sha(Path(__file__)))
    output['簡潔な解釈']=['第一段階20条件の両商品共通の収支/最大下落の参考首位は、観測・指定の両モデルとも元E01_G_U。全日安定を達成したという意味ではない。', 'Sのまま出口だけ狭めた4条件は、両商品とも総損失を減らした。しかし削った利益の方が大きく、全期間収支は全4条件で低下した。', 'T2_Sは2026-09-24ナイトを両商品黒字へ改善するが、残り29場は元よりTOPIX348557円、NK225128300円悪化。特定夜間の改善を一般化できない。', 'T0_A1では基準と同じ入口の94組/108組の損益は一致。新たな入口はTOPIX201組で705933円赤字、NK225178組で186160円赤字。いずれも手数料前から赤字で、単なる料金負けではない。', '追加入口のうち、直前の赤字組と同じ方向へ再参加した組もTOPIX103組で323010円赤字、NK22585組で70200円赤字。ただし途中のEMA状態不変までは確認していない。', '基準は前16と後14の両方で両商品黒字。ただし後14の最大利益日(Day+Night)を除くと両商品赤字。元候補でも安定性を断言する根拠は足りない。', '第一段階Aは損切り後も含む一律高速化。親組黒字の後だけ早める仮説を否定する結果とは扱わず、別固定の第2段階で確認する。']
    (HERE/'独立解釈.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    for model in fixed['models']:
        print(model,'参考上位',ranks[model][:3],'共通性',counts[model],flush=True)
        for ident in list(dict.fromkeys([BASE,'T3_A1']+ranks[model][:2])):
            for symbol in SYMBOLS:
                row=lookup[model,ident,'全30',symbol]
                print(ident,symbol,{k:row[k] for k in ('net','profit','loss','fees','cycles','positive_sessions','max_drawdown','best_day_removed')},flush=True)


if __name__=='__main__': main()
