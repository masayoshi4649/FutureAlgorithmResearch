"""保存会計adapterを架空八仕様だけへ接続し結果本文の初読前に確かめる。"""

import hashlib
import importlib.util
from pathlib import Path
import sys


def main() -> None:
    """
    機能: 架空足と気配を使い、46親/21準備/二脚独立会計を八仕様で確認する。
    引数: なし。
    返り値: None。人工証跡だけ保存し、実市場・cache・完成結果を使用しない。
    """
    here=Path(__file__).resolve().parent;v8=here.parent
    sys.path.insert(0,str(v8));sys.path.insert(0,str(here))
    import audit_result_v8 as subject
    import engine_v8 as engine
    spec=importlib.util.spec_from_file_location('_saved_v8_synthetic_owner',v8/'artificial_v8.py')
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    material=fixture.material();details=[]
    for method in ('ratio_mr','ols_mr'):
        for lookback in (30,60):
            for mode in (0,1):
                close=material[2]['time'][-1]-10.
                answer=engine.run_pair(*material,dict(method=method,lookback=lookback,exit_mode=mode,entry_end=close-10.,close_time=close))
                saved=dict(answer['summary'],legs=answer['leg_summary'])
                arrays={k:answer[k] for k in ('orders','parents','curve','models','preparations','positions')}
                subject.independent_pair(arrays,(material[2],material[3]),saved,close,mode)
                subject.verify_extremes_and_exits(arrays,(material[2],material[3]),mode,close)
                details.append(dict(method=method,lookback=lookback,exit_mode=mode,実親=len(answer['parents'])))
    subject.write(here/'四十六親列と二十一準備列の保存会計八仕様の純人工.json',dict(全合格=True,検査数=subject.audit.CHECKS,settings=details,監査源SHA256=hashlib.sha256((here/'audit_result_v8.py').read_bytes()).hexdigest(),市場読取=0,完成結果読取=0,cache読取=0,正式金融=0,留保='人工入力の運転だけ。既知市場の金融再実行や新たな有効性標本ではない。'))
    print(subject.audit.CHECKS)


if __name__=='__main__':main()
