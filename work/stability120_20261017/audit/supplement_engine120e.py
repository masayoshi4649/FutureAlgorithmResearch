"""全返済行と既予約新規の処理順、翌行再開、判断後gapを明確に分ける。"""

import hashlib
import json
import os
from pathlib import Path

import numpy as np

import independent_engine120e as test


HERE=Path(__file__).resolve().parent


def main() -> None:
    """
    機能: eの重要な同原row状態境界を人工だけで確認し、既主監査と結合して固定用証跡を作る。
    引数: なし。
    返り値: None。実市場・NPZ・実結果・台帳の読取と変更は零。
    """
    os.environ.pop('NUMBA_BOUNDSCHECK',None);test.E=test.load('audit120e_state_boundary',test.SOURCE)
    pending=test.fixtures.material([100,103,103,110,107,107,107,107,107,107,107,107],2,entry_end=8,close=9)
    answer=test.run(pending);orders=answer[0]
    test.check(np.any((orders[:,1]==2)&(orders[:,4]==5)&(orders[:,2]==-1)) and np.any((orders[:,1]==1)&(orders[:,4]==5)&(orders[:,2]==-1)),'旧最後買玉の返済と以前予約した売新規を同原rowで実行し途中flatで取消さない')
    cases=[]
    mid=[100,103,103,106,105,105,110,110,110,110,110,110]
    last=[100,103,103,105,104,107,110,110,110,110,110,110]
    for mode in range(3):
        args=test.fixtures.material(mid,mode,last=last,entry_end=8,close=9)
        answer=test.run(args);o=answer[0];entry=o[o[:,1]==1]
        test.check(np.any((o[:,1]==2)&(o[:,4]==5)),'全flatが実返済row五で完了')
        test.check(not np.any(entry[:,3]==5),'全flat完了原rowでは新規しない')
        new=entry[entry[:,3]==6];test.check(len(new)==1 and new[0,17]==110,'全flatrowのLast百七から翌row百十で再開可能')
        # 判断時は純益一単位、次BBOで二十四単位損失へ飛んでも実損を残す。
        gap=mid.copy();gap[5]=80
        gargs=test.fixtures.material(gap,mode,last=last,entry_end=5,close=9)
        loss=test.run(gargs);ex=loss[0][loss[0][:,1]==2]
        first=ex[ex[:,4]==5]
        test.check(len(first)==1 and first[0,16]==-24,'組又は個別の利益判断後gapは実約定損失として残す')
        cases.append(dict(mode=mode,close_fill_row=5,new_decision_row=6,new_trigger=110,gap_net=-24))
    primary=test.OUT/'カバー保持飽和救済と上下個別回転の独立人工.json'
    original=json.loads(primary.read_text(encoding='utf8'))
    test.check(original['passed'] is True and original['engine_sha256']==test.EXPECTED,'主人工の修正源と合格を委譲')
    source_names=('engine120e.py','catalog120e.py','run120e.py','runtime120e.py','register120e.py')
    paths=[test.OWNER/'recovery_e'/name for name in source_names]+[test.OWNER/'catalog120.py']
    sources={p.relative_to(test.OWNER.parents[1]).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    test.check(sources[(test.OWNER/'recovery_e'/'engine120e.py').relative_to(test.OWNER.parents[1]).as_posix()]==test.EXPECTED,'補足終端engineSHA不変')
    proof=dict(passed=True,engine_sha256=test.EXPECTED,source_SHA256=sources,primary_audit_sha256=hashlib.sha256(primary.read_bytes()).hexdigest(),audit_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),accounting_source_sha256=hashlib.sha256(Path(test.core.__file__).read_bytes()).hexdigest(),checks=dict(test.CHECKS),accounting_checks=dict(test.core.CHECKS),cases=cases,original_market_reads=0,NPZ_reads=0,result_reads=0,financial_replay=0,registry_changes=0,source_changes=0,留保='主人工に具体3993/3994及び3993/3984と鏡像を保存。初回反対極値未更新は金融前に所有者が修正。全状態を残玉込みで確認する人工監査で、新しい予測標本ではない。')
    target=HERE/'e全十八条件の独立人工と全返済境界の最終拘束.json';test.core.save(target,proof)
    print(json.dumps(dict(passed=True,engine_sha256=test.EXPECTED,sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
