"""独立選定の前16集計、数値改変拒否と段階ガードを人工だけで検査する。"""

import copy
from datetime import date,timedelta
import importlib.util
import json
import math
from pathlib import Path
import pickle

import numpy as np

import selection


def write(path: Path, value: object) -> None:
    """
    機能: 人工専用領域だけへ台帳又はJSONを保存する。
    引数: path(Path)、value(object)。
    返り値: None。正式front/backには保存しない。
    """
    assert path.resolve().is_relative_to((selection.HERE/'選定人工').resolve())
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.pkl':
        with path.open('wb') as stream:pickle.dump(value,stream,protocol=5)
    else:path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def parent_rows(config: dict, symbol: str, day: int) -> tuple:
    """
    機能: 正しい料と呼値相当の価格差を持つ人工親2本又は無取引を作る。
    引数: config(dict)、symbol(str)、day(int)。
    返り値: tuple[ndarray,dict]は人工tradesと直接算術の期待G/L。
    """
    q=config['trend_budget']*(1 if symbol=='TOPIX' else 2)
    base,value,unit=(1000.,1000.,41.8) if symbol=='TOPIX' else (50000.,10.,11.)
    fee=math.floor(q*unit+1e-8)
    deltas=(() if day==15 else ((2.,-.5) if day<12 else (.5,-1.))) if symbol=='TOPIX' else (
        () if day==15 else ((100.,-25.) if day<12 else (25.,-50.)))
    trades=np.zeros((len(deltas),16),float);profit=loss=gross_total=0.;wins=loses=0
    for i,delta in enumerate(deltas):
        gross=delta*q*value;net=gross-2*fee
        trades[i]=[i+1,0,1,2,1,q,base,base+delta,fee,fee,gross,net,10,1,1,0]
        gross_total+=gross
        if net>0:profit+=net;wins+=1
        elif net<0:loss-=net;loses+=1
    average_win=profit/wins if wins else None;average_loss=loss/loses if loses else None
    expected=dict(profit=profit,loss=loss,net=profit-loss,gross=gross_total,fees=len(deltas)*2*fee,
        campaigns=len(deltas),winning_campaigns=wins,losing_campaigns=loses,flat_campaigns=0,
        winning_lots=wins*q,losing_lots=loses*q,flat_lots=0,lots=len(deltas)*q,
        profit_share=profit/(profit+loss) if profit+loss else None,average_win=average_win,average_loss=average_loss,
        payoff=average_win/average_loss if average_win is not None and average_loss is not None else None)
    return trades,expected


def expect_reject(action: object) -> None:
    """
    機能: 数値又は段階の不正が実際に拒否されることを確認する。
    引数: action(callable)は検査対象。
    返り値: None。拒否されなければ人工検査を失敗させる。
    """
    try:action()
    except AssertionError:return
    raise AssertionError('改変又は未完の資料を受理しました')


def stage_cases() -> int:
    """
    機能: 候補集合と固定順位を手書きの独立期待値で検査する。
    引数: なし。
    返り値: intは優先段階及び順位境界の件数。
    """
    def simple(ident: str, *, campaign: int=20, active: int=8, net: float=1.,
               payoff: float|None=2., rest: float=1., share: float=.7, rms: float=.1) -> dict:
        """
        機能: 親集計と順位を分離して試す手書きの候補を作る。
        引数: ident(str)、campaign/active(int)、net/payoff/rest/share/rms(float|None)。
        返り値: dictは優先集合の人工summary。
        """
        return dict(config=dict(id=ident),periods={s:dict(campaigns=campaign,active_sessions=active,
            net=net,payoff=payoff,without_best_day=dict(net=rest),profit_share=share) for s in selection.SYMBOLS},
            stability={s:dict(downside_rms_units=rms,positive_session_rate=.75,
                worst_session_loss_units=.5,active_net_q25_units=1.) for s in selection.SYMBOLS})
    count=0
    for level,change in ((0,dict(share=.8)),(1,{}),(2,dict(rest=0.)),(3,dict(payoff=1.)),
                         (4,dict(net=0.)),(5,dict(campaign=19))):
        assert selection.choose([simple('A',**change)])['level']==level;count+=1
    assert selection.choose([simple('A',active=7)])['level']==5;count+=1
    assert selection.choose([simple('A',payoff=None)])['level']==3;count+=1
    result=selection.choose([simple('大収益',net=100000.,rms=2.),simple('安定',net=100.,rms=.1)])
    assert result['selected']=='安定';count+=1
    result=selection.choose([simple('80%対象',share=.8,rms=2.),simple('低損失',share=.799999,rms=.01)])
    assert result['selected']=='80%対象' and result['level']==0;count+=1
    assert selection.choose([simple('B'),simple('A')])['selected']=='A';count+=1
    return count


def main() -> None:
    """
    機能: 人工全38前16の集計と改変拒否を検査し、正式結果を読まず証跡保存する。
    引数: なし。
    返り値: Noneは選定コード指紋付き人工合格証。
    """
    spec=importlib.util.spec_from_file_location('選定人工95の条件読取',selection.WORK/'catalog.py')
    catalog=importlib.util.module_from_spec(spec);spec.loader.exec_module(catalog)
    configs=catalog.catalog();sessions=[str(date(2000,1,3)+timedelta(days=i))+'_Day' for i in range(16)]
    generation=1;base=selection.HERE/'選定人工'/f'{generation:05d}'
    while base.exists():generation+=1;base=selection.HERE/'選定人工'/f'{generation:05d}'
    fixed=dict(条件=configs,前16=sessions)
    first_prices={(session,symbol):(1000. if symbol=='TOPIX' else 50000.) for session in sessions for symbol in selection.SYMBOLS}
    summaries=[];paths=[Path(__file__),Path(selection.__file__),selection.WORK/'catalog.py',
        selection.WORK/'research.py',selection.WORK/'セッション安定性の事前評価.json']
    for config in configs:
        ledgers={};rows=[]
        for day,session in enumerate(sessions):
            for symbol in selection.SYMBOLS:
                trades,expected=parent_rows(config,symbol,day)
                ledgers[session,symbol]=dict(trades=trades)
                rows.append(dict(session=session,symbol=symbol,**expected))
        summary=selection.summarize(config,rows,sessions,first_prices);summaries.append(summary)
        ledger_path=base/'front/ledgers'/(config['id']+'.pkl');write(ledger_path,ledgers)
        result=dict(config=config,rows=rows,periods={'前16':summary['periods']},stability=summary['stability'],ledger_SHA256=selection.sha(ledger_path))
        result_path=base/'front/results'/(config['id']+'.json');write(result_path,result)
        paths.extend((ledger_path,result_path))
    actual=selection.inspect(base,fixed,first_prices)
    # ----------------------------------------
    # 全16分母・無取引除外・親数と金額は、固定した手算値へ一致させる。
    sample=next(result for result in actual if result['config']['id']=='P0_R0')
    p,s=sample['periods']['TOPIX'],sample['stability']['TOPIX']
    assert p['profit']==193980 and p['loss']==82020 and p['net']==111960 and p['campaigns']==30
    assert p['active_sessions']==15 and p['without_best_day']['net']==101296
    assert s['comparison_cap']==10 and s['session_count']==16 and s['no_trade_sessions']==1
    assert s['positive_session_rate']==12/15 and s['worst_session_loss_yen']==5336
    selection.close(s['downside_rms_units'],math.sqrt(3*(5336/10000)**2/16),'手算RMS')
    selection.close(s['active_net_q25_units'],10664/10000,'手算q25')
    chosen=selection.choose(actual)
    assert chosen['selected']=='P3_R3_N_Q4' and chosen['level']==1 and len(chosen['eligible'])==38
    # ----------------------------------------
    # 数字を増減しても、指紋だけ更新すれば通るという経路を拒絶する。
    target=base/'front/results/P0_R0.json';original=selection.read(target);rejections=0
    for field in ('profit','loss','net','campaigns'):
        altered=copy.deepcopy(original);altered['rows'][0][field]+=1
        write(target,altered);expect_reject(lambda:selection.inspect(base,fixed,first_prices));rejections+=1
        write(target,original)
    for field in ('downside_rms_units','positive_session_rate','worst_session_loss_units','active_net_q25_units'):
        altered=copy.deepcopy(original);altered['stability']['TOPIX'][field]+=.001
        write(target,altered);expect_reject(lambda:selection.inspect(base,fixed,first_prices));rejections+=1
        write(target,original)
    missing=base/'front/results/P0_R0.退避';target.rename(missing)
    expect_reject(lambda:selection.guard(base,fixed));missing.rename(target);rejections+=1
    back=base/'back/results/後15人工.json';write(back,dict(人工=True))
    expect_reject(lambda:selection.guard(base,fixed));rejections+=1
    # backが存在する最後の人工状態を残し、根の正式データには触れない。
    paths.append(back);boundaries=stage_cases()
    proof=dict(全合格=True,人工条件数=38,人工前16口座数=1216,候補集合38と数量比較=True,
        手算親金額及び全16RMSと活動黒字率一致=True,改変及び段階不正拒否=rejections,
        優先集合及び固定順位人工=boundaries,根score及びselect呼出=0,正式結果閲覧=0,正式新売買実行=0,
        SHA256={str(path.relative_to(selection.ROOT)):selection.sha(path) for path in paths},API取得=0,実注文=0)
    path=selection.HERE/'独立前16選定の親会計と手算順位及び数値改変と段階拒否の人工.json'
    path.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in proof.items() if k!='SHA256'},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
