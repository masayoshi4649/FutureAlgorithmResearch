"""金額で利益8対損失2を目標に、二市場判断と損益保護を事前固定して比較する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle
import socket
import sys

import numpy as np
import numba

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
numba.config.CACHE_DIR=str(HERE/'numba_cache')
import engine
import accounting

SYMBOLS=('TOPIX','NK225')
BASELINE='J0_P0_R40_T40_H30_A0'


def load(path: Path) -> object:
    """機能: 保存資料を読み取る。

    引数: path(Path)。返り値: 内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def save(path: Path,value: object) -> None:
    """機能: 本作業配下だけに結果を保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.pkl':path.write_bytes(pickle.dumps(value,protocol=5))
    else:path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def digest(path: Path) -> str:
    """機能: ファイル指紋を計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as f:
        while data:=f.read(4*1024*1024):h.update(data)
    return h.hexdigest()


def module(name: str,path: Path) -> object:
    """機能: 同名モジュールの衝突を避けて原本を読み込む。

    引数: name(str)、path(Path)。返り値: モジュール(object)。
    """
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m;spec.loader.exec_module(m);return m


def deny(*args,**kwargs) -> None:
    """機能: バックテスト中の外部通信を禁止する。

    引数: args/kwargs(任意)。返り値: なし(None)、常に例外。
    """
    raise RuntimeError('保存データのみ使用し、通信しない')


def identity(c: dict) -> str:
    """機能: 一設定の識別子を決定する。

    引数: c(dict)。返り値: ID(str)。
    """
    return f"{c['entry']}_P{c['policy']}_R{c['stop_bp']}_T{c['trail_bp']}_H{c['hold_minutes']}_A{c['allocation']}"


def catalog() -> list[dict]:
    """機能: 12入口と固定出口・数量を492条件に組み合わせる。

    引数: なし。返り値: 設定列(list[dict])。
    """
    configs=[]
    for family in ('J','Q','P'):
        for variant in range(4):
            profiles=[(0,40,40,30,0)]+[(p,r,r if p==2 else 2*r,h,a) for p in range(1,6) for r in (10,20) for h in (30,60) for a in (0,1)]
            for policy,stop,trail,hold,allocation in profiles:
                c=dict(entry=f'{family}{variant}',family=family,policy=policy,stop_bp=stop,trail_bp=trail,
                    hold_minutes=hold,allocation=allocation,cooldown=30. if policy==0 else 300.,delay=5)
                c['id']=identity(c);configs.append(c)
    assert len(configs)==492 and len({c['id'] for c in configs})==492
    return configs


def freeze() -> None:
    """機能: 条件・評価・未見確認・プログラムと入力の指紋を損益前に固定する。

    引数: なし。返り値: なし(None)。固定済みは上書きしない。
    """
    assert not (HERE/'事前固定.json').exists()
    meta=load(HERE/'inputs/metadata.json')
    files=[HERE/x for x in ('study.py','engine.py','accounting.py','signals.py','prepare_signals.py','inputs/core.py','inputs/prepare.py',
        'inputs/metadata.json','prepared/prepare_legacy.py','theory/金額8対2を目指す改善の事前仮説.json')]
    files+=sorted((HERE/'prepared').glob('*.pkl'))
    assert len(list((HERE/'prepared').glob('signals_delay*.pkl')))==3
    assert len(list((HERE/'prepared').glob('legacy_delay*.pkl')))==3
    paths=set(meta['reused_input_hashes'])|{str((HERE/'inputs'/p).relative_to(ROOT)) for p in meta['hashes']}
    files += [ROOT/p for p in sorted(paths)]
    save(HERE/'事前固定.json',dict(条件=catalog(),前16=meta['sessions'][:16],後13=meta['sessions'][16:29],全29=meta['sessions'][:29],
        追加1=meta['sessions'][29:],全30=meta['sessions'],基準=BASELINE,
        目標='同商品内の手数料後・建値別利益/(利益+損失)>=80%、すなわちPF>=4。両商品別々に判定、円を混ぜない。',
        会計='初回から全返済までを1組。追加玉の負けを他玉と相殺せず建値別に利益と損失を合算。組勝率は別指標。',
        入口='J旧J1と逆OFI除外・300秒足並み/効率、Q最良1段板と逆OFI除外・180秒進行、P共通300秒方向中の30/60秒反落後再開。12入口。signals.pyが厳密仕様。',
        管理='P0旧即時トレール。P1初期損切りと利益追従を独立。P2 0.5Rで費用込み建値保護。P3 2Rで追従幅半減/1R利益保護。P4観測済180秒高安で初期損切り。P5 5分進展なし＆共通方向不支持30秒で撤退。',
        停滞='P5は時間切れ性質の確認で同一板でも経過する。有効格子の連続を要求。反対返済の30秒確認は双方参照更新も要求する。',
        逆行判断='P1からP5は両30秒進行と両F15が反対を30秒継続すると全返済。一時的中立だけで利益玉を返済しない。',
        幅='観測済み始値の0.1/0.2%を初期損切り、最低2呼値切上げ。P2追従は同幅、他は倍幅。P4実建値から高安までをRとするが上限超過なら即返済判断。ATRなし。',
        数量='A0最初からTOPIXmini10/NK225micro20。A1初回2/4、追加3/6、追加5/10。順行0.5R/1Rかつ共通方向、全玉が既存保護線で損切られても初回損失枠を超えない時だけ追加。',
        枚数と約定='片方向上限10/20。判断後の次有効ラージ気配で買ask売bid、ミニ/マイクロ代用。数量毎注文費用切捨て、TOP41.8円/NK11円。追加後超過は次行返済し未来を見て注文取消しない。',
        場内='保有上限30/60分、終了5分前から新規停止、終了60秒前全返済判断、データ末尾の未返済は成功にしない。',
        時計='共通5秒格子、5秒より前の同時計先頭を参照。最終約定時計代理、真の共通受信時計なし。1/15秒遅延を固定感度とする。',
        選定='前16だけ。各3入口群、両商品20組8活動場以上が対象。悪い側金額損失割合、割合和、多い組数、IDの順で各1代表。未充足なら最良比較例を記録するが有望認定しない。',
        確認='後13の両商品10組5活動場以上、黒字、各80%以上を目標。最大黒字場を除いた割合・収支も示す。前29は既知資料で独立未知検証ではない。',
        感度='代表各々同一入口R幅期限のP1-5×A0/1と基準を固定し遅延1/15秒へ変更。結果で代表差替えなし。',
        未見='最後2026-10-09_Nightは前29の代表と対照を固定後にその群だけ1回、5秒で確認。未見の損益を見て再選定しない。',
        SHA256={str(p.relative_to(ROOT)):digest(p) for p in files},API取得=0,実注文=0))


def material(delay: int) -> tuple:
    """機能: 全30場の素材と固定共同信号を接続する。

    引数: delay(int)。返り値: ready,book,state,maps,legacy,meta(tuple)。
    """
    meta=load(HERE/'inputs/metadata.json');ready={};book={}
    for name in meta['input_paths']['ready']:ready.update(load(ROOT/name))
    for name in meta['input_paths']['features']:book.update(load(ROOT/name))
    ready.update(load(HERE/'inputs/extra_inputs.pkl'));book.update(load(HERE/'inputs/extra_features.pkl'))
    state=load(HERE/'prepared'/f'signals_delay{delay}.pkl')
    signal_module=module('共同信号77利用',HERE/'signals.py')
    maps={k:signal_module.mapping(state[k[0]]['grid'],r) for k,r in ready.items()}
    legacy=load(HERE/'prepared'/f'legacy_delay{delay}.pkl')
    return ready,book,state,maps,legacy,meta


def arguments(c: dict,key: tuple,ready: dict,book: dict,state: dict,maps: dict,legacy: dict,meta: dict) -> tuple:
    """機能: 一口座の原本と機械的注文条件を接続する。

    引数: 設定と素材(dict)、key(tuple)。返り値: 再生器引数(tuple)。
    """
    r,f=ready[key],book[key];s=state[key[0]];e=s['entries'][c['entry']];mapped=maps[key]
    event=np.zeros(len(r['time_s']),dtype=np.int8)
    if c['family']=='J':
        candidates=legacy[key]['candidates']
        for candidate in candidates:
            i,d=int(candidate[1]),int(candidate[2]);g=int(mapped[i])
            if c['entry']=='J0' or g>=0 and (e['long_allowed'][g] if d==1 else e['short_allowed'][g]):event[i]=d
    else:
        ix=np.flatnonzero(mapped>=0);event[ix]=e['event'][mapped[ix]]
    quality=np.asarray(f['valid']&(f['bid']>0)&(f['ask']>f['bid'])&(f['ask']-f['bid']<=2*r['tick']+1e-9),dtype=bool)
    opening=meta['references']['|'.join(key)]['ref_open']['value']
    assert meta['references']['|'.join(key)]['ref_open']['known_from_i']==0
    stop=max(2,math.ceil(opening*c['stop_bp']/10000/r['tick']-1e-10))*r['tick']
    trail=max(2,math.ceil(opening*c['trail_bp']/10000/r['tick']-1e-10))*r['tick']
    cap,value,fee=(10,1000.,41.8) if key[1]=='TOPIX' else (20,10.,11.)
    ref=s['reference'][key[1]]
    return (r['time_s'],f['bid'],f['ask'],quality,f['reset'],event,mapped,s['grid'],s['valid'],s['common'],s['opposite_long'],s['opposite_short'],
        ref['long'],ref['short'],r['tick'],r['start'],r['limit'],cap,value,fee,stop,trail,c['hold_minutes']*60.,c['policy'],c['allocation'],c['cooldown'])


def base_path(delay: int,unseen: bool=False) -> Path:
    """機能: 既往比較・感度・未見を異なる保存先にする。

    引数: delay(int)、unseen(bool)。返り値: ディレクトリ(Path)。
    """
    return HERE/'unseen' if unseen else HERE if delay==5 else HERE/'sensitivity'/f'delay{delay}'


def run_one(c: dict,materials: tuple,fixed: dict,delay: int,unseen: bool=False) -> str:
    """機能: 既往29場又は未見1場を分離して原本順に再生する。

    引数: c/fixed(dict)、materials(tuple)、delay(int)、unseen(bool)。返り値: ID(str)。
    """
    base=base_path(delay,unseen);target=base/'results'/(c['id']+'.json')
    if target.exists():return c['id']
    ready,book,state,maps,legacy,meta=materials;rows=[];ledgers={};front=hashlib.sha256()
    sessions=fixed['追加1'] if unseen else fixed['全29']
    for key in sorted(ready):
        if key[0] not in sessions:continue
        args=arguments(c,key,*materials);out=engine.simulate(*args)
        row=accounting.account(key,args,out);row['candidate_count']=int(np.count_nonzero(args[5]));rows.append(row)
        ledgers[key]=dict(orders=out[0],trades=out[1],stats=out[3],risk_events=out[4],curve_hash=hashlib.sha256(out[2].tobytes()).hexdigest())
        if key[0] in fixed['前16']:front.update(str(key).encode('utf8'));front.update(out[0].tobytes())
    path=base/'ledgers'/(c['id']+'.pkl');save(path,ledgers)
    periods={name:{s:accounting.aggregate(rows,s,fixed[name]) for s in SYMBOLS} for name in (('追加1',) if unseen else ('前16','後13','全29'))}
    save(target,dict(config=dict(c,delay=delay),rows=rows,periods=periods,ledger_SHA256=digest(path),front_orders_SHA256=front.hexdigest()))
    return c['id']


def score(r: dict) -> tuple:
    """機能: 前16の金額損失割合を悪い側優先で比較する。

    引数: r(dict)。返り値: 昇順評価(tuple)。
    """
    a=[r['periods']['前16'][s] for s in SYMBOLS];v=[x['money_loss_share'] if x['money_loss_share'] is not None else 1. for x in a]
    return max(v),sum(v),-sum(x['trades'] for x in a),r['config']['id']


def controls(c: dict) -> list[str]:
    """機能: 同じ入口・損切り幅・期限の保護と配分対照を列挙する。

    引数: c(dict)。返り値: 対照ID(list[str])。
    """
    if c['policy']==0:return [c['id']]
    return [identity(dict(c,policy=p,allocation=a,trail_bp=c['stop_bp'] if p==2 else 2*c['stop_bp'])) for p in range(1,6) for a in (0,1)]


def select() -> None:
    """機能: 前16だけで3代表と未見・感度対象を固定する。

    引数: なし。返り値: なし(None)。
    """
    assert not (HERE/'前半選定.json').exists()
    results=[load(p) for p in sorted((HERE/'results').glob('*.json'))];assert len(results)==492
    representatives=[];ids={BASELINE}
    for family in ('J','Q','P'):
        pool=[r for r in results if r['config']['family']==family]
        eligible=[r for r in pool if all(r['periods']['前16'][s]['trades']>=20 and r['periods']['前16'][s]['active_sessions']>=8 for s in SYMBOLS)]
        options=eligible or [r for r in pool if all(r['periods']['前16'][s]['trades']>0 for s in SYMBOLS)] or pool
        chosen=min(options,key=score);group=controls(chosen['config']);ids.update(group)
        representatives.append(dict(id=chosen['config']['id'],family=family,eligible=bool(eligible),score=score(chosen),controls=group))
    save(HERE/'前半選定.json',dict(代表=representatives,基準=BASELINE,感度対象=sorted(ids),未見対象=sorted(ids),前16だけで選択=True))
    print(json.dumps(representatives,ensure_ascii=False),flush=True)


def check_benchmark(delay: int) -> None:
    """機能: 旧J1の全58口座の注文・決済・全行時価を照合する。

    引数: delay(int)。返り値: なし(None)。
    """
    old=ROOT/'work/wave_v76' if delay==5 else ROOT/'work/wave_v76/sensitivity'/f'delay{delay}'
    prior=load(old/'ledgers/B_F15_E0_M0_C0_T40_H30.pkl')
    current=load(base_path(delay)/'ledgers'/(BASELINE+'.pkl'))
    for key,v in current.items():
        assert np.array_equal(v['orders'][:,:8],prior[key]['orders']),(key,'旧基準注文')
        assert np.array_equal(v['trades'][:,:11],prior[key]['trades']),(key,'旧基準決済')
        assert v['curve_hash']==prior[key]['curve_hash'],(key,'旧基準時価')
    save(base_path(delay)/'旧J1の完全一致.json',dict(合格=True,口座数=58,遅延=delay))


def main() -> None:
    """機能: 事前固定・492条件再生・選定・感度・固定未見検証を実行する。

    引数: CLIのfreeze/select/unseen(bool)、delay/workers(int)。返り値: なし(None)。
    """
    p=argparse.ArgumentParser()
    for flag in ('freeze','select','unseen'):p.add_argument('--'+flag,action='store_true')
    p.add_argument('--delay',type=int,default=5);p.add_argument('--workers',type=int,default=6);a=p.parse_args()
    socket.socket.connect=deny;socket.create_connection=deny
    if a.freeze:freeze();print('492条件を損益前に固定しました',flush=True);return
    if a.select:select();return
    fixed=load(HERE/'事前固定.json');assert a.delay in (1,5,15)
    assert all(digest(ROOT/path)==value for path,value in fixed['SHA256'].items()),'事前固定後の変更'
    configs=fixed['条件']
    if a.delay!=5 or a.unseen:
        chosen=load(HERE/'前半選定.json');ids=set(chosen['未見対象' if a.unseen else '感度対象']);configs=[c for c in configs if c['id'] in ids]
    if a.unseen:
        assert a.delay==5 and not (HERE/'未見確認開始.json').exists(),'未見は固定群を一度だけ実行'
        save(HERE/'未見確認開始.json',dict(対象=[c['id'] for c in configs],選定SHA256=digest(HERE/'前半選定.json'),未見=fixed['追加1']))
    for name in ('results','ledgers'):(base_path(a.delay,a.unseen)/name).mkdir(parents=True,exist_ok=True)
    materials=material(a.delay)
    # ----------------------------------------
    # JIT準備には必ず既往最初の口座を使い、未見損益の先行実行をしない。
    engine.simulate(*arguments(configs[0],sorted(materials[0])[0],*materials))
    with ThreadPoolExecutor(max_workers=max(1,min(12,a.workers))) as pool:
        tasks=[pool.submit(run_one,c,materials,fixed,a.delay,a.unseen) for c in configs]
        for i,task in enumerate(as_completed(tasks),1):
            ident=task.result()
            if i%24==0 or i==len(tasks):print(f'遅延{a.delay}秒 {i}/{len(tasks)}条件 {ident}',flush=True)
    if not a.unseen:check_benchmark(a.delay)
    else:save(HERE/'未見確認完了.json',dict(合格=True,固定群数=len(configs),追加場=fixed['追加1'],差替え=False))


if __name__=='__main__':
    main()
