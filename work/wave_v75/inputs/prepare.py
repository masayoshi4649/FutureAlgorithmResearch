"""保存29場の時計欄を原本で再点検し、既存入力を変更せず二銘柄の同期行を固定する。"""

from collections import Counter
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
       'features':['work/wave_v69/prepared/features.pkl','work/wave_v71/prepared/extra_features.pkl']}
DELAYS=(1,5,15,60)
CLOCK_KEYS=re.compile(rb'"([^"\r\n]*(?:Time|time|Date|date|Stamp|stamp|Receiv|receiv|Receipt|receipt|Seq|seq)[^"\r\n]*)"\s*:')


def digest(path: Path) -> str:
    """機能: 読取専用資料の内容指紋を計算する。

    引数: path(Path)。返り値: SHA256の16進表記(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(4*1024*1024):
            h.update(chunk)
    return h.hexdigest()


def save_json(name: str, value: dict) -> None:
    """機能: 担当する入力領域へ日本語UTF-8の検査記録を保存する。

    引数: name(str)、value(dict)。返り値: なし(None)。
    """
    (HERE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def load_material() -> tuple[dict,dict]:
    """機能: 旧56口座と追加2口座の既存配列を重複なく読取結合する。

    引数: なし。返り値: ready/features(tuple[dict,dict])。
    """
    output=[]
    for kind in ('ready','features'):
        merged={}
        for name in PATHS[kind]:
            current=pickle.loads((ROOT/name).read_bytes())
            assert not set(merged)&set(current)
            merged.update(current)
        output.append(merged)
    assert set(output[0])==set(output[1])
    return tuple(output)


def raw_clock_probe(key: tuple[str,str], ready: dict, feature: dict, expected: dict) -> dict:
    """機能: 全原本行の時計らしい欄を走査し、先頭・途中・末尾の同seq価格を照合する。

    引数: key(tuple[str,str])、ready/feature/expected(dict)。
    返り値: 時計欄の出現数、原本指紋、同seqサンプル(dict)。
    名前の走査は全行、値のJSON解釈は指定行のみとする。価格変動による損益を採点しない。
    """
    path=ROOT/'book'/key[1]/(key[0]+'.jsonl')
    n=len(ready['seq'])
    target={0,int(ready['seq'][0]),int(ready['seq'][n//2]),int(ready['seq'][-1])}
    names=Counter()
    samples=[]
    top_keys=set()
    h=hashlib.sha256()
    count=0
    with path.open('rb') as stream:
        for i,line in enumerate(stream):
            count=i+1
            h.update(line)
            names.update(m.group(1).decode('utf8') for m in CLOCK_KEYS.finditer(line))
            if i in target:
                raw=json.loads(line)
                top_keys.update(raw)
                samples.append(dict(seq=i,keys=list(raw),clock_values={k:v for k,v in raw.items() if isinstance(v,str) and ('Time' in k or 'time' in k)},
                    bid=raw.get('Buy1',{}).get('Price'),ask=raw.get('Sell1',{}).get('Price'),last=raw.get('CurrentPrice'),
                    nested_keys={k:list(v) for k,v in raw.items() if isinstance(v,dict)}))
                j=int(np.searchsorted(ready['seq'],i))
                if j<n and int(ready['seq'][j])==i:
                    assert datetime.fromisoformat(raw['CurrentPriceTime']).timestamp()==ready['time_s'][j]
                    assert raw['Buy1']['Price']==feature['bid'][j] and raw['Sell1']['Price']==feature['ask'][j]
                    assert raw['CurrentPrice']==ready['last'][j]
    assert h.hexdigest()==expected['raw_SHA256'] and count==expected['raw_rows'],('原本が以前の検査後に変更',key)
    return dict(session=key[0],symbol=key[1],raw_rows=count,raw_SHA256=h.hexdigest(),clock_key_counts=dict(sorted(names.items())),
        sampled_top_keys=sorted(top_keys),same_seq_samples=samples,全行時計名走査=True,原本同seq一致=True)


def quality(key: tuple[str,str], ready: dict, feature: dict) -> dict:
    """機能: 代理時計の繰返し、空白、無効板とリセットを価格予測なしで集計する。

    引数: key(tuple[str,str])、ready/feature(dict)。返り値: 品質集計(dict)。
    """
    t=ready['time_s']
    unique,first,counts=np.unique(t,return_index=True,return_counts=True)
    gaps=np.diff(unique)
    n=len(t)
    for field in ('seq','time_s','last'):
        np.testing.assert_array_equal(ready[field],feature[field])
    assert (np.diff(ready['seq'])>0).all() and (np.diff(t)>=0).all()
    assert all(len(a)==n for a in feature.values())
    return dict(session=key[0],symbol=key[1],rows=n,start=float(ready['start']),limit=float(ready['limit']),end=float(ready['limit']+300),
        valid_rows=int(feature['valid'].sum()),reset_rows=int(feature['reset'].sum()),unique_clock_count=len(unique),
        same_clock_extra_rows=n-len(unique),same_clock_extra_fraction=(n-len(unique))/n,
        same_clock_largest_batch=int(counts.max()),first_clock_reset_rows=int(feature['reset'][first].sum()),
        gaps_gt10=int((gaps>10).sum()),gaps_gt60=int((gaps>60).sum()),max_clock_gap=float(gaps.max(initial=0)),
        reset_reason_counts={str(int(v)):int(c) for v,c in zip(*np.unique(feature['reset_reason'],return_counts=True))},
        first_time=float(t[0]),last_time=float(t[-1]),first_seq=int(ready['seq'][0]),last_seq=int(ready['seq'][-1]))


def artificial_tests() -> list[str]:
    """機能: 厳密過去・同時計先頭・古さ・無効・リセット・未来切断を人工例で検査する。

    引数: なし。返り値: 合格した検査名(list[str])。
    """
    t=np.array([10.,10.,11.,11.,15.,30.])
    valid=np.ones(len(t),dtype=bool)
    reset=np.zeros(len(t),dtype=bool)
    targets=np.array([10.,11.,12.,20.,25.,31.,50.])
    got,_=core.asof_indices(targets,t,valid,reset,10.)
    np.testing.assert_array_equal(got,[-1,0,2,4,4,5,-1])
    bad=valid.copy();bad[2]=False
    np.testing.assert_array_equal(core.asof_indices(np.array([12.]),t,bad,reset)[0],[-1])
    reset[4]=True
    np.testing.assert_array_equal(core.asof_indices(np.array([20.]),t,valid,reset)[0],[-1])
    a=core.asof_indices(targets[:3],t[:4],valid[:4],reset[:4])
    b=core.asof_indices(targets[:3],t,valid,reset)
    np.testing.assert_array_equal(a[0],b[0]);np.testing.assert_array_equal(a[1],b[1])
    return ['期限と同時計の相手観測を不採用','同時計末尾ではなく先頭行','期限から10秒超は不採用',
        '無効先頭は同秒後続やより古い行で救済しない','reset行は不採用','未来付加前後で過去の採用行と古さが一致']


def main() -> None:
    """機能: 全保存場を検出し既存入力と照合、同期索引と時計監査を保存する。

    引数: なし。返り値: なし(None)。API取得と原本書込と損益閲覧は行わない。
    """
    HERE.mkdir(parents=True,exist_ok=True)
    ready,features=load_material()
    sessions=sorted({k[0] for k in ready})
    old=json.loads((ROOT/'work/wave_v74/inputs/refmetadata.json').read_text(encoding='utf8'))
    expected={(r['session'],r['symbol']):r for r in old['rows']}
    inventory={s:sorted(p.stem for p in (ROOT/'book'/s).glob('*.jsonl')) for s in ('TOPIX','NK225')}
    assert all(inventory[s]==sessions for s in inventory),('未準備原本場を検出',inventory)
    hashes={name:digest(ROOT/name) for names in PATHS.values() for name in names}
    assert hashes==old['input_SHA256']
    sync={s:core.session_sync(ready,features,s) for s in sessions}
    (HERE/'sync.pkl').write_bytes(pickle.dumps(sync,protocol=5))
    quality_rows=[quality(k,ready[k],features[k]) for k in sorted(ready)]
    coverage=[]
    for session,value in sync.items():
        for delay in DELAYS:
            total=len(value['grid'])
            coverage.append(dict(session=session,delay=delay,grid_count=total,
                TOPIX=int((value['indices'][delay]['TOPIX']>=0).sum()),NK225=int((value['indices'][delay]['NK225']>=0).sum()),
                both=int(value['both_available'][delay].sum()),both_fraction=float(value['both_available'][delay].mean())))
    spec=dict(sessions=sessions,accounts=len(ready),input_paths=PATHS,input_SHA256=hashes,prepared_quality=quality_rows,coverage=coverage,
        grid_step_seconds=15,delays=list(DELAYS),baseline_delay=5,max_cutoff_age_seconds=10,
        時計='CurrentPriceTimeの最終約定代理時計。共通受信時刻がないため実受信順を保証しない。',
        同期='start+300以上limit-300未満の共通15秒grid。両市場ともtime<grid-delayの最新時刻を選び、その同時計先頭準備行だけを採用する。',
        鮮度='cutoffからの古さ10秒以内。実古さはcutoff古さ+delay。無効又はreset先頭の救済なし。',
        履歴='窓始点にも同じstrict asof関数を使う。途中resetと観測欠損の連続性は算法側が検査し、この索引だけで窓を有効とみなさない。',
        配列仕様='sync[session]={grid,indices[delay][symbol],observation_age[delay][symbol],actual_age[delay][symbol],both_available[delay]}。欠測index=-1/age=NaN。',
        functions={'asof_indices':'targets,times,valid,reset,max_age=10 → (int32 indices,float32 age)','session_sync':'ready,features,session,delays=(1,5,15,60),step=15,max_age=10 → dict'},
        synthetic_tests=artificial_tests(),sync_SHA256=digest(HERE/'sync.pkl'),API取得=0,実注文=0,損益閲覧=0)
    save_json('同期入力仕様.json',spec)
    probes=[]
    for key in sorted(ready):
        probes.append(raw_clock_probe(key,ready[key],features[key],expected[key]))
        print(f'{key[0]} {key[1]} 時計・原本同seq照合完了',flush=True)
    save_json('原本時計の再調査.json',dict(sessions=sessions,accounts=len(ready),原本調査=probes,
        欄名走査範囲='Time/time/Date/date/Stamp/stamp/Receiv/receiv/Receipt/receipt/Seq/seqを含む全行キー。ほかの意味の受信時計が絶対にないという証明ではない。',
        判断='保存原本に共通受信時計と銘柄間共通連番は見つからない。CurrentPriceTimeは同時計で大量の板更新があり、先頭採用と遅延でも実受信因果は証明しない。',
        原本全58指紋一致=True,全保存場同期済=True,API取得=0,実注文=0,損益閲覧=0))
    print('29場・58口座の同期入力と原本時計監査が完了',flush=True)


if __name__=='__main__':
    main()
