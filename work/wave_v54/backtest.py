"""銘柄共通の仮説を先に固定し、14の部品対照で反証する。"""

from __future__ import annotations

from datetime import datetime,timedelta,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle

import numpy as np

from engine import execute,REASONS
from signals import methods,events,decisions,MAIN,POLICIES,GATES
from features import load_inputs_only


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
REPORT=ROOT/'アルゴリズム調査/00051_銘柄共通の境界反応とリスク効率'
module=importlib.util.spec_from_file_location('export54',HERE.parent/'wave_v52/export.py')
export=importlib.util.module_from_spec(module)
module.loader.exec_module(export)


def clean(value: object) -> object:
    """機能: 未観測値をJSONのnullへ変換し、未知とゼロを区別する。

    引数: value(object)。返り値: 有限JSONに格納可能な値(object)。
    """
    if isinstance(value,dict):
        return {k:clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):
        return [clean(v) for v in value]
    if isinstance(value,(np.integer,np.floating)):
        return clean(value.item())
    if isinstance(value,float) and not np.isfinite(value):
        return None
    return value


def save(path: Path, value: object) -> None:
    """機能: 日本語JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def freeze(configs: list) -> None:
    """機能: 利益を計算する前に主案、尺度、部品対照と棄却条件を固定する。

    引数: configs(list)。返り値: なし(None)。無記録の変更は再実行時に拒否する。
    """
    hashes={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ('signals.py','engine.py','features.py','backtest.py')}
    path=HERE/'売買仕様固定.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf8'))['コードSHA256']==hashes,'凍結後の変更です。修正理由と再検証を別途記録してください。'
        return
    save(path,dict(固定時刻=datetime.now(timezone(timedelta(hours=9))).isoformat(),主案=MAIN,条件=configs,コードSHA256=hashes,
                   入口='当場20分高安を終値が0.1ATR越えたt0で線・ATR・中点・板の過去尺度を固定。t0を含む2本連続外なら定着、後の終値が内0.1ATRへ戻れば失敗。10分以内、最初の確定だけを消費。',
                   失敗線='定着は線より内0.1ATR。失敗は分類足を含むイベント突出端より外0.1ATR。判断時距離2呼値以上0.75ATR以下。失敗からの回帰は固定中点まで2倍以上の幅が必要。',
                   供給='確認足の同価格非出来高増加行の[(bid追加−減少)−(ask追加−減少)]/近接板厚に入口符号を掛け、t0直前20分の絶対値中央値以上。尺度は有効10分以上で計算。尺度ゼロ・不明・確認足板不正は不成立。',
                   活動='確認足出来高がt0直前20分中央値以上。尺度ゼロ・不明・確認足板不正は不成立。',
                   保有='初期構造stop固定、1R進展後1R追跡、最大30分。比較Fは追跡に代えて2R固定利確。半減・逆転・追加・連敗停止なし。返済後60秒休止。',
                   R='実約定から固定線までの方向付き距離。約定が線を越えた例は即失敗返済し計画Rを会計分母として別件数表示。全組を計画Rで正規化した平均も併記。',
                   共通性='銘柄名は入口と管理に渡さない。呼値・枚数・倍率のみ商品定義。両銘柄それぞれで収支>0、平均R>0、計画R平均>0、最大利益場除外>0が必要。',
                   件数='取引30組以上かつ活動8場以上を最低の説明用件数とする。無取引を成功としない。これは統計的有意性の閾値ではない。',
                   安定='前10場/次9場/後4場のRがすべて正、最大利益場除外Rも正を別に報告。平均勝ちR/負けR>1と1枚平均勝ち/負け>1も別判定。',
                   反証='主案が不合格でも対照の最高利益へ差し替えない。部品の追加価値と主案の成立を分ける。',
                   実行='TOPIXmini5枚、NK225micro10枚。上限10/20内、全玉場内返済。判断後の次有効原本行の最終価格、費用0。',
                   試験範囲='既読23場での数値固定後照合。未知期間ではない。API取得0。'))


def summarize(accounts: list[dict]) -> dict:
    """機能: 名目金額と、各組が引き受けた固定Rの成果を別々に集計する。

    引数: accounts(list[dict])。返り値: 損益・リスク効率(dict)。
    """
    out=export.summarize(accounts)
    groups=np.asarray([g for a in accounts for g in a['risk_groups']],float).reshape(-1,11)
    rs=groups[:,4]
    profit=float(rs[rs>0].sum())
    loss=float(-rs[rs<0].sum())
    plan=groups[:,4]*groups[:,3]/groups[:,9]
    wins,losses=rs[rs>0],-rs[rs<0]
    peak=balance=drawdown=0.
    for a in sorted(accounts,key=lambda x:x['session']):
        curve=balance+a['r_curve']
        peaks=np.maximum.accumulate(np.r_[peak,curve])[1:]
        drawdown=max(drawdown,float(np.max(peaks-curve,initial=0)))
        peak=max(peak,float(np.max(curve,initial=peak)))
        balance+=a['r_net']
    out.update(r_net=float(rs.sum()),r_mean=float(rs.mean()) if len(rs) else None,r_profit=profit,r_loss=loss,
               r_pf=profit/loss if loss else None,r_payoff=float(wins.mean()/losses.mean()) if len(wins) and len(losses) else None,
               r_median=float(np.median(rs)) if len(rs) else None,r_worst=float(np.min(rs)) if len(rs) else None,
               planned_r_net=float(plan.sum()),planned_r_mean=float(plan.mean()) if len(plan) else None,
               r_without_best_session=float(rs.sum()-max([a['r_net'] for a in accounts],default=0)),
               r_without_best_trade=float(rs.sum()-rs.max(initial=0)),
               without_best_trade=out['net']-max([l[6] for a in accounts for l in a['trades']],default=0),
               r_drawdown=drawdown,gap_entries=sum(a['gap_entries'] for a in accounts),
               continuation_trades=int((groups[:,1]==1).sum()),rejection_trades=int((groups[:,1]==-1).sum()))
    out['common_pass']=bool(out['net']>0 and out['r_net']>0 and out['planned_r_net']>0 and out['without_best']>0 and out['r_without_best_session']>0 and out['cycles']>=30 and out['active_sessions']>=8)
    out['payoff_pass']=bool(out['payoff'] is not None and out['r_payoff'] is not None and out['payoff']>1 and out['r_payoff']>1)
    return out


def week(session: str) -> str:
    """機能: 開始日を月曜起点の週へ分ける。

    引数: session(str)。返り値: 週開始日(str)。
    """
    day=datetime.strptime(session[:10],'%Y-%m-%d')
    return (day-timedelta(days=day.weekday())).date().isoformat()


def ledger(account: dict) -> list[dict]:
    """機能: 原本の判断行・約定行と、全玉の固定Rを台帳へ保存する。

    引数: account(dict)。返り値: 日本語台帳(list[dict])。
    """
    groups={int(g[0]):g for g in account['risk_groups']}
    return [dict(判断時刻=export.stamp(o[0]),約定時刻=export.stamp(o[1]),判断原本行=int(o[2]),約定原本行=int(o[3]),
                 区分='新規' if o[4]==1 else '返済',方向='買い' if o[5]>0 else '売り',枚数=int(o[6]),価格=o[7],収支円=o[8],
                 理由=REASONS[int(o[9])],組=int(o[10]),実効R値幅=o[12],計画R値幅=groups[int(o[10])][9],
                 事件=int(groups[int(o[10])][2]),状態='定着' if groups[int(o[10])][1]==1 else '突破失敗',
                 返済R=groups[int(o[10])][4] if o[4]==2 else 0)
            for o in account['orders']]


def main() -> None:
    """機能: 凍結した14対照を再生し、各銘柄の効率と共通主案の成否を保存する。

    引数: なし。返り値: なし(None)。新しい成績で規則を選び直さない。
    """
    configs=methods()
    freeze(configs)
    features=pickle.loads((HERE/'特徴.pkl').read_bytes())
    inputs=load_inputs_only()
    sessions=sorted({k[0] for k in inputs})
    event_map={key:events(frame,inputs[key]['tick']) for key,frame in features.items()}
    event_counts=[]
    for key,records in event_map.items():
        save(HERE/'事件'/f'{key[0]}_{key[1]}.json',records)
        event_counts.append(dict(session=key[0],symbol=key[1],events=len(records),
                                 confirmed=sum(bool(r['kind']) for r in records),
                                 geometry=sum(bool(r.get('geometry')) for r in records),
                                 continuation=sum(r['kind']==1 and bool(r.get('geometry')) for r in records),
                                 rejection=sum(r['kind']==-1 and bool(r.get('geometry')) for r in records)))
    signal_map={}
    for key,records in event_map.items():
        for policy,_ in POLICIES:
            for gate,_ in GATES:
                signal_map[(key,policy,gate)]=decisions(records,policy,gate)
    (HERE/'判断.pkl').write_bytes(pickle.dumps(signal_map,pickle.HIGHEST_PROTOCOL))
    output,session_rows,week_rows=[],[],[]
    for config in configs:
        accounts=[]
        for key in sorted(inputs):
            qty,value=(5,1000) if key[1]=='TOPIX' else (10,10)
            signals=signal_map[(key,config['policy'],config['gate'])]
            a=execute(inputs[key],signals,config['exit']=='T',qty,value)
            a['intervals']=export.intervals(inputs[key],a)
            a['candidate_count']=len(signals)
            accounts.append(a)
            assert a['win_qty']+a['loss_qty']+a['flat_qty']==a['cycles']*qty
            export.save_csv(HERE/'台帳'/config['id']/f'{key[0]}_{key[1]}.csv',ledger(a))
            session_rows.append(dict(手法=config['id'],セッション=key[0],銘柄=key[1],利益円=a['profit'],損失円=a['loss'],収支円=a['net'],
                                     利益枚数=a['win_qty'],損失枚数=a['loss_qty'],同値枚数=a['flat_qty'],枚数差=a['win_qty']-a['loss_qty'],
                                     組数=a['cycles'],合計R=a['r_net'],平均R=a['r_net']/a['cycles'] if a['cycles'] else None,
                                     計画R合計=a['planned_r_net'],ギャップ異常約定=a['gap_entries']))
        summary,weeks,periods={},{},{}
        for symbol in ('TOPIX','NK225'):
            selected=[a for a in accounts if a['symbol']==symbol]
            summary[symbol]=summarize(selected)
            weeks[symbol]={w:summarize([a for a in selected if week(a['session'])==w]) for w in sorted({week(s) for s in sessions})}
            periods[symbol]={name:summarize([a for a in selected if a['session'] in keys]) for name,keys in [('前10場',sessions[:10]),('次9場',sessions[10:19]),('後4場',sessions[19:])]}
            summary[symbol]['period_pass']=all(v['r_net']>0 for v in periods[symbol].values())
            for w,a in weeks[symbol].items():
                week_rows.append(dict(手法=config['id'],週開始=w,銘柄=symbol,利益円=a['profit'],損失円=a['loss'],収支円=a['net'],
                                      利益枚数=a['win_qty'],損失枚数=a['loss_qty'],同値枚数=a['flat_qty'],枚数差=a['win_qty']-a['loss_qty'],
                                      組数=a['cycles'],合計R=a['r_net'],平均R=a['r_mean']))
        compact=[{k:v for k,v in a.items() if k not in ('curve','r_curve','planned_curve')} for a in accounts]
        output.append(dict(**config,accounts=compact,summary=summary,weeks=weeks,periods=periods))
        print(config['id'],[(s,summary[s]['net'],round(summary[s]['r_mean'] or 0,4),summary[s]['cycles']) for s in ('TOPIX','NK225')],flush=True)
    # ----------------------------------------
    # 部品差は同じ方向政策の内側で比較し、主案の合否を最良対照で置き換えない。
    by_id={m['id']:m for m in output}
    component=[]
    for policy,_ in POLICIES:
        for symbol in ('TOPIX','NK225'):
            values={str(gate):by_id[f'{policy}{gate}_T']['summary'][symbol] for gate,_ in GATES}
            component.append(dict(policy=policy,symbol=symbol,values=values,
                                  supply_delta=values['1']['r_net']-values['0']['r_net'],activity_delta=values['2']['r_net']-values['0']['r_net'],
                                  both_delta=values['3']['r_net']-values['0']['r_net']))
    export.save_csv(REPORT/'セッション別損益.csv',session_rows)
    export.save_csv(REPORT/'週別損益.csv',week_rows)
    save(HERE/'売買結果.json',dict(methods=output,sessions=sessions,component=component,event_counts=event_counts,
                                 meta=dict(main=MAIN,conditions=14,accounts=14*len(inputs),qty='TOPIXmini5枚/NK225micro10枚、追加なし',
                                           scope='保存済み2026-09-21〜2026-10-06の23場',current_api_requests=0,unseen=False,
                                           main_common_pass=all(by_id[MAIN]['summary'][s]['common_pass'] for s in ('TOPIX','NK225')))))


if __name__ == '__main__':
    main()
