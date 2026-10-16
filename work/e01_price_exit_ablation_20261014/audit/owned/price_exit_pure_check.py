"""反対価格票の退出だけを外す対照を、旧独立純参照と小反例へ先に固定する。"""

import hashlib
import json
import math
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OLD=ROOT/'work/e01_protect_reentry_20261014/audit/owned'
sys.dont_write_bytecode=True
sys.path.append(str(OLD))
from protect_state_reference import Reference as OldReference,Row
from price_exit_reference import Reference


def point(symbol: str, side: int, clock: float, shift: float=0., opposite: bool=False, quiet: bool=False) -> Row:
    """
    機能: 一貫した側の小BBOと両市場の明示価格票を作る。
    引数: symbol(str)、side(int)、clock/shift(float)、opposite/quiet(bool) は人工条件。
    返り値: Row は当時気配/Last/票。実相場の方向検知精度とは別。
    """
    base=4000. if symbol=='TOPIX' else 65000.;tick=.5 if symbol=='TOPIX' else 10.
    bid=base+side*shift-(tick if side<0 else 0.)
    vote=dict(known=True,count=4,balance=-side if opposite else side)
    return Row(clock,base+side*shift,bid,bid+tick,True,vote,vote,quiet)


def make(symbol: str, side: int, exit_id: str, on: bool, mode: str='ORIGIN') -> Reference:
    """
    機能: 一紙上親・一実UIDを独立な正常FAKでfillする。
    引数: symbol/exit_id/mode(str)、side(int)、on(bool) は商品/出口/入口/側/反票退出。
    返り値: Reference は初回保有。反票判定以外の係数を変更しない。
    """
    r=Reference(symbol,mode,exit_id,price_exit_enabled=on);base=4000. if symbol=='TOPIX' else 65000.
    r.step(0,point(symbol,side,0),[])
    r.step(1,point(symbol,side,300),[dict(new=True,cid=7,side=side,q=5 if symbol=='TOPIX' else 10,price=base)])
    r.step(2,point(symbol,side,301),[]);assert r.held is not None
    return r


# ----------------------------------------
def main() -> None:
    """
    機能: ON旧同値とOFF反票単独不退出/他停止保持を必要な小反例だけで検査する。
    引数: なし。旧独立参照sourceと新純参照だけを読み、owner未importで固定する。
    返り値: None。旧108金融本文/packet/台帳/APIを読まず小証跡を保存する。
    """
    target=HERE/'反票ON旧同値とOFF他停止保持の独立純期待.json';assert not target.exists()
    observations=[];same_cases=0
    for symbol in ('TOPIX','NK225'):
        base=4000. if symbol=='TOPIX' else 65000.;tick=.5 if symbol=='TOPIX' else 10.
        for side in (1,-1):
            for mode in ('ORIGIN','PULL','BREAK','ADAPTIVE'):
                for exit_id in ('TARGET','TIGHT_TRAIL','WIDE_TRAIL'):
                    old=OldReference(symbol,mode,exit_id);new=Reference(symbol,mode,exit_id,price_exit_enabled=True)
                    for i,row in enumerate([point(symbol,side,0),point(symbol,side,300),point(symbol,side,301),
                                           point(symbol,side,302,opposite=True),point(symbol,side,303),point(symbol,side,1000)]):
                        feed=[dict(new=True,cid=7,side=side,q=5 if symbol=='TOPIX' else 10,price=base)] if i==1 else []
                        old.step(i,row,feed);new.step(i,row,feed)
                    assert (old.orders,old.parents,old.curve,old.publications)==(new.orders,new.parents,new.curve,new.publications)
                    same_cases+=1
            for exit_id in ('TARGET','TIGHT_TRAIL','WIDE_TRAIL'):
                on=make(symbol,side,exit_id,True);off=make(symbol,side,exit_id,False);N=off.held['N']
                for r in (on,off):r.step(3,point(symbol,side,302,opposite=True),[])
                assert on.queue and on.queue['reason']=='両市場反対' and off.queue is None
                for r in (on,off):r.step(4,point(symbol,side,303),[])
                assert on.held is None and off.held and off.held['N']==N and off.held['uid']==0
                move=math.ceil(base*.002/tick)*tick
                off.step(5,point(symbol,side,304,move),[])
                if exit_id=='TARGET':
                    assert off.queue and off.queue['reason']=='親目標'
                    off.step(6,point(symbol,side,305,move),[])
                else:
                    assert off.held['armed'] and off.queue is None
                    off.step(6,point(symbol,side,305,move-math.ceil(base*.0005/tick)*tick),[])
                    assert off.queue and off.queue['reason']=='親追尾'
                    off.step(7,point(symbol,side,306,move-math.ceil(base*.0005/tick)*tick),[])
                assert not off.held and len(off.parents)==1 and len(off.orders)==2
                observations.append(dict(symbol=symbol,side=side,exit=exit_id,反票単独OFF保持=True,親目標又は保護保持=True,N固定=True))
            for cause in ('親損失','paper全退出','quiet','期限','場損失','場利益'):
                r=make(symbol,side,'TARGET',False);N=r.held['N'];row=point(symbol,side,302)
                events=[]
                if cause=='親損失':row=point(symbol,side,302,-math.ceil(base*.001/tick)*tick)
                elif cause=='paper全退出':events=[dict(new=False,cid=7,side=-side,q=5 if symbol=='TOPIX' else 10,price=base)]
                elif cause=='quiet':row=point(symbol,side,302,quiet=True)
                elif cause=='期限':row=point(symbol,side,1000)
                elif cause=='場損失':row=point(symbol,side,302,-math.ceil(base*.004/tick)*tick)
                elif cause=='場利益':row=point(symbol,side,302,math.ceil(base*.005/tick)*tick)
                r.step(3,row,events)
                if cause in ('quiet','期限'):assert not r.held
                else:
                    assert r.queue and r.held['N']==N
                    r.step(4,point(symbol,side,row.clock+1,side*(row.last-base)),[])
                    assert not r.held
                assert len(r.parents)==1 and len(r.orders)==2
                observations.append(dict(symbol=symbol,side=side,停止=cause,反票OFFでも保持=True))
    value=dict(全合格=True,ON旧純同値口座=same_cases,OFF必要反例=len(observations),観測=observations,
               純source_SHA256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in
                    (OLD/'price_vote_reference.py',OLD/'protect_state_reference.py',HERE/'price_exit_reference.py',Path(__file__))},
               scope='所有実装未import。旧独立純参照のON経済状態と反票OFFだけの比較。完成sourceと正式specへの接続は別。',
               未結合=['owner旧ON九出力同値','新OFFのPython/JIT配列同値','新最終source/spec/登録','副診断paper残量の入口不使用'],
               新金融=0,元108金融本文=0,保存packet=0,台帳本文=0,原板=0,API=0)
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('反票対照の純期待合格 '+str(same_cases)+'/'+str(len(observations))+' SHA '+hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
