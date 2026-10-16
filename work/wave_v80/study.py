"""小幅売買の初回探索・原因を踏まえた改修・固定代表の後半再確認を分ける。"""

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
import numba
numba.config.CACHE_DIR=str(HERE/'numba_cache')
import numpy as np
import engine
import accounting

SYMBOLS=('TOPIX','NK225')
PROFILES=[dict(profile='P1',target=1,stop=2,hold=15,trail=0),dict(profile='P2',target=2,stop=2,hold=30,trail=0),
          dict(profile='P3',target=3,stop=2,hold=60,trail=0),dict(profile='P4',target=2,stop=3,hold=60,trail=0),
          dict(profile='P5',target=2,stop=2,hold=60,trail=1),dict(profile='P6',target=4,stop=3,hold=120,trail=0)]


def load(path: Path) -> object:
    """機能: 保存済み素材だけを読み込む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def save(path: Path,value: object) -> None:
    """機能: 今回作業内にだけ素材を保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE);path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.pkl':path.write_bytes(pickle.dumps(value,protocol=5))
    else:path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def digest(path: Path) -> str:
    """機能: 事前固定と再生結果の内容指紋を計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(4*1024*1024):h.update(chunk)
    return h.hexdigest()


def deny(*args,**kwargs) -> None:
    """機能: 売買再生からの外部通信を禁止する。

    引数: 任意。返り値: なし(None)、例外を送出する。
    """
    raise RuntimeError('保存資料のみを用いる')


def catalog() -> list:
    """機能: 初回損益前に8入口・6管理・3約定・2休止の288条件を定める。

    引数: なし。返り値: 設定一覧(list)。
    """
    return [dict(id=f'S{s+1}_{p["profile"]}_M{mode}_C{cool}',signal=s,entry_mode=mode,cooldown=cool,repair_mode=0,**p)
            for s in range(8) for p in PROFILES for mode in range(3) for cool in (5,30)]


def input_paths() -> list:
    """機能: 再生で読む既往の原本対応素材を列挙する。

    引数: なし。返り値: パス一覧(list[Path])。
    """
    meta=load(ROOT/'work/wave_v77/inputs/metadata.json')
    return [ROOT/p for kind in ('ready','features') for p in meta['input_paths'][kind]]+[ROOT/'work/wave_v77/inputs/extra_inputs.pkl',ROOT/'work/wave_v77/inputs/extra_features.pkl']


def freeze() -> None:
    """機能: 初回の条件・選択規則・後半隔離・約定制約を固定する。

    引数: なし。返り値: なし(None)。上書き不可。
    """
    assert not (HERE/'初回事前固定.json').exists()
    sessions=load(ROOT/'work/wave_v77/inputs/metadata.json')['sessions']
    files=input_paths()+[HERE/p for p in ('engine.py','accounting.py','study.py','signals.py','prepare.py','prepared/signals.pkl')]
    save(HERE/'初回事前固定.json',dict(条件=catalog(),全30=sessions,前16=sessions[:16],後14=sessions[16:],
        発見='まず前16場・発注遅延5秒だけで全288条件。後14の新損益は代表固定まで見ない。過去研究では既知の30場なので未知とは呼ばない。',
        代表選択='成行・到着価格上限・待機指値ごとに1条件。両商品で20決済以上かつ8稼働場以上を優先。低い方の金額利益割合、次に両平均、次に低い方の収支/手数料、最後IDの順。該当数不足なら参考診断用とする。無方向S8は代表の選定対象外で対照専用。',
        改修='初回の損失を入口/到達まで/保有/返済待ち/再エントリーへ分解してから少数改修を固定する。原本の未来価格では入口を変えない。改修後の利益喪失を併記し、結果を見た後半差替えはしない。',
        確認='前半で選んだ基本3と改修3を固定した後、全30場を遅延0/1/5秒で再生。両商品後14黒字、各20決済以上、両商品の後14最大勝ち場除外黒字、両方金額利益割合>=0.8を強い候補条件とする。未達は未達と表示。',
        時間='信号1秒格子、情報はgrid-1秒の厳密過去・同時計先頭、現在の古さ10秒以内・窓始点15秒以内。3秒以内案は損益を計算する前に観測不足と分かり、原本更新間隔だけを理由に変更。厳格版を別保存。注文は判断から指定秒後の最初の有効原本行。新規も返済も遅延。原本は最終約定代理時計で、真の受信因果や実際の5秒を保証できない。',
        指値='M1は到達時の気配が判断時気配より不利1呼値以内の即時判定上限指値近似。M2は判断時自己側気配で待ち、到達後に対向気配が1呼値通過した時だけ指値で全量約定する仮定。15秒期限+取消到達待ち、同時計は取消優先。実商品板・待ち順位・部分約定は未再現。',
        料金='TOPIXミニ10枚1000円/pt・片道41.8円/枚、日経マイクロ20枚10円/pt・片道11円/枚。注文単位円未満切捨て。価格基準の呼値は観測ラージ0.5/10。',
        共通='全量初回・ナンピン/両建てなし。場内全返済。未決済・未処理注文は失格。保有/取消期限は価格観測がなくても時計で発火する。',
        SHA256={str(p.relative_to(ROOT)):digest(p) for p in files},API取得=0,実注文=0))


def material() -> tuple:
    """機能: 元の価格列と、損益に依存しない新しい秒信号を接続する。

    引数: なし。返り値: ready/book/signals/maps(tuple)。
    """
    meta=load(ROOT/'work/wave_v77/inputs/metadata.json');ready={};books={}
    for kind,target in (('ready',ready),('features',books)):
        for p in meta['input_paths'][kind]:target.update(load(ROOT/p))
    ready.update(load(ROOT/'work/wave_v77/inputs/extra_inputs.pkl'));books.update(load(ROOT/'work/wave_v77/inputs/extra_features.pkl'))
    signals=load(HERE/'prepared/signals.pkl')
    maps={k:(np.searchsorted(signals[k]['grid'],r['time_s'],side='right')-1).astype(np.int32) for k,r in ready.items()}
    return ready,books,signals,maps


def arguments(c: dict,key: tuple,materials: tuple,delay: int) -> tuple:
    """機能: 決めた入口と管理を遅延エンジンの引数へ接続する。

    引数: c(dict)、key/materials(tuple)、delay(int)。返り値: エンジン引数(tuple)。
    """
    ready,books,signals,maps=materials;r,f,s=ready[key],books[key],signals[key]
    quality=f['valid']&~f['reset']&np.isfinite(f['bid'])&np.isfinite(f['ask'])&(f['bid']>0)&(f['ask']>f['bid'])&(f['ask']-f['bid']<=r['tick']+1e-8)
    qty,value,fee=(10,1000.,41.8) if key[1]=='TOPIX' else (20,10.,11.)
    return (r['time_s'],f['bid'],f['ask'],quality,f['reset'],maps[key],s['grid'],s['states'][c['signal']],s['source_self'],s['source_peer'],s['bid'],s['ask'],
        r['tick'],r['start'],r['limit'],qty,value,fee,float(delay),c['entry_mode'],float(c['target']),float(c['stop']),float(c['hold']),c['trail'],float(c['cooldown']),c['repair_mode'])


def run_one(c: dict,materials: tuple,sessions: list,base: Path,delay: int,fixed: dict) -> str:
    """機能: 一条件を対象の全場で完全再生し、全注文と取消を残す。

    引数: c/fixed(dict)、materials(tuple)、sessions(list)、base(Path)、delay(int)。返り値: 設定ID(str)。
    """
    target=base/'results'/f'{c["id"]}.json'
    if target.exists():return c['id']
    rows=[];ledgers={}
    for key in sorted(materials[0]):
        if key[0] not in sessions:continue
        args=arguments(c,key,materials,delay);out=engine.simulate(*args);rows.append(accounting.account(key,args,out))
        ledgers[key]=dict(orders=out[0],trades=out[1],curve_hash=hashlib.sha256(out[2].tobytes()).hexdigest(),stats=out[3],events=out[4])
    periods={name:{s:accounting.aggregate(rows,s,subset) for s in SYMBOLS} for name,subset in [('対象',sessions),('前16',fixed['前16']),('後14',fixed['後14'])]}
    path=base/'ledgers'/f'{c["id"]}.pkl';save(path,ledgers)
    save(target,dict(config=dict(c,latency=delay),rows=rows,periods=periods,ledger_SHA256=digest(path)))
    return c['id']


def score(result: dict) -> tuple:
    """機能: 両商品の低い方の金額比率で前半だけを順位付けする。

    引数: result(dict)。返り値: 大きい方が上位の順位キー(tuple)。
    """
    a=[result['periods']['前16'][s] for s in SYMBOLS]
    eligible=all(v['trades']>=20 and v['active_sessions']>=8 for v in a)
    shares=[v['profit_share'] if v['profit_share'] is not None else -1. for v in a]
    return (eligible,min(shares),sum(shares)/2,min(v['net']/max(1.,v['fees']) for v in a),result['config']['id'])


def choose_initial() -> None:
    """機能: 後半を見ず、約定方式ごとの初回代表を固定する。

    引数: なし。返り値: なし(None)。上書き不可。
    """
    assert not (HERE/'初回前半選定.json').exists()
    results=[load(p) for p in (HERE/'first/results').glob('*.json')];assert len(results)==288
    chosen=[max([r for r in results if r['config']['entry_mode']==mode and r['config']['signal']!=7],key=score) for mode in (0,1,2)]
    save(HERE/'初回前半選定.json',dict(代表=[r['config'] for r in chosen],順位根拠=[dict(id=r['config']['id'],score=score(r),前16=r['periods']['前16']) for r in chosen],後半未参照=True,
        SHA256={str(p.relative_to(ROOT)):digest(p) for p in (HERE/'first/results').glob('*.json')}))


def main() -> None:
    """機能: 初回探索又は固定した後半確認だけを実行する。

    引数: CLI --freeze/--select(bool)、--stage(str)、--delay/--workers(int)。返り値: なし(None)。
    """
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--select',action='store_true');p.add_argument('--stage',choices=('first','repair','final'),default='first');p.add_argument('--delay',type=int,choices=(0,1,5),default=5);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    socket.socket.connect=deny;socket.create_connection=deny
    if a.freeze:freeze();print('初回288条件と選択規則を固定');return
    fixed=load(HERE/'初回事前固定.json');assert all(digest(ROOT/name)==sha for name,sha in fixed['SHA256'].items())
    if a.select:choose_initial();print('初回代表を前半だけで固定');return
    if a.stage=='first':configs=fixed['条件'];sessions=fixed['前16'];base=HERE/'first';assert a.delay==5
    elif a.stage=='repair':configs=load(HERE/'改修事前固定.json')['条件'];sessions=fixed['前16'];base=HERE/'repair';assert a.delay==5
    else:configs=load(HERE/'最終前半選定.json')['確認条件'];sessions=fixed['全30'];base=HERE/'final'/f'delay{a.delay}'
    materials=material();engine.simulate(*arguments(configs[0],(sessions[0],'TOPIX'),materials,a.delay))
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        tasks=[pool.submit(run_one,c,materials,sessions,base,a.delay,fixed) for c in configs]
        for i,f in enumerate(as_completed(tasks),1):
            identifier=f.result()
            if i%12==0 or i==len(configs):print(f'{a.stage} 遅延{a.delay}秒 {i}/{len(configs)} {identifier}',flush=True)


if __name__=='__main__':
    main()
