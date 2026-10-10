"""保存済み29場を再利用し、追加ナイトだけ同じ原本順で準備して価格窓を接続する。"""

from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle
import re
import socket
import sys

import numpy as np

import core


sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
EXTRA='2026-10-09_Night'
DELAYS=(1,5,15)
PATHS={'ready':['work/wave_v69/prepared/inputs.pkl','work/wave_v71/prepared/extra_inputs.pkl'],
       'features':['work/wave_v69/prepared/features.pkl','work/wave_v71/prepared/extra_features.pkl'],
       'snapshots':['work/wave_v76/inputs/snapshots.pkl']}
CLOCK_PATTERN=re.compile(rb'"([^"\r\n]*(?:Time|time|Date|date|Stamp|stamp|Receiv|receiv|Receipt|receipt|Seq|seq)[^"\r\n]*)"\s*:')


def module(name: str,path: Path) -> object:
    """機能: 監査済み抽出器を旧ファイル変更なしで読み込む。

    引数: name(str)、path(Path)。返り値: 読み込んだモジュール(object)。
    """
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value;spec.loader.exec_module(value)
    return value


def load(path: Path) -> object:
    """機能: 指定した入力資料を読み取る。

    引数: path(Path)。返り値: 保存値(object)。損益台帳を読まない。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 保存資料の指紋を一定メモリーで計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(4*1024*1024):h.update(chunk)
    return h.hexdigest()


def save(name: str,value: object) -> None:
    """機能: 担当入力領域にだけ新しい準備結果を保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    path=HERE/name;assert path.resolve().is_relative_to(HERE)
    if path.suffix=='.pkl':path.write_bytes(pickle.dumps(value,protocol=5))
    else:path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def deny(*args: object,**kwargs: object) -> None:
    """機能: 入力準備からのネットワーク接続を禁止する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)。呼出し時は例外で停止。
    """
    raise RuntimeError('保存入力の準備中に通信することは禁止')


def extract_extra(symbol: str) -> tuple:
    """機能: 追加一口座を旧最良気配フィルタと旧57の逐次状態で準備する。

    引数: symbol(str)。返り値: key、ready、full特徴、snapshot、監査、参照probe(tuple)。
    ATRや旧familiesは未使用のため作らず、価格・気配・時計・連番の互換性を保つ。
    """
    rawmod=module('最良気配抽出77_'+symbol,ROOT/'work/wave_v8/raw_features.py')
    board=module('逐次板抽出77_'+symbol,ROOT/'work/wave_v57/features.py')
    state=board.ReplenishmentState(board.MULTIPLIER[symbol]);tick=rawmod.TICKS[symbol]
    start,end=rawmod.session_bounds(EXTRA);start_s,end_s=start.timestamp(),end.timestamp()
    path=ROOT/'book'/symbol/(EXTRA+'.jsonl');h=hashlib.sha256();clocks=set()
    times=[];seqs=[];lasts=[];fields={k:[] for k in (*board.FLOAT_COLUMNS,'valid','reset','reset_reason')}
    snapshots={k:[] for k in core.LEGACY.SNAPSHOT_FIELDS};snapshot_valid=[];events=[]
    earliest=latest=first_valid=None;raw_samples=[];count=0;previous_time=-math.inf
    rejected=dict(時計欠測=0,場外=0,最良気配不正=0,現在値不正=0)
    with path.open('rb') as stream:
        for seq,line in enumerate(stream):
            count=seq+1;h.update(line);clocks.update(m.group(1).decode('utf8') for m in CLOCK_PATTERN.finditer(line))
            raw=json.loads(line);text=raw.get('CurrentPriceTime')
            if not text:rejected['時計欠測']+=1;continue
            stamp=datetime.fromisoformat(text)
            assert stamp.tzinfo is not None and stamp.timestamp()>=previous_time
            t=stamp.timestamp();previous_time=t
            if not start_s<=t<end_s:rejected['場外']+=1;continue
            cp=board.finite(raw.get('CurrentPrice'))
            if cp is not None and cp>0:
                point=dict(value=cp,seq=seq,time=t,kind='observed_CurrentPrice')
                if earliest is None:earliest=point
                latest=point
            quote,_=rawmod.parse_snapshot(raw)
            if quote is None:rejected['最良気配不正']+=1;continue
            if cp is None:rejected['現在値不正']+=1;continue
            i=len(seqs);now=board.snapshot(raw);value,completed=state.step(now,seq,t,i)
            instant=core.LEGACY.snapshot_values(raw,tick)
            assert instant['valid']==value['valid']
            times.append(t);seqs.append(seq);lasts.append(cp);events.extend(completed)
            for k in fields:fields[k].append(value[k])
            for k in snapshots:snapshots[k].append(instant[k])
            snapshot_valid.append(instant['valid'])
            if first_valid is None:
                first_valid=raw
                raw_samples.append(dict(i=i,seq=seq,raw={k:raw.get(k) for k in ['CurrentPriceTime','OpeningPrice','OpeningPriceTime','CurrentPrice']+
                    [f'{side}{depth}' for side in ('Buy','Sell') for depth in range(1,11)]}))
    ready=dict(seq=np.array(seqs,dtype=np.int64),time_s=np.array(times),last=np.array(lasts),session=EXTRA,symbol=symbol,
               start=start_s,limit=end_s-300.,tick=tick,us_open=(start.replace(hour=22,minute=30)).timestamp())
    features={k:np.array(v,dtype=bool if k in ('valid','reset') else np.uint8 if k=='reset_reason' else np.float64) for k,v in fields.items()}
    features.update(seq=ready['seq'].copy(),time_s=ready['time_s'].copy())
    snapshot={k:np.array(v) for k,v in snapshots.items()};snapshot.update(seq=ready['seq'].copy(),time_s=ready['time_s'].copy(),valid=np.array(snapshot_valid,bool))
    assert first_valid is not None and earliest is not None and latest is not None
    for k in ('seq','time_s','last'):np.testing.assert_array_equal(features[k],ready[k])
    assert (np.diff(ready['seq'])>0).all() and (np.diff(ready['time_s'])>=0).all()
    audit=dict(session=EXTRA,symbol=symbol,n=len(seqs),raw_rows=count,raw_SHA256=h.hexdigest(),bytes=path.stat().st_size,
        start=start_s,limit=end_s-300.,end=end_s,tick=tick,first_time=times[0],last_time=times[-1],
        valid_rows=int(features['valid'].sum()),reset_rows=int(features['reset'].sum()),
        clock_keys=sorted(clocks),同clock更新数=int((np.diff(ready['time_s'])==0).sum()),
        rejected=rejected,原本同seq価格時計一致=True,raw_samples=raw_samples)
    probe=dict(first_valid=first_valid,earliest=earliest,latest=latest,end=end_s)
    return (EXTRA,symbol),ready,features,snapshot,audit,probe


def base_material() -> tuple[dict,dict,dict]:
    """機能: 既往58口座と追加2口座を重複なしで接続する。

    引数: なし。返り値: ready、book、snapshot(tuple[dict,dict,dict])。
    """
    values=[]
    for kind,extra_name in [('ready','extra_inputs.pkl'),('features','extra_features.pkl'),('snapshots','extra_snapshots.pkl')]:
        result={}
        for name in PATHS[kind]:result.update(load(ROOT/name))
        more=load(HERE/extra_name);assert not set(result)&set(more);result.update(more);values.append(result)
    assert set(values[0])==set(values[1])==set(values[2]) and len(values[0])==60
    return tuple(values)


def material(delay: int=5) -> tuple:
    """機能: 算法担当へ保存済み価格・板・窓とメタを渡す。

    引数: delay(int:1/5/15)。返り値: ready、book、snapshot、grid、meta(tuple)。
    """
    assert delay in DELAYS
    return (*base_material(),load(HERE/f'grids_delay{delay}.pkl'),load(HERE/'metadata.json'))


def coverage(grids: dict,delay: int) -> list[dict]:
    """機能: 価格窓・レンジ・板フローの共同取得率だけを数える。

    引数: grids(dict)、delay(int)。返り値: 場別の十分性(list[dict])。
    """
    rows=[]
    for session,record in grids.items():
        a,b=(record['markets'][s] for s in ('TOPIX','NK225'))
        row=dict(session=session,delay=delay,grid_count=len(record['grid']),both_current=int((a['current']['valid']&b['current']['valid']).sum()),windows={},ranges={},flow={})
        for w in core.WINDOWS:
            x,y=a['windows'][w],b['windows'][w];valid=x['source_valid']&y['source_valid']
            row['windows'][str(w)]=dict(both_source_valid=int(valid.sum()),both_efficiency=int((valid&np.isfinite(x['efficiency'])&np.isfinite(y['efficiency'])).sum()),
                actual_seconds_TOP=[float(z) for z in np.quantile(x['actual_seconds'][valid],[0,.5,1])] if valid.any() else None,
                actual_seconds_NK=[float(z) for z in np.quantile(y['actual_seconds'][valid],[0,.5,1])] if valid.any() else None)
        for w in core.RANGES:
            x,y=a['ranges'][w],b['ranges'][w]
            row['ranges'][str(w)]=dict(both_source_valid=int((x['source_valid']&y['source_valid']).sum()),
                                      both_position=int((x['position_valid']&y['position_valid']).sum()))
        for w in (15,30):
            x,y=a['flow'][w],b['flow'][w]
            row['flow'][str(w)]=dict(both_source_valid=int((x['source_valid']&y['source_valid']).sum()),
                both_valid_min3=int((x['valid']&y['valid']&(x['nonzero_ofi_count']>=3)&(y['nonzero_ofi_count']>=3)).sum()))
        rows.append(row)
    return rows


def main() -> None:
    """機能: 新Nightだけ原本から準備し、全30場の価格素材を損益前に固定する。

    引数: なし。返り値: なし(None)。旧成果上書き、API取得、損益計算はしない。
    """
    socket.socket.connect=deny;socket.create_connection=deny
    assert not (HERE/'metadata.json').exists(),'完成入力は上書きしない'
    with ProcessPoolExecutor(max_workers=2) as pool:extra=list(pool.map(extract_extra,('TOPIX','NK225')))
    for name,index in [('extra_inputs.pkl',1),('extra_features.pkl',2),('extra_snapshots.pkl',3)]:save(name,{x[0]:x[index] for x in extra})
    ready,book,snapshots=base_material();sessions=sorted({k[0] for k in ready});assert len(sessions)==30 and sessions[-1]==EXTRA
    oldmeta=load(ROOT/'work/wave_v74/inputs/refmetadata.json');oldspec=load(ROOT/'work/wave_v76/inputs/入力と即時板特徴の仕様.json')
    refs=module('原板参照値77読取',ROOT/'work/wave_v74/inputs/prepare_refs.py')
    references=dict(oldmeta['references']);checks=[]
    for key,r,f,s,audit,probe in extra:
        refopen=refs.opening_ref(key,r,probe);pred=('2026-10-09_Day',key[1]);previous=ready[pred]
        oldrow=next(x for x in oldmeta['rows'] if x['session']==pred[0] and x['symbol']==pred[1])
        latest=refs.last_current(ROOT/'book'/pred[1]/(pred[0]+'.jsonl'),oldrow['raw_rows'],previous['start'],previous['limit']+300.)
        references['|'.join(key)]=dict(session=key[0],symbol=key[1],ref_open=refopen,
            ref_prev=refs.previous_ref(key,r,pred,ready,{pred:dict(latest=latest,end=previous['limit']+300.)}))
        checks.append(audit)
    prior_rows={}
    for item in oldspec['原本照合']:
        path=ROOT/'book'/item['symbol']/(item['session']+'.jsonl');assert path.exists()
        prior_rows[(item['session'],item['symbol'])]=dict(item)
    quality=[]
    for key,r in sorted(ready.items()):
        f=book[key];quality.append(dict(session=key[0],symbol=key[1],n=len(r['seq']),start=r['start'],limit=r['limit'],tick=r['tick'],
            first_time=float(r['time_s'][0]),last_time=float(r['time_s'][-1]),valid_rows=int(f['valid'].sum()),reset_rows=int(f['reset'].sum())))
    rows=[]
    for delay in DELAYS:
        grids={session:core.session_features(ready,book,snapshots,session,delay) for session in sessions}
        save(f'grids_delay{delay}.pkl',grids);rows.extend(coverage(grids,delay));del grids
        print(f'遅延{delay}秒の全30場価格窓・レンジ・板F完成',flush=True)
    save('入力十分性.json',dict(rows=rows,損益閲覧=0,API取得=0,実注文=0))
    save('metadata.json',dict(sessions=sessions,existing29=sessions[:-1],unseen_session=EXTRA,accounts=60,
        references=references,rows=quality,extra_raw_audit=checks,input_paths=PATHS,
        extra_paths={'ready':'work/wave_v77/inputs/extra_inputs.pkl','features':'work/wave_v77/inputs/extra_features.pkl','snapshots':'work/wave_v77/inputs/extra_snapshots.pkl'},
        原本同一性='旧58は旧76の同seq抽出済み指紋と準備入力指紋を再利用。追加2は全行hashを今回取得。旧原本の全量再走査はしない。',
        新Night扱い='共同情報として今回初めて双方が揃った唯一の未見確認場。特徴準備のみで、前29の設定固定まで損益再生しない。',
        windows=list(core.WINDOWS),ranges=list(core.RANGES),flow_windows=[15,30],delays=list(DELAYS),grid_seconds=5,max_age=30,
        時刻='CurrentPriceTimeは最終約定代理時計。同時計先頭だけtime<grid-delayのstrict asof、期限から30秒以内。共通受信時計なしで受信因果は証明不能。',
        単位='ret_bpは10000倍の相対中値変化。displacement/total_variationとrange high/low/widthは現物価格単位。bid/ask/high/low距離はラージ呼値数。',
        効率='同時計先頭中値だけを並べoldからnowまでの価格差絶対和を総変動とし、絶対始終差/総変動。0分母NaN、途中reset/invalid拒否。',
        レンジ='oldはgrid-delay-windowより厳密に前の最新同時計先頭、nowはgrid-delayより厳密に前の最新同時計先頭。oldを含みnowを除く先頭行だけの高安。nowと同じclock後続は入らない。2観測以上、値幅0は位置不明。位置は0未満や1超も有効な逸脱として残す。',
        可用性='価格current.valid/windows.source_validとQのq_valid、Fのvalid/event件数を分離。Q/F不足を価格方向の必須条件にしない。実観測秒数は予定窓と異なることがある。',
        追加ready='seq/time_s/last/session/symbol/start/limit/tick/us_openのみ。旧ATR/families/trend_sideは本検証で使わないため複製しない。',
        hashes={name:digest(HERE/name) for name in ['core.py','prepare.py','extra_inputs.pkl','extra_features.pkl','extra_snapshots.pkl',*[f'grids_delay{d}.pkl' for d in DELAYS]]},
        reused_input_hashes={name:digest(ROOT/name) for names in PATHS.values() for name in names},旧58原本指紋={ '|'.join(k):v['raw_SHA256'] for k,v in prior_rows.items()},
        API取得=0,実注文=0,損益閲覧=0))
    print('共通30場60口座の価格方向・短期再加速素材を準備しました',flush=True)


if __name__=='__main__':
    main()
