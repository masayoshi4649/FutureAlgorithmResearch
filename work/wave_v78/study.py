"""歴代の知見を同じ入口・幅・枚数で分解し、162通りの機械的統合を検証する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
import math
from pathlib import Path
import pickle
import socket

import numpy as np
import numba

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
numba.config.CACHE_DIR=str(HERE/'numba_cache')
import engine
import accounting
import signals

SYMBOLS=('TOPIX','NK225')
BENCHMARK='J2_F0_B0_H0_R0'


def load(path: Path) -> object:
    """機能: 保存資料を読み込む。

    引数: path(Path)。返り値: 内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def save(path: Path,value: object) -> None:
    """機能: 当作業の出力だけを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE);path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.pkl':path.write_bytes(pickle.dumps(value,protocol=5))
    else:path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def digest(path: Path) -> str:
    """機能: 保存資料の指紋を求める。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as f:
        while data:=f.read(4*1024*1024):h.update(data)
    return h.hexdigest()


def deny(*args,**kwargs) -> None:
    """機能: 検証中の外部通信を禁止する。

    引数: 任意。返り値: なし(None)、常に例外。
    """
    raise RuntimeError('保存データのみを使用する')


def identity(c: dict) -> str:
    """機能: 入口と管理四軸をIDにする。

    引数: c(dict)。返り値: ID(str)。
    """
    return f"{c['entry']}_F{c['flow_mode']}_B{c['protect_level']}_H{c['hold_mode']}_R{c['rest_mode']}"


def catalog() -> list[dict]:
    """機能: 仮説から固定した162条件を列挙する。

    引数: なし。返り値: 条件列(list[dict])。
    """
    output=[]
    for entry in ('J0','J1','J2'):
        for f in range(3):
            for b in range(3):
                for h in range(3):
                    for r in range(2):
                        c=dict(entry=entry,flow_mode=f,protect_level=b,protect_fraction=(0.,.25,.5)[b],hold_mode=h,rest_mode=r,width_fraction=.004,delay=5)
                        c['id']=identity(c);output.append(c)
    assert len(output)==162;return output


def freeze() -> None:
    """機能: 統合条件・採点・既知資料という位置づけを損益前に固定する。

    引数: なし。返り値: なし(None)。上書きしない。
    """
    assert not (HERE/'事前固定.json').exists();meta=load(ROOT/'work/wave_v77/inputs/metadata.json')
    files=[HERE/p for p in ('study.py','engine.py','accounting.py','signals.py','prepare_signals.py','theory/統合前の敵対仮説.json')]
    files+=list((HERE/'evidence').glob('*.json'))+list((HERE/'prepared').glob('*.pkl'))
    old=load(ROOT/'work/wave_v77/事前固定.json');hashes=dict(old['SHA256'])
    hashes.update({str(p.relative_to(ROOT)):digest(p) for p in files})
    save(HERE/'事前固定.json',dict(条件=catalog(),前16=meta['sessions'][:16],後14=meta['sessions'][16:],全30=meta['sessions'],
        後13=meta['sessions'][16:29],追加1既知=meta['sessions'][29:],基準=BENCHMARK,
        意味='全30場は既に調査済み。前16選定と後14確認は既知資料内の再探索で未見検証ではない。現在APIで補完しない。',
        目的='各商品別に金額利益80%を目標。損小利大は平均勝ち/平均負け>1、安定性は黒字場数・週別・日夜・連敗・最大日除外・最大時価下落で別確認。全場黒字も別判定し無取引は勝ちにしない。',
        入口='J0旧J1の共通300秒進行と短期維持。J1は明確な逆OFIを除外。J2はさらに弱い側の300秒進行が強い側の1/4以上。旧77入口を完全継承。',
        F='F0なし、F1両市場FD(15秒OFIと距離板)の強反対を15秒確認、F2それに両市場30秒両気配の逆行各1呼値を同時に15秒確認。両source更新必須。ドテンなし。',
        B='トレール幅は全方式始値0.4%一定。B0無、B1その幅の1/4順行、B2その半分順行で費用込み建値へ保護線を引上げ。以後幅自体は狭めず、次原本行から既設線として判定。',
        H='H0固定30分、H1期限時に費用後含み益・共通方向維持・過去5分内に実順行極値更新・新鮮な既知格子があれば15分ずつ最大90分まで延長。H2固定90分。大欠測で15分延長先まで過ぎたら延長不可。',
        R='R0なし、R1確定2連敗で30分新規休止。その30分が過ぎてから、共通300秒方向が最後の負け方向以外(有効な中立含む)を60秒かつ双方参照更新で再準備。その後の通常入口だけで再開。セッションを跨いで連敗を継承しない。',
        枚数='TOPIXミニ10/NKマイクロ20を全量初回。追加も損玉持越しもなく、枚数削減で金額損失を良く見せない。',
        約定='判断後次有効原本気配の買ask/売bid。0.4%幅は最低2呼値切上げ。料金片道TOP41.8円/NK11円を注文合計切捨て。ラージ代用と時計の限界は旧77同じ。',
        優先='場末→保有期限又は延長判断→既設保護線→反対判断→新規。返済後30秒、休止中の新規は無効。開始5分後〜limit5分前が新規、limit60秒前返済判断。',
        選定='前16だけで各入口群1つと全体代表を固定。両商品20組8活動場以上を要求し、両黒字かつ平均勝負>1の群を優先、なければ両黒字、なければ活動充足のみ。最悪側金額損失割合→最悪側赤字活動場率→損失割合和→ID。',
        後半合格='後14両商品10組6活動場以上、黒字・平均勝負>1・最大黒字日(デイ＋ナイト)除外黒字を全て満たすか別判定。全日黒字/80%/3週黒字/遅延感度も別に表示。',
        感度='前半代表、基準、単一部品対照、代表から一部品を外す対照を1/15秒遅延でも再生。結果で代表差替えなし。',
        SHA256=hashes,API取得=0,実注文=0))


def material(delay: int) -> tuple:
    """機能: 旧77の固定入力と入口へ今回の共同管理を接続する。

    引数: delay(int)。返り値: ready,book,state,maps,entries,legacy,meta(tuple)。
    """
    meta=load(ROOT/'work/wave_v77/inputs/metadata.json');ready={};book={}
    for p in meta['input_paths']['ready']:ready.update(load(ROOT/p))
    for p in meta['input_paths']['features']:book.update(load(ROOT/p))
    ready.update(load(ROOT/'work/wave_v77/inputs/extra_inputs.pkl'));book.update(load(ROOT/'work/wave_v77/inputs/extra_features.pkl'))
    state=load(HERE/'prepared'/f'signals_delay{delay}.pkl')
    maps={k:signals.mapping(state[k[0]]['grid'],r) for k,r in ready.items()}
    entries=load(ROOT/'work/wave_v77/prepared'/f'signals_delay{delay}.pkl');legacy=load(ROOT/'work/wave_v77/prepared'/f'legacy_delay{delay}.pkl')
    return ready,book,state,maps,entries,legacy,meta


def arguments(c: dict,key: tuple,ready: dict,book: dict,state: dict,maps: dict,entries: dict,legacy: dict,meta: dict) -> tuple:
    """機能: 一場一商品の固定入口・共同状態・注文条件を作る。

    引数: cと素材(dict)、key(tuple)。返り値: 再生引数(tuple)。
    """
    r,f=ready[key],book[key];s=state[key[0]];e=entries[key[0]]['entries'][c['entry']];mapped=maps[key]
    event=np.zeros(len(r['time_s']),dtype=np.int8)
    for candidate in legacy[key]['candidates']:
        i,d=int(candidate[1]),int(candidate[2]);g=int(mapped[i])
        if c['entry']=='J0' or g>=0 and (e['long_allowed'][g] if d==1 else e['short_allowed'][g]):event[i]=d
    quality=np.asarray(f['valid']&(f['bid']>0)&(f['ask']>f['bid'])&(f['ask']-f['bid']<=2*r['tick']+1e-9),dtype=bool)
    reference=meta['references']['|'.join(key)]['ref_open'];assert reference['known_from_i']==0
    width=max(2,math.ceil(reference['value']*.004/r['tick']-1e-10))*r['tick']
    qty,value,fee=(10,1000.,41.8) if key[1]=='TOPIX' else (20,10.,11.)
    return (r['time_s'],f['bid'],f['ask'],quality,f['reset'],event,mapped,s['grid'],s['valid'],s['common'],s['fd_long'],s['fd_short'],
        s['fd_price_long'],s['fd_price_short'],r['tick'],r['start'],r['limit'],qty,value,fee,width,s['current300_valid'],s['trend300'],s['source_top'],s['source_nk'],
        c['flow_mode'],c['protect_fraction'],c['hold_mode'],c['rest_mode'])


def base_path(delay: int) -> Path:
    """機能: 主結果と感度を分ける。

    引数: delay(int)。返り値: 保存先(Path)。
    """
    return HERE if delay==5 else HERE/'sensitivity'/f'delay{delay}'


def run_one(c: dict,materials: tuple,fixed: dict,delay: int) -> str:
    """機能: 固定条件で全30場を再生し全明細と期間会計を保存する。

    引数: c/fixed(dict)、materials(tuple)、delay(int)。返り値: ID(str)。
    """
    base=base_path(delay);target=base/'results'/(c['id']+'.json')
    if target.exists():return c['id']
    rows=[];ledgers={};front=hashlib.sha256()
    for key in sorted(materials[0]):
        args=arguments(c,key,*materials);out=engine.simulate(*args);row=accounting.account(key,args,out)
        row['candidate_count']=int(np.count_nonzero(args[5]));rows.append(row)
        ledgers[key]=dict(orders=out[0],trades=out[1],stats=out[3],events=out[4],curve_hash=hashlib.sha256(out[2].tobytes()).hexdigest())
        if key[0] in fixed['前16']:front.update(str(key).encode('utf8'));front.update(out[0].tobytes())
    path=base/'ledgers'/(c['id']+'.pkl');save(path,ledgers)
    periods={p:{s:accounting.aggregate(rows,s,fixed[p]) for s in SYMBOLS} for p in ('前16','後14','全30','後13','追加1既知')}
    save(target,dict(config=dict(c,delay=delay),rows=rows,periods=periods,ledger_SHA256=digest(path),front_orders_SHA256=front.hexdigest()))
    return c['id']


def score(r: dict) -> tuple:
    """機能: 両商品で悪い側の金額比率と赤字場率を優先する。

    引数: r(dict)。返り値: 昇順評価(tuple)。
    """
    a=[r['periods']['前16'][s] for s in SYMBOLS];loss=[v['money_loss_share'] if v['money_loss_share'] is not None else 1. for v in a]
    red=[1-v['positive_session_rate'] if v['positive_session_rate'] is not None else 1. for v in a]
    return max(loss),max(red),sum(loss),r['config']['id']


def controls(c: dict) -> list[str]:
    """機能: 同入口の基準、部品単独、代表から一部品だけ外す対照を固定する。

    引数: c(dict)。返り値: 対照ID列(list[str])。
    """
    base=dict(c,flow_mode=0,protect_level=0,hold_mode=0,rest_mode=0);ids={identity(base),c['id']}
    for key,values in [('flow_mode',(1,2)),('protect_level',(1,2)),('hold_mode',(1,2)),('rest_mode',(1,))]:
        for value in values:ids.add(identity(dict(base,**{key:value})))
        ids.add(identity(dict(c,**{key:0})))
    return sorted(ids)


def select() -> None:
    """機能: 前16だけの代表を固定し、後14を理由に選び直さない。

    引数: なし。返り値: なし(None)。
    """
    assert not (HERE/'前半選定.json').exists();results=[load(p) for p in sorted((HERE/'results').glob('*.json'))];assert len(results)==162
    representatives=[];sensitivity={BENCHMARK,'J0_F0_B0_H0_R0','J0_F1_B0_H0_R0'}
    for entry in ('J0','J1','J2'):
        pool=[r for r in results if r['config']['entry']==entry]
        active=[r for r in pool if all(r['periods']['前16'][s]['trades']>=20 and r['periods']['前16'][s]['active_sessions']>=8 for s in SYMBOLS)]
        positive=[r for r in active if all(r['periods']['前16'][s]['net']>0 for s in SYMBOLS)]
        good=[r for r in positive if all(r['periods']['前16'][s]['payoff'] is not None and r['periods']['前16'][s]['payoff']>1 for s in SYMBOLS)]
        level=0 if good else 1 if positive else 2 if active else 3
        chosen=min(good or positive or active or pool,key=score);control=controls(chosen['config']);sensitivity.update(control)
        representatives.append(dict(id=chosen['config']['id'],entry=entry,level=level,eligible=bool(active),front_payoff_qualified=bool(good),score=score(chosen),controls=control))
    primary=min(representatives,key=lambda r:(r['level'],*r['score']))['id']
    save(HERE/'前半選定.json',dict(代表=representatives,主候補=primary,基準=BENCHMARK,感度対象=sorted(sensitivity),前16だけで選択=True,未見確認ではない=True))
    print(json.dumps(dict(代表=representatives,主候補=primary,感度数=len(sensitivity)),ensure_ascii=False))


def check_benchmarks(delay: int) -> None:
    """機能: 部品なしのJ0/J2とFD単独の旧注文・全曲線を完全照合する。

    引数: delay(int)。返り値: なし(None)。
    """
    base=base_path(delay);oldbase=ROOT/'work/wave_v77' if delay==5 else ROOT/'work/wave_v77/sensitivity'/f'delay{delay}'
    count=0
    for entry in ('J0','J2'):
        old=load(oldbase/'ledgers'/f'{entry}_P0_R40_T40_H30_A0.pkl')
        if delay==5:old.update(load(ROOT/'work/wave_v77/unseen/ledgers'/f'{entry}_P0_R40_T40_H30_A0.pkl'))
        new=load(base/'ledgers'/f'{entry}_F0_B0_H0_R0.pkl')
        for key,v in old.items():
            for field in ('orders','trades'):assert np.array_equal(v[field],new[key][field]),(entry,key,field)
            assert v['curve_hash']==new[key]['curve_hash'];count+=1
    oldbase=ROOT/'work/wave_v76' if delay==5 else ROOT/'work/wave_v76/sensitivity'/f'delay{delay}'
    old=load(oldbase/'ledgers/B_FD15_E0_M1_C15_T40_H30.pkl');new=load(base/'ledgers/J0_F1_B0_H0_R0.pkl')
    for key,v in old.items():
        assert np.array_equal(v['orders'],new[key]['orders'][:,:8]) and np.array_equal(v['trades'],new[key]['trades'][:,:11]) and v['curve_hash']==new[key]['curve_hash'];count+=1
    save(base/'旧3基準の完全一致.json',dict(合格=True,口座数=count,遅延=delay))


def main() -> None:
    """機能: 事前固定、主再生、前半選定、同条件遅延感度を実行する。

    引数: CLI freeze/select(bool)、delay/workers(int)。返り値: なし(None)。
    """
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--select',action='store_true');p.add_argument('--delay',type=int,default=5);p.add_argument('--workers',type=int,default=6);a=p.parse_args()
    socket.socket.connect=deny;socket.create_connection=deny
    if a.freeze:freeze();print('162条件を損益前に固定しました');return
    if a.select:select();return
    fixed=load(HERE/'事前固定.json');assert a.delay in (1,5,15)
    assert all(digest(ROOT/p)==h for p,h in fixed['SHA256'].items()),'事前固定後変更'
    configs=fixed['条件']
    if a.delay!=5:
        ids=set(load(HERE/'前半選定.json')['感度対象']);configs=[c for c in configs if c['id'] in ids]
    for name in ('results','ledgers'):(base_path(a.delay)/name).mkdir(parents=True,exist_ok=True)
    materials=material(a.delay);engine.simulate(*arguments(configs[0],sorted(materials[0])[0],*materials))
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        tasks=[pool.submit(run_one,c,materials,fixed,a.delay) for c in configs]
        for i,f in enumerate(as_completed(tasks),1):
            ident=f.result()
            if i%18==0 or i==len(tasks):print(f'遅延{a.delay}秒 {i}/{len(tasks)} {ident}',flush=True)
    check_benchmarks(a.delay)


if __name__=='__main__':
    main()
