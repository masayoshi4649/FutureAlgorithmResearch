"""保存した観測出力だけを一読し、方向採点の分子分母を別実装で照合する。"""

from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
from fractions import Fraction
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OWN=HERE/'result_audit'
RESULT=HERE/'measurement/方向予測の採点結果.json'
PLAN=OWN/'保存観測だけの一読独立集計の固定.json'
SOURCE_NAMES=('plan.py','measure.py','input_contract.py','engine.py','artificial.py',
              'aggregate.py','artificial_aggregate.py','artificial_root.py')
ARRAY_NAMES=('events','labels','terminal_rows','eligible','nonoverlap','entry_available',
             'entry_rows','entry_prices','mfe','mae','continuous_end_exclusive',
             'source_qualified','eligibility_reason_mask','entry_reason_mask')
RULES=('A','B','C')
WIDTHS=(.0005,.001,.002)
ORIGINS=('公開mid','次行新規・費用後気配')
ORIGIN_CODES=('publication_mid','next_raw_net_quote')
GROUPS=('全候補','非重複')
DIRECTIONS=('全体','買い','売り')
CODES={1:'favorable_first',-1:'adverse_first',0:'price_cut',2:'eof',3:'window_end',-2:'entry_unavailable'}
COUNT_FIELDS=tuple(CODES.values())
CELL_KEYS=('rule','group','width_fraction','origin','direction')
PROFILE_KEYS=('rule','group','origin','direction')
CHECKS=0


def digest(raw: bytes) -> str:
    """
    機能: 同一読取bytesの指紋を作る。
    引数: raw(bytes)。
    返り値: SHA256文字列(str)。
    """
    return hashlib.sha256(raw).hexdigest()


def sources() -> dict:
    """
    機能: 検査前後の所有源八ファイル不変更を確認する。
    引数: なし。
    返り値: dict[str,str]。入力・結果を読む関数ではない。
    """
    return {(HERE/name).relative_to(ROOT).as_posix():digest((HERE/name).read_bytes()) for name in SOURCE_NAMES}


def write(path: Path, value: dict) -> None:
    """
    機能: 独立検査の所有域へ証跡を新規保存する。
    引数: path(Path)、value(dict)。
    返り値: None。旧成功・False・市場入力を変更しない。
    """
    assert path.resolve().is_relative_to(OWN) and not path.exists()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def key(row: dict, names: tuple) -> tuple:
    """
    機能: セル・極値群の対応キーを作る。
    引数: row(dict)、names(tuple[str,...])。
    返り値: tuple。
    """
    return tuple(row[name] for name in names)


def equal(expected: object, actual: object) -> None:
    """
    機能: 件数・未知を厳密に、浮動小数の記述統計だけ許容誤差内で照合する。
    引数: expected/actual(object)。
    返り値: None。浮動誤差は相対5e-12、絶対5e-12以内。
    """
    global CHECKS
    if expected is None:assert actual is None
    elif isinstance(expected,bool):assert actual is expected
    elif isinstance(expected,int):assert not isinstance(actual,bool) and actual==expected
    elif isinstance(expected,float):assert isinstance(actual,(int,float)) and not isinstance(actual,bool) and math.isfinite(actual) and math.isclose(expected,actual,rel_tol=5e-12,abs_tol=5e-12)
    else:assert expected==actual
    CHECKS+=1


def rates(counter: Counter) -> dict:
    """
    機能: 六状態のCounterから全候補・解決内・解決率を独立算術で求める。
    引数: counter(Counter[int]) はラベル件数。
    返り値: dict。打切と新規不可を±勝敗に入れず、空率はNone。
    """
    assert not set(counter)-set(CODES)
    n=sum(counter.values());resolved=counter[1]+counter[-1]
    return dict(**{name:int(counter[code]) for code,name in CODES.items()},n=n,resolved=resolved,
        favorable_rate_all=float(Fraction(counter[1],n)) if n else None,
        favorable_rate_resolved=float(Fraction(counter[1],resolved)) if resolved else None,
        resolution_rate=float(Fraction(resolved,n)) if n else None)


def quantile(values: list[float], fraction: Fraction) -> float | None:
    """
    機能: 並べた有限値の順位をFractionで求め、線形分位点を計算する。
    引数: values(list[float])、fraction(Fraction)。
    返り値: float|None。
    """
    if not values:return None
    position=(len(values)-1)*fraction
    lower=position.numerator//position.denominator
    remainder=position-lower
    return values[lower] if not remainder else values[lower]+float(remainder)*(values[lower+1]-values[lower])


def statistics(values: list[float]) -> dict:
    """
    機能: NaN空観測を除き、signed極値の分位点と和を独立に求める。
    引数: values(list[float])。
    返り値: dict。負値を丸めず、原価格経路を再計算しない。
    """
    assert not any(math.isinf(value) for value in values)
    good=sorted(value for value in values if not math.isnan(value))
    n=len(good);total=math.fsum(good)
    return dict(n=n,sum=total,mean=total/n if n else None,min=good[0] if n else None,
        q25=quantile(good,Fraction(1,4)),median=quantile(good,Fraction(1,2)),
        q75=quantile(good,Fraction(3,4)),max=good[-1] if n else None)


def pooled(values: list[dict]) -> dict:
    """
    機能: 場ごとの和と件数を再加算し、場中央値の分布だけを別名にする。
    引数: values(list[dict]) は独立statisticsの結果。
    返り値: dict。全観測中央値はNoneを維持する。
    """
    good=[value for value in values if value['n']]
    n=sum(value['n'] for value in values);total=math.fsum(value['sum'] for value in values)
    return dict(n=n,sum=total,mean=total/n if n else None,
        min=min(value['min'] for value in good) if good else None,
        max=max(value['max'] for value in good) if good else None,q25=None,median=None,q75=None,
        場中央値の分布=statistics([value['median'] for value in good]))


def inspect_arrays(arrays: dict, fields: list[str]) -> dict:
    """
    機能: 保存済み観測ラベル・資格・共通非重複と符号の内的整合を確認する。
    引数: arrays(dict[str,ndarray])、fields(list[str])。
    返り値: dict はPython列だけ。原経路の初到達を再検査した意味ではない。
    """
    assert len(fields)==len(set(fields))==31
    events=arrays['events'];n=len(events)
    assert events.shape==(n,31) and events.dtype==np.float64 and np.isfinite(events).all()
    pub=[int(value) for value in events[:,fields.index('pub_i')]]
    side=[int(value) for value in events[:,fields.index('d')]]
    assert pub==sorted(pub) and all(value>=0 for value in pub) and all(value in (-1,1) for value in side)
    assert all(events[i,fields.index('pub_i')]==pub[i] and events[i,fields.index('d')]==side[i] for i in range(n))
    assert arrays['labels'].shape==arrays['terminal_rows'].shape==(n,3,2)
    assert arrays['labels'].dtype==np.int8 and arrays['terminal_rows'].dtype==np.int64
    assert arrays['eligible'].shape==arrays['nonoverlap'].shape==arrays['source_qualified'].shape==(n,3)
    assert all(arrays[name].dtype==bool for name in ('eligible','nonoverlap','source_qualified','entry_available'))
    assert arrays['entry_available'].shape==arrays['entry_rows'].shape==arrays['entry_prices'].shape==(n,)
    assert arrays['mfe'].shape==arrays['mae'].shape==arrays['continuous_end_exclusive'].shape==(n,2)
    labels=arrays['labels'].tolist();terminal=arrays['terminal_rows'].tolist()
    eligible=arrays['eligible'].tolist();chosen=arrays['nonoverlap'].tolist();source=arrays['source_qualified'].tolist()
    available=arrays['entry_available'].tolist();entry=arrays['entry_rows'].tolist()
    for i in range(n):
        row=events[i];typ=int(row[fields.index('type')])
        initial=row[fields.index('opposite_q0')];minimum=row[fields.index('opposite_min_q')]
        buy=row[fields.index('bid_q_at_public')];sell=row[fields.index('ask_q_at_public')]
        b=typ==1 and minimum>=initial
        c=b and ((buy>=sell) if side[i]>0 else (sell>=buy))
        assert source[i]==[typ==0,bool(b),bool(c)]
        assert eligible[i]==[qualifies and arrays['eligibility_reason_mask'][i]==0 for qualifies in source[i]]
        assert bool(available[i])==(arrays['entry_reason_mask'][i]==0)
        assert entry[i]==(pub[i]+1 if available[i] else -1)
        assert math.isfinite(arrays['entry_prices'][i]) if available[i] else math.isnan(arrays['entry_prices'][i])
        for origin in range(2):
            end=int(arrays['continuous_end_exclusive'][i,origin])
            first=pub[i]+1 if origin==0 else entry[i]
            finite=(origin==0 or available[i]) and end>first
            assert math.isfinite(arrays['mfe'][i,origin])==finite
            assert math.isfinite(arrays['mae'][i,origin])==finite
            assert not math.isinf(arrays['mfe'][i,origin]) and not math.isinf(arrays['mae'][i,origin])
            if finite:assert arrays['mfe'][i,origin]>=arrays['mae'][i,origin]
            for width in range(3):
                code,at=int(labels[i][width][origin]),int(terminal[i][width][origin])
                assert code in CODES
                if origin==1 and not available[i]:assert code==-2 and at==end==-1
                elif code in (-1,1):assert first<=at<end
                elif code in (0,3):assert at==end
                else:assert code==2 and at==end-1
    expected=[[False]*3 for _ in range(n)]
    for rule in range(3):
        indices=[i for i in range(n) if eligible[i][rule]]
        positions=[pub[i] for i in indices];at=0
        while at<len(indices):
            i=indices[at];expected[i][rule]=True
            until=max(terminal[i][2])
            at=bisect_right(positions,until,lo=at+1)
    assert chosen==expected
    return dict(pub=pub,side=side,labels=labels,eligible=eligible,chosen=chosen,available=available,
        mfe=arrays['mfe'].tolist(),mae=arrays['mae'].tolist())


def independent_account(symbol: str, session: str, observed: dict) -> dict:
    """
    機能: PythonのCounterと選択indexから全108セルを独立に再集計する。
    引数: symbol/session(str)、observed(dict) はinspect_arraysの列。
    返り値: dict は数値セルと極値群。aggregate.accountは呼ばない。
    """
    cells={};profiles={}
    for ri,rule in enumerate(RULES):
        for group in GROUPS:
            flags=observed['eligible'] if group=='全候補' else observed['chosen']
            for direction in DIRECTIONS:
                indices=[i for i,d in enumerate(observed['side']) if flags[i][ri] and
                    (direction=='全体' or d==(1 if direction=='買い' else -1))]
                for oi,origin in enumerate(ORIGINS):
                    pk=(rule,group,origin,direction)
                    profiles[pk]=dict(n=len(indices),mfe=statistics([observed['mfe'][i][oi] for i in indices]),
                        mae=statistics([observed['mae'][i][oi] for i in indices]))
                    for wi,width in enumerate(WIDTHS):
                        values=[int(observed['labels'][i][wi][oi]) for i in indices]
                        summary=rates(Counter(values))
                        if oi==0:
                            physical=[value*observed['side'][i] if value in (-1,1) else value for i,value in zip(indices,values)]
                            short=[-value if value in (-1,1) else value for value in physical]
                            summary['baseline']={'常時買い':rates(Counter(physical)),'常時売り':rates(Counter(short))}
                        else:summary['baseline']=None
                        cells[rule,group,width,origin,direction]=summary
    return dict(symbol=symbol,session=session,全保存候補数=len(observed['side']),
        直後新規可能数=sum(observed['available']),cells=cells,profiles=profiles)


def compare_account(expected: dict, actual: dict) -> None:
    """
    機能: 一口座の全セル・固定方向対照・極値記述を保存集計へ照合する。
    引数: expected/actual(dict)。
    返り値: None。
    """
    for field in ('symbol','session','全保存候補数','直後新規可能数'):equal(expected[field],actual[field])
    cells={key(row,CELL_KEYS):row for row in actual['cells']}
    profiles={key(row,PROFILE_KEYS):row for row in actual['profiles']}
    assert len(cells)==len(actual['cells'])==len(expected['cells'])==108
    assert len(profiles)==len(actual['profiles'])==len(expected['profiles'])==36
    for k,wanted in expected['cells'].items():
        saved=cells[k]
        for field,value in wanted.items():
            if field!='baseline':equal(value,saved[field])
            elif value is None:equal(None,saved['baseline'])
            else:
                for direction,stats in value.items():
                    for name,n in stats.items():equal(n,saved['baseline'][direction][name])
    for k,wanted in expected['profiles'].items():
        equal(wanted['n'],profiles[k]['n'])
        for name in ('mfe','mae'):
            for field,value in wanted[name].items():equal(value,profiles[k][name][field])


def independent_period(accounts: list[dict]) -> dict:
    """
    機能: 独立口座小集計から期間別の分子分母を再加算する。
    引数: accounts(list[dict])。
    返り値: dict。原ラベルの再読はしない。
    """
    assert accounts
    cells={};profiles={}
    for k in accounts[0]['cells']:
        counter=Counter({code:sum(row['cells'][k][field] for row in accounts) for code,field in CODES.items()})
        value=rates(counter)
        if accounts[0]['cells'][k]['baseline'] is None:value['baseline']=None
        else:
            value['baseline']={direction:rates(Counter({code:sum(row['cells'][k]['baseline'][direction][field] for row in accounts) for code,field in CODES.items()}))
                for direction in ('常時買い','常時売り')}
        cells[k]=value
    for k in accounts[0]['profiles']:
        profiles[k]=dict(n=sum(row['profiles'][k]['n'] for row in accounts),
            mfe=pooled([row['profiles'][k]['mfe'] for row in accounts]),
            mae=pooled([row['profiles'][k]['mae'] for row in accounts]))
    return dict(session_count=len(accounts),cells=cells,profiles=profiles)


def compare_period(expected: dict, actual: dict) -> None:
    """
    機能: 期間別の全数値と、全観測分位点を未知にした範囲を確認する。
    引数: expected/actual(dict)。
    返り値: None。
    """
    equal(expected['session_count'],actual['session_count'])
    dummy=dict(symbol='集計',session='集計',全保存候補数=0,直後新規可能数=0,
        cells=list(actual['cells']),profiles=[])
    expected_cells=expected['cells']
    indexed={key(cell,CELL_KEYS):cell for cell in actual['cells']}
    assert len(indexed)==108
    for k,row in expected_cells.items():
        saved=indexed[k]
        for field,value in row.items():
            if field!='baseline':equal(value,saved[field])
            elif value is None:equal(None,saved['baseline'])
            else:
                for label,b in value.items():
                    for name,n in b.items():equal(n,saved['baseline'][label][name])
    profiles={key(profile,PROFILE_KEYS):profile for profile in actual['profiles']}
    assert len(profiles)==36
    for k,row in expected['profiles'].items():
        equal(row['n'],profiles[k]['n'])
        for label in ('mfe','mae'):
            for name,value in row[label].items():
                if name=='場中央値の分布':
                    for field,n in value.items():equal(n,profiles[k][label][name][field])
                else:equal(value,profiles[k][label][name])


def self_test() -> dict:
    """
    機能: カウンタ・物理方向・未知・極値分位の別算術を手計算へ照合する。
    引数: なし。
    返り値: dict。実結果や保存出力は読まない。
    """
    count=rates(Counter([1,-1,0,2,3,-2]))
    assert count['n']==6 and count['resolved']==2 and count['favorable_rate_all']==1/6 and count['resolution_rate']==1/3
    assert rates(Counter())['favorable_rate_resolved'] is None
    stats=statistics([-2.,0.,4.,float('nan')])
    assert stats['n']==3 and stats['q25']==-1 and stats['median']==0 and stats['q75']==2
    total=pooled([statistics([0.,100.]),statistics([3.])])
    assert total['n']==3 and total['mean']==103/3 and total['median'] is None
    assert total['場中央値の分布']['median']==26.5
    assert [-1*-1,1*1]==[1,1]
    return dict(全合格=True,範囲='CounterとFraction分位と空分母だけ。原経路や測定結果は未読。')


def prepare() -> None:
    """
    機能: 完成結果を探さず、目的・出力列・一読予算・所有源不変更を固定する。
    引数: なし。
    返り値: None。
    """
    assert not PLAN.exists()
    proof=self_test()
    write(PLAN,dict(状態='結果本文未読。根の完成通知とSHA指定後だけ実行。',source_SHA256=sources(),
        audit_source_SHA256=digest(Path(__file__).read_bytes()),結果予定=RESULT.relative_to(ROOT).as_posix(),
        結果最大bytes=64*1024*1024,対象='全66観測出力。108セル/36極値群、10商品期間、常時買売対照。',
        観測出力列=list(ARRAY_NAMES),読取予算=dict(完成結果=1,新observationsNPZ='66件各一回',原NPZ=0,event入力=0,再measure=0,新金融=0,API=0),
        保存='同bytesのSHA/サイズ照合後、私有copyをparse前に保存。NPZはallow_pickle=False、指定列だけdecode。',
        検査範囲='保存ラベル/資格/共通非重複から独立Counter再加算。原価格経路から初到達を再検証する監査ではない。',
        純算術人工=proof,主評価='事前固定C・0.10%・共通非重複・公開mid。次気配は参考。最良幅の事後選択をしない。'))


def run(expected_sha: str) -> None:
    """
    機能: 根の通知後、結果一読と新観測66各一読で全保存集計を独立照合する。
    引数: expected_sha(str) は根指定の完成結果SHA256。
    返り値: None。原入力・旧金融・再測定にはアクセスしない。
    """
    assert len(expected_sha)==64 and all(c in '0123456789abcdef' for c in expected_sha)
    final=OWN/'保存66観測と全セル対照及び期間の独立集計確認.json'
    assert not final.exists()
    fixed=json.loads(PLAN.read_text(encoding='utf-8'))
    assert fixed['source_SHA256']==sources() and fixed['audit_source_SHA256']==digest(Path(__file__).read_bytes())
    assert RESULT.stat().st_size<=fixed['結果最大bytes']
    raw=RESULT.read_bytes()
    assert digest(raw)==expected_sha
    copy=OWN/'完成結果の同bytes私有コピー.json'
    assert not copy.exists()
    copy.write_bytes(raw)
    result=json.loads(raw.decode('utf-8'))
    assert result['全合格'] is True and result['金融'] is False and result['source_SHA256']==fixed['source_SHA256']
    sessions=result['sessions'];assert len(sessions)==len(set(sessions))==33
    outputs=result['outputs'];assert len(outputs)==66
    metadata={(row['symbol'],row['session']):row for row in result['metadata']}
    saved_accounts={(row['symbol'],row['session']):row for row in result['accounts']}
    assert len(metadata)==len(saved_accounts)==66
    expected_keys={(symbol,session) for symbol in ('TOPIX','NK225') for session in sessions}
    assert set(metadata)==set(saved_accounts)=={(row['symbol'],row['session']) for row in outputs}==expected_keys
    references=[];locators=[];seen=set()
    for index,info in enumerate(outputs,1):
        k=(info['symbol'],info['session']);path=(ROOT/info['path']).resolve()
        assert path.is_relative_to((HERE/'measurement/observations').resolve()) and path not in seen
        seen.add(path)
        assert path.stat().st_size==info['bytes']
        body=path.read_bytes()
        assert len(body)==info['bytes'] and digest(body)==info['SHA256']
        destination=OWN/'output_copies'/(info['session']+'_'+info['symbol']+'.npz')
        destination.parent.mkdir(exist_ok=True)
        assert not destination.exists()
        destination.write_bytes(body)
        with np.load(BytesIO(body),allow_pickle=False) as archive:
            assert set(archive.files)==set(info['arrays']) and set(ARRAY_NAMES).issubset(archive.files)
            arrays={name:archive[name] for name in ARRAY_NAMES}
        for name,array in arrays.items():
            assert str(array.dtype)==info['arrays'][name]['dtype'] and list(array.shape)==info['arrays'][name]['shape']
        observed=inspect_arrays(arrays,metadata[k]['fields'])
        reference=independent_account(*k,observed)
        compare_account(reference,saved_accounts[k])
        references.append(reference);locators.append(dict(symbol=k[0],session=k[1],path=info['path'],SHA256=info['SHA256']))
        del arrays,observed,body
        if index%11==0:print(json.dumps(dict(独立再加算=index,比較項目=CHECKS),ensure_ascii=False),flush=True)
    combined=result['combined'];equal(True,combined['全合格'])
    assert len(combined['accounts'])==66
    for reference in references:
        same=[row for row in combined['accounts'] if row['symbol']==reference['symbol'] and row['session']==reference['session']]
        assert len(same)==1
        compare_account(reference,same[0])
    groups={'全33':sessions,'前16':sessions[:16],'後17':sessions[16:],
        'デイ':[s for s in sessions if s.endswith('_Day')],'ナイト':[s for s in sessions if s.endswith('_Night')]}
    summary={}
    for symbol in ('TOPIX','NK225'):
        own=[row for row in references if row['symbol']==symbol]
        periods={}
        for label,ids in groups.items():
            if not ids:continue
            expected=independent_period([row for row in own if row['session'] in ids])
            compare_period(expected,combined['symbols'][symbol]['periods'][label])
            # 小要約は両起点・各幅・各方向の共通非重複だけ。全候補は主C0.1を併記。
            cells=[]
            for k,value in expected['cells'].items():
                if k[1]=='非重複' or (k[0]=='C' and k[2]==.001 and k[4]=='全体'):
                    cells.append(dict(zip(CELL_KEYS,k),**value))
            periods[label]=dict(session_count=expected['session_count'],cells=cells)
        summary[symbol]=dict(periods=periods)
    assert sources()==fixed['source_SHA256'] and len(seen)==66
    projection=OWN/'方向採点の主評価と各幅及び前後昼夜方向の独立小射影.json'
    write(projection,dict(全合格=True,元結果SHA256=expected_sha,symbols=summary,
        各場主評価=[dict(symbol=row['symbol'],session=row['session'],cells=[dict(zip(CELL_KEYS,k),**value)
            for k,value in row['cells'].items() if k[0]=='C' and k[1]=='非重複' and k[2]==.001 and k[4]=='全体']) for row in references],
        留保='保存観測からの独立再加算。新しい方向予測標本や実利益の検証ではない。'))
    write(final,dict(全合格=True,結果SHA256=expected_sha,監査計画SHA256=digest(PLAN.read_bytes()),
        source_SHA256=sources(),audit_source_SHA256=digest(Path(__file__).read_bytes()),
        出力66=locators,数値比較項目=CHECKS,口座=66,口座セル=7128,期間セル=1080,
        独立小射影SHA256=digest(projection.read_bytes()),原NPZ=0,event入力=0,再measure=0,新金融=0,API=0,
        範囲='原価格経路の初到達は再検証せず、保存label/eligible/nonoverlap/terminal/dの整合と集計だけを監査。'))
    print(json.dumps(dict(全合格=True,SHA256=digest(final.read_bytes()),比較項目=CHECKS),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--root-result-sha')
    args=parser.parse_args()
    assert args.prepare_only != bool(args.root_result_sha)
    prepare() if args.prepare_only else run(args.root_result_sha)
