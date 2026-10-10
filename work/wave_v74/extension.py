"""新規方向だけを基準で制限し、保有はトレールへ任せる未検証の休止組合せを補う。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import pickle
import socket

import study


HERE=Path(__file__).resolve().parent
OUT=HERE/'extension'


def save(path: Path, value: object) -> None:
    """機能: 追加検証専用の既定領域へ結果を保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.parent.mkdir(parents=True,exist_ok=True)
    assert path.resolve().is_relative_to(OUT.resolve())
    if path.suffix=='.pkl':
        path.write_bytes(pickle.dumps(value,protocol=pickle.HIGHEST_PROTOCOL))
    else:
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def freeze() -> None:
    """機能: 未検証240条件と、既存48条件を含めた前半選定を実行前に固定する。

    引数: なし。返り値: なし(None)。既存480結果と既存固定は変更しない。
    """
    assert not (OUT/'追記固定.json').exists()
    parent=study.load(HERE/'事前固定.json')
    originals=[c for c in parent['条件'] if c['group']=='基準跨ぎ返済なし']
    configs=[]
    for c in originals:
        for pause in range(1,6):
            configs.append(dict(c,id=c['id'].rsplit('_P',1)[0]+f'_P{pause}',pause_mode=pause))
    assert len(configs)==240
    files=[Path(__file__),HERE/'事前固定.json',HERE/'前半選定.json',HERE/'engine.py',HERE/'study.py']
    save(OUT/'追記固定.json',dict(条件=configs,再利用条件=originals,全29=parent['全29'],前16=parent['前16'],後13=parent['後13'],
        追加理由='ユーザー指定の新規方向制限と、主案で当方が追加した基準反転時の即返済を切り分ける。基準跨ぎ返済なしのP0は既存48条件で検証したが、休止との組合せ240が未検証だったため補う。',
        事後追加=True,第1段階結果を閲覧済み=True,第2段階結果を見る前に固定=True,
        選定='K既存48+追加240の288条件だけから、基準別3代表を前16で選ぶ。両銘柄20取引・8活動場以上、悪い側の金額損失割合→両率合計→取引数→ID。後13では差替えない。',
        結果の扱い='第一段階480の結果・選定を保持。独立な未知期間評価とは呼ばない。候補を増やしたことも公開する。後13の両銘柄黒字・平均利益損失比>1・最大黒字場除外黒字を別判定。',
        変更点='許可方向が反対になっても、その事実だけでは保有を返済しない。入口・新規親取消・損切り・追跡・60分期限・手数料・次気配約定・休止は同一実装。',
        SHA256={str(p.relative_to(study.ROOT)):study.digest(p) for p in files},API取得=0,実注文=0))


def run_one(c: dict, ready: dict, features: dict, meta: dict, prepared: dict, fixed: dict) -> str:
    """機能: 第1段階と同一の再生・会計を未検証の休止設定へ適用する。

    引数: c/ready/features/meta/prepared/fixed(dict)。返り値: 条件ID(str)。
    """
    target=OUT/'results'/(c['id']+'.json')
    if target.exists():
        return c['id']
    rows,ledger=[],{}
    for key in sorted(ready):
        args=study.arguments(c,key,ready,features,prepared)
        output=study.engine.simulate(*args)
        rows.append(study.account(c,key,args,output,prepared[key]['missing_previous']))
        ledger[key]=dict(orders=output[0],trades=output[1],pauses=output[3],stats=output[4],
                         curve_hash=study.hashlib.sha256(output[2].tobytes()).hexdigest())
    path=OUT/'ledgers'/(c['id']+'.pkl')
    save(path,ledger)
    periods={name:{s:study.aggregate(rows,s,fixed[name]) for s in study.SYMBOLS} for name in ('前16','後13','全29')}
    save(target,dict(config=c,rows=rows,periods=periods,ledger_SHA256=study.digest(path)))
    return c['id']


def select() -> None:
    """機能: 新規だけ方向制限する全288条件から基準別の代表を前16で選ぶ。

    引数: なし。返り値: なし(None)。第1段階の選定は変更しない。
    """
    fixed=study.load(OUT/'追記固定.json')
    results=[study.load(HERE/'results'/(c['id']+'.json')) for c in fixed['再利用条件']]
    results += [study.load(OUT/'results'/(c['id']+'.json')) for c in fixed['条件']]
    assert len(results)==288
    choices=[]
    for reference in range(3):
        pool=[r for r in results if r['config']['reference']==reference]
        qualified=[r for r in pool if all(r['periods']['前16'][s]['trades']>=20 and r['periods']['前16'][s]['active_sessions']>=8 for s in study.SYMBOLS)]
        eligible=bool(qualified)
        if not qualified:
            qualified=[r for r in pool if all(r['periods']['前16'][s]['trades']>0 for s in study.SYMBOLS)]
        def score(r: dict) -> tuple:
            """機能: 前16の両商品金額損失割合だけで代表を比較する。

            引数: r(dict)。返り値: 昇順評価値(tuple)。
            """
            a=[r['periods']['前16'][s] for s in study.SYMBOLS]
            return max(x['money_loss_share'] for x in a),sum(x['money_loss_share'] for x in a),-sum(x['trades'] for x in a),r['config']['id']
        chosen=min(qualified,key=score)
        f=chosen['periods']['後13']
        passed=all(f[s]['net']>0 and f[s]['payoff'] is not None and f[s]['payoff']>1 and f[s]['without_best_session']>0 for s in study.SYMBOLS)
        choices.append(dict(id=chosen['config']['id'],reference=reference,eligible=eligible,score=score(chosen),後13有望条件=passed))
    save(OUT/'選定.json',dict(代表=choices,前16だけで選択=True,後13で変更なし=True,第一段階からの事後追加=True,全条件数=288,追加実行数=240))
    print(json.dumps(choices,ensure_ascii=False),flush=True)


def main() -> None:
    """機能: 追記固定、追加再生、又は前半選定を実行する。

    引数: --freeze/--select(bool)、--workers(int)。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--freeze',action='store_true')
    parser.add_argument('--select',action='store_true')
    parser.add_argument('--workers',type=int,default=6)
    args=parser.parse_args()
    socket.socket.connect=study.deny
    socket.create_connection=study.deny
    if args.freeze:
        freeze()
        print('未検証240条件と前16による別代表選定を追記固定しました',flush=True)
        return
    if args.select:
        select()
        return
    fixed=study.load(OUT/'追記固定.json')
    assert all(study.digest(study.ROOT/p)==h for p,h in fixed['SHA256'].items())
    for name in ('results','ledgers'):
        (OUT/name).mkdir(parents=True,exist_ok=True)
    ready,features,meta=study.material()
    prepared=study.prepare(ready,features,meta)
    study.engine.simulate(*study.arguments(fixed['条件'][0],sorted(ready)[0],ready,features,prepared))
    with ThreadPoolExecutor(max_workers=max(1,min(12,args.workers))) as pool:
        tasks=[pool.submit(run_one,c,ready,features,meta,prepared,fixed) for c in fixed['条件']]
        for i,task in enumerate(as_completed(tasks),1):
            ident=task.result()
            if i%24==0 or i==len(tasks):
                print(f'追加{i}/{len(tasks)}条件完了（{ident}）',flush=True)


if __name__=='__main__':
    main()
