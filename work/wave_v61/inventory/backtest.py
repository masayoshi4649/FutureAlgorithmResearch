"""場内在庫180条件を3価格モデルで再生し、軽量集計と独立台帳を保存する。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

import engine
from features import load_accounts


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent.parent / 'wave_v60'
CODE_FILES = ('accounting.py','features.py','engine.py','check_engine.py','backtest.py')
FAMILIES = ['有限寿命の往復格子','在庫中心移動と返済優先','逆行追加停止と整理','含み益方向への追加','期限付き逆行カバー']
PRICE_MODES = ('quote','mid','passive')


def digest(path: Path) -> str:
    """機能: 大きい原本を分割してSHA256で固定する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(4*1024*1024):
            result.update(block)
    return result.hexdigest()


def clean(value: object) -> object:
    """機能: NumPy型と非有限値を日本語JSONへ保存できる値に変換する。

    引数: value(object)。返り値: 変換済み値(object)。
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
    """機能: 有限値だけを持つ日本語JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def methods() -> list[dict]:
    """機能: 損益を見る前に合意した180条件と三つの注文モデルを列挙する。

    引数: なし。返り値: 540モデルの設定(list[dict])。主5条件を固定する。
    """
    result = []
    for family,label in enumerate(FAMILIES):
        for minutes in (5,15,30,60,120,240):
            for width_id,fraction in (('D075',.00075),('D125',.00125)):
                for activity,topcap,steps,cooldown in ((0,2,2,300),(1,5,5,60),(2,10,5,0)):
                    condition = f'I{family+1}_H{minutes:03d}_{width_id}_A{activity}'
                    for mode,price_mode in enumerate(PRICE_MODES):
                        result.append(dict(id=f'{condition}_{price_mode}',condition_id=condition,family=f'I{family+1}',
                            name=label,price_mode=price_mode,primary=minutes==60 and width_id=='D075' and activity==1 and mode==0,
                            config=dict(family=family,minutes=minutes,fraction=fraction,activity=activity,
                                        top_cap=topcap,steps=steps,cooldown_seconds=cooldown,mode=mode)))
    return result


def freeze(configs: list[dict]) -> dict:
    """機能: コード・子仕様・親仕様・元入力を損益前に固定し、以後の差分を拒否する。

    引数: configs(list[dict])。返り値: 固定記録(dict)。
    """
    fixed = dict(コードSHA256={n:digest(HERE/n) for n in CODE_FILES},
        入力SHA256={n:digest(SOURCE/n) for n in ('inputs.pkl','quotes.pkl')},
        親仕様SHA256=digest(HERE.parent/'調査仕様.json'),子仕様SHA256=digest(HERE/'個別仕様.json'),条件=configs)
    path = HERE/'売買仕様固定.json'
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf8'))
        assert {k:saved[k] for k in fixed} == fixed, '損益前固定後にコード・入力・仕様が変化しました'
        return saved
    fixed.update(固定時刻=datetime.now(timezone.utc).isoformat(),実データ損益未計算=True,API取得数=0,
                 留意='元資料25場は既知。事前の主条件と事後の参考順位を区別する')
    save(path,fixed)
    return fixed


def account(data: dict, result: tuple, config: dict) -> dict:
    """機能: 全玉が同じ場で返済されたことと、純収支・資産・費用・期限を照合する。

    引数: data(dict)、result(tuple)、config(dict)。返り値: 当場の台帳を除く会計(dict)。
    """
    orders,trades,curve,mid_curve,risks,resets,pos,pending,book,cancelled,counts = result
    assert not np.any(pos[:,1]) and not np.any(pending[:,0])
    np.testing.assert_allclose(trades[:,18],trades[:,15]-trades[:,16]-trades[:,17],atol=1e-7)
    np.testing.assert_allclose(orders[:,13].sum(),trades[:,16:18].sum(),atol=1e-6)
    np.testing.assert_allclose(curve[-1],trades[:,18].sum(),atol=1e-5)
    np.testing.assert_allclose(curve[-1],book[2]-book[3]-book[1],atol=1e-5)
    gross, net = trades[:,15],trades[:,18]
    holding = trades[:,22]
    core = trades[trades[:,2]==0]
    late = np.maximum(0.,core[:,22]*60-config['config']['minutes']*60)
    path,mpath = np.r_[0.,curve],np.r_[0.,mid_curve]
    entries,exits = orders[orders[:,9]==1],orders[orders[:,9]==2]
    delayed = exits[(exits[:,15]==1)]
    return dict(session=data['session'],symbol=data['symbol'],week=data['week'],price_mode=config['price_mode'],
        gross_profit=float(gross[gross>0].sum()),gross_loss=float(-gross[gross<0].sum()),gross_pnl=float(gross.sum()),
        fees=float(orders[:,13].sum()),net=float(curve[-1]),unrealized_start=0.,unrealized_end=0.,
        unrealized_change=0.,equity_change=float(curve[-1]),
        closed_net_profit=float(net[net>0].sum()),closed_net_loss=float(-net[net<0].sum()),
        cycles=len(trades),wins=int((net>0).sum()),losses=int((net<0).sum()),
        win_qty=int(trades[net>0,4].sum()),loss_qty=int(trades[net<0,4].sum()),flat_qty=int(trades[net==0,4].sum()),
        gross_win_qty=int(trades[gross>0,4].sum()),gross_loss_qty=int(trades[gross<0,4].sum()),
        order_count=len(orders),entry_order_count=len(entries),exit_order_count=len(exits),
        candidate_count=int(counts[0]),fifo_candidate_count=int(counts[1]),cover_scheduled_count=int(counts[2]),
        cancelled_entry_count=len(cancelled),
        equity_min=float(path.min()),equity_max=float(path.max()),
        drawdown=float(np.max(np.maximum.accumulate(path)-path)),
        mid_equity_min=float(mpath.min()),mid_equity_max=float(mpath.max()),
        mid_drawdown=float(np.max(np.maximum.accumulate(mpath)-mpath)),
        max_long_qty=int(risks[:,0].max()),max_short_qty=int(risks[:,1].max()),
        max_gross_qty=int(np.max(risks[:,0]+risks[:,1])),max_abs_net_qty=int(np.max(abs(risks[:,0]-risks[:,1]))),
        max_losing_inventory=float(-min(0.,risks[:,4].min())),
        max_long_unrealized_loss=float(-min(0.,risks[:,2].min())),max_short_unrealized_loss=float(-min(0.,risks[:,3].min())),
        hold_median_minutes=float(np.median(holding)) if len(holding) else None,
        hold_mean_minutes=float(holding.mean()) if len(holding) else None,
        hold_p90_minutes=float(np.quantile(holding,.9)) if len(holding) else None,
        max_hold_minutes=float(holding.max()) if len(holding) else None,
        deadline_overrun_count=int((late>1e-6).sum()),
        max_deadline_overrun_seconds=float(late.max()) if len(late) else 0.,
        forced_exit_delay_seconds=float(np.max(delayed[:,4]-(data['limits'][0]-60.))) if len(delayed) else None,
        last_exit_time=float(exits[-1,4]) if len(exits) else None,
        holding_values=holding.tolist(),
        ledger_path=f'ledger/{config["id"]}.pkl',ledger_key=[data['session'],data['symbol']])


def summarize(accounts: list[dict]) -> dict:
    """機能: 場内完結の損益と累積資産の下落を、全場の極値・場内DDから正確に集計する。

    引数: accounts(list[dict])。返り値: 集計(dict)。実保有統計は返済玉単位。
    """
    sums = ('gross_profit','gross_loss','gross_pnl','fees','net','closed_net_profit','closed_net_loss',
            'cycles','wins','losses','win_qty','loss_qty','flat_qty','order_count','entry_order_count','exit_order_count',
            'candidate_count','fifo_candidate_count','cover_scheduled_count','cancelled_entry_count','deadline_overrun_count')
    out = {name:sum(a[name] for a in accounts) for name in sums}
    out.update(sessions=len(accounts),active_sessions=sum(a['order_count']>0 for a in accounts),
        positive_sessions=sum(a['net']>0 for a in accounts),negative_sessions=sum(a['net']<0 for a in accounts),
        without_best=out['net']-max(0.,max((a['net'] for a in accounts),default=0.)),
        worst_session=min((a['net'] for a in accounts),default=0.),
        win_rate=out['wins']/out['cycles'] if out['cycles'] else None,
        pf=out['closed_net_profit']/out['closed_net_loss'] if out['closed_net_loss'] else None,
        gross_pf=out['gross_profit']/out['gross_loss'] if out['gross_loss'] else None)
    avgwin=out['closed_net_profit']/out['win_qty'] if out['win_qty'] else None
    avgloss=out['closed_net_loss']/out['loss_qty'] if out['loss_qty'] else None
    out.update(win_per_lot=avgwin,loss_per_lot=avgloss,payoff=avgwin/avgloss if avgwin is not None and avgloss else None)
    balance=peak=dd=mpeak=mdd=0.
    for a in sorted(accounts,key=lambda x:x['session']):
        dd=max(dd,a['drawdown'],peak-(balance+a['equity_min']))
        mdd=max(mdd,a['mid_drawdown'],mpeak-(balance+a['mid_equity_min']))
        peak=max(peak,balance+a['equity_max'])
        mpeak=max(mpeak,balance+a['mid_equity_max'])
        balance+=a['net']
    out.update(drawdown=dd,mid_drawdown=mdd)
    for name in ('max_long_qty','max_short_qty','max_gross_qty','max_abs_net_qty','max_losing_inventory',
                 'max_long_unrealized_loss','max_short_unrealized_loss','max_deadline_overrun_seconds'):
        out[name]=max((a[name] for a in accounts),default=0)
    holding=np.asarray([v for a in accounts for v in a['holding_values']])
    out.update(hold_median_minutes=float(np.median(holding)) if len(holding) else None,
        hold_mean_minutes=float(holding.mean()) if len(holding) else None,
        hold_p90_minutes=float(np.quantile(holding,.9)) if len(holding) else None,
        max_hold_minutes=float(holding.max()) if len(holding) else None)
    return out


def main() -> None:
    """機能: 合成と親GO後、固定した全モデルを一度計算し台帳を逐次保存する。

    引数: CLI --freeze-only/--run。返り値: なし(None)。外部取得や実注文は行わない。
    """
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--freeze-only',action='store_true')
    group.add_argument('--run',action='store_true')
    args=parser.parse_args()
    configs=methods()
    frozen=freeze(configs)
    if args.freeze_only:
        print('180条件×3モデルの損益前固定が完了しました',flush=True)
        return
    assert not (HERE/'集計結果.json').exists(), '既に結果があります。条件を変えて繰り返しません'
    data=load_accounts()
    ledger_dir=HERE/'ledger'
    ledger_dir.mkdir(exist_ok=True)
    output=[]
    for number,config in enumerate(configs,1):
        accounts,ledgers=[],{}
        for key,source in data.items():
            spec=config['config']
            cap=spec['top_cap']*(1 if source['symbol']=='TOPIX' else 2)
            value,fee=(1000.,418) if source['symbol']=='TOPIX' else (10.,110)
            fields={name:source[name] for name in ('times','seqs','mid','bid','ask','sessions','limits','events','tick')}
            knobs={name:spec[name] for name in ('family','steps','mode','fraction','minutes','cooldown_seconds')}
            raw=engine.replay(**fields,**knobs,cap=cap,value=value,fee_tenths=fee)
            accounts.append(account(source,raw,config))
            ledgers[key]=dict(orders=raw[0],trades=raw[1],resets=raw[5],cancellations=raw[9],counts=raw[10])
        summary,weeks={},{}
        for symbol in ('TOPIX','NK225'):
            selected=[a for a in accounts if a['symbol']==symbol]
            summary[symbol]=summarize(selected)
            weeks[symbol]={w:summarize([a for a in selected if a['week']==w]) for w in sorted({a['week'] for a in selected})}
            assert abs(summary[symbol]['net']-(summary[symbol]['gross_profit']-summary[symbol]['gross_loss']-summary[symbol]['fees']))<1e-5
        ledger_path=ledger_dir/f'{config["id"]}.pkl'
        ledger_path.write_bytes(pickle.dumps(ledgers,protocol=pickle.HIGHEST_PROTOCOL))
        compact=[{k:v for k,v in a.items() if k!='holding_values'} for a in accounts]
        model=dict(**config,accounts=compact,summary=summary,weeks=weeks,
                   ledger_path=f'ledger/{ledger_path.name}',ledger_sha256=digest(ledger_path))
        output.append(model)
        with (HERE/'中間集計.jsonl').open('a',encoding='utf8') as destination:
            destination.write(json.dumps(clean(model),ensure_ascii=False,allow_nan=False)+'\n')
        if config['primary'] or number%18==0:
            print(number,config['id'],[(s,summary[s]['net'],summary[s]['fees'],summary[s]['drawdown']) for s in ('TOPIX','NK225')],flush=True)
    freeze(configs)
    save(HERE/'集計結果.json',dict(methods=output,sessions=sorted({k[0] for k in data}),
        meta=dict(conditions=180,price_models=3,replays=540,accounts=27000,known_sessions=25,unseen=False,
            main_ids=[m['id'] for m in configs if m['primary']],order_columns=engine.ORDER_COLUMNS,
            trade_columns=engine.TRADE_COLUMNS,reasons=engine.REASONS,price_models_independent=True,
            freeze_sha256=digest(HERE/'売買仕様固定.json'),input_sha256=frozen['入力SHA256'],
            code_sha256=frozen['コードSHA256'],current_api_requests=0,
            cycle_definition='cyclesは返済玉数。全玉返済を1組とする方向性枝の組数と異なり、coverも別玉に数える。',
            passive_fifo_assumption='I2の待機指値は通過約定時に反対玉FIFOへ割当可能とするネット在庫モデル。実APIでの対象玉固定・取消競合の再現ではない。主評価はquote。',
            session_pnl='場内全返済。純収支=返済粗利益−返済粗損失−全新規返済費用。含み込みDDを別計算。',
            hold_definition='返済玉単位。元coreは新規約定からHで返済判断し、次観測/約定までの超過を残す。coverは別期限。',
            quantity_definition='勝敗枚数は入口出口費用控除後に返済した累計。保有上限ではない。')))
    print('全540モデルの保存が完了しました',flush=True)


if __name__=='__main__':
    main()
