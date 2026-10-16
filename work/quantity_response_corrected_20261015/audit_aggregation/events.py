"""生成済み66出力の各一読だけで数量分類・終点・追加flagを独立監査する。"""

import argparse
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone
from fractions import Fraction
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
from statistics import median
import sys
import traceback

import numpy as np

sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding='utf-8')
HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[1]
PLAN=HERE/'生成出力66だけの分類と追加欄の一読固定.json'
EXPECTED_FIELDS=['type','episode','start_i','pub_i','d','bid','ask','bid_q0','ask_q0','bid_q_at_public','ask_q_at_public','min_bid_q','min_ask_q',
 'opposite_q0','opposite_q_at_public','opposite_min_q','quantity_ratio','minimum_quantity_ratio','quantity_group','total_volume','npositive',
 'first_positive_i','fresh_price_time','volume_after_price','volume_clock_known','first_positive_fresh_price_time',
 'first_positive_volume_after_price','first_positive_volume_clock_known','start_raw_seq','pub_raw_seq','pub_price_time_s']
ARRAY_NAMES={'events','outcomes','analysis_outcomes','publication_raw_seq','publication_time_s','terminal_raw_seq','terminal_time_s','terminal_bid','terminal_ask','terminal_price_reason'}
COUNTS=('n','plus','minus','unknown','eof','window_end','resolved')
GROUPS=('type0_all','type0_reached','type1_all','type1_decreased','type1_maintained','type1_never_below','type1_recovered')
CHECKS=0


def sha(path: Path) -> str:
    """
    機能: source又は私有小証跡の指紋を返す。
    引数: path(Path)はsource又は自所有JSON。出力NPZの別hashに使わない。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path,value: dict) -> None:
    """
    機能: 私有新資料へだけ非有限JSON禁止で保存する。
    引数: path(Path)、value(dict)は新規保存先と内容。
    返り値: None。成功/Falseを上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def equal(value: object,expected: object) -> None:
    """
    機能: 独立件数/分数/中央値を保存groupへ照合する。
    引数: value/expected(object)は値と期待値。
    返り値: None。葉の検査数を加算する。
    """
    global CHECKS
    if isinstance(expected,dict):
        assert set(value)==set(expected)
        for k,v in expected.items():equal(value[k],v)
    elif expected is None:assert value is None;CHECKS+=1
    elif isinstance(expected,(int,float,Fraction)):
        assert isinstance(value,(int,float,np.number)) and not isinstance(value,(bool,np.bool_)) and math.isfinite(float(value))
        assert abs(float(value)-float(expected))<=max(1e-12,abs(float(expected))*1e-12),(value,expected);CHECKS+=1
    else:assert value==expected;CHECKS+=1


def group(events: np.ndarray,outcomes: np.ndarray,columns: dict,indices: list,with_median: bool=True) -> dict:
    """
    機能: 保存行をPython Counterとstatistics.medianで独立分類する。
    引数: events/outcomes(ndarray)、columns(dict)、indices(list[int])、with_median(bool)。
    返り値: dictは件数・率・任意中央値。root run.groupは呼ばない。
    """
    count=Counter(int(outcomes[i,0]) for i in indices);plus=count[1];minus=count[-1]
    result=dict(n=len(indices),plus=plus,minus=minus,unknown=count[0],eof=count[2],window_end=count[3],resolved=plus+minus,
        rate=float(Fraction(plus,plus+minus)) if plus+minus else None)
    if with_median:
        for name in ('opposite_q0','quantity_ratio','minimum_quantity_ratio','total_volume','npositive'):
            result['median_'+name]=float(median([float(events[i,columns[name]]) for i in indices])) if indices else None
    return result


def add(accumulator: dict,key: str,g: dict) -> None:
    """
    機能: 追加群の件数だけを合算する。
    引数: accumulator(dict)、key(str)、g(dict)は集約先と群。
    返り値: None。率や中央値を足さない。
    """
    if key not in accumulator:accumulator[key]={k:0 for k in COUNTS}
    for k in COUNTS:accumulator[key][k]+=g[k]


def completed(accumulator: dict) -> dict:
    """
    機能: 件数集約後に解決例率を算出する。
    引数: accumulator(dict)は件数だけの集約。
    返り値: dictは分子/分母と率。
    """
    return {key:dict(value,rate=float(Fraction(value['plus'],value['resolved'])) if value['resolved'] else None) for key,value in accumulator.items()}


def inspect(meta: dict,arrays: dict) -> tuple[dict,dict]:
    """
    機能: 一出力の型・群・同episode・終点成立を原入力無しで検算する。
    引数: meta/arrays(dict)は固定目録と一読した新出力。
    返り値: tuple[dict,dict]は主groupと追加欄。先着前の全経路は未保存として留保する。
    """
    global CHECKS
    assert set(arrays)==ARRAY_NAMES and meta['fields']==EXPECTED_FIELDS and meta['outcome_fields']==['code','end_i']
    ev=arrays['events'];original=arrays['outcomes'];out=arrays['analysis_outcomes'];n=len(ev);col={name:i for i,name in enumerate(EXPECTED_FIELDS)}
    assert n==meta['events']['n'] and ev.shape==(n,31) and original.shape==out.shape==(n,2)
    assert ev.dtype==original.dtype==out.dtype==np.float64
    assert np.isfinite(ev).all() and np.isfinite(original).all() and np.isfinite(out).all()
    for name,a in arrays.items():
        if name in ('events','outcomes','analysis_outcomes'):continue
        assert a.shape==(n,)
        expected=np.uint16 if name=='terminal_price_reason' else np.int64 if name in ('publication_raw_seq','terminal_raw_seq') else np.float64
        assert a.dtype==expected
    ints=[name for name in EXPECTED_FIELDS if name not in ('bid','ask','bid_q0','ask_q0','bid_q_at_public','ask_q_at_public','min_bid_q','min_ask_q',
       'opposite_q0','opposite_q_at_public','opposite_min_q','quantity_ratio','minimum_quantity_ratio','total_volume','pub_price_time_s')]
    for name in ints:assert np.all(ev[:,col[name]]==np.floor(ev[:,col[name]]))
    for name in ('type','quantity_group','fresh_price_time','volume_after_price','volume_clock_known','first_positive_fresh_price_time','first_positive_volume_after_price','first_positive_volume_clock_known'):
        assert np.isin(ev[:,col[name]],(0,1)).all()
    assert np.isin(ev[:,col['d']],(-1,1)).all()
    assert np.isin(original[:,0],(-1,0,1,2)).all() and np.isin(out[:,0],(-1,0,1,2,3)).all()
    assert np.all(ev[:,col['pub_i']]>ev[:,col['start_i']]) and np.all(out[:,1]>=ev[:,col['pub_i']])
    assert np.all(out[:,1]<meta['raw_rows'])
    np.testing.assert_array_equal(ev[:,col['pub_raw_seq']].astype(np.int64),arrays['publication_raw_seq'])
    np.testing.assert_array_equal(ev[:,col['pub_price_time_s']],arrays['publication_time_s'])
    assert np.all(arrays['terminal_raw_seq']>=arrays['publication_raw_seq'])
    date,period=meta['session'].split('_');dt=datetime.fromisoformat(date).replace(tzinfo=timezone(timedelta(hours=9)))
    boundary=(dt.replace(hour=15,minute=40) if period=='Day' else (dt+timedelta(days=1)).replace(hour=5,minute=55)).timestamp()
    expected=original.copy();window=(original[:,0]==0)&np.isfinite(arrays['terminal_time_s'])&(arrays['terminal_time_s']>=boundary)
    expected[window,0]=3;np.testing.assert_array_equal(out,expected);np.testing.assert_array_equal(original[:,1],out[:,1])
    assert np.all(arrays['terminal_price_reason'][original[:,0]==0]!=0)
    assert np.all(arrays['terminal_price_reason'][np.isin(original[:,0],(-1,1,2))]==0)
    tick=.5 if meta['symbol']=='TOPIX' else 10.
    by_episode={};masks={name:[] for name in GROUPS};extra={}
    for i,row in enumerate(ev):
        kind=int(row[col['type']]);ep=int(row[col['episode']]);side=int(row[col['d']]);pub=int(row[col['pub_i']]);start=int(row[col['start_i']])
        assert kind not in by_episode.setdefault(ep,{})
        by_episode[ep][kind]=i
        first=int(row[col['first_positive_i']]);assert start<first<=pub
        assert row[col['bid']]<row[col['ask']] and row[col['bid_q0']]>0 and row[col['ask_q0']]>0
        q0=row[col['ask_q0'] if side>0 else col['bid_q0']]
        q=row[col['ask_q_at_public'] if side>0 else col['bid_q_at_public']]
        minimum=row[col['min_ask_q'] if side>0 else col['min_bid_q']]
        for a,b in ((row[col['opposite_q0']],q0),(row[col['opposite_q_at_public']],q),(row[col['opposite_min_q']],minimum),
                    (row[col['quantity_ratio']],q/q0),(row[col['minimum_quantity_ratio']],minimum/q0)):equal(float(a),float(b))
        assert 0<minimum<=min(q0,q) and row[col['minimum_quantity_ratio']]<=1
        assert int(row[col['quantity_group']])==int(q>=q0)
        assert row[col['total_volume']]>0 and row[col['npositive']]>=1
        if kind==0:assert pub==first and row[col['npositive']]==1
        else:assert row[col['total_volume']]>=q0
        code=int(out[i,0]);terminal=int(out[i,1]);tb=arrays['terminal_bid'][i];ta=arrays['terminal_ask'][i]
        if code in (-1,1):
            assert terminal>pub and np.isfinite(tb) and np.isfinite(ta) and 0<tb<ta
            direction=side if code==1 else -side
            assert direction*(tb-row[col['bid']])>=tick and direction*(ta-row[col['ask']])>=tick
            CHECKS+=2
        CHECKS+=9
    reached={ep for ep,parts in by_episode.items() if 1 in parts}
    for ep,parts in by_episode.items():
        assert 0 in parts
        if 1 in parts:
            a,b=parts[0],parts[1]
            np.testing.assert_array_equal(original[a],original[b]);np.testing.assert_array_equal(out[a],out[b])
            for name in ('start_i','first_positive_i','d','bid','ask','bid_q0','ask_q0','first_positive_fresh_price_time','first_positive_volume_after_price','first_positive_volume_clock_known'):
                equal(float(ev[a,col[name]]),float(ev[b,col[name]]))
            assert ev[b,col['pub_i']]>=ev[a,col['pub_i']] and ev[b,col['total_volume']]>=ev[a,col['total_volume']]
    for i,row in enumerate(ev):
        kind=int(row[col['type']]);ep=int(row[col['episode']]);high=row[col['quantity_ratio']]>=1;always=row[col['minimum_quantity_ratio']]>=1
        if kind==0:masks['type0_all'].append(i)
        if kind==0 and ep in reached:masks['type0_reached'].append(i)
        if kind==1:
            masks['type1_all'].append(i);masks['type1_maintained' if high else 'type1_decreased'].append(i)
            if high:masks['type1_never_below' if always else 'type1_recovered'].append(i)
    main={}
    for name,indices in masks.items():
        g=group(ev,out,col,indices);equal(meta['expected_groups'][name],g);main[name]=g
        for side,label in ((1,'buy'),(-1,'sell')):
            equal(meta['expected_groups']['by_side'][label][name],group(ev,out,col,[i for i in indices if ev[i,col['d']]==side]))
        for label,condition in (('one',lambda x:x==1),('wider',lambda x:x>1),('narrower',lambda x:x<1)):
            subset=[i for i in indices if condition((ev[i,col['ask']]-ev[i,col['bid']])/tick)]
            equal(meta['expected_groups']['by_spread'][label][name],group(ev,out,col,subset))
    type1=masks['type1_all']
    selections={}
    for name in ('quantity_ratio','minimum_quantity_ratio'):
        for op,fn in (('lt1',lambda x:x<1),('eq1',lambda x:x==1),('gt1',lambda x:x>1)):
            selections[name+'_'+op]=[i for i in type1 if fn(ev[i,col[name]])]
    selections.update(end_equal_never_below=[i for i in type1 if ev[i,col['quantity_ratio']]==1 and ev[i,col['minimum_quantity_ratio']]==1],
        end_above_never_below=[i for i in type1 if ev[i,col['quantity_ratio']]>1 and ev[i,col['minimum_quantity_ratio']]==1],
        end_equal_recovered=[i for i in type1 if ev[i,col['quantity_ratio']]==1 and ev[i,col['minimum_quantity_ratio']]<1],
        end_above_recovered=[i for i in type1 if ev[i,col['quantity_ratio']]>1 and ev[i,col['minimum_quantity_ratio']]<1])
    for name in ('fresh_price_time','first_positive_fresh_price_time','volume_after_price','first_positive_volume_after_price','volume_clock_known','first_positive_volume_clock_known'):
        for v in (0,1):selections[name+'_'+str(v)]=[i for i in type1 if ev[i,col[name]]==v]
    histogram=sorted({int(ev[i,col['npositive']]) for i in type1})
    for v in histogram:selections['npositive_'+str(v)]=[i for i in type1 if ev[i,col['npositive']]==v]
    for quantity,condition in (('lt1',lambda x:x<1),('eq1',lambda x:x==1),('gt1',lambda x:x>1)):
        for fresh in (0,1):
            for first_fresh in (0,1):
                for after in (0,1):
                    key=f'joint_{quantity}_fresh{fresh}_first{first_fresh}_after{after}'
                    selections[key]=[i for i in type1 if condition(ev[i,col['quantity_ratio']]) and ev[i,col['fresh_price_time']]==fresh and ev[i,col['first_positive_fresh_price_time']]==first_fresh and ev[i,col['volume_after_price']]==after]
    extra={name:group(ev,out,col,indices,False) for name,indices in selections.items()}
    for name in ('type0_all','type0_reached','type1_all'):extra[name]=group(ev,out,col,masks[name],False)
    assert extra['minimum_quantity_ratio_gt1']['n']==0
    equal(main['type1_all']['n'],sum(extra[k]['n'] for k in ('quantity_ratio_lt1','quantity_ratio_eq1','quantity_ratio_gt1')))
    return main,extra


def prepare() -> None:
    """
    機能: 公開JSON一読から保存した目録だけを用い、66新出力の一読条件を固定する。
    引数: なし。
    返り値: None。原入力/出力NPZ本文はまだ0。
    """
    path=HERE/'新出力66だけの後続監査用目録.json';value=json.loads(path.read_text(encoding='utf-8'))
    assert len(value['targets'])==66
    for item in value['targets']:
        target=(ROOT/item['events']['path']).resolve();assert target.is_relative_to(BASE/'measurement/events')
        assert target.stat().st_size==item['events']['bytes'] and item['fields']==EXPECTED_FIELDS
    save(PLAN,dict(目的='新出力66から数量群/median/flags/終点成立/同episode同値を独立再算術する。原入力再読0。',
        目録SHA256=sha(path),監査source_SHA256=sha(Path(__file__)),targets=value['targets'],必要配列=sorted(ARRAY_NAMES),
        fields=EXPECTED_FIELDS,予定出力NPZ一読=66,原入力NPZ一読=0,
        追加区分='ratio/minratioの1境界、回復内訳、fresh/firstfresh/volumeafter flags、npositive全離散値、type0全/達成集合。',
        重要限界='ratio==minratio==1は終点同量かつ初期割れなし。全区間数量不変の証明でない。全将来path未読のため最初endpoint/初回Q0到達はsource人工へ委譲。'))
    print(json.dumps(dict(prepared=True,plan_SHA256=sha(PLAN),予定出力=66,原NPZ=0),ensure_ascii=False))


def main() -> None:
    """
    機能: 固定済み新出力66を各一読して同bytes私有保全し、分類監査と追加射影を保存する。
    引数: CLI --prepare/--run(bool)は固定又は監査。
    返り値: None。元結果/原入力/金融/APIを読まない。
    """
    parser=argparse.ArgumentParser();g=parser.add_mutually_exclusive_group(required=True);g.add_argument('--prepare',action='store_true');g.add_argument('--run',action='store_true');args=parser.parse_args()
    if args.prepare:prepare();return
    plan=json.loads(PLAN.read_text(encoding='utf-8'));assert plan['監査source_SHA256']==sha(Path(__file__))
    counts=0;rows=[];totals=defaultdict(dict);copied=HERE/'output_copies';assert not copied.exists();copied.mkdir()
    try:
        for meta in plan['targets']:
            path=ROOT/meta['events']['path'];raw=path.read_bytes();counts+=1
            assert len(raw)==meta['events']['bytes'] and hashlib.sha256(raw).hexdigest()==meta['events']['SHA256']
            private=copied/path.name;assert not private.exists();private.write_bytes(raw)
            with np.load(io.BytesIO(raw),allow_pickle=False) as saved:arrays={name:saved[name] for name in saved.files}
            main_groups,extra=inspect(meta,arrays)
            row=dict(session=meta['session'],symbol=meta['symbol'],main=main_groups,additional=extra);rows.append(row)
            for period in ('all','Day' if meta['session'].endswith('_Day') else 'Night'):
                key=meta['symbol']+'_'+period
                for name,group_value in extra.items():add(totals[key],name,group_value)
            if counts%10==0:print(str(counts)+' /66 新出力だけの分類監査完了',flush=True)
        assert counts==66 and len(rows)==66
        projection=dict(全合格=True,出力NPZ一読=66,原入力NPZ=0,rows=rows,totals={k:completed(v) for k,v in totals.items()},
            限界='終点成立と保存分類の監査。先着前の全BBO/Qty経路、全数量更新なし、原field更新同期、実行可能損益は未測。')
        out=HERE/'数量境界と活動時計及び初回活動基準の独立射影.json';save(out,projection)
        proof=dict(全合格=True,plan_SHA256=sha(PLAN),監査source_SHA256=sha(Path(__file__)),目録SHA256=plan['目録SHA256'],
            出力NPZ一読=66,算術項目=CHECKS,同bytes私有保存=True,独立Median分類=True,同episode同値=True,
            終点検査='保存±1T終点の両BBO閾値成立、unknown原理由、analysis3の予定上限と排他を検算。最初性は全path未読のためsource人工に委譲。',
            追加射影SHA256=sha(out),原入力NPZ=0,原板=0,cache=0,金融=0,API=0)
        output=HERE/'六十六出力の数量分類と終点及び追加欄の独立監査.json';save(output,proof)
        print(json.dumps(dict(全合格=True,proof_SHA256=sha(output),算術項目=CHECKS,出力一読=66,原入力NPZ=0,
            totals={s:{k:v for k,v in projection['totals'][s+'_all'].items() if k in ('quantity_ratio_lt1','quantity_ratio_eq1','quantity_ratio_gt1','end_equal_never_below','end_above_never_below','end_equal_recovered','end_above_recovered','fresh_price_time_0','fresh_price_time_1','first_positive_fresh_price_time_0','first_positive_fresh_price_time_1','volume_after_price_0','volume_after_price_1','type0_all','type0_reached')} for s in ('TOPIX','NK225')}),ensure_ascii=False))
    except BaseException:
        save(HERE/'新出力分類監査_初回False.json',dict(全合格=False,原因=traceback.format_exc(),出力本文読取=counts,再開は私有copyだけ=True,原入力NPZ=0,金融=0));raise


if __name__=='__main__':main()
