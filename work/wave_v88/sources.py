"""GU・M3逆360分・C03の独立紙上注文を、共通原本行の8列へ接続する。"""
from pathlib import Path
import importlib.util
import json
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def module(name,path):
    """
    機能: 今回の接続モジュールを固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value


prepare=module('wave88_source_prepare',HERE/'source_prepare.py')
old=module('wave88_gu85',ROOT/'work/wave_v85/strategy.py')
m3=module('wave88_m3_engine',HERE/'m3_engine.py')
import numba
numba.config.CACHE_DIR=str(HERE/'cache')
ORDER_COLUMNS=['紙上約定行','判断元行','親組','注文方向','枚数','紙上約定価格','理由','新規区分']
M3_FIXED=json.loads((ROOT/'M3_逆_A00_360分版/固定条件.json').read_text(encoding='utf-8'))
C03_FIXED=json.loads((ROOT/'work/wave_v52/売買仕様固定.json').read_text(encoding='utf-8'))
C03_SPEC=next(v['spec'] for v in C03_FIXED['手法'] if v['id']=='C03')


def declarations():
    """
    機能: 配分と独立した紙上源の固定条件を返す。
    引数: なし。
    返り値: dict[str,dict]。
    """
    return dict(
        GU=dict(名称='E01_G_U',数量=dict(TOPIX=5,NK225=10),仕様='旧85を無変更で観測価格再生。元のU停止・途中半減・部分利確・通常影時計を保持。'),
        M3=dict(名称='M3_逆_A00_360分版',数量=dict(TOPIX=1,NK225=1),信号=M3_FIXED['信号条件'],設定=M3_FIXED['一枚でのエンジン設定'],
            仕様='旧19のS00を保持。既設線成立時と初回建値を観測CurrentPriceへ一貫して変更する。'),
        C03=dict(名称='価格だけの反転確認',数量=dict(TOPIX=5,NK225=10),設定=C03_SPEC,尺度=C03_FIXED['尺度'],
            仕様='旧52の板・出来高品質による観測採否を保持。先頭10場の固定尺度を変更しない。未来ラベルを使わない。'))


def initialize(inputs,signals):
    """
    機能: 紙上源の過去特徴だけを読み、GUの既存因果特徴を構成する。
    引数: inputs/signals(dict) は旧85全口座入力。
    返り値: dict[tuple,dict] の口座別源特徴。未来終了時刻や親損益を含めない。
    """
    package,proof=prepare.load(verify=True)
    gu=old.initialize(inputs,signals)
    assert set(inputs)==set(package['m3'])==set(package['c03'])
    return {key:dict(GU=gu[key],M3=package['m3'][key],C03=package['c03'][key],
                    source_input_sha=proof['生成物SHA256']['work/wave_v88/prepared/sources.pkl']) for key in inputs}


def c03_native(ready,decisions,finish=True):
    """
    機能: 旧C03再生器を固定数量で呼び、源注文と原本行対応だけを返す。
    引数: ready(dict)、decisions(ndarray)、finish(bool)。
    返り値: tuple[ndarray,ndarray] の標準8列注文と旧形式10列注文。
    """
    qty,value=(5,1000) if ready['symbol']=='TOPIX' else (10,10)
    s=C03_SPEC
    params=np.array([qty,value,s['stop_atr'],s['activation_atr'],s['trail_atr'],s['hold_seconds'],
        int(s['exit_neutral']),s['failure_seconds'],s['failure_atr'],s['cooldown_seconds']],float)
    native,_,_,_,_=prepare.replay.drive(ready['time_s'],ready['seq'],ready['last'],ready['atr'],decisions,params,ready['limit'],finish)
    orders=np.empty((len(native),8));cid=-1
    for j,row in enumerate(native):
        at=int(np.searchsorted(ready['seq'],int(row[3])));source=int(np.searchsorted(ready['seq'],int(row[2])))
        assert ready['seq'][at]==row[3] and ready['seq'][source]==row[2]
        isnew=int(row[4]==1)
        if isnew:cid+=1
        assert cid>=0
        orders[j]=[at,source,cid,row[5],row[6],row[7],row[9],isnew]
    return orders,native


def validate(ready,orders,initial,finish=True):
    """
    機能: 公開行・判断行・価格・親単位の残枚数を検査する。
    引数: ready(dict)、orders(ndarray)、initial(int)、finish(bool)。
    返り値: dict の注文公開証拠。親IDは未来台帳から割り当てない。
    """
    qty=0;cid=-1;side=0;parents=0
    for row in orders:
        i,s,c=int(row[0]),int(row[1]),int(row[2])
        assert 0<=s<i<len(ready['last'])
        assert ready['time_s'][s]<=ready['time_s'][i]
        assert row[5]==ready['last'][i]
        if row[7]:
            assert qty==0 and c>cid and row[4]==initial
            cid=c;side=int(row[3]);qty=int(row[4]);parents+=1
        else:
            assert c==cid and row[3]==-side and 0<row[4]<=qty
            qty-=int(row[4])
    if finish:assert qty==0
    return dict(注文数=len(orders),親数=parents,残枚数=qty,判断元より後の原本行で公開=True,紙上価格は当行CurrentPrice=True)


def play(source_id,key,ready,features,finish=True):
    """
    機能: 独立源を再生し、紙上約定の当行に初公開する標準注文を返す。
    引数: source_id(str:GU/M3/C03)、key(tuple)、ready(dict)、features(dict:全口座又は当口座)、finish(bool)。
    返り値: dict。ordersの配分・実注文価格・実手数料は共通実行層の責務。
    """
    feature=features[key] if key in features else features
    assert source_id in ('GU','M3','C03') and key==(ready['session'],ready['symbol'])
    if source_id=='GU':
        result,_=old.play(dict(id='E01_G_U',mask=1,time_mode='U',changes={}),ready,feature['GU'],True)
        orders=result['orders'].copy()
    elif source_id=='M3':
        result=m3.run(ready,np.asarray(feature['M3'])[:len(ready['last'])],M3_FIXED['一枚でのエンジン設定'],detail=False,observed_fill=True)
        orders=result['orders'].copy()
    else:
        decisions=np.asarray(feature['C03']);decisions=decisions[decisions[:,0]<len(ready['last'])]
        orders,_=c03_native(ready,decisions,finish=finish)
    declaration=declarations()[source_id]
    proof=validate(ready,orders,declaration['数量'][key[1]],finish=finish)
    return dict(orders=orders,columns=ORDER_COLUMNS,declaration=declaration,sourceproof=proof)
