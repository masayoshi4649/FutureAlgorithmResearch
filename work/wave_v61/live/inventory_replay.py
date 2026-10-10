"""取得前固定の場内在庫候補を現在原本へ適用し、既知前半と追加区間を分ける。"""

import argparse
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
INVENTORY=HERE.parent/'inventory'
sys.path.insert(0,str(INVENTORY))
import backtest
import engine
import features


def snapshot(result: tuple, count: int, times: np.ndarray, value: float) -> dict:
    """機能: 同じ一回の再生の任意境界で、実現・発生費用・全含みを切り分ける。

    引数: result(tuple)、count(int)は観測済み行数、times(ndarray)、value(float)は円倍率。返り値: 境界会計(dict)。
    """
    orders,trades,curve,mid_curve,risks=result[:5]
    assert 0<=count<=len(curve)
    observed=orders[orders[:,2]<count]
    legs=trades[trades[:,8]<count]
    gross=float(observed[:,14].sum())
    fee=float(observed[:,13].sum())
    cash=float((-observed[:,10]*observed[:,11]*observed[:,12]*value-observed[:,13]).sum())
    unrealized=float(risks[count-1,2:4].sum()) if count else 0.
    net=float(curve[count-1]) if count else 0.
    np.testing.assert_allclose(gross-fee+unrealized,net,atol=1e-5)
    return dict(観測行数=count,保存時計=float(times[count-1]) if count else None,
        realized_gross_pnl=gross,fees_incurred=fee,unrealized=unrealized,net=net,
        gross_realized=gross,fees=fee,cash=cash,realized_after_incurred_fees=gross-fee,
        long_qty=int(risks[count-1,0]) if count else 0,short_qty=int(risks[count-1,1]) if count else 0,
        gross_qty=int(risks[count-1,:2].sum()) if count else 0,
        entry_order_count=int((observed[:,9]==1).sum()),exit_order_count=int((observed[:,9]==2).sum()),
        closed_lots=len(legs))


def partial_account(ready: dict, quote: dict, config: dict, known_count: int) -> dict:
    """機能: 当場の固定規則を一度だけ再生し、既知前半を引いた追加区間の資産変化を得る。

    引数: ready/quote/config(dict)、known_count(int)。返り値: 残玉と各境界会計を含む辞書(dict)。
    """
    np.testing.assert_array_equal(ready['seq'],quote['seq'])
    np.testing.assert_array_equal(ready['time_s'],quote['time_s'])
    assert 0<=known_count<=len(ready['seq'])
    code=ready['symbol']
    knobs=config['config']
    cap=knobs['top_cap']*(1 if code=='TOPIX' else 2)
    value,fee=(1000.,418) if code=='TOPIX' else (10.,110)
    if not len(ready['seq']):
        empty=dict(観測行数=0,保存時計=None,realized_gross_pnl=0.,fees_incurred=0.,unrealized=0.,net=0.,
                   gross_realized=0.,fees=0.,cash=0.,realized_after_incurred_fees=0.,
                   long_qty=0,short_qty=0,gross_qty=0,entry_order_count=0,exit_order_count=0,closed_lots=0)
        return dict(session=ready['session'],symbol=code,id=config['id'],price_mode=config['price_mode'],
                    状態='有効原本なし。準備待ち',セッション期首=empty,既知境界=empty,現在末尾=empty,
                    追加区間=dict(gross_realized=0.,fees=0.,cash=0.,unrealized=0.,net=0.,
                        realized_after_incurred_fees=0.,valid_rows=0,long_qty_start=0,long_qty_end=0,short_qty_start=0,short_qty_end=0),
                    既知有効行数=known_count,追加区間純変化=0.,
                    net=0.,orders=[],trades=[],open_positions=[],pending=[])
    fields={name:knobs[name] for name in ('family','steps','mode','fraction','minutes','cooldown_seconds')}
    material=features.direction_events(ready,quote)
    raw=engine.replay(times=ready['time_s'],seqs=ready['seq'],mid=quote['mid'],bid=quote['bid'],ask=quote['ask'],
        sessions=np.zeros(len(ready['seq']),np.int64),limits=np.array([ready['limit']]),events=material,
        **fields,cap=cap,value=value,tick=ready['tick'],fee_tenths=fee,finish=False)
    start=snapshot(raw,0,ready['time_s'],value)
    known=snapshot(raw,known_count,ready['time_s'],value)
    current=snapshot(raw,len(ready['seq']),ready['time_s'],value)
    additional=dict(realized_gross_pnl=current['realized_gross_pnl']-known['realized_gross_pnl'],
        fees_incurred=current['fees_incurred']-known['fees_incurred'],
        unrealized_change=current['unrealized']-known['unrealized'],net=current['net']-known['net'],
        entry_order_count=current['entry_order_count']-known['entry_order_count'],
        exit_order_count=current['exit_order_count']-known['exit_order_count'],
        closed_lots=current['closed_lots']-known['closed_lots'],
        observed_rows=len(ready['seq'])-known_count)
    additional.update(gross_realized=additional['realized_gross_pnl'],fees=additional['fees_incurred'],
        cash=current['cash']-known['cash'],realized_after_incurred_fees=additional['realized_gross_pnl']-additional['fees_incurred'],
        unrealized=additional['unrealized_change'],valid_rows=len(ready['seq'])-known_count,
        long_qty_start=known['long_qty'],long_qty_end=current['long_qty'],
        short_qty_start=known['short_qty'],short_qty_end=current['short_qty'])
    np.testing.assert_allclose(additional['net'],additional['realized_gross_pnl']-additional['fees_incurred']+additional['unrealized_change'],atol=1e-5)
    open_positions=[]
    for slot,pos in enumerate(raw[6]):
        if pos[1]<=0:
            continue
        mark=engine.liquidation_price(int(pos[0]),len(ready['seq'])-1,quote['mid'],quote['bid'],quote['ask'],knobs['mode'])
        open_positions.append(dict(段番号=slot,side=int(pos[0]),qty=int(pos[1]),role='cover' if pos[9] else 'core',
            entry_price=float(pos[2]),entry_fee=float(pos[3]),entry_index=int(pos[4]),entry_time=float(ready['time_s'][int(pos[4])]),
            liquidation_price=float(mark),unrealized=float(pos[0]*pos[1]*(mark-pos[2])*value),将来返済費用未計上=True))
    np.testing.assert_allclose(sum(p['unrealized'] for p in open_positions),current['unrealized'],atol=1e-5)
    path=np.r_[0.,raw[2]]
    return dict(session=ready['session'],symbol=code,id=config['id'],price_mode=config['price_mode'],config=knobs,
        状態='取得原本の末尾で停止。未決済を仮想清算しない',セッション期首=start,既知境界=known,現在末尾=current,
        追加区間=additional,net=current['net'],additional_net=additional['net'],
        既知有効行数=known_count,追加区間純変化=additional['net'],
        realized_gross_pnl=current['gross_realized'],fees_incurred=current['fees'],unrealized_end=current['unrealized'],
        long_qty=current['long_qty'],short_qty=current['short_qty'],
        drawdown=float(np.max(np.maximum.accumulate(path)-path)),
        open_positions=open_positions,pending=raw[7][raw[7][:,0]!=0].tolist(),
        orders=raw[0].tolist(),trades=raw[1].tolist(),resets=raw[5].tolist(),cancellations=raw[9].tolist(),
        全場仮想清算=False,有効方向公開数=int(material[:,3].sum()),最終行未約定予約数=int((raw[7][:,0]!=0).sum()))


def freeze_wrapper() -> dict:
    """機能: 現在資料を取得する前に接続会計実装と元エンジンの固定を照合する。

    引数: なし。返り値: 固定記録(dict)。ネットワーク・現在入力の読取りを行わない。
    """
    backtest.freeze(backtest.methods())
    audit_path=HERE/'在庫途中会計の合成監査.json'
    assert json.loads(audit_path.read_text(encoding='utf8'))['合格']
    current=dict(wrapper_sha256=backtest.digest(Path(__file__)),
                 strategy_freeze_sha256=backtest.digest(INVENTORY/'売買仕様固定.json'),
                 synthetic_sha256=backtest.digest(audit_path))
    path=HERE/'在庫現在実装固定.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf8'))==current
    else:
        backtest.save(path,current)
    return current


def main() -> None:
    """機能: 親GO後の固定候補をquote/midで再生し、既知前半を別表示する。

    引数: CLI --freeze-only又は--run。返り値: なし(None)。API取得や実注文を一切行わない。
    """
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--freeze-only','--prepare',dest='freeze_only',action='store_true')
    group.add_argument('--run',action='store_true')
    args=parser.parse_args()
    fixed=freeze_wrapper()
    if args.freeze_only:
        print('現在原本を読まずに在庫の現在確認実装を固定しました')
        return
    path=HERE/'現在在庫の途中損益.json'
    assert not path.exists(),'現在確認は既に完了しています。候補を変え再実行しません'
    selection=json.loads((HERE/'候補固定.json').read_text(encoding='utf8'))
    before_fetch=json.loads((HERE/'取得直前照合.json').read_text(encoding='utf8'))
    assert backtest.digest(HERE/'候補固定.json')==before_fetch['候補SHA']
    assert backtest.digest(INVENTORY/'集計結果.json')==selection['sources']['inventory']
    selected=selection['selected']['inventory']
    condition=selected['id']
    configs=[m for m in backtest.methods() if m['condition_id']==condition and m['price_mode'] in ('quote','mid')]
    assert len(configs)==2
    inputs=pickle.loads((HERE/'inputs.pkl').read_bytes())
    quotes=pickle.loads((HERE/'quotes.pkl').read_bytes())
    manifest=json.loads((HERE/'既知前半と追加区間.json').read_text(encoding='utf8'))
    boundary={(a['セッション'],a['銘柄']):int(a['既知有効行数']) for a in manifest['照合']}
    assert set(inputs)==set(quotes)==set(boundary)
    accounts=[partial_account(inputs[key],quotes[key],config,boundary[key]) for key in sorted(inputs) for config in configs]
    freeze_wrapper()
    backtest.save(path,dict(選定候補=selected,wrapper_fixed=fixed,accounts=accounts,既知前半と追加区間=manifest,
        入力SHA256={name:backtest.digest(HERE/name) for name in ('inputs.pkl','quotes.pkl')},
        候補固定SHA256=backtest.digest(HERE/'候補固定.json'),注文列=engine.ORDER_COLUMNS,返済列=engine.TRADE_COLUMNS,
        会計='追加区間net=現在net−既知境界net。実現粗損益差−発生費用差＋含み差に一致。残玉の未発生返済費用は課さない。',
        限界='既知前半を未知の検証に数えない。quote主とmid参考は独立再生。ラージ気配で小型商品の実約定を保証しない。'))
    print(json.dumps(dict(完了=True,口座数=len(accounts),候補=condition,
                         追加区間=[(a['symbol'],a['price_mode'],a.get('additional_net',0.)) for a in accounts]),ensure_ascii=False))


if __name__=='__main__':
    main()
