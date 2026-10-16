"""前半で判明した気配差負担・繰返し・遅い追随に対する修正を固定して再検証する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
from pathlib import Path
import sys

sys.dont_write_bytecode=True
import numpy as np
from numba import njit
import study
import engine
import accounting

HERE=Path(__file__).resolve().parent


@njit(cache=True)
def once_per_wave(states,valid,grid):
    """機能: 同じ方向状態では一度だけ新規を許し、有効中立10秒又は反対で再準備する。

    引数: states/valid/grid(ndarray)。返り値: 原方向の新規パルス(ndarray)。
    欠測は中立秒数へ算入せず、中立確認を破棄する。
    """
    out=np.zeros(len(states),np.int8);last=0;neutral=-1.
    for i in range(len(states)):
        if not valid[i]:neutral=-1.;continue
        d=states[i]
        if d==0:
            if neutral<0:neutral=grid[i]
            if grid[i]-neutral>=10.:last=0
        else:
            if d!=last:out[i]=d;last=d
            neutral=-1.
    return out


def altered_states(c: dict,s: dict) -> np.ndarray:
    """機能: 確認前入口又は一回だけの入口を、過去状態から作る。

    引数: c/s(dict)。返り値: 方向配列(ndarray)。
    """
    mode=c.get('state_mode',0)
    states=s['raw_states'][c['signal']] if mode==1 else s['states'][c['signal']]
    if mode==2:states=once_per_wave(states,s['valid'],s['grid'])
    return -states if c.get('invert',False) else states


def configs() -> list:
    """機能: 初回の原因から42の改修対照を作る。

    引数: なし。返り値: 条件一覧(list)。
    """
    originals=study.load(HERE/'初回前半選定.json')['代表'];out=[]
    for n,b in enumerate(originals):
        for repair,name in ((1,'追いかけ抑制'),(2,'反対で返済'),(3,'連敗休止'),(4,'同方向一度')):
            c=dict(b,id=f'R{n+1}{repair}',parent=b['id'],explanation=name,state_mode=2 if repair==4 else 0,repair_mode=repair if repair<4 else 0)
            out.append(c)
    for s in (0,1,5,6):
        for p in (study.PROFILES[1],study.PROFILES[2],study.PROFILES[5]):
            for mode in (0,1):
                out.append(dict(id=f'A{s+1}_{p["profile"]}_M{mode}',signal=s,entry_mode=mode,cooldown=30,repair_mode=0,state_mode=1,invert=False,
                    explanation='3秒持続の確認前に有効な板条件で入り、追随の遅れを減らす対照',**p))
    for p in (study.PROFILES[1],study.PROFILES[3],study.PROFILES[5]):
        for mode in (0,1):
            out.append(dict(id=f'V3_{p["profile"]}_M{mode}',signal=2,entry_mode=mode,cooldown=30,repair_mode=0,state_mode=0,invert=True,
                explanation='共同価格進行の反対へ入る対照。損益を符号反転せず注文から再生する',**p))
    assert len(out)==42
    return out


def freeze() -> None:
    """機能: 改修の損益を見る前に因果仮説と全42条件を保存する。

    引数: なし。返り値: なし(None)。上書き不可。
    """
    assert not (HERE/'改修事前固定.json').exists()
    sparse=[study.load(p)['config'] for p in sorted((HERE/'first/results').glob('*.json')) if all(study.load(p)['periods']['前16'][s]['net']>0 for s in study.SYMBOLS)]
    study.save(HERE/'改修事前固定.json',dict(条件=configs(),初回少数黒字=sparse,
        原因='成行代表のTOP中値差−17500円に気配差1152500円・料金176396円、NK中値差+126000円に気配差378000円・料金70400円。追随の小さな優位より費用が大きい。5秒悪化だけで赤字を説明できない。',
        改修思想='既存3代表は追いかけ抑制/反対返済/2連敗120秒休止/同方向一度の4対照。OFI先行・二市場OFI先行・失速反転・表示回復は3秒持続確認を待たない入口を3管理×2約定で検証。共同追随の反対方向6条件は反転しても費用は消えない対照。',
        制約='同方向一度は中立をvalid==Trueかつ確認済みstate==0と定義する。欠測を中立として再準備しない。瞬時案も厳密過去の参照/品質は維持し、原本受信時計の欠如は解決しない。',
        選択='修正42を前16/注文5秒だけで比較。成行/上限/待機ごと1条件を初回と同じstudy.scoreで固定し、初回3と並べる。少数黒字の4条件は別枠で後半確認し、3取引を十分な証拠へ格上げしない。',
        SHA256={'work/wave_v80/pdca.py':study.digest(Path(__file__))},後半損益未参照=True))


def arguments(c: dict,key: tuple,materials: tuple,delay: int) -> tuple:
    """機能: 固定した改修状態だけを元エンジンへ差し替える。

    引数: c(dict)、key/materials(tuple)、delay(int)。返り値: 引数(tuple)。
    """
    args=list(study.arguments(c,key,materials,delay));args[7]=altered_states(c,materials[2][key]);return tuple(args)


def run_one(c: dict,materials: tuple,sessions: list,base: Path,delay: int,fixed: dict) -> str:
    """機能: 改修した注文経路と全時価を商品別に再計算する。

    引数: c/fixed(dict)、materials(tuple)、sessions(list)、base(Path)、delay(int)。返り値: 条件ID(str)。
    """
    target=base/'results'/f'{c["id"]}.json'
    if target.exists():return c['id']
    rows=[];ledgers={}
    for key in sorted(materials[0]):
        if key[0] not in sessions:continue
        args=arguments(c,key,materials,delay);out=engine.simulate(*args);rows.append(accounting.account(key,args,out))
        ledgers[key]=dict(orders=out[0],trades=out[1],curve_hash=hashlib.sha256(out[2].tobytes()).hexdigest(),stats=out[3],events=out[4])
    periods={name:{s:accounting.aggregate(rows,s,subset) for s in study.SYMBOLS} for name,subset in [('対象',sessions),('前16',fixed['前16']),('後14',fixed['後14'])]}
    path=base/'ledgers'/f'{c["id"]}.pkl';study.save(path,ledgers)
    study.save(target,dict(config=dict(c,latency=delay),rows=rows,periods=periods,ledger_SHA256=study.digest(path)))
    return c['id']


def select() -> None:
    """機能: 改修の代表を前半で固定し、以後後半結果で差し替えない。

    引数: なし。返り値: なし(None)。上書き不可。
    """
    assert not (HERE/'最終前半選定.json').exists()
    rs=[study.load(p) for p in (HERE/'repair/results').glob('*.json')];assert len(rs)==42
    chosen=[max([r for r in rs if r['config']['entry_mode']==mode],key=study.score) for mode in (0,1,2)]
    originals=study.load(HERE/'初回前半選定.json')['代表'];fixed=study.load(HERE/'改修事前固定.json')
    controls=[dict(c,id='N_'+c['id'],signal=7,state_mode=0,invert=False,repair_mode=0) for c in [r['config'] for r in chosen if r['config']['entry_mode']==0]]
    targets={c['id']:c for c in originals+[r['config'] for r in chosen]+fixed['初回少数黒字']+controls}
    study.save(HERE/'最終前半選定.json',dict(初回=originals,改修=[r['config'] for r in chosen],少数黒字=fixed['初回少数黒字'],無方向対照=controls,確認条件=list(targets.values()),
        順位根拠=[dict(id=r['config']['id'],score=study.score(r),前16=r['periods']['前16']) for r in chosen],後半未参照=True,
        SHA256={str(p.relative_to(study.ROOT)):study.digest(p) for p in (HERE/'repair/results').glob('*.json')}))


def main() -> None:
    """機能: 固定改修の前半評価と、代表だけの後半・遅延確認を実行する。

    引数: CLI --freeze/--select/--final(bool)、--delay/--workers(int)。返り値: なし(None)。
    """
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--select',action='store_true');p.add_argument('--final',action='store_true');p.add_argument('--delay',type=int,choices=(0,1,5),default=5);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    study.socket.socket.connect=study.deny;study.socket.create_connection=study.deny
    initial=study.load(HERE/'初回事前固定.json');assert all(study.digest(study.ROOT/n)==h for n,h in initial['SHA256'].items())
    if a.freeze:freeze();print('原因対応42改修を損益前に固定');return
    fixed=study.load(HERE/'改修事前固定.json');assert all(study.digest(study.ROOT/n)==h for n,h in fixed['SHA256'].items())
    if a.select:select();print('最終代表を前半だけで固定');return
    if a.final:configs=study.load(HERE/'最終前半選定.json')['確認条件'];sessions=initial['全30'];base=HERE/'final'/f'delay{a.delay}'
    else:configs=fixed['条件'];sessions=initial['前16'];base=HERE/'repair';assert a.delay==5
    # 並列の最初の書込みで存在しない親を解決させず、作業内の出力先を先に確定する。
    for name in ('results','ledgers'):(base/name).mkdir(parents=True,exist_ok=True)
    materials=study.material();engine.simulate(*arguments(configs[0],(sessions[0],'TOPIX'),materials,a.delay))
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        fs=[pool.submit(run_one,c,materials,sessions,base,a.delay,initial) for c in configs]
        for i,f in enumerate(as_completed(fs),1):print(f'{"final" if a.final else "repair"} 遅延{a.delay}秒 {i}/{len(configs)} {f.result()}',flush=True)


if __name__=='__main__':
    main()
