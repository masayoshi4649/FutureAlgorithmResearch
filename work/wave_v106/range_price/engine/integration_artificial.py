"""入力ownerの範囲候補をnative呼値へ写し、同じ接口で注文状態へ接続する。"""

from copy import deepcopy
from pathlib import Path
import sys

import numpy as np

import artificial
import common

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
INPUT=common.module('106R_PRICE結合の入力人工',HERE.parent/'input_artificial.py')
FEATURES=common.module('106R_PRICE結合の当時価格特徴',HERE.parent/'features.py')
SELECT=common.module('106R_PRICE結合の純価格選択',HERE.parent/'selection.py')
CATALOG=common.module('106R_PRICE結合の24定義',HERE.parent/'catalog.py')


def main() -> None:
    """
    機能: 元input人工を各商品のnative呼値へ同じ比例変換し、市場/指値を実quantityへ結ぶ。
    引数: なし。
    返り値: None。正式raw/cache/金融は読み込まない。
    """
    target=HERE/'範囲入力と単一執行の結合人工検査.json';assert not target.exists()
    paths=[HERE/n for n in ('core.py','common.py','artificial.py','integration_artificial.py')]
    paths+=[HERE.parent/n for n in ('interface.py','features.py','selection.py','input_artificial.py','catalog.py')]
    before={str(p.relative_to(common.ROOT)):common.digest(p) for p in paths};checks={}
    for reflected in (False,True):
        raws,records,cases=INPUT.fixture()
        for symbol in ('TOPIX','NK225'):
            scale=.5 if symbol=='TOPIX' else 10.
            for holder in (raws[symbol],records[symbol]):
                if reflected:
                    bid,ask=holder['bid'].copy(),holder['ask'].copy();holder['bid']=212.-ask;holder['ask']=212.-bid
                for key in ('bid','ask','price'):
                    if key in holder:holder[key]=holder[key]*scale
            records[symbol]['tick']=scale;records[symbol]['人工素材']=True
        prepared={s:dict(record=records[s],reference_open=100.*records[s]['tick'],signal=dict(trend_width=2.*records[s]['tick'])) for s in records}
        measured={s:FEATURES.build(raws,records,s) for s in records}
        packet=dict(prepared=prepared,cases={s:dict(C_OWN=cases[s]) for s in records},measured=measured)
        for entry,margin in (('MARKET',2),('LIMIT',4)):
            cfg=next(c for c in CATALOG.catalog() if c['mode']=='R_ONLY' and c['range_er']==.2 and c['margin_ticks']==margin and c['range_entry']==entry)
            normal=SELECT.build(packet,'TOPIX',cfg)
            assert normal['event'][7]==(-1 if reflected else 1)
            p=prepared['TOPIX'];out=artificial.INTERFACE.play(p,normal,cfg,quantity=5,finish=False,python=True)
            if entry=='MARKET':assert len(out['orders'])==1 and out['orders'][0,0]==8 and out['orders'][0,1]==7 and out['orders'][0,9]==209
            else:assert len(out['orders'])==0 and out['target_trace'][-1,4]==5
            checks['native TOP入力の'+entry+'を低量単一位置へ接続']=checks.get('native TOP入力の'+entry+'を低量単一位置へ接続',0)+1
            assert normal['decisions'][0]['selected_support_roots']==[]
            checks['R入力に旧C quantity不明/resetと架空板rootsを混ぜない']=checks.get('R入力に旧C quantity不明/resetと架空板rootsを混ぜない',0)+1
        # ----------------------------------------
        # C原根拠はsyntheticの価格基準だけnativeへ同変換し、AUTO選択後も同じ辞書を保持する。
        old=packet['cases']['TOPIX']['C_OWN'];side=-1 if reflected else 1;support=(112. if reflected else 100.)*.5
        old['event'][9]=side;old['support_price'][9]=support;old['entry_quality'][9]=True;old['entry_reset'][9]=False
        old['decisions']=[dict(row=9,normal_row=9,raw_row=9,raw_seq=209,side=side,support_price=support,
            selected_support_roots=[dict(anchor_raw_seq=201,support_price=support)],episode=('人工旧C',201))]
        packet['measured']['TOPIX']['states']['0.2'][9]=2*side
        cfg=dict(cfg,mode='AUTO');normal=SELECT.build(packet,'TOPIX',cfg)
        assert normal['entry_families'][9]==1 and normal['decisions'][-1]==old['decisions'][0]
        p=prepared['TOPIX'];out=artificial.INTERFACE.play(p,normal,cfg,quantity=5,finish=False,python=True)
        check='AUTOのC支持とepisodeは入力同辞書exactのまま接続';checks[check]=checks.get(check,0)+1
        assert not np.any((out['target_trace'][:,0]>0)&(out['target_trace'][:,1]>0))
        checks['C/Rが同時両建てを作らず単一位置を共有']=checks.get('C/Rが同時両建てを作らず単一位置を共有',0)+1
    assert before=={p:common.digest(common.ROOT/p) for p in before}
    common.save(target,dict(全合格=True,人工専用=True,検査件数=checks,source_SHA256=before,開始終端source一致=True,
        正式input読取=0,新金融再生=0,原板読取=0,API取得=0,
        限界='入力factory tick1をnativeへ比例変換した人工。実場で全24条件が発火したことは示していない。'))
    print('入力/執行結合人工 '+str(sum(checks.values()))+'件',flush=True)


if __name__=='__main__':main()
