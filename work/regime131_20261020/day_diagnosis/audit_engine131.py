"""時間帯・状態切替核を独立の人工資料と現金台帳で確認する。実市場再生は行わない。"""

import copy
import hashlib
import json
import os
import pickle
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
os.environ["NUMBA_CACHE_DIR"] = str(HERE/"jit")
sys.path.insert(0, str(WORK))
import engine131 as core
import features131 as features
import run131 as runner

CHECKS = []


def check(label, condition):
    """
    機能: 独立期待条件を照合して記録する。
    引数: label(str)は検査名、condition(bool)は成否。
    返り値: None。不成立なら中断する。
    """
    assert condition, label
    CHECKS.append(label)


def equal(label, actual, expected):
    """
    機能: 数値配列をNaN同値・厳密許容で比較する。
    引数: label(str)、actual/expected(ndarray)は実値と期待。
    返り値: None。
    """
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-8, equal_nan=True, err_msg=label)
    CHECKS.append(label)


def tape():
    """
    機能: 単一商品・当時既知の十五列を持つ人工原行を作る。
    引数: なし。
    返り値: dictは合成時刻・気配・尺度・二市場・設定。
    """
    t = np.arange(1251, dtype=float)
    h = np.zeros((len(t), 15))
    h[:,0] = 100.; h[:,1] = 100.; h[:,2] = 2.; h[:,3] = 110.; h[:,4] = 90.
    h[:,5] = .5; h[:,6] = 1.; h[:,7] = 2.; h[:,8] = 99.
    h[:,9] = t-120.; h[:,10] = 1.; h[:,11] = 2.; h[:,12] = .5
    h[:,13] = 3.; h[:,14] = t-180.
    m = np.zeros((len(t), 12))
    m[:,:2] = 100.; m[:,2:4] = 4.; m[:,4:8] = .1
    m[:,8] = t-1.; m[:,9] = t-31.; m[:,10] = t-32.; m[:,11] = 1.
    return dict(times=t,bid=np.full(len(t),99.75),ask=np.full(len(t),100.25),
        qok=np.ones(len(t),bool),atr=np.full(len(t),4.),h=h,market=m,
        phase=np.ones(len(t),np.int64),start=0.,end=1200.,tick=.25,
        quantity=5,multiplier=1000.,fee_per_contract=41.8,
        parameters=np.array([0.,0.,1.,1.,.75,0.,45.,0.,0.]))


def mirror(data):
    """
    機能: 中心100で価格・方向だけを上下反転し、原時計・数量を保持する。
    引数: data(dict)は合成資料。
    返り値: dictは対称ケース。
    """
    other = copy.deepcopy(data)
    other["bid"], other["ask"] = 200.-data["ask"], 200.-data["bid"]
    for col in (0,1,8):
        other["h"][:,col] = 200.-data["h"][:,col]
    other["h"][:,3],other["h"][:,4] = 200.-data["h"][:,4],200.-data["h"][:,3]
    other["h"][:,[6,7,10,11,13]] *= -1
    other["market"][:,:2] = 200.-data["market"][:,:2]
    other["market"][:,4:8] *= -1
    return other


def run(data, jit=False):
    """
    機能: 人工資料だけを対象核へ渡す。
    引数: data(dict)は人工資料、jit(bool)はコンパイル版の選択。
    返り値: tuple[ndarray,...]は人工注文・親・曲線。
    """
    fn = core.simulate if jit else core.simulate.py_func
    return fn(**data)


def cash_audit(data, values, label):
    """
    機能: 作者核とは別の現金・在庫台帳から全原行時価と完結親損益を照合する。
    引数: data(dict)、values(tuple)、label(str)は人工資料と結果。
    返り値: None。
    """
    orders,trades,curve = values
    check(label+"次原行", np.all(orders[:,0] > orders[:,1]))
    good = data["qok"] & np.isfinite(data["bid"]) & np.isfinite(data["ask"])
    good &= (data["bid"] > 0.) & (data["ask"] > data["bid"])
    for o in orders:
        fill,source,side,quantity = int(o[0]),int(o[1]),int(o[3]),int(o[4])
        future = np.flatnonzero(good & (np.arange(len(good)) > source))
        check(label+"次正常_"+str(fill),len(future)>0 and fill==future[0])
        equal(label+"取得気配_"+str(fill),o[5],data["ask" if side>0 else "bid"][fill])
        equal(label+"片道料_"+str(fill),o[8],int(quantity*data["fee_per_contract"]))
        equal(label+"原判断時計_"+str(fill),o[10],data["times"][source])
    cash=0.;position=0;last_bid=np.nan;last_ask=np.nan
    expected = []
    for i in range(len(data["times"])):
        if good[i]:
            last_bid,last_ask=data["bid"][i],data["ask"][i]
        for o in orders[orders[:,0] == i]:
            cash -= o[3]*o[4]*o[5]*data["multiplier"]+o[8]
            position += int(o[3]*o[4])
        current=cash
        if position:
            current += position*(last_bid if position>0 else last_ask)*data["multiplier"]
            current -= int(abs(position)*data["fee_per_contract"])
        expected.append(current)
        equal(label+"数量_"+str(i),curve[i,1],position)
    equal(label+"全行現金時価",curve[:,0],np.array(expected))
    check(label+"終端返済",position==0)
    equal(label+"総合会計",trades[:,9].sum(),cash)
    for trade in trades:
        owned=orders[orders[:,2]==trade[0]]
        signed=-(owned[:,3]*owned[:,4]*owned[:,5]*data["multiplier"]).sum()
        equal(label+"親総損益_"+str(int(trade[0])),trade[7],signed)
        equal(label+"親費用_"+str(int(trade[0])),trade[8],owned[:,8].sum())
        equal(label+"親純額_"+str(int(trade[0])),trade[9],signed-owned[:,8].sum())
    summary=runner.summarize(orders,trades,curve,dict(session="2099-01-01_Day",symbol="TOPIX",time_s=data["times"]),
        dict(id="人工",name="人工"))
    equal(label+"集計料",summary["fees"],orders[:,8].sum())
    equal(label+"集計純額",summary["net"],cash)
    equal(label+"時間帯清算差合計",sum(summary["phase_equity_changes"].values()),cash)


def compare_mirror(data,label):
    """
    機能: 買い売り鏡像の注文時計・理由・数量・利益を比較する。
    引数: data(dict)、label(str)は人工資料と名称。
    返り値: None。
    """
    a=run(data);b=run(mirror(data))
    equal(label+"鏡像注文形状",a[0].shape,b[0].shape)
    equal(label+"鏡像注文時計理由",a[0][:,[0,1,2,4,6,7,8,9,10,11]],b[0][:,[0,1,2,4,6,7,8,9,10,11]])
    equal(label+"鏡像方向",a[0][:,3],-b[0][:,3])
    equal(label+"鏡像価格",a[0][:,5],200.-b[0][:,5])
    equal(label+"鏡像収支",a[1][:,[7,8,9,10,11,12]],b[1][:,[7,8,9,10,11,12]])
    equal(label+"鏡像時価",a[2][:,[0,2,3,4]],b[2][:,[0,2,3,4]])


def feature_audit():
    """
    機能: 全13時計区分と欧米夏時間差、特徴の将来変更不変を人工資料で点検する。
    引数: なし。
    返り値: None。
    """
    jst=ZoneInfo("Asia/Tokyo")
    day=["08:59:59","09:00:00","11:29:59","11:30:00","12:29:59","12:30:00","15:24:59","15:25:00"]
    values=np.array([datetime.fromisoformat("2026-10-09T"+v).replace(tzinfo=jst).timestamp() for v in day])
    equal("現物全境界",features.phases(dict(time_s=values,session="2026-10-09_Day")),np.array([0,1,1,2,2,3,3,4]))
    equal("祝日日中",features.phases(dict(time_s=values,session="2026-10-12_Day")),np.full(len(values),5))
    for date in ("2026-10-20","2026-10-28","2026-11-04"):
        opening=datetime.fromisoformat(date+"T09:30").replace(tzinfo=ZoneInfo("America/New_York")).timestamp()
        close=datetime.fromisoformat(date+"T16:30").replace(tzinfo=ZoneInfo("Europe/London")).timestamp()
        ts=np.array([opening-3601,opening-3600,opening-1,opening,opening+1799,opening+1800,
                     close-1,close,opening+19799,opening+19800,opening+23399,opening+23400])
        equal("欧米時計境界"+date,features.phases(dict(time_s=ts,session=date+"_Night",us_open=opening)),
              np.array([6,7,7,8,8,9,9,10,10,11,11,12]))
    start=datetime.fromisoformat("2026-10-09T08:45").replace(tzinfo=jst).timestamp()
    t=start+np.arange(2401,dtype=float)
    packet=dict(inputs={},quotes={})
    for sym,offset in (("TOPIX",0),("NK225",.5)):
        px=100.+np.arange(len(t))*.01+offset
        packet["inputs"]["2026-10-09_Day",sym]=dict(time_s=t+offset,last=px,atr=np.full(len(t),4.),
            seq=np.arange(len(t)),start=start,limit=start+2400,tick=.25,session="2026-10-09_Day",symbol=sym,us_open=np.inf)
        packet["quotes"]["2026-10-09_Day",sym]=dict(bid=px-.25,ask=px+.25,quote_valid=np.ones(len(t),bool))
    base=features.build(packet)
    poisoned=copy.deepcopy(packet)
    for sym in ("TOPIX","NK225"):
        key="2026-10-09_Day",sym
        poisoned["quotes"][key]["bid"][1801:]+=500.
        poisoned["quotes"][key]["ask"][1801:]+=500.
        poisoned["inputs"][key]["atr"][1801:]*=10.
    later=features.build(poisoned)
    for k in packet["inputs"]:
        for ix in (1,2,3):
            equal("特徴未来不変"+str(k)+str(ix),base[ix][k][:1801],later[ix][k][:1801])
        check("相手厳密過去"+str(k),np.all(base[1][k][np.isfinite(base[1][k][:,8]),8] <
             base[0][k]["time_s"][np.isfinite(base[1][k][:,8])]))
        finite=np.isfinite(base[2][k][:,9])
        check("自己足公開遅延"+str(k),np.all(base[0][k]["time_s"][finite]-base[2][k][finite,9] >= 60.))
        finite=np.isfinite(base[2][k][:,14])
        check("相手足公開遅延"+str(k),np.all(base[0][k]["time_s"][finite]-base[2][k][finite,14] >= 120.))


def connection_audit():
    """
    機能: 実行入口を架空packet・架空登録・検査用核へ差替え、全15引数の接続を確認する。
    引数: なし。
    返り値: None。保存結果は人工作業域のみで、実金融は呼ばない。
    """
    target=HERE/"接続人工"
    target.mkdir(exist_ok=True)
    calls=[];outputs=[];saved_arrays=[]
    scene="2099-01-01_Day"
    packet=dict(inputs={},quotes={})
    inputs={};markets={};history={};phases={}
    for sym,offset in (("TOPIX",0),("NK225",1)):
        data=tape();key=scene,sym
        data["times"] += offset
        inputs[key]=dict(time_s=data["times"],atr=data["atr"],start=0.,limit=1200.,tick=.25,
                         session=scene,symbol=sym)
        packet["quotes"][key]=dict(bid=data["bid"],ask=data["ask"],quote_valid=data["qok"])
        markets[key]=data["market"];history[key]=data["h"];phases[key]=data["phase"]
    path=target/"架空入力.pkl"
    path.write_bytes(pickle.dumps(packet))
    ref=dict(path=path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),session=scene)
    configs=[]
    for selector in (0,4):
        c=dict(zip(runner.PARAMETERS,[selector,1,1.,1.,.75,2,2700.,1,1]))
        c.update(id="人工"+str(selector),name="人工条件")
        configs.append(c)
    fixed=dict(sources={},artificial=[],input_references=[],configs=configs)
    original={name:getattr(runner,name) for name in ("HERE","read","reference","save","sources")}
    oldbuild=features.build;oldsimulate=core.simulate;oldsavez=np.savez_compressed;oldargv=sys.argv.copy()

    def fake_read(location):
        """
        機能: 既知の架空登録と架空入力参照だけを返す。
        引数: location(Path)は呼出元が求めた位置。
        返り値: dictは人工資料。
        """
        name=Path(location).name
        if name=="固定計画.json":return fixed
        if name=="登録.json":return dict(returncode=0)
        if name=="入力準備.json":return dict(packets=[ref])
        raise AssertionError(str(location))

    def fake_reference(location):
        """
        機能: 人工packetの指紋、又は未保存の人工出力の印を返す。
        引数: location(Path)は対象。
        返り値: dictは参照。
        """
        location=Path(location)
        if location==path:return {k:ref[k] for k in ("path","sha256")}
        return dict(path=location.relative_to(ROOT).as_posix(),sha256="人工未保存")

    def fake_core(*args):
        """
        機能: 実核を呼ばず、入力の順序・商品数量・料金を独立期待へ照合する。
        引数: args(tuple)は実行接続からの15引数。
        返り値: tupleは空の人工会計。
        """
        index=len(calls);sym=("TOPIX","NK225")[index//len(configs)];c=configs[index%len(configs)]
        key=scene,sym;rd=inputs[key];q=packet["quotes"][key]
        check("接続引数数"+str(index),len(args)==15)
        expected=[rd["time_s"],q["bid"],q["ask"],q["quote_valid"],rd["atr"],history[key],
                  markets[key],phases[key],0.,1200.,.25,5 if sym=="TOPIX" else 10,
                  1000. if sym=="TOPIX" else 10.,41.8 if sym=="TOPIX" else 11.,
                  np.array([c[k] for k in runner.PARAMETERS])]
        for i,value in enumerate(expected):equal("接続_"+str(index)+"_"+str(i),args[i],value)
        calls.append(sym)
        return np.zeros((0,12)),np.zeros((0,17)),np.zeros((len(rd["time_s"]),5))

    try:
        runner.HERE=target;runner.read=fake_read;runner.reference=fake_reference
        runner.save=lambda p,v:outputs.append((str(p),v));runner.sources=lambda:{}
        features.build=lambda p:(inputs,markets,history,phases)
        core.simulate=fake_core;np.savez_compressed=lambda p,**v:saved_arrays.append((str(p),v))
        sys.argv=["run131.py","--round","架空実行"]
        runner.main()
        check("接続全商品全設定",calls==["TOPIX","TOPIX","NK225","NK225"])
        check("接続保存列",len(saved_arrays)==2 and all(len(v)==6 for _,v in saved_arrays))
        check("接続会計完成",len(outputs[-1][1]["rows"])==4)
    finally:
        for name,value in original.items():setattr(runner,name,value)
        features.build=oldbuild;core.simulate=oldsimulate;np.savez_compressed=oldsavez;sys.argv=oldargv


def main():
    """
    機能: 新核の人工期待・会計・対称・将来不変を実行し、源指紋付き証拠を保存する。
    引数: なし。
    返り値: None。市場packetは読まない。
    """
    feature_audit()
    connection_audit()
    base=tape()
    a=run(base)
    check("初回期限の判断と約定",a[0][0,1]==45 and a[0][0,0]==46 and a[0][0,6]==82)
    check("終場検知の次原行",a[0][-1,1]==1200 and a[0][-1,0]==1201 and a[0][-1,6]==93)
    cash_audit(base,a,"期限基本")
    for selector in range(5):
        for width in range(2):
            for qty,fee,mult in ((5,41.8,1000.),(10,11.,10.)):
                v=tape();v["parameters"][0]=selector;v["parameters"][1]=width
                v["quantity"]=qty;v["fee_per_contract"]=fee;v["multiplier"]=mult
                v["bid"][100:200]=103.75;v["ask"][100:200]=104.25
                v["bid"][200:]=101.75;v["ask"][200:]=102.25
                label=f"方式{selector}幅{width}枚数{qty}"
                compare_mirror(v,label)
                cash_audit(v,run(v),label)
    # ----------------------------------------
    # 自然な追随準備と帯回帰準備を、期限参加とは独立に検査する。
    for selector in (0,1):
        v=tape();v["parameters"][0]=selector;v["parameters"][5]=1;v["parameters"][6]=2000
        v["h"][:,0]=100.;v["h"][:,1]=99. if selector==0 else 110.
        v["bid"][1]=98.75;v["ask"][1]=99.25
        a=run(v)
        check("自然入口_"+str(selector),len(a[0])==2 and a[0][0,1]==2 and a[0][0,6]==80+selector)
        compare_mirror(v,"自然"+str(selector));cash_audit(v,a,"自然"+str(selector))
        # 未知を挟んで古い極値を使わず、新しい準備からやり直す。
        broken=copy.deepcopy(v);broken["h"][2,:]=np.nan
        b=run(broken)
        check("未知で旧極値破棄"+str(selector),len(b[0])==0)
    # ----------------------------------------
    # 強制停止は未知履歴でも働き、気配不適格行では約定しない。
    v=tape();v["bid"][100:]=95.75;v["ask"][100:]=96.25
    v["h"][100:]=np.nan;v["qok"][101:103]=False
    a=run(v)
    check("停止未知継続",a[0][-1,1]==100 and a[0][-1,0]==103 and a[0][-1,6]==32)
    cash_audit(v,a,"未知停止")
    # 初回方向票は相手の単位を1000倍にしても変わらない。
    v=tape();v["h"][:,7]=2;v["h"][:,11]=-3;v["h"][:,10]=0
    first=run(v)
    v["h"][:,11]*=1000.;v["market"][:,3]=np.nan
    second=run(v)
    equal("単位変換で初回方向不変",first[0][:,3],second[0][:,3])
    # 60秒撤退の時計は不明・不適格・15秒超空白で一度切る。
    for kind in ("気配未知","市場未知","時計空白"):
        v=tape();v["parameters"][8]=1.
        v["bid"][60:]=98.75;v["ask"][60:]=99.25
        v["market"][60:,5]=-.5;v["market"][60:,7]=-.5;v["h"][60:,6]=-1.
        if kind=="気配未知":v["qok"][90]=False
        elif kind=="市場未知":v["market"][90,11]=0.
        else:v["times"][90:]+=20.;v["end"]+=20.
        a=run(v);expected=152 if kind!="時計空白" else 151
        check("持続切断_"+kind,a[0][-1,0]==expected and a[0][-1,6]==75)
        cash_audit(v,a,"持続"+kind)
    # 未来の変更は過去の注文・全行時価に影響しない。
    v=tape();v["bid"][200:]=108.;v["ask"][200:]=108.5
    a=run(v);p=copy.deepcopy(v)
    p["bid"][101:]=80.;p["ask"][101:]=80.5;p["h"][101:]=np.nan;p["phase"][101:]=4
    b=run(p)
    equal("核未来注文不変",a[0][a[0][:,0]<=100],b[0][b[0][:,0]<=100])
    equal("核未来全行時価不変",a[2][:101],b[2][:101])
    # 参加期限が未知や完全無方向を支持へ変換しないことを確認する。
    v=tape();v["h"][:]=np.nan
    check("未知では期限参加なし",len(run(v)[0])==0)
    v=tape();v["h"][:,[6,7,10,11,13]]=0.;v["h"][:,8]=100.
    check("完全無方向では期限参加なし",len(run(v)[0])==0)
    # PythonとJITの独立実行結果を一致確認する。
    v=tape();v["bid"][100:]=105.75;v["ask"][100:]=106.25
    plain,compiled=run(v),run(v,True)
    for i in range(3):equal("JIT一致"+str(i),plain[i],compiled[i])
    proof=dict(passed=True,checks=len(CHECKS),labels=CHECKS,
        sources=runner.sources(),audit_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        financial_replays=0,market_data_reads=0,
        scope="人工資料のみ。既知・未知、上下、全13時計、夏時間差、次正常原行、独立現金会計、未来変更、JITを確認。",
        limitations=["実データ全場で最低1回入れること、利益が出ることはこの人工検査では証明しない。",
                    "短期市場資料が未知でも中期履歴が既知なら自然入口は許される設計。未知を支持へ置換したとは扱わない。"])
    path=HERE/f"状態切替核の独立人工_{time.time_ns()}.json"
    path.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(path.as_posix(),len(CHECKS),"合格",flush=True)


if __name__=="__main__":
    main()
