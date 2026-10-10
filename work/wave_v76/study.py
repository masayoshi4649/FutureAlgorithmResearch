"""二市場の高速入口と支持に基づく保有管理を、入口と管理の対照付きで検証する。"""

from __future__ import annotations

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
import prepare_signals
import signals

SYMBOLS=('TOPIX','NK225')
META=ROOT/'work/wave_v74/inputs/refmetadata.json'


def load(path: Path) -> object:
    """機能: 保存資料を読み取る。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 保存資料のSHA256を一定メモリーで求める。

    引数: path(Path)。返り値: 指紋(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(4*1024*1024):h.update(chunk)
    return h.hexdigest()


def save(path: Path,value: object) -> None:
    """機能: 新作業内だけへ再生結果を保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.pkl':path.write_bytes(pickle.dumps(value,protocol=5))
    else:path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def identity(c: dict) -> str:
    """機能: 入口と保有管理の設定を一意なIDへする。

    引数: c(dict)。返り値: 設定ID(str)。
    """
    return f"{'B_' if c['legacy_entry'] else ''}{c['signal_id']}_E{c['entry_confirm']}_M{c['manage_mode']}_C{c['manage_confirm']}_T{int(c['width_fraction']*10000)}_H{int(c['hold_seconds']/60) if c['hold_seconds'] else 'S'}"


def catalog() -> list[dict]:
    """機能: 高速入口896と従来入口の途中管理100を損益前に列挙する。

    引数: なし。返り値: 996設定(list[dict])。
    """
    output=[]
    modes=[(0,0)]+[(mode,confirm) for mode in (1,2,3) for confirm in (15,30)]
    for legacy in (False,True):
        definitions=signals.definitions()
        if legacy:definitions=[d for d in definitions if d['id'] in ('F15','F30','FD15','FD30')]
        for d in definitions:
            for entry in ((0,) if legacy else (0,10)):
                for mode,confirm in modes:
                    if legacy and mode==0 and d['id']!='F15':continue
                    for width in (.002,.004):
                        for hold in (1800.,0.):
                            family=6 if legacy else d['family']
                            c=dict(signal_id=d['id'],family=family,name=signals.FAMILIES[family],kind=d['kind'],
                                window=d['window'],threshold=d['threshold'],legacy_entry=legacy,
                                entry_source='legacy_J1' if legacy else d['id'],entry_confirm=entry,
                                manage_mode=mode,manage_confirm=confirm,width_fraction=width,hold_seconds=hold,
                                reference=0,group='従来J1入口' if legacy else '短期二市場入口',delay=5,max_age=30,
                                cooldown=30.,flip_expiry=30.)
                            c['id']=identity(c);output.append(c)
    assert len(output)==996 and len({c['id'] for c in output})==996
    return output


def freeze() -> None:
    """機能: 入口・途中・出口・選定と時計の限界を、損益再生前に保存する。

    引数: なし。返り値: なし(None)。固定済みを上書きしない。
    """
    assert not (HERE/'事前固定.json').exists()
    meta=load(META)
    files=[HERE/name for name in ('study.py','engine.py','signals.py','accounting.py','prepare_signals.py',
        'inputs/core.py','inputs/prepare.py','inputs/snapshots.pkl','inputs/grids.pkl',
        'inputs/入力と即時板特徴の仕様.json','prepared/signals_delay5.pkl','prepared/入口状態_delay5.json',
        'theory/板の支持で保有を更新する事前仮説.json')]
    files.append(META)
    for name in meta['input_paths']['ready']+meta['input_paths']['features']:files.append(ROOT/name)
    for delay in (1,5,15):files.append(ROOT/'work/wave_v75/prepared'/f'signals_delay{delay}.pkl')
    save(HERE/'事前固定.json',dict(条件=catalog(),全29=meta['sessions'],前16=meta['sessions'][:16],後13=meta['sessions'][16:],
        保存範囲='共通29場58口座。追加TOPIX10/09NightはNK未保存なので共同判断不能、本比較外。現在API補完なし。',
        即時の意味='5秒格子で判定し、格子から5秒前より厳密に過去の同時計先頭行。鮮度30秒。最終約定時計の代理であり実受信のリアルタイム性は証明できない。',
        入口='最良数量/距離加重10段数量の偏り0.10/0.25、最良OFI符号比0.10、OFIと距離板の各0.10一致、両気配1呼値進行。窓5/15/30/60秒。各市場が強方向で一致。価格進行を必須にするのは価格方式だけ。',
        弱支持='数量偏りとOFIの閾値は入口の半分、価格方式は中値が同方向へ進行。両市場が弱支持している間は保持根拠あり。',
        証拠不足='既知のゼロ/三イベント未満OFIは強方向/弱支持なし。始終同一行・板欠測・区間切断は無効で時計を進めない。',
        確認='新規0/10秒、途中15/30秒の連続有効格子。0秒以外は確認開始後に両参照行が少なくとも一度進む。条件false/無効/格子gapで破棄。',
        再準備='合意なし（中立又は不一致）の有効10秒又は反対方向の確認成立。最短新規発火60秒。保有中も発火を消費、欠測では再準備しない。',
        管理='M0保険だけ、M1両市場の強い反対合意で返済、M2その返済後に新しい格子で反対合意を再確認し反対へ新規、M3は両市場の弱支持消失でも返済し強反対時だけドテン。',
        反転='返済実約定より後の原本行かつ後の共通格子で強反対と持続条件を再確認して新規判断、さらに次有効行で約定。再確認時の不一致/欠測又は30秒期限で取消。新規と返済に別々の手数料。',
        保険='観測済み始値0.2/0.4%を呼値へ切上げ最低2呼値、実建値から即時トレール。30分上限又は上限なし（場末まで）を比較。優先順位は場末、時間上限、保険、二市場判断。',
        約定='共通格子は以後10秒以内の最初の原本行へ対応、同じ行なら最新格子を採用し古い発火を捨てる。新規/途中判断は現在も正常で幅2呼値以下、判断後次有効気配で買ask売bid。保険と場末返済は悪化気配でも継続。',
        枚数料金='TOPIXmini10枚×1000円/pt・片道41.8円、NK225micro20枚×10円/pt・片道11円。注文合計切捨て。ラージ気配をミニ/マイクロ約定に代用。',
        従来対照='J1_W300_L0の入口をそのまま用いF15/F30/FD15/FD30の途中判断だけを追加。M0幅0.4%保有30分は00071のJ1と完全一致を要求。',
        選定='前16だけ。六機構各々、両商品20取引8活動場以上から最悪側金額損失割合、両割合合計、取引数、IDの順で選ぶ。未充足は比較例。主3は前半注文列が同一の重複を除く。',
        確認基準='後13で両商品黒字・平均勝負比>1・最大黒字場除外黒字。加えて同設定M0対照と00071基準を比較。既知29場の再探索なので未知の将来証明ではない。',
        感度='選定後の機構代表と同設定の管理M0/M1/M2/M3（確認15/30）の群、旧J1基準を固定し、情報遅延1/15秒へ変更。再選定しない。',
        SHA256={str(p.relative_to(ROOT)):digest(p) for p in files},API取得=0,実注文=0))


def material(delay: int) -> tuple:
    """機能: 固定した価格・板・共同状態と旧J1入口を接続する。

    引数: delay(int)。返り値: ready,book,state,maps,legacy,meta(tuple)。
    """
    meta=load(META);ready={};book={}
    for path in meta['input_paths']['ready']:ready.update(load(ROOT/path))
    for path in meta['input_paths']['features']:book.update(load(ROOT/path))
    state=load(HERE/'prepared'/f'signals_delay{delay}.pkl')
    maps={key:signals.mapping(state['Q10'][key[0]]['grid'],r) for key,r in ready.items()}
    legacy=load(ROOT/'work/wave_v75/prepared'/f'signals_delay{delay}.pkl')['J1_W300_L0']
    return ready,book,state,maps,legacy,meta


def arguments(c: dict,key: tuple,ready: dict,book: dict,state: dict,maps: dict,legacy: dict,meta: dict) -> tuple:
    """機能: 共通状態を自原本順の二市場管理再生器へ渡す。

    引数: c/ready/book/state/maps/legacy/meta(dict)、key(tuple)。返り値: 再生引数(tuple)。
    """
    r,f=ready[key],book[key];s=state[c['signal_id']][key[0]];mapped=maps[key]
    event=np.zeros(len(r['time_s']),dtype=np.int8)
    if c['legacy_entry']:
        candidates=legacy[key]['candidates']
        if len(candidates):event[candidates[:,1].astype(int)]=candidates[:,2].astype(np.int8)
    else:
        positions=np.flatnonzero(mapped>=0);event[positions]=s['entry'][c['entry_confirm']][mapped[positions]]
    quality=np.asarray(f['valid']&(f['bid']>0)&(f['ask']>f['bid'])&(f['ask']-f['bid']<=2*r['tick']+1e-9),dtype=bool)
    opening=meta['references']['|'.join(key)]['ref_open']['value']
    assert meta['references']['|'.join(key)]['ref_open']['known_from_i']==0
    width=max(2.,math.ceil(opening*c['width_fraction']/r['tick']-1e-10))*r['tick']
    qty,value,fee=(10,1000.,41.8) if key[1]=='TOPIX' else (20,10.,11.)
    m=s['management'][c['manage_confirm'] or 15]
    return (r['time_s'],f['bid'],f['ask'],quality,f['reset'],event,mapped,r['tick'],r['start'],r['limit'],
        qty,value,fee,width,r['tick'],s['grid'],s['valid'],s['strong'],m['loss_long'],m['loss_short'],
        m['opposite_long'],m['opposite_short'],c['manage_mode'],c['hold_seconds'],c['cooldown'],c['flip_expiry'])


def run_one(c: dict,materials: tuple,fixed: dict,delay: int) -> str:
    """機能: 一設定を全58口座で実行し、全損失を含む会計と注文台帳を保存する。

    引数: c/fixed(dict)、materials(tuple)、delay(int)。返り値: 設定ID(str)。
    """
    base=HERE if delay==5 else HERE/'sensitivity'/f'delay{delay}'
    target=base/'results'/(c['id']+'.json')
    if target.exists():return c['id']
    ready,book,state,maps,legacy,meta=materials
    rows=[];ledgers={};front=hashlib.sha256()
    for key in sorted(ready):
        args=arguments(c,key,ready,book,state,maps,legacy,meta);out=engine.simulate(*args)
        row=accounting.account(c,key,args,out,False)
        row.update(flip_count=int(out[4][7]),flip_cancel_count=int(out[4][8]),candidate_count=int(np.count_nonzero(args[5])))
        rows.append(row)
        ledgers[key]=dict(orders=out[0],trades=out[1],pauses=out[3],stats=out[4],curve_hash=hashlib.sha256(out[2].tobytes()).hexdigest())
        if key[0] in fixed['前16']:
            front.update(str(key).encode('utf8'));front.update(out[0].tobytes())
    path=base/'ledgers'/(c['id']+'.pkl');save(path,ledgers)
    periods={name:{s:accounting.aggregate(rows,s,fixed[name]) for s in SYMBOLS} for name in ('前16','後13','全29')}
    for name,period in periods.items():
        for s,a in period.items():
            selected=[r for r in rows if r['symbol']==s and r['session'] in fixed[name]]
            a['flip_count']=sum(r['flip_count'] for r in selected)
            a['flip_cancel_count']=sum(r['flip_cancel_count'] for r in selected)
    save(target,dict(config=dict(c,delay=delay),delay=delay,rows=rows,periods=periods,
        ledger_SHA256=digest(path),front_orders_SHA256=front.hexdigest()))
    return c['id']


def score(r: dict) -> tuple:
    """機能: 前半の銘柄別金額損失割合を、悪い側から評価する。

    引数: r(dict)。返り値: 昇順評価(tuple)。
    """
    a=[r['periods']['前16'][s] for s in SYMBOLS]
    values=[x['money_loss_share'] if x['money_loss_share'] is not None else 1. for x in a]
    return max(values),sum(values),-sum(x['trades'] for x in a),r['config']['id']


def control_ids(c: dict) -> list[str]:
    """機能: 入口・保険・保有期限を固定し、管理だけを変えた七対照を列挙する。

    引数: c(dict)。返り値: 設定ID列(list[str])。
    """
    result=[]
    for mode,confirm in [(0,0)]+[(m,t) for m in (1,2,3) for t in (15,30)]:
        v=dict(c,manage_mode=mode,manage_confirm=confirm)
        if c['legacy_entry'] and mode==0:v['signal_id']='F15'
        result.append(identity(v))
    return result


def select() -> None:
    """機能: 前16の六機構代表と主3・固定感度群を保存する。

    引数: なし。返り値: なし(None)。後半で代表を差し替えない。
    """
    assert not (HERE/'前半選定.json').exists()
    results=[load(p) for p in sorted((HERE/'results').glob('*.json'))];assert len(results)==996
    lookup={r['config']['id']:r for r in results};representatives=[]
    for family in range(1,7):
        pool=[r for r in results if r['config']['family']==family]
        qualified=[r for r in pool if all(r['periods']['前16'][s]['trades']>=20 and r['periods']['前16'][s]['active_sessions']>=8 for s in SYMBOLS)]
        eligible=bool(qualified)
        if not qualified:qualified=[r for r in pool if all(r['periods']['前16'][s]['trades']>0 for s in SYMBOLS)] or pool
        chosen=min(qualified,key=score);follow=chosen['periods']['後13']
        passed=all(follow[s]['net']>0 and follow[s]['payoff'] is not None and follow[s]['payoff']>1 and follow[s]['without_best_session']>0 for s in SYMBOLS)
        representatives.append(dict(id=chosen['config']['id'],family=family,eligible=eligible,score=score(chosen),
            後13有望条件=passed,front_orders_SHA256=chosen['front_orders_SHA256'],controls=control_ids(chosen['config'])))
    main=[];used=set()
    for r in sorted((r for r in representatives if r['eligible']),key=lambda r:r['score']):
        if r['front_orders_SHA256'] not in used:main.append(r['id']);used.add(r['front_orders_SHA256'])
        if len(main)==3:break
    sensitivity={ident for r in representatives for ident in r['controls']}
    benchmark='B_F15_E0_M0_C0_T40_H30';sensitivity.add(benchmark)
    assert all(ident in lookup for ident in sensitivity)
    save(HERE/'前半選定.json',dict(代表=representatives,主3=main,基準=benchmark,感度対象=sorted(sensitivity),前16だけで選択=True,後13で変更なし=True))
    print(json.dumps(dict(代表=representatives,主3=main,感度条件数=len(sensitivity)),ensure_ascii=False),flush=True)


def check_benchmark(delay: int) -> None:
    """機能: 保険のみの旧J1入口が、前作の注文と全決済へ完全一致するか検査する。

    引数: delay(int)。返り値: なし(None)。
    """
    base=HERE if delay==5 else HERE/'sensitivity'/f'delay{delay}'
    old=ROOT/'work/wave_v75' if delay==5 else ROOT/'work/wave_v75/sensitivity'/f'delay{delay}'
    new_ledger=load(base/'ledgers/B_F15_E0_M0_C0_T40_H30.pkl')
    old_ledger=load(old/'ledgers/J1_W300_L0_T40_H30.pkl')
    for key,new in new_ledger.items():
        assert np.array_equal(new['orders'],old_ledger[key]['orders']),(key,'旧J1注文不一致')
        assert np.array_equal(new['trades'],old_ledger[key]['trades']),(key,'旧J1決済不一致')
        assert new['curve_hash']==old_ledger[key]['curve_hash'],(key,'旧J1時価不一致')
    save(base/'旧J1の完全一致.json',dict(合格=True,口座数=58,遅延=delay,新規及び返済及び全行時価一致=True))


def main() -> None:
    """機能: 事前固定、996条件再生、前半選定、固定情報遅延を実行する。

    引数: --freeze/--select(bool)、--delay/--workers(int)。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true');parser.add_argument('--select',action='store_true')
    parser.add_argument('--delay',type=int,default=5);parser.add_argument('--workers',type=int,default=6);args=parser.parse_args()
    socket.socket.connect=prepare_signals.deny;socket.create_connection=prepare_signals.deny
    if args.freeze:freeze();print('二市場の996条件を損益前に固定しました',flush=True);return
    if args.select:select();return
    fixed=load(HERE/'事前固定.json');assert args.delay in (1,5,15)
    assert all(digest(ROOT/path)==expected for path,expected in fixed['SHA256'].items())
    configurations=fixed['条件']
    if args.delay!=5:
        ids=set(load(HERE/'前半選定.json')['感度対象']);configurations=[c for c in configurations if c['id'] in ids]
    materials=material(args.delay)
    c=configurations[0];engine.simulate(*arguments(c,sorted(materials[0])[0],*materials))
    with ThreadPoolExecutor(max_workers=max(1,min(12,args.workers))) as pool:
        tasks=[pool.submit(run_one,c,materials,fixed,args.delay) for c in configurations]
        for i,task in enumerate(as_completed(tasks),1):
            ident=task.result()
            if i%48==0 or i==len(tasks):print(f'遅延{args.delay}秒 {i}/{len(tasks)}条件完了（{ident}）',flush=True)
    check_benchmark(args.delay)


if __name__=='__main__':
    main()
