"""入口審査後の実sideだけの反転を、独立会計と旧純期待へ接続する。"""

from __future__ import annotations

import ast
from fractions import Fraction
import hashlib
import importlib
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
BASE=HERE.parents[1]
ROOT=BASE.parents[1]
OLD=ROOT/'work/quantity_execution_20261015'
OLD_AUDIT=OLD/'audit/owned'
sys.path.insert(0,str(OLD_AUDIT))
from cash_reference import PRODUCTS, order_fee
from execution_expectations import fixtures
from connect_execution_v2 import materialize, select_config, check_parent, prefix_checks


def sha(path: Path) -> str:
    """
    機能: 小sourceを指紋化する。
    引数: path(Path)。
    返り値: str SHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(path: Path) -> ast.Module:
    """
    機能: sourceのASTを取得する。
    引数: path(Path)。
    返り値: ast.Module。
    """
    return ast.parse(path.read_text(encoding='utf-8'))


def reversed_material(symbol: str, actual_side: int, ticks: list[int]) -> tuple[dict,dict,dict]:
    """
    機能: 実side基準の価格経路と逆符号の元proxyを別々に固定する。
    引数: symbol(str)、actual_side(int)、ticks(list[int])。
    返り値: tuple 原配列・元公開feature・時刻方針。
    """
    arrays,signal,policy=materialize(symbol,actual_side,ticks)
    signal['events'][:,3]=-actual_side
    source_side=-actual_side
    bidq,askq=(20.,10.) if source_side==1 else (10.,20.)
    signal['events'][:,4:6]=10.
    signal['events'][:,6]=bidq;signal['events'][:,7]=askq
    arrays['bid_qty'][:]=bidq;arrays['ask_qty'][:]=askq
    return arrays,signal,policy


def fixed_time_identity() -> tuple[int,list[dict]]:
    """
    機能: 時刻と注文分割を固定した逆売買の会計恒等式を純計算する。
    引数: なし。
    返り値: tuple 確認数・例。新アルゴリズムの損益予測には使わない。
    """
    checks=0;examples=[]
    for p in PRODUCTS:
        for side in (1,-1):
            for move in (-4,0,4):
                for width in (1,3):
                    d=side*move*p.tick*p.quantity*p.multiplier
                    crossing=Fraction(1+width,2)*p.tick*p.quantity*p.multiplier
                    fees=2*order_fee(p,p.quantity)
                    old=d-crossing-fees;reverse=-d-crossing-fees
                    assert old+reverse==-2*(crossing+fees)
                    assert reverse==-old-2*(crossing+fees)
                    if move==0:assert old==reverse<0
                    checks+=3 if move==0 else 2
                    examples.append(dict(商品=p.symbol,方向=side,中値進行T=move,返済幅T=width,
                                         固定時刻旧net=float(old),固定時刻逆net=float(reverse),両方に掛かる横断と料=float(crossing+fees)))
    return checks,examples


def main() -> None:
    """
    機能: 完成済みのengine/catalog subsetだけを独立に接続する。
    引数: なし。
    返り値: None。金融・実入力は読まない。最終九源は人工完成後に別途束縛する。
    """
    subset={name:sha(BASE/name) for name in ('engine.py','catalog.py')}
    old_code=(OLD/'engine.py').read_text(encoding='utf-8')
    expected=old_code.replace("chosen.append((row,index,d,typ,event[j['episode']]))","chosen.append((row,index,d*config['direction_multiplier'],typ,event[j['episode']]))")
    assert ast.dump(ast.parse(expected),include_attributes=False)==ast.dump(tree(BASE/'engine.py'),include_attributes=False)
    old_run=next(x for x in tree(OLD/'engine.py').body if isinstance(x,ast.FunctionDef) and x.name=='_run')
    new_run=next(x for x in tree(BASE/'engine.py').body if isinstance(x,ast.FunctionDef) and x.name=='_run')
    assert ast.dump(old_run,include_attributes=False)==ast.dump(new_run,include_attributes=False)
    private=HERE/'完成経済subsetと旧基準の私有複製';private.mkdir(exist_ok=True)
    for name in ('engine.py','catalog.py'):(private/name).write_bytes((BASE/name).read_bytes())
    (private/'baseline_engine.py').write_bytes((OLD/'engine.py').read_bytes())
    (private/'baseline_catalog.py').write_bytes((OLD/'catalog.py').read_bytes())
    sys.path.insert(0,str(private))
    catalog=importlib.import_module('catalog');engine=importlib.import_module('engine')
    baseline_catalog=importlib.import_module('baseline_catalog')
    sys.modules['catalog']=baseline_catalog
    baseline=importlib.import_module('baseline_engine')
    sys.modules['catalog']=catalog
    for a,b in zip(baseline_catalog.configs(),catalog.configs()):
        actual=dict(b);actual.pop('direction_multiplier')
        actual['id']=actual['id'].replace('QREVERSE_','QEXEC_',1)
        assert actual==a
    checks=14;accounts=0;records=[];prefix=0
    for fixture in fixtures():
        p=next(x for x in PRODUCTS if x.symbol==fixture['symbol'])
        for entry in range(3):
            arrays,signal,policy=reversed_material(p.symbol,fixture['side'],fixture['ticks'])
            saved=signal['events'].copy()
            out=engine.simulate(arrays,signal,p.symbol,0.,2000.,float(p.tick),policy,select_config(catalog,entry,fixture['mode']))
            checks+=check_parent(out,fixture);accounts+=1
            np.testing.assert_array_equal(signal['events'],saved)
            assert out['orders'][0,5]==-saved[0,3]
            checks+=2
            if entry==2:
                count=prefix_checks(engine,catalog,fixture,out,arrays,signal,policy)
                checks+=count;prefix+=count
            records.append(dict(経路=fixture['name'],入口=entry,元proxy方向=int(saved[0,3]),実side=fixture['side'],期待net=float(fixture['net'])))
    # Cの数量を実sideで選び直す実装なら、この二対照は逆の採否になる。
    for source in (1,-1):
        for same in (9.,10.,11.):
            arrays,signal,policy=reversed_material('TOPIX',-source,[-1,-1,2,1,0,0])
            bidq,askq=(same,10.) if source==1 else (10.,same)
            signal['events'][:,6:8]=[bidq,askq]
            arrays['bid_qty'][:]=bidq;arrays['ask_qty'][:]=askq
            out=engine.simulate(arrays,signal,'TOPIX',0.,2000.,.5,policy,select_config(catalog,2,0))
            assert (len(out['orders'])>0)==(same>=10.)
            if same>=10.:assert out['orders'][0,5]==-source
            checks+=2
    # 同じ旧入口でも、反転後の出口判断は旧返済時刻を流用しない。
    comparisons=[]
    for p in PRODUCTS:
        for source_side in (1,-1):
            arrays,signal,policy=materialize(p.symbol,source_side,[-1,-1,-3,-4,-3,-3])
            old=baseline.simulate(arrays,signal,p.symbol,0.,2000.,float(p.tick),policy,select_config(baseline_catalog,0,0))
            reverse=engine.simulate(arrays,signal,p.symbol,0.,2000.,float(p.tick),policy,select_config(catalog,0,0))
            assert old['parent'][0]['exit_row']==3 and reverse['parent'][0]['exit_row']==4
            assert old['parent'][0]['side']==source_side and reverse['parent'][0]['side']==-source_side
            expected_old=-4*p.tick*p.quantity*p.multiplier-2*order_fee(p,p.quantity)
            expected_new=p.tick*p.quantity*p.multiplier-2*order_fee(p,p.quantity)
            assert old['summary']['収支']==float(expected_old)
            assert reverse['summary']['収支']==float(expected_new)
            entry_index,exit_index=1,3
            e=arrays['bid'][entry_index] if source_side>0 else arrays['ask'][entry_index]
            x=arrays['ask'][exit_index] if source_side>0 else arrays['bid'][exit_index]
            fixed=-source_side*(Fraction(str(x))-Fraction(str(e)))*p.quantity*p.multiplier-2*order_fee(p,p.quantity)
            assert fixed!=expected_new
            comparisons.append(dict(商品=p.symbol,元side=source_side,旧返済原行=3,反転再判定返済原行=4,
                                    旧net=float(expected_old),旧時刻に固定した逆net=float(fixed),反転アルゴnet=float(expected_new)))
            checks+=5
    identity_checks,identities=fixed_time_identity();checks+=identity_checks
    assert subset=={name:sha(BASE/name) for name in subset}
    proof=dict(全合格=True,source_SHA256=subset,確認数=checks,純具体口座=accounts,接頭確認数=prefix,
        元源_SHA256={name:sha(OLD/name) for name in ('engine.py','catalog.py')},
        具体経路=records,固定時刻逆売買の恒等式=identities,再判定で返済時刻が変わる純反例=comparisons,
        金融=0,原入力=0,原NPZ=0,旧金融結果=0,台帳=0,API=0,
        範囲='完成engine/catalog subsetだけ。更新中artificialを含む最終九源固定・登録は別。旧純期待と同一の約定/費用/出口規則を実sideから再計算。',
        重要区別='同時刻逆売買の会計恒等式を反転アルゴnetへ適用しない。元C審査後にsideだけ反転、元保存eventsは不変更。',
        独立源_SHA256=sha(Path(__file__)))
    output=HERE/'同入口審査後のside反転と新出口再判定の独立SOURCE_ONLY接続.json'
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,確認数=checks,path=str(output),SHA256=sha(output)),ensure_ascii=False))


if __name__=='__main__':main()
