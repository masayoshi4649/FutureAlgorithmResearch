"""次反復の三点位相について、価格資格と同原行上限だけを人工独立照合する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
SOURCE=ROOT/'work/wave_v106/local_phase/features.py'


def oracle(points: np.ndarray, known: bool, tick: float) -> dict:
    """
    機能: 三点だけの有資格/純幅/総変化/強方向を独立した逐点算術で算定する。
    引数: points(ndarray[float]3)、known(bool)、tick(float)は当時三点と資格/呼値。
    返り値: dictは独立期待値。市場データ又は金融結果を参照しない。
    """
    if not known or not all(np.isfinite(x) and x>0 for x in points):return dict(known=False,direction=0)
    net=(float(points[2])-float(points[0]))/tick
    tv=(abs(float(points[1])-float(points[0]))+abs(float(points[2])-float(points[1])))/tick
    er=abs(net)/tv if tv else 0.
    direction=(1 if net>0 else -1) if er>=.6 and abs(net)>=2 else 0
    return dict(known=True,direction=direction,net_ticks=net,TV_ticks=tv,ER=er)


def fixture() -> dict:
    """
    機能: 先頭公表midと当行midを変え、尾部未知/気配不明/中立/境界を持つ小入力を作る。
    引数: なし。
    返り値: dictは人工packet。原行又は旧33cacheは読まない。
    """
    n=8;time=600.+np.arange(n);actual=np.array([112.,112.,112.,112.,100.,100.,103.,102.])
    own_mid=np.full((n,6),200.);own_mid[:,-3]=[100.,100.,100.,100.,100.,104.,100.,100.]
    own_mid[:,-2]=[110.,110.,110.,110.,100.,102.,104.,np.nan]
    peer_mid=np.full((n,6),1000.);peer_mid[:,-3:]=np.array([1000.,1040.,1030.])
    own=dict(midpoint=own_mid,rows=np.tile(np.arange(n)[:,None],(1,6)),known=np.ones(n,bool))
    peer=dict(midpoint=peer_mid,times=np.tile(time[:,None],(1,6))-1.,known=np.ones(n,bool))
    known=np.ones(n,bool);known[1]=False;qok=np.ones(n,bool);qok[2]=False;peer_known=np.ones(n,bool);peer_known[3]=False
    return dict(prepared=dict(TOPIX=dict(record=dict(seq=np.arange(n),time_s=time,bid=actual-.25,ask=actual+.25,tick=.5)),
        NK225=dict(record=dict(tick=10.))),measured=dict(TOPIX=dict(sample_tables=dict(own=own,peer=peer),normal_sample_index=np.arange(n),
        raw_mapping=np.arange(n),own_known=known,qok=qok,peer_known=peer_known)))


def run() -> None:
    """
    機能: 当行mid/各商品呼値/自己尾部/相手過去/接頭不変と三方針UNKNOWN扱いを独立確認する。
    引数: なし。
    返り値: None。既金融・全33素材・現Night/APIを読まない。
    """
    path=HERE/'直近位相の価格資格と同原行の独立確認.json';assert not path.exists()
    before=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    spec=importlib.util.spec_from_file_location('現在入力担当の局所位相読取だけ',SOURCE)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    packet=fixture();actual=module.build(packet,'TOPIX');n=8;count=0
    for row in range(n):
        for side in ('own','peer'):
            expected=oracle(actual[side]['points'][row],bool(packet['measured']['TOPIX']['own_known'][row] and packet['measured']['TOPIX']['qok'][row]) if side=='own' else bool(packet['measured']['TOPIX']['peer_known'][row]),.5 if side=='own' else 10.)
            for key,value in expected.items():
                assert actual[side][key][row]==value,(side,row,key,value,actual[side][key][row]);count+=1
    assert actual['own']['points'][0,-1]==112. and actual['own']['points'][0,-1]!=200.
    assert not actual['own']['known'][1] and packet['measured']['TOPIX']['sample_tables']['own']['known'][1]
    assert not actual['own']['known'][2] and not actual['peer']['known'][3]
    assert actual['own']['known'][4] and actual['own']['direction'][4]==0 and actual['own']['ER'][4]==0
    bad=deepcopy(packet);bad['measured']['TOPIX']['sample_tables']['own']['rows'][0,-1]=1
    try:module.build(bad,'TOPIX');raise RuntimeError('未来自己公表行を受理した')
    except AssertionError:count+=1
    bad=deepcopy(packet);bad['measured']['TOPIX']['sample_tables']['peer']['times'][0,-1]=packet['prepared']['TOPIX']['record']['time_s'][0]
    try:module.build(bad,'TOPIX');raise RuntimeError('相手同clockを受理した')
    except AssertionError:count+=1
    future=deepcopy(packet)
    for v in ('bid','ask'):future['prepared']['TOPIX']['record'][v][5:]+=1000
    future['measured']['TOPIX']['sample_tables']['own']['midpoint'][5:]+=1000
    changed=module.build(future,'TOPIX')
    for s in ('own','peer'):
        for field in ('known','direction','ER','TV_ticks','net_ticks','points'):
            np.testing.assert_array_equal(actual[s][field][:5],changed[s][field][:5]);count+=1
    for policy in ('OWN_VETO','BOTH_VETO','ALIGNED'):
        allowed,cancel=module.decisions(actual,1,policy)
        assert not cancel[1] and not cancel[2]
        if policy=='ALIGNED':assert not allowed[1] and not allowed[2] and not allowed[3]
        count+=1
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==before
    value=dict(全合格=True,独立照合件数=count,source_SHA256={SOURCE.relative_to(ROOT).as_posix():before},
        確認=['120/60点＋当行実midで同時計先頭mid代用なし','own_knownは原row尾部資格、qokも必要','peer_known/厳密過去を維持',
            'TV0既知中立と不明を区別','自己先頭公表行が未来原rowなら拒否','相手同clockなら拒否','未来行変更で先行三点不変'],
        静的所見='Rだけ追加新規拒否/方向別待機取消。C根拠と元基準イベントは保持。UNKNOWNの拒否なしは反対不明を反対としない仕様であり、支持ありの判定ではない。',
        限界='三点ERは間の全tick経路を測らず、実損益改善はこの検査から言えない。OWN/BOTH vetoでの新規可は相手支持を意味しない。',
        全33cache読取=0,新Night内容読取=0,金融結果読取=0,金融再生=0,原板API=0)
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8',newline='\n')
    print('局所位相の価格資格と原行独立人工が合格',count,flush=True)


if __name__=='__main__':run()
