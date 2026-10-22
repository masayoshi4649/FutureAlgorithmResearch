"""完成した四十八条件を、総額より各場の安定を先にして再集計する。"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

import plan120 as P


def metrics(rows: list[dict]) -> dict:
    """
    機能: 同一商品の全四十場から活動と利益依存を測る。
    引数: rows(list[dict])は同一政策・同一商品の保存小会計40行。
    返り値: dictは場数、費用後損益、上位3場除外、玉別損益と在庫リスク。
    """
    assert len(rows)==40
    net=np.asarray([r['net'] for r in rows])
    positive=net[net>0]
    profit=sum(r['profit'] for r in rows)
    loss=sum(r['loss'] for r in rows)
    wins=sum(r['wins'] for r in rows)
    losses=sum(r['losses'] for r in rows)
    return dict(net=float(net.sum()),black=int(np.count_nonzero(net>0)),red=int(np.count_nonzero(net<0)),
        inactive=sum(r['entries']==0 for r in rows),zero_active=sum(r['entries']>0 and r['net']==0 for r in rows),
        median=float(np.median(net)),mean=float(np.mean(net)),worst=float(net.min()),best=float(net.max()),
        top3_removed=float(net.sum()-np.sort(positive)[-3:].sum()),
        mean_positive=float(np.mean(positive)) if len(positive) else None,
        mean_abs=float(np.mean(np.abs(net))),profit=profit,loss=loss,fees=sum(r['fees'] for r in rows),
        gross=float(net.sum()+sum(r['fees'] for r in rows)),
        closed_lots=sum(r['closed_lots'] for r in rows),wins=wins,losses=losses,
        mean_win=profit/wins if wins else None,mean_loss=loss/losses if losses else None,
        profit_share=profit/(profit+loss) if profit+loss else None,
        unclosed=sum(r['unclosed'] for r in rows),max_long=max(r['max_long'] for r in rows),
        max_short=max(r['max_short'] for r in rows),max_drawdown=max(r['max_drawdown'] for r in rows),
        forced_loss=sum(r['forced_loss'] for r in rows),forced_profit=sum(r['forced_profit'] for r in rows),
        trail_net=sum(r['trail_net'] for r in rows),long_net=sum(r['long_net'] for r in rows),short_net=sum(r['short_net'] for r in rows))


def main(path: Path, expected: str, output: Path | None = None) -> None:
    """
    機能: 完成結果を同bytes保全して一読し、全候補の同じ尺度を保存する。
    引数: path(Path)は完成結果、expected(str)は完成時SHA256、output(Path|None)は別所有先。
    返り値: None。新しい金融・原市場追加読取・独立有効性根拠は0。
    """
    payload=path.read_bytes()
    assert hashlib.sha256(payload).hexdigest()==expected
    out=P.HERE/'root_owned' if output is None else output
    out.mkdir(exist_ok=False)
    (out/path.name).write_bytes(payload)
    result=json.loads(payload)
    assert len(result['runs'])==len(result['specs'])*80
    rows=[]
    for spec in result['specs']:
        m={symbol:metrics([r for r in result['runs'] if r['method']==spec['id'] and r['symbol']==symbol])
            for symbol in ('TOPIX','NK225')}
        qualified=all(v['net']>0 and v['median']>0 and v['top3_removed']>0 and v['unclosed']==0 for v in m.values())
        rows.append(dict(id=spec['id'],name=spec['name'],metrics=m,qualified=qualified,
            weakest_black=min(v['black'] for v in m.values()),
            weakest_median=min(v['median']/max(v['mean_abs'],1.) for v in m.values())))
    rows.sort(key=lambda r:(-int(r['qualified']),-r['weakest_black'],-r['weakest_median'],r['id']))
    P.save(out/'全条件の場内安定指標.json',dict(source_sha256=expected,rankings=rows,
        qualification_count=sum(r['qualified'] for r in rows),financial_replay=0,
        意味='既知40場の参考序列。無取引を勝ちにせず、利益の大きさだけで選ばない。'))
    wanted=['HEDGE_S2_T1']+[r['id'] for r in rows[:3]]
    print(json.dumps(dict(qualified=sum(r['qualified'] for r in rows),
        both_net_positive=sum(all(v['net']>0 for v in r['metrics'].values()) for r in rows),
        examples=[r for r in rows if r['id'] in wanted]),ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--result',type=Path,required=True)
    parser.add_argument('--sha',required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    main(args.result,args.sha,args.output)
