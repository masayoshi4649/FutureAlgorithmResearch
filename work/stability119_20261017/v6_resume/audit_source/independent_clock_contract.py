"""高水位資格と原44列の接続を独立した人工行だけで検証する。"""

import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile

import numpy as np


HERE = Path(__file__).resolve().parent
V6 = HERE.parent
ROOT = V6.parents[2]
MIRROR = V6/'legacy_root'


def module(path: Path, name: str) -> object:
    """
    機能: I/Oを起動しない数値又は抽出部品を一意名で接続する。
    引数: path(Path)、name(str)はSOURCEとmodule名。
    返り値: objectは部品。実市場や既存cacheは読まない。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value
    spec.loader.exec_module(value)
    return value


def correction(path: Path) -> object:
    """
    機能: 旧訂正関数の同一ASTと明示CHANGED定数だけを接続する。
    引数: path(Path)は所有SOURCE。
    返り値: objectは44列中2列だけを保守的に訂正する関数。
    """
    tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    changed=next(v for v in tree.body if isinstance(v,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CHANGED' for t in v.targets))
    fn=next(v for v in tree.body if isinstance(v,ast.FunctionDef) and v.name=='correct_arrays')
    namespace={'np':np,'CHANGED':ast.literal_eval(changed.value)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),str(path),'exec'),namespace)
    return namespace['correct_arrays']


def main() -> None:
    """
    機能: 時計資格・原行同一性・LP後reset・出来高票を人工の具体例で確認する。
    引数: なし。
    返り値: None。独立証跡のみ保存する。金融・元stage・元原本は使用しない。
    """
    paths=[V6/'clock_adapter.py',MIRROR/'work/wave_v103/input/core.py',MIRROR/'work/wave_v103/input_v2/correction.py',MIRROR/'work/wave_v106/trade_gate/votes.py',MIRROR/'work/wave_v8/raw_features.py',MIRROR/'work/wave_v23/depth_features.py']
    sources={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    clock=module(paths[0],'_independent_h_clock')
    core=module(paths[1],'_independent_h_raw44')
    correct=correction(paths[2]);votes=module(paths[3],'_independent_h_votes')
    extract=module(paths[4],'_independent_h_raw8');depth=module(paths[5],'_independent_h_depth23')
    base=datetime(2026,10,14,4,tzinfo=timezone(timedelta(hours=9)))
    start=(base-timedelta(hours=11)).timestamp();end=(base+timedelta(hours=1,minutes=55)).timestamp()
    checks=[]
    def check(name: str, condition: bool) -> None:
        """
        機能: 独立期待との一致を意味付きで記録する。
        引数: name(str)、condition(bool)は確認内容と判定。
        返り値: None。不一致なら金融へ進めず停止する。
        """
        assert condition,name
        checks.append(name)

    def row(seconds: int, volume: int) -> dict:
        """
        機能: 原clockと全十段を持つ人工行を構成する。
        引数: seconds/volume(int)は基準からの秒と累計出来高。
        返り値: dictは一つの合成原行。
        """
        stamp=(base+timedelta(seconds=seconds)).isoformat()
        raw={'Symbol':'TEST','SymbolName':'人工TOPIX','Exchange':2,'CurrentPriceTime':stamp,'CurrentPrice':4000.,'TradingVolume':volume,'TradingVolumeTime':stamp,'TradingValue':volume*4000.,'TradingValueTime':stamp}
        for i in range(1,11):
            raw['Buy'+str(i)]={'Price':4000.-.5*i,'Qty':10.+i}
            raw['Sell'+str(i)]={'Price':4000.+.5*(i-1),'Qty':20.+i}
        return raw

    rows=[row(s,100+i) for i,s in enumerate([0,1,-86400+2,-86400+3,1,2,3,4,5])]
    unchanged=deepcopy(rows)
    view,reasons=clock.transform(rows,start,end)
    check('古日付二行だけ不採用で元高水位同値に復帰',reasons==[0,0,12,12,0,0,0,0,0])
    check('原行辞書と全原時計を不変更',rows==unchanged)
    check('表示は時計資格だけ変更し全数量等を保持',all({k:v for k,v in raw.items() if k!='CurrentPriceTime'}=={k:v for k,v in out.items() if k!='CurrentPriceTime'} for raw,out in zip(rows,view)))
    check('同clock後半も原順で採用',view[4]['CurrentPriceTime']==rows[1]['CurrentPriceTime'])
    for cut in (1,2,3,4,5,8):
        prefix=clock.transform(rows[:cut],start,end)
        future=deepcopy(rows)
        for raw in future[cut:]:raw['CurrentPriceTime']=(base+timedelta(days=200)).isoformat();raw['CurrentPrice']=99999.
        check('接頭'+str(cut),prefix==(view[:cut],reasons[:cut]) and clock.transform(future,start,end)[0][:cut]==view[:cut])
    for bad in (None,False,0.,-1.,float('nan'),float('inf')):
        raw=row(100,200);raw['CurrentPrice']=bad
        _,water,reason=clock.step(raw,base.timestamp(),start,end)
        check('無効Last未来時計は水位不更新:'+repr(bad),water==base.timestamp() and bool(reason&2))
    for bad in (None,'不正',base.replace(tzinfo=None).isoformat()):
        raw=row(100,200);raw['CurrentPriceTime']=bad
        _,water,reason=clock.step(raw,base.timestamp(),start,end)
        check('不明時計は水位不更新:'+repr(bad),water==base.timestamp() and bool(reason&1))
    out,water,reason=clock.step(row(7200,200),base.timestamp(),start,end)
    check('場外未来時計は水位不更新',water==base.timestamp() and bool(reason&4) and out['CurrentPriceTime'] is None)
    crossed=row(1,200);crossed['Buy1']['Price']=5000.
    _,water,reason=clock.step(crossed,base.timestamp(),start,end)
    check('BBO資格とLast時計資格は独立',reason==0 and water==base.timestamp()+1)

    # ----------------------------------------
    # 旧原44列には未加工全原行を渡し、normalだけ適格原seqへ対応させる。
    accepted=np.flatnonzero(np.asarray(reasons)==0)
    normal={'seq':accepted.astype(np.int64),'time_s':np.asarray([clock.price_clock(rows[i]['CurrentPriceTime']) for i in accepted]),'price':np.full(len(accepted),4000.),'bid':np.full(len(accepted),3999.5),'ask':np.full(len(accepted),4000.)}
    raw,diagnosis=core.extract_rows(enumerate(rows),start,end,normal)
    revised,delta_diagnostic=correct(raw)
    check('全原seqを欠落なく保持',np.array_equal(raw['raw_seq'],np.arange(len(rows))))
    check('normal対応は適格原seqだけ',np.array_equal(revised['execution_to_raw_index'],accepted))
    check('raw44は古日付を補正しない',revised['price_time_s'][2]==base.timestamp()-86400+2)
    check('訂正は42列を完全保持',delta_diagnostic['不変配列数']==42 and all(np.array_equal(raw[k],revised[k],equal_nan=True) for k in raw if k not in ('volume_delta_usable','volume_delta')))
    check('stale原行は価格reset8と出来高不適格',all((revised['price_reset_reason'][i]&8)!=0 and not revised['volume_delta_usable'][i] for i in (2,3)))
    check('高水位復帰直後の出来高を救済しない',not revised['volume_delta_usable'][4] and math.isnan(revised['volume_delta'][4]))
    check('正常隣接復帰後だけ出来高資格復帰',bool(revised['volume_delta_usable'][5]) and revised['volume_delta'][5]==1.)
    context=votes.context(revised)
    candidate=votes.measure(revised,context,5,60,1)
    check('staleを含むW60は既知へ昇格しない',not candidate['known'] and not candidate['accepted'])

    # ----------------------------------------
    # 表示ファイルを旧板/depthへ通し、同clock封印と原seqの意味を確かめる。
    with tempfile.TemporaryDirectory(dir=HERE) as directory:
        source=Path(directory)/'original.jsonl';target=Path(directory)/'view.jsonl'
        payload=b''.join((json.dumps(v,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8') for v in rows)
        source.write_bytes(payload)
        saved=clock.write_view(source,target,hashlib.sha256(payload).hexdigest(),start,end)
        decoded=[json.loads(line) for line in target.read_bytes().splitlines()]
        check('派生表示は同原行数かつ全採否一致',saved['rows']==len(rows) and decoded==view and saved['rejected_rows']==2)
        check('人工元bytesを一切変更しない',source.read_bytes()==payload)
        quotes=[]
        frame,audit=extract.extract_features(target,'TOPIX','2026-10-13_Night',quotes=quotes)
        extended,depth_audit=depth.extract(target,'TOPIX','2026-10-13_Night',frame)
        check('旧板quoteは適格原seqだけを保持',[v['seq'] for v in quotes]==accepted.tolist())
        check('旧特徴の公開原seqは参照末尾より後',bool((frame.source_last_seq<frame.seq).all()))
        check('旧depthと公開行の完全一致',np.array_equal(extended.seq.to_numpy(),frame.seq.to_numpy()))
        check('EOFの最終同clockブロックを公開しない',audit['未解放末尾ブロック時刻']==rows[-1]['CurrentPriceTime'] and int(frame.seq.iloc[-1])==8)
        cut=7
        prefix=Path(directory)/'prefix.jsonl';prefix.write_bytes(b''.join(target.read_bytes().splitlines(keepends=True)[:cut]))
        short,_=extract.extract_features(prefix,'TOPIX','2026-10-13_Night')
        expected=frame.loc[frame.seq<cut].reset_index(drop=True)
        check('旧公開特徴の接頭不変',short.reset_index(drop=True).equals(expected))
    ending={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assert ending==sources
    proof={'全合格':True,'確認':checks,'source_SHA256':sources,'source_end_SHA256':ending,'原本読取':0,'既stage本文読取':0,'金融':0,'登録':0,'原source変更':0,'留保':'新h入力資格は旧f無修正入力と異なる。原時計は復元せず、真受信時計も証明しない。'}
    result=HERE/'原時計資格とLP出来高reset及び原seq接続の独立人工.json'
    assert not result.exists()
    result.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'確認':len(checks),'証跡SHA256':hashlib.sha256(result.read_bytes()).hexdigest()},ensure_ascii=False))


if __name__=='__main__':main()
