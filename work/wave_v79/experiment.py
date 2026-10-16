"""J2赤字上位の原因から事前固定した18防止策を、全30場で完全再生する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
import math
from pathlib import Path
import pickle
import socket
import sys

sys.dont_write_bytecode=True
import numba
import numpy as np
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
numba.config.CACHE_DIR=str(HERE/'numba_cache')
import engine
import accounting
import signals
import prevention

BASELINE='J2_F0_B0_H0_R0'
SYMBOLS=('TOPIX','NK225')


def load(path: Path) -> object:
    """機能: 固定済みの保存素材を読み込む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def save(path: Path,value: object) -> None:
    """機能: 今回の作業内へ検証資料を保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE);path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.pkl':path.write_bytes(pickle.dumps(value,protocol=5))
    else:path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def digest(path: Path) -> str:
    """機能: 固定条件と素材の指紋を計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while data:=stream.read(4*1024*1024):h.update(data)
    return h.hexdigest()


def deny(*args,**kwargs) -> None:
    """機能: 保存データ以外への通信を禁止する。

    引数: 任意。返り値: なし(None)、例外を送出する。
    """
    raise RuntimeError('保存資料のみを使用する')


def catalog() -> list[dict]:
    """機能: 理由ごとの入口6種と出口3種を固定する。

    引数: なし。返り値: 全18設定(list[dict])。
    """
    return [dict(id=f'E{entry}_X{exit_mode}',entry=entry,exit_mode=exit_mode) for entry in range(6) for exit_mode in range(3)]


def freeze() -> None:
    """機能: 防止策の損益を見る前に条件と全場評価方法を固定する。

    引数: なし。返り値: なし(None)。固定資料は上書きしない。
    """
    assert not (HERE/'事前固定.json').exists()
    baseline=load(ROOT/'work/wave_v78/results'/f'{BASELINE}.json');prior=load(ROOT/'work/wave_v78/事前固定.json')
    sessions=prior['全30'];worst={s:[r['session'] for r in sorted([r for r in baseline['rows'] if r['symbol']==s],key=lambda r:(r['net'],r['session']))[:3]] for s in SYMBOLS}
    excluded=set(worst['TOPIX']+worst['NK225']);days={}
    for s in SYMBOLS:
        values={}
        for r in baseline['rows']:
            if r['symbol']==s:values[r['session'][:10]]=values.get(r['session'][:10],0.)+r['net']
        days[s]=sorted(values.items(),key=lambda v:(v[1],v[0]))[:3]
    hashes=dict(prior['SHA256'])
    files=[HERE/p for p in ('experiment.py','prevention.py','engine.py','accounting.py','signals.py')]
    files+=[ROOT/'work/wave_v78/results'/f'{BASELINE}.json',ROOT/'work/wave_v78/ledgers'/f'{BASELINE}.pkl']
    hashes.update({str(p.relative_to(ROOT)):digest(p) for p in files})
    save(HERE/'事前固定.json',dict(条件=catalog(),対象=BASELINE,全30=sessions,前16=sessions[:16],後14=sessions[16:],商品別赤字上位3=worst,
        診断対象5場=sorted(excluded),対象外25=[s for s in sessions if s not in excluded],開始日合計の赤字上位3=days,
        E0='基準J2の入口をそのまま再生。',
        E1='両市場15秒OFIが有効・非ゼロ3件以上・方向比>=0.1の明確な支持を必須とする。',
        E2='発注判断時点の自己気配が、旧入口候補が実際に使った自己原本行の参照気配より不利に1呼値を超えて進んでいたら新規を見送る。買ask・売bidで比較。J2追加確認の5秒格子の参照行とは区別し、未来の約定値は参照しない。',
        E3='E1とE2を両方満たす場合だけ入る。',
        E4='既往J3同様、双方の過去300秒の価格純移動/総変動>=0.2を必要とする。入口の往復を除く対照。',
        E5='双方の有効な距離加重板の偏りが入口方向と逆でないこと(方向×偏り>=0)を必要とする。板厚仮説の対照。',
        X0='0.4%幅・30分期限・場内撤収という基準J2の出口。',
        X1='X0に加え、両市場の30秒売買両気配が各1呼値逆行する状態を15秒確認して返済する。両方の参照行更新、有効価格窓が必須。',
        X2='X0に加え、自己の30秒売買両気配が各1呼値逆行し、相手の30秒中値も保有方向へ進んでいない状態を15秒確認して返済する。相手の中立は可、欠測は不可。双方参照行更新必須。',
        共通='基準の全量10/20枚、片道手数料41.8/11円を注文合計で円未満切捨て、判断後次有効ラージ気配約定。既存エンジンを同一内容で使用。追跡幅や保有時間を変えない。',
        評価='基準の最悪3場だけでなく、商品別の残27場、いずれかが対象だった5場を除く25場、全30、前16/後14で各商品別に利益・損失・収支・勝ち削減・最大時価下落を比較する。1/5/15秒を全18条件で再生。',
        後知恵の扱い='損失日は結果から選んだ説明用標本。全30は既知で未見ではない。条件は今回の診断から立案したもので、未来の防止能力の証明ではない。終値・将来極値で取引を止めず、結果を見て閾値追加/代表差替えはしない。',
        日の扱い='主診断は各セッション。開始日デイ+ナイト合計の上位3も併記する。商品間の円を合算しない。',
        SHA256=hashes,現在API=0,実注文=0))


def material(delay: int) -> tuple:
    """機能: 原本対応素材と厳密過去の共同情報へ防止条件を接続する。

    引数: delay(int)。返り値: ready,book,state,maps,entries,legacy,meta,prevent(tuple)。
    """
    meta=load(ROOT/'work/wave_v77/inputs/metadata.json');ready={};book={}
    for p in meta['input_paths']['ready']:ready.update(load(ROOT/p))
    for p in meta['input_paths']['features']:book.update(load(ROOT/p))
    ready.update(load(ROOT/'work/wave_v77/inputs/extra_inputs.pkl'));book.update(load(ROOT/'work/wave_v77/inputs/extra_features.pkl'))
    state=load(ROOT/'work/wave_v78/prepared'/f'signals_delay{delay}.pkl')
    maps={k:signals.mapping(state[k[0]]['grid'],r) for k,r in ready.items()}
    entries=load(ROOT/'work/wave_v77/prepared'/f'signals_delay{delay}.pkl');legacy=load(ROOT/'work/wave_v77/prepared'/f'legacy_delay{delay}.pkl')
    prepared=prevention.build(load(ROOT/'work/wave_v77/inputs'/f'grids_delay{delay}.pkl'))
    return ready,book,state,maps,entries,legacy,meta,prepared


def arguments(c: dict,key: tuple,ready: dict,book: dict,state: dict,maps: dict,entries: dict,legacy: dict,meta: dict,prevent: dict) -> tuple:
    """機能: 基準J2の新規だけを現在証拠で棄却し、返済旗を接続する。

    引数: 設定と素材(dict)、key(tuple)。返り値: 旧エンジン互換の29引数(tuple)。
    """
    r,f=ready[key],book[key];s=state[key[0]];e=entries[key[0]]['entries']['J2'];mapped=maps[key];p=prevent[key[0]]['markets'][key[1]]
    event=np.zeros(len(r['time_s']),dtype=np.int8)
    for candidate in legacy[key]['candidates']:
        i,d=int(candidate[1]),int(candidate[2]);g=int(mapped[i]);name='long' if d==1 else 'short'
        if g<0 or not e[f'{name}_allowed'][g]:continue
        if c['entry'] in (1,3) and not p[f'support_{name}'][g]:continue
        if c['entry'] in (2,3):
            source=int(candidate[3])
            assert 0<=source<i
            quote,reference=(f['ask'][i],f['ask'][source]) if d==1 else (f['bid'][i],f['bid'][source])
            if not np.isfinite(reference) or d*(quote-reference)>r['tick']+1e-8:continue
        if c['entry']==4 and not p[f'efficient_{name}'][g]:continue
        if c['entry']==5 and not p[f'depth_{name}'][g]:continue
        event[i]=d
    quality=np.asarray(f['valid']&(f['bid']>0)&(f['ask']>f['bid'])&(f['ask']-f['bid']<=2*r['tick']+1e-9),dtype=bool)
    reference=meta['references']['|'.join(key)]['ref_open'];assert reference['known_from_i']==0
    width=max(2,math.ceil(reference['value']*.004/r['tick']-1e-10))*r['tick']
    qty,value,fee=(10,1000.,41.8) if key[1]=='TOPIX' else (20,10.,11.)
    exits=[p[f'x{c["exit_mode"]}_{name}'] if c['exit_mode'] else np.zeros(len(s['grid']),dtype=bool) for name in ('long','short')]
    return (r['time_s'],f['bid'],f['ask'],quality,f['reset'],event,mapped,s['grid'],s['valid'],s['common'],*exits,
        s['fd_price_long'],s['fd_price_short'],r['tick'],r['start'],r['limit'],qty,value,fee,width,s['current300_valid'],s['trend300'],s['source_top'],s['source_nk'],
        int(c['exit_mode']>0),0.,0,0)


def scopes(fixed: dict,symbol: str) -> dict:
    """機能: 診断対象と対象外の成績を分ける期間を返す。

    引数: fixed(dict)、symbol(str)。返り値: 期間名→セッション(list)のdict。
    """
    worst=fixed['商品別赤字上位3'][symbol]
    return {'全30':fixed['全30'],'赤字上位3':worst,'残り27':[s for s in fixed['全30'] if s not in worst],
            '対象外25':fixed['対象外25'],'前16':fixed['前16'],'後14':fixed['後14']}


def output_base(delay: int) -> Path:
    """機能: 主条件と情報遅延感度の保存先を区別する。

    引数: delay(int)。返り値: 保存先(Path)。
    """
    return HERE if delay==5 else HERE/'sensitivity'/f'delay{delay}'


def run_one(c: dict,materials: tuple,fixed: dict,delay: int) -> str:
    """機能: 一条件を全場再生し、決済・全時価・損失対象外も保存する。

    引数: c/fixed(dict)、materials(tuple)、delay(int)。返り値: 条件ID(str)。
    """
    base=output_base(delay);target=base/'results'/(c['id']+'.json')
    if target.exists():return c['id']
    rows=[];ledgers={}
    for key in sorted(materials[0]):
        args=arguments(c,key,*materials);out=engine.simulate(*args);row=accounting.account(key,args,out)
        row['candidate_count']=int(np.count_nonzero(args[5]));rows.append(row)
        ledgers[key]=dict(orders=out[0],trades=out[1],stats=out[3],events=out[4],curve_hash=hashlib.sha256(out[2].tobytes()).hexdigest())
    periods={p:{s:accounting.aggregate(rows,s,scopes(fixed,s)[p]) for s in SYMBOLS} for p in scopes(fixed,'TOPIX')}
    path=base/'ledgers'/(c['id']+'.pkl');save(path,ledgers)
    save(target,dict(config=dict(c,delay=delay),rows=rows,periods=periods,ledger_SHA256=digest(path)))
    return c['id']


def check_baseline(delay: int) -> None:
    """機能: 今回の無変更基準を旧78全60口座と完全照合する。

    引数: delay(int)。返り値: なし(None)。
    """
    oldbase=ROOT/'work/wave_v78' if delay==5 else ROOT/'work/wave_v78/sensitivity'/f'delay{delay}'
    old=load(oldbase/'ledgers'/f'{BASELINE}.pkl');new=load(output_base(delay)/'ledgers/E0_X0.pkl')
    assert len(old)==len(new)==60
    for key,v in old.items():
        for field in ('orders','trades','stats','events'):assert np.array_equal(v[field],new[key][field]),(key,field)
        assert v['curve_hash']==new[key]['curve_hash']
    save(output_base(delay)/'J2基準完全一致.json',dict(合格=True,口座数=60,遅延秒=delay))


def main() -> None:
    """機能: 事前固定後だけ18条件を再生し、基準が変わっていないか検査する。

    引数: CLI --freeze(bool)、--delay/--workers(int)。返り値: なし(None)。
    """
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--delay',type=int,choices=(1,5,15),default=5);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    socket.socket.connect=deny;socket.create_connection=deny
    if a.freeze:freeze();print('18条件を新損益前に固定');return
    fixed=load(HERE/'事前固定.json');assert all(digest(ROOT/p)==h for p,h in fixed['SHA256'].items())
    materials=material(a.delay);configs=fixed['条件']
    engine.simulate(*arguments(configs[0],sorted(materials[0])[0],*materials))
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        tasks=[pool.submit(run_one,c,materials,fixed,a.delay) for c in configs]
        for i,f in enumerate(as_completed(tasks),1):print(f'遅延{a.delay}秒 {i}/18 {f.result()}',flush=True)
    check_baseline(a.delay)


if __name__=='__main__':
    main()
