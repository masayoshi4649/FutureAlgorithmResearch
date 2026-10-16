"""完成signalを先に固定した純期待へ接続し、Native会計は他担当へ分離する。"""

from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import traceback

import numpy as np

import signal_reference as R
import signal_pure_expectations as F

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
ENGINE=ROOT/'work/e01_current_reassessment_20261015/engine'
OUTPUT=HERE/'完成signalと独立純期待及び八源不変更のSOURCE_ONLY接続.json'
OWNER_SHA='f1ba3ca610322e74d787faccac041694a1b9c9cc80305b3b32a223e7d1464eaf'
SIGNAL_SHA='9a037e59b9f6f5c6c0b8b8ca676e6351d7ccc0f318251b94b24b0418f0ddd892'
COUNTS=Counter()


def check(ok:bool,label:str) -> None:
    """
    機能: 完成源と独立期待の条件を分類して確認する。
    引数: ok(bool)、label(str) は判断と分類。
    返り値: None。不一致は停止する。
    """
    assert bool(ok),label
    COUNTS[label]+=1


def args(points:list[R.Observation],tick:float) -> tuple:
    """
    機能: 純観測をownerの公開API配列へ機械的に変換する。
    引数: points(list[Observation])、tick(float) は人工と観測呼値。
    返り値: tuple はgenerate引数。owner源から期待を作らない。
    """
    arr=lambda name,dtype:np.asarray([getattr(p,name) for p in points],dtype=dtype)
    return (arr('bid',float),arr('ask',float),arr('normal',bool),arr('high',float),arr('low',float),
        arr('bucket',np.int64),arr('confirmed',np.int64),arr('volume_known',bool),arr('price_known',bool),
        arr('volume_gate',bool),arr('price_gate',bool),arr('interval_known',bool),arr('new_up',np.int64),arr('new_down',np.int64),tick,2)


def compare(actual:tuple,events:list[dict],state:R.Reference,points:list[R.Observation]) -> None:
    """
    機能: sourceの16列候補・公開消費・不成立終了を独立stateと照合する。
    引数: actual(tuple)、events(list[dict])、state(Reference)、points(list[Observation]) は出力と独立期待。
    返り値: None。Native実注文や勝敗の確認とは称しない。
    """
    rows,breakpoints,consumed,retired=actual
    check(rows.shape==(len(events),16) and breakpoints.ndim==2 and breakpoints.shape[1]==9,'候補16列と診断9列の完成schema')
    episode_map={};inverse={}
    keys={0:'row',1:'mode',2:'side',4:'bucket',5:'level',6:'break_row',7:'b0',8:'a0',9:'opposite_row',10:'bp',11:'ap',12:'confirmed',13:'opposite_lower'}
    for row,e in zip(rows,events):
        for col,key in keys.items():
            if e[key] is None:check(np.isnan(row[col]),'mode①②の未測反対基準をNaN保持')
            else:check(row[col]==e[key],'独立認定行と固定L_BBO_新反対票の一致')
        identifier=int(row[3]);reference=e['episode']
        if identifier in episode_map:check(episode_map[identifier]==reference,'同episode各modeは同じ構造識別子')
        else:episode_map[identifier]=reference
        if reference in inverse:check(inverse[reference]==identifier,'再武装前の同episode識別子を取り直さない')
        else:inverse[reference]=identifier
        check(row[14]==(e['opposite_row']-1 if e['mode']==2 else -1),'反対下限の前normal行であり最後新票seqではない')
        check(row[15]==e['row'],'公開行を過去に巻戻さない')
        if e['mode']==2:
            check(e['break_row']<e['opposite_row']<e['row'],'突破後の新反対票と後の認定row')
    for direction,side in enumerate((1,-1)):
        episode=state.episodes[side]
        for mode in range(3):
            check(bool(consumed[direction,mode])==(mode in episode.used),'公開済消費と不成立終了を別に確認')
            check(bool(retired[direction,mode])==(mode in state.blocked_probes[side]),'③終了は公開と区別し同episode再取得禁止')
    for record in breakpoints:
        row,_,side,mode,level,bucket,confirmed,ended,reason=record
        p=points[int(row)]
        check(int(confirmed)==p.confirmed and int(bucket)==p.bucket and int(side) in (-1,1) and int(mode) in (0,1,2),'break診断の当時row_L_bucket系譜')
        if ended:check(mode==2 and int(reason) in (1,2,3),'正常必要known逆行の③終了は未公開状態')
        else:check(int(confirmed)<int(row),'Lは接触前に認定される')


def main() -> None:
    """
    機能: 14源署名を確認し、signalsだけを私有JIT/Pythonと独立期待へ接続する。
    引数: なし。
    返り値: None。Native会計・実入力・正式登録は担当外のまま。
    """
    assert not OUTPUT.exists()
    art_saved=(ENGINE/'確定閉足と現在九Native及び実料支持接頭の人工検査.json').read_bytes()
    check(hashlib.sha256(art_saved).hexdigest()==OWNER_SHA,'完成owner人工の根指定署名')
    art=json.loads(art_saved);signatures=art['source_SHA256']
    check(art['全合格'] and len(signatures)==14,'完成経済十四源の境界だけを束縛')
    snapshot=HERE/'完成signal接続の私有十四源';snapshot.mkdir(exist_ok=False)
    for relative,digest in signatures.items():
        saved=(ROOT/relative).read_bytes()
        check(hashlib.sha256(saved).hexdigest()==digest,'完成十四源の現在指紋')
        (snapshot/Path(relative).name).write_bytes(saved)
    check(signatures['work/e01_current_reassessment_20261015/engine/signals.py']==SIGNAL_SHA,'完成signalの根裁定後指紋')
    subset=json.loads((HERE/'確定足と当時票差及び厳密結合八源subsetの独立純人工_v3.json').read_bytes())
    for relative,digest in subset['source_SHA256'].items():
        check(signatures[relative]==digest,'既684subsetの八源不変更')
    spec=importlib.util.spec_from_file_location('independent_current_signal',snapshot/'signals.py')
    owner=importlib.util.module_from_spec(spec);sys.modules[spec.name]=owner;spec.loader.exec_module(owner)
    arrays=prefixes=0
    for name,(original,_) in F.fixtures().items():
        for points in (original,[R.mirror(p) for p in original]):
            events,state=R.run(points,1.)
            python=owner.generate.py_func(*args(points,1.));compiled=owner.generate(*args(points,1.))
            for a,b in zip(python,compiled):
                np.testing.assert_array_equal(a,b,err_msg=name+' Python/JIT');arrays+=1
            compare(python,events,state,points)
            for length in range(1,len(points)+1):
                part_events,part_state=R.run(points[:length],1.)
                result=owner.generate.py_func(*args(points[:length],1.))
                compare(result,part_events,part_state,points[:length])
                np.testing.assert_array_equal(result[0],python[0][python[0][:,0]<length],err_msg=name+' 接頭候補')
                np.testing.assert_array_equal(result[1],python[1][python[1][:,0]<length],err_msg=name+' 接頭診断')
                prefixes+=1;arrays+=2
    for relative,digest in signatures.items():
        check(hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==digest,'完成十四源開始終端不変')
    value=dict(全合格=True,状態='SOURCE_ONLY。signals完成接続、Native会計と正式spec/登録は別監査待ち。',
        検査数=sum(COUNTS.values()),分類=dict(COUNTS),配列照合=arrays,接頭数=prefixes,
        source_SHA256=signatures,owner人工SHA256=OWNER_SHA,
        独立純期待SHA256=hashlib.sha256((HERE/'突破と反対活動の入口状態の独立純期待.json').read_bytes()).hexdigest(),
        監査source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        接続='L認定→必要known突破BBO固定→①②1T又は③新反対票後2T→現在資格→各入口一公開。買売鏡像/全接頭一致。',
        金融前の精密化='③のB0再取得を正常/必要known切断又は>1T逆行後に禁止。公開consumedと不成立retiredを別stateとして確認。',
        分離='busy/費用拒否・FAK失効後も候補構造の消費は戻らない。実受理・FAK順序と支持線/親会計はcause担当で未完了。',
        新二場='この作業では本文未読。過去試行の既読照合前なので正式な未見holdoutとは称しない。',
        実入力=0,元cache=0,金融本文=0,金融=0,NPZ=0,実台帳=0,原board=0,API=0,旧源JIT書込=0,共有編集=0)
    OUTPUT.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('完成signal接続 '+str(value['検査数'])+'合格 / '+str(arrays)+'配列 / '+str(prefixes)+'接頭。SHA '+hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),flush=True)


if __name__=='__main__':
    try:main()
    except Exception:
        p=HERE/'完成signal接続初版False.json';assert not p.exists()
        p.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),分類=dict(COUNTS),元cache=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
