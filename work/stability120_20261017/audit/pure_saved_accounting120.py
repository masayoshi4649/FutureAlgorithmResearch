"""完成値を読む前に、保存会計監査の独立算術を小さな人工だけで検査する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

import saved_accounting120 as accounting


HERE=Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 修正源の人工出力を保存台帳扱いとして全八mode・複数capの独立算術へ接続する。
    引数: なし。
    返り値: None。実結果・実NPZ・原市場は読まず、人工だけの小証跡を保存する。
    """
    path=HERE.parent/'recovery_b'/'engine120b.py'
    spec=importlib.util.spec_from_file_location('audit_accounting120_engine_bounds',path)
    engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
    rng=np.random.default_rng(20261017);mid=(65000+np.cumsum(rng.integers(-4,5,50))*10).astype(float)
    rows=np.arange(len(mid),dtype=np.int64);times=rows.astype(float)
    samples=[]
    for cap in (1,2,10,20):
        for mode in range(8):
            settings=dict(cap=cap,multiplier=10.,fee=11.,observed_tick=10.,session_start=0.,entry_end=40.,close_time=45.,session_end=51.)
            policy=dict(mode=mode,fraction=.000125,trail=1.)
            orders,lots,curve,summary=engine.replay(rows,times,mid,mid-10,mid+10,**settings,**policy)
            row=dict(zip(engine.SUMMARY_COLUMNS,summary.tolist()))
            row.update(realized_net=row['profit']-row['loss'],forced_loss=float(np.sum(np.maximum(-lots[lots[:,14]==9,13],0))),forced_profit=float(np.sum(np.maximum(lots[lots[:,14]==9,13],0))),trail_net=float(np.sum(lots[lots[:,14]==1,13])),long_net=float(np.sum(lots[lots[:,1]==1,13])),short_net=float(np.sum(lots[lots[:,1]==-1,13])))
            q=dict(row=rows,time=times,last=mid,bid=mid-10,ask=mid+10)
            samples.append(dict(cap=cap,mode=mode,**accounting.audit_account(q,orders,lots,curve,row,settings,policy)))
    proof=dict(passed=True,engine_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),audit_source_sha256=hashlib.sha256(Path(accounting.__file__).read_bytes()).hexdigest(),checks=dict(accounting.CHECKS),total_checks=sum(accounting.CHECKS.values()),samples=samples,result_reads=0,NPZ_reads=0,market_reads=0,financial_replay=0,留保='人工だけの接続検査。旧実金融結果の再生又は追加有効性標本ではない。')
    target=HERE/'保存会計監査の全八管理小人工_資格等価の効率化.json';accounting.save(target,proof)
    print(json.dumps(dict(passed=True,checks=sum(accounting.CHECKS.values()),sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
