"""即時板の原本同seq特徴を新たに抽出し、損益を見ずに5秒同期の取得率を固定する。"""

from concurrent.futures import ProcessPoolExecutor,as_completed
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import re

import numpy as np

import core


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PATHS={'ready':['work/wave_v69/prepared/inputs.pkl','work/wave_v71/prepared/extra_inputs.pkl'],
       'book':['work/wave_v69/prepared/features.pkl','work/wave_v71/prepared/extra_features.pkl']}
DELAYS=(1,5,15)
WINDOWS=(5,15,30,60)
CLOCK_KEYS=re.compile(rb'"([^"\r\n]*(?:Time|time|Date|date|Stamp|stamp|Receiv|receiv|Receipt|receipt|Seq|seq)[^"\r\n]*)"\s*:')


def load(path: Path) -> object:
    """機能: 既存準備資料と今回入力だけを読み取る。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 入力と抽出結果の内容指紋を計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(4*1024*1024):h.update(chunk)
    return h.hexdigest()


def save(name: str,value: object) -> None:
    """機能: 担当入力領域だけへJSON又はpickleを保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    path=HERE/name;assert path.resolve().is_relative_to(HERE)
    if path.suffix=='.pkl':path.write_bytes(pickle.dumps(value,protocol=5))
    else:path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def base_material() -> tuple[dict,dict]:
    """機能: 既存58口座の価格・最良板特徴を変更せず結合する。

    引数: なし。返り値: readyとbook(tuple[dict,dict])。
    """
    output=[]
    for kind in ('ready','book'):
        merged={}
        for name in PATHS[kind]:
            value=load(ROOT/name);assert not set(merged)&set(value);merged.update(value)
        output.append(merged)
    assert set(output[0])==set(output[1]) and len(output[0])==58
    return tuple(output)


def extract_one(args: tuple) -> tuple:
    """機能: 一口座の全ready連番と同じ原本行から瞬時の10段特徴を抽出する。

    引数: args(tuple:口座key、seq/time/bid/ask/qty/valid配列、tick、旧原本hash)。
    返り値: key、特徴dict、原本照合dict(tuple)。全原本の時計名再走査は行わない。
    """
    key,seq,times,bid,ask,bqty,aqty,valid,tick,expected=args
    n=len(seq);pointer=0;raw_count=0;h=hashlib.sha256()
    output={k:np.full(n,np.nan) for k in core.SNAPSHOT_FIELDS}
    output.update(seq=seq.copy(),time_s=times.copy(),valid=np.zeros(n,bool))
    targets={0,n//2,n-1}
    samples=[]
    path=ROOT/'book'/key[1]/(key[0]+'.jsonl')
    with path.open('rb') as stream:
        for raw_i,line in enumerate(stream):
            h.update(line);raw_count=raw_i+1
            if pointer>=n or raw_i!=seq[pointer]:continue
            raw=json.loads(line)
            assert datetime.fromisoformat(raw['CurrentPriceTime']).timestamp()==times[pointer]
            assert raw['Buy1']['Price']==bid[pointer] and raw['Sell1']['Price']==ask[pointer]
            assert raw['Buy1']['Qty']==bqty[pointer] and raw['Sell1']['Qty']==aqty[pointer]
            result=core.snapshot_values(raw,tick)
            assert result['valid']==bool(valid[pointer]),('10段valid差',key,pointer)
            output['valid'][pointer]=result['valid']
            for field in core.SNAPSHOT_FIELDS:output[field][pointer]=result[field]
            if pointer in targets:
                samples.append(dict(i=pointer,seq=raw_i,raw={name:raw.get(name) for name in ['CurrentPriceTime']+
                    [f'{s}{d}' for s in ('Buy','Sell') for d in range(1,11)]},
                    features={k:v if result['valid'] else None for k,v in result.items()}))
            pointer+=1
    assert pointer==n and h.hexdigest()==expected['raw_SHA256'] and raw_count==expected['raw_rows']
    good=output['valid']
    assert np.isfinite(np.column_stack([output[k][good] for k in core.SNAPSHOT_FIELDS])).all()
    np.testing.assert_allclose(output['micro_offset_ticks'][good],output['best_imbalance'][good]*(ask[good]-bid[good])/(2*tick),rtol=1e-9,atol=1e-9)
    return key,output,dict(session=key[0],symbol=key[1],rows=n,valid_rows=int(good.sum()),raw_rows=raw_count,
        raw_SHA256=h.hexdigest(),原本同seq価格数量時計一致=True,旧原本指紋一致=True,原本サンプル=samples)


def extra_inventory(common_sessions: list[str]) -> dict:
    """機能: 本検証外の追加原本を検出し、追加分だけ時計欄と相手欠測を確認する。

    引数: common_sessions(list[str])。返り値: 原本一覧と追加時計調査(dict)。
    """
    inventory={s:sorted(p.stem for p in (ROOT/'book'/s).glob('*.jsonl')) for s in ('TOPIX','NK225')}
    extra=[]
    for symbol,sessions in inventory.items():
        for session in sessions:
            if session in common_sessions:continue
            path=ROOT/'book'/symbol/(session+'.jsonl');keys=set();h=hashlib.sha256();count=0;samples=[]
            with path.open('rb') as stream:
                for i,line in enumerate(stream):
                    count=i+1;h.update(line);keys.update(m.group(1).decode('utf8') for m in CLOCK_KEYS.finditer(line))
                    if i==0:
                        raw=json.loads(line);samples.append(dict(seq=i,keys=list(raw),時計={k:raw.get(k) for k in keys}))
            peer='NK225' if symbol=='TOPIX' else 'TOPIX'
            extra.append(dict(session=session,symbol=symbol,raw_rows=count,bytes=path.stat().st_size,SHA256=h.hexdigest(),
                clock_keys=sorted(keys),sample=samples,peer_present=session in inventory[peer],
                handling='相手欠測で共同判定不能・本検証比較対象外。API補完なし。'))
    return dict(inventory=inventory,common_sessions=common_sessions,common_accounts=58,extra=extra)


def coverage(grids: dict) -> list[dict]:
    """機能: 共通5秒判断での即時板、窓、証拠件数の取得率だけを数える。

    引数: grids(dict[delay][session])。返り値: 場別の入力十分性(list[dict])。
    """
    rows=[]
    for delay,records in grids.items():
        for session,record in records.items():
            markets=record['markets'];total=len(record['grid'])
            d=dict(session=session,delay=delay,grid_count=total,
                both_snapshot=int((markets['TOPIX']['current']['valid']&markets['NK225']['current']['valid']).sum()))
            for window in WINDOWS:
                a,b=(markets[s]['windows'][window] for s in ('TOPIX','NK225'))
                clean=a['source_valid']&b['source_valid'];flow=a['valid']&b['valid']
                d[str(window)]=dict(both_source_valid=int(clean.sum()),both_ofi_valid=int(flow.sum()),
                    both_min3_ofi_events=int((flow&(a['nonzero_ofi_count']>=3)&(b['nonzero_ofi_count']>=3)).sum()),
                    same_row_TOP=int(a['same_row'].sum()),same_row_NK=int(b['same_row'].sum()),
                    zero_denominator_TOP=int(a['zero_ofi_denominator'].sum()),zero_denominator_NK=int(b['zero_ofi_denominator'].sum()),
                    observed_seconds_TOP=[float(v) for v in np.quantile(a['actual_seconds'][clean],[0,.5,1])] if clean.any() else None,
                    observed_seconds_NK=[float(v) for v in np.quantile(b['actual_seconds'][clean],[0,.5,1])] if clean.any() else None)
            rows.append(d)
    return rows


def material() -> tuple[dict,dict,dict,dict]:
    """機能: 算法担当へ旧価格・旧最良特徴・新snapshot・新gridを読み取りで渡す。

    引数: なし。返り値: ready,book,snapshots,grids(tuple[dict,dict,dict,dict])。
    """
    ready,book=base_material()
    return ready,book,load(HERE/'snapshots.pkl'),load(HERE/'grids.pkl')


def main() -> None:
    """機能: 最大4並列で同seq10段特徴を採取し、窓別同期と十分性を損益前に保存する。

    引数: なし。返り値: なし(None)。原本と既存入力を変更せず、APIと損益は参照しない。
    """
    HERE.mkdir(parents=True,exist_ok=True)
    ready,book=base_material();sessions=sorted({k[0] for k in ready})
    expected={(r['session'],r['symbol']):r for r in load(ROOT/'work/wave_v74/inputs/refmetadata.json')['rows']}
    inventory=extra_inventory(sessions);save('保存範囲と追加時計.json',inventory)
    jobs=[]
    for key,r in sorted(ready.items()):
        f=book[key]
        jobs.append((key,r['seq'],r['time_s'],f['bid'],f['ask'],f['bid_qty'],f['ask_qty'],f['valid'],r['tick'],expected[key]))
    snapshots={};checks=[]
    with ProcessPoolExecutor(max_workers=4) as pool:
        tasks=[pool.submit(extract_one,arg) for arg in jobs]
        for task in as_completed(tasks):
            key,value,check=task.result();snapshots[key]=value;checks.append(check)
            print(f'{key[0]} {key[1]} 同seq板特徴 {len(value["seq"]):,}行',flush=True)
    snapshots=dict(sorted(snapshots.items()));save('snapshots.pkl',snapshots)
    grids={delay:{s:core.session_features(ready,book,snapshots,s,delay) for s in sessions} for delay in DELAYS}
    save('grids.pkl',grids)
    save('入力十分性.json',dict(rows=coverage(grids),API取得=0,実注文=0,損益閲覧=0))
    save('入力と即時板特徴の仕様.json',dict(sessions=sessions,accounts=58,input_paths=PATHS,
        input_SHA256={p:digest(ROOT/p) for names in PATHS.values() for p in names},原本照合=sorted(checks,key=lambda r:(r['session'],r['symbol'])),
        snapshot_fields=list(core.SNAPSHOT_FIELDS),delays=list(DELAYS),windows=list(WINDOWS),grid_step_seconds=5,max_age_seconds=30,
        grid='開始300秒後からlimit−60を含む5秒刻み。新規はlimit−300以後禁止、保有判断は場末まで。',
        best_imbalance='(bidQty−askQty)/(bidQty+askQty)。数量0の最良板は無効、他段数量0は有効。',
        microprice='(bid*askQty+ask*bidQty)/(bidQty+askQty)。厚い買板ならask寄りの数量加重中値代理。',
        micro_offset='(microprice−mid)/tick = best_imbalance*(ask−bid)/(2*tick)。最良偏りと代数同値なので独立の二票にしない。',
        depth='各側最良価格からの非負呼値距離dに1/(1+d)を掛けた10段表示数量。比=(買重み数量−売重み数量)/(和)。価格逆転・欠測段・負数量は全段無効。',
        weighted_distance='同じ重み付き数量で距離dを加重平均。各sideの最良から測る。',
        ofi='旧最良OFI。窓old+1〜nowまでのsum/abs-sum。nonzero_ofi_countは有限かつ絶対値>0のイベント数。3未満は証拠不足であり欠測とは別。',
        validity='snapshotはfresh30・spread<=2tick・非reset。窓source_validは始終点有効・異なる行・途中reset/不正なし。validはさらにOFI欠測なし・絶対和>0。同一行は無変化でなく無効。',
        clock='同時計先頭のtime<判断−delayのみ。CurrentPriceTimeは最終約定代理時計であり実受信順を証明しない。共通受信時刻/銘柄間共通seqは旧75全行調査と追加原本調査で未検出。',
        実窓長='予定windowと実source時刻差は異なる場合がある。actual_secondsと同一row/zero分母を記録し、5秒の正確なリアルタイム取得と混同しない。',
        storage={'snapshots':'work/wave_v76/inputs/snapshots.pkl key=(session,symbol)、全旧ready行1対1',
                 'grids':'work/wave_v76/inputs/grids.pkl key=delay→session→{grid,markets[symbol]→{current,windows[window]}}'},
        API={'material':'prepare.material()→ready,book,snapshots,grids','snapshot_values':'core.snapshot_values(raw,tick)→dict',
             'market_features':'core.market_features(grid,delay,ready,book,snapshot,windows,max_age)→dict',
             'session_features':'core.session_features(ready,books,snapshots,session,delay)→dict'},
        hashes={n:digest(HERE/n) for n in ('core.py','prepare.py','snapshots.pkl','grids.pkl')},API取得=0,実注文=0,損益閲覧=0))
    print('共通29場・58口座の即時板と5秒窓入力完成',flush=True)


if __name__=='__main__':
    main()
