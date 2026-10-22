"""旧核未参加時の一回追加を、未来の旧取引を使わない人工例で監査する。"""

import copy
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
os.environ["NUMBA_CACHE_DIR"]=str(HERE/"jit_participation")
sys.path.insert(0,str(WORK))
import participation131 as addon
import audit_engine131 as helper


def arguments(data, core_starts=None, style=0):
    """
    機能: 独立人工素材を一回追加核の引数へ対応する。
    引数: data(dict)、core_starts(ndarray又はNone)、style(int)は人工資料と当行旧新規数。
    返り値: dictは追加核の15引数。
    """
    return dict(times=data["times"],bid=data["bid"],ask=data["ask"],qok=data["qok"],
        atr=data["atr"],history=data["h"],phase=data["phase"],
        core_starts=np.zeros(len(data["times"]),np.int64) if core_starts is None else core_starts,
        activation=45.,end=data["end"],tick=data["tick"],quantity=data["quantity"],
        multiplier=data["multiplier"],fee_per_contract=data["fee_per_contract"],style=style)


def simulate(data, starts=None, style=0, jit=False):
    """
    機能: 純人工資料だけを一回追加核へ渡す。
    引数: data(dict)、starts(ndarray又はNone)、style(int)、jit(bool)。
    返り値: tuple[ndarray,...]は追加注文・親・全行時価。
    """
    return (addon.simulate if jit else addon.simulate.py_func)(**arguments(data,starts,style))


def mirror_audit(data,style,label):
    """
    機能: 上下鏡像で一回追加の時計・料金・収支が対称かを確かめる。
    引数: data(dict)、style(int)、label(str)は人工資料と検査名。
    返り値: None。
    """
    first=simulate(data,style=style);second=simulate(helper.mirror(data),style=style)
    helper.equal(label+"注文時計理由",first[0][:,[0,1,2,4,6,7,8,9,10,11]],second[0][:,[0,1,2,4,6,7,8,9,10,11]])
    helper.equal(label+"方向",first[0][:,3],-second[0][:,3])
    helper.equal(label+"価格",first[0][:,5],200.-second[0][:,5])
    helper.equal(label+"利益",first[1][:,[7,8,9,10,11,12]],second[1][:,[7,8,9,10,11,12]])
    helper.equal(label+"全時価",first[2][:,[0,2,3,4]],second[2][:,[0,2,3,4]])


def main():
    """
    機能: 同時旧新規・後発旧新規・未知・終端・未来毒化・会計・対称を独立人工で点検する。
    引数: なし。
    返り値: None。保存市場データを読まず、指紋付き証拠を新規保存する。
    """
    helper.CHECKS.clear()
    for style in (0,1):
        for qty,fee,mult in ((5,41.8,1000.),(10,11.,10.)):
            data=helper.tape()
            data.update(quantity=qty,fee_per_contract=fee,multiplier=mult)
            result=simulate(data,style=style)
            label=f"方式{style}枚数{qty}"
            helper.check(label+"期限判断",result[0][0,1]==45 and result[0][0,0]==46)
            helper.check(label+"同量一回",len(result[0])==2 and result[0][0,4]==qty and len(result[1])==1)
            helper.equal(label+"初期幅",result[1][0,10],10.)
            helper.check(label+"終場次行",result[0][-1,1]==1200 and result[0][-1,0]==1201)
            helper.cash_audit(data,result,label)
            mirror_audit(data,style,label)
            for row in (0,44,45):
                starts=np.zeros(len(data["times"]),np.int64);starts[row]=1
                blocked=simulate(data,starts,style)
                helper.check(label+"既参加抑止"+str(row),len(blocked[0])==0)
                helper.equal(label+"既参加時価零"+str(row),blocked[2][:,:4],np.zeros_like(blocked[2][:,:4]))
            for row in (46,47,100,1199):
                starts=np.zeros(len(data["times"]),np.int64);starts[row]=1
                later=simulate(data,starts,style)
                for i in range(3):helper.equal(label+"後発を遡及参照しない"+str(row)+"/"+str(i),result[i],later[i])
            # ----------------------------------------
            # 初期停止は未知履歴でも動き、不適格気配を越えた次正常行で返済する。
            loss=copy.deepcopy(data)
            loss["bid"][100:]=89.75;loss["ask"][100:]=90.25
            loss["h"][100:]=np.nan;loss["qok"][101:103]=False
            output=simulate(loss,style=style)
            helper.check(label+"未知中損切り",output[0][-1,1]==100 and output[0][-1,0]==103 and output[0][-1,6]==32)
            helper.cash_audit(loss,output,label+"損切り")
            mirror_audit(loss,style,label+"損切り鏡像")
            # 1.5R起動後だけ1R戻りの床を動かす。
            trail=copy.deepcopy(data)
            trail["bid"][100:]=116.;trail["ask"][100:]=116.5
            trail["bid"][101:]=105.75;trail["ask"][101:]=106.25
            output=simulate(trail,style=style)
            helper.check(label+"利益追尾",output[0][-1,1]==101 and output[0][-1,0]==102 and output[0][-1,6]==70)
            helper.cash_audit(trail,output,label+"追尾")
            mirror_audit(trail,style,label+"追尾鏡像")
    # ----------------------------------------
    # 期限時に未知なら回復まで待ち、未約定で終場なら注文を取り消す。
    data=helper.tape();data["h"][45:60]=np.nan
    output=simulate(data)
    helper.check("未知回復後の判断",output[0][0,1]==60 and output[0][0,0]==61)
    data=helper.tape();data["qok"][46:1200]=False
    output=simulate(data)
    helper.check("終場未約定取消",len(output[0])==0 and len(output[1])==0)
    helper.equal("未約定費用零",output[2][:,:4],np.zeros_like(output[2][:,:4]))
    data=helper.tape();data["h"][:]=np.nan
    helper.check("全未知無取引を捏造しない",len(simulate(data)[0])==0)
    data=helper.tape();data["h"][:,[6,7,10,11,13]]=0.;data["h"][:,8]=100.
    helper.check("方向情報ゼロを捏造しない",len(simulate(data)[0])==0)
    # 数値単位が変わっても方向の重みは変わらない。
    for style in (0,1):
        data=helper.tape();base=simulate(data,style=style)
        data["h"][:,[10,11,13]]*=1000.
        transformed=simulate(data,style=style)
        helper.equal("相手単位不変"+str(style),base[0],transformed[0])
    # 未来の価格・旧核新規・履歴を変更しても過去の注文と時価は同じ。
    data=helper.tape();base=simulate(data)
    later=copy.deepcopy(data);later["bid"][101:]=80.;later["ask"][101:]=80.5
    later["h"][101:]=np.nan;starts=np.zeros(len(data["times"]),np.int64);starts[102:]=1
    changed=simulate(later,starts)
    helper.equal("未来注文不変",base[0][base[0][:,0]<=100],changed[0][changed[0][:,0]<=100])
    helper.equal("未来時価不変",base[2][:101],changed[2][:101])
    # 幅は判断時の既知値で固定し、将来のATRへ選び直さない。
    data=helper.tape();data["atr"][46:]=200.
    helper.equal("判断幅固定",simulate(data)[1][:,10],np.array([10.]))
    # Pythonとコンパイル版の結果が一致する。
    data=helper.tape();data["bid"][100:]=89.75;data["ask"][100:]=90.25
    py,jit=simulate(data),simulate(data,jit=True)
    for i in range(3):helper.equal("JIT一致"+str(i),py[i],jit[i])
    output=HERE/f"未参加一回追加核の独立人工_{time.time_ns()}.json"
    source=WORK/"participation131.py"
    proof=dict(passed=True,checks=len(helper.CHECKS),labels=helper.CHECKS,
        sources={source.relative_to(ROOT).as_posix():hashlib.sha256(source.read_bytes()).hexdigest()},
        audit_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        helper_sha256=hashlib.sha256((HERE/"audit_engine131.py").read_bytes()).hexdigest(),
        financial_replays=0,market_data_reads=0,
        scope="追加核の人工確認のみ。旧核会計・新runner接続・両核同時保有上限は別担当の検査。",
        limitation="期限後に完全未知・全方向零なら追加しない。実資料の参加ゼロ件は金融後に別途確認する。")
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(output.as_posix(),len(helper.CHECKS),"合格",flush=True)


if __name__=="__main__":
    main()
