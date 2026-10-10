"""二市場共同イベントと自市場証拠の対照を、事前固定の同じ出口で検証する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
import math
from pathlib import Path
import pickle
import socket

import numba
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
numba.config.CACHE_DIR=str(HERE/'numba_cache')

import engine
import accounting
import prepare_signals
import signals

SYMBOLS=('TOPIX','NK225')


def load(path: Path) -> object:
    """機能: 保存資料を読み込む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 大きな入力も一定のメモリー量で指紋化する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(4*1024*1024):
            h.update(chunk)
    return h.hexdigest()


def save(path: Path,value: object) -> None:
    """機能: 今回の作業領域へ結果を保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.parent.mkdir(parents=True,exist_ok=True)
    assert path.resolve().is_relative_to(HERE.resolve())
    if path.suffix=='.pkl':
        path.write_bytes(pickle.dumps(value,protocol=pickle.HIGHEST_PROTOCOL))
    else:
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def catalog() -> list[dict]:
    """機能: 七機構・二窓・二強度・三幅・二保有期限・共同対照を結果によらず列挙する。

    引数: なし。返り値: 336設定(list[dict])。
    """
    configurations=[]
    for paired in (True,False):
        for family in range(1,8):
            for window in (60,300):
                for level in (0,1):
                    entry=f'{"J" if paired else "S"}{family}_W{window}_L{level}'
                    for width in (.001,.002,.004):
                        for hold in (1800.,3600.):
                            ident=entry+f'_T{int(width*10000)}_H{int(hold/60)}'
                            configurations.append(dict(id=ident,signal_id=entry,family=family,
                                name=signals.FAMILIES[family-1],window=window,level=level,paired=paired,
                                group='共同判定' if paired else '自市場証拠の対照',
                                width_fraction=width,hold_seconds=hold,entry_type=0,pause_mode=0,
                                exit_on_reverse=False,reference=0,cooldown=30.,delay=5,max_age=30))
    assert len(configurations)==336
    return configurations


def freeze() -> None:
    """機能: 設定・主選定・遅延感度・時計の限界を損益再生前に固定する。

    引数: なし。返り値: なし(None)。完成した固定を上書きしない。
    """
    target=HERE/'事前固定.json'
    assert not target.exists()
    meta=load(ROOT/'work/wave_v74/inputs/refmetadata.json')
    inputs=load(HERE/'inputs/同期入力仕様_fresh30.json')
    files=[HERE/name for name in ('study.py','signals.py','prepare_signals.py','engine.py','accounting.py',
        'inputs/core.py','inputs/sync_fresh30.pkl','inputs/同期入力仕様_fresh30.json',
        'prepared/signals_delay5.pkl','prepared/入口件数_delay5.json','theory/二指数を同時に見る事前仮説.json')]
    files.append(ROOT/'work/wave_v74/inputs/refmetadata.json')
    save(target,dict(条件=catalog(),全29=meta['sessions'],前16=meta['sessions'][:16],後13=meta['sessions'][16:],
        共通時刻='予定セッション時刻から15秒刻み。現在代理時計から5秒引いた時点より厳密に過去の同時計先頭行。両市場の最終約定時計は実受信時計ではない。',
        鮮度='参照期限から30秒以内。10/30/60秒の入力取得率だけを損益前に比較して30秒を採用。観測されない相手を中立又は最新へ補完しない。',
        指標='窓60/300秒の中値変化3/6bp、15秒で売買両気配1呼値進行、OFI符号比0.1/0.2。相対価格は直前4窓のlog価格比平均/標準偏差と過去相関0.3。ATR不使用。',
        六機構='共同進行、相手先行と自追随開始、自先行失敗、相対価格の偏り縮小、両OFI先行、片側の圧力吸収失敗。先行順序・真の約定消費・参加者心理の直接証明ではない。',
        自動選択='第7機構は共同進行→追随→相対戻りの順。結果や当日の将来損益によって手法を切り替えない。',
        再準備='初回準備済み。発火後は有効中立が連続60秒必要、発火から600秒以内は再発火しない。保有中又は写像失敗の発火も間隔に数える。欠測を中立にしない。',
        対照='同じ両市場観測可能時点で、相手の価格とOFIの内容を使わない自己証拠対照。状態による再準備も変化するので約定機会の完全一致対照ではない。第4の対照は自己価格の平均回帰で、フィルター除去とは別。',
        新規='共通判断時刻以上の最初の自原本行へ写像し、10秒より遅い又は悪い板なら棄却。さらに次有効原本行で買ask売bid。TOPmini10/NKmicro20、全量。',
        出口='始値0.1/0.2/0.4%をラージ呼値へ切り上げ、最低2呼値。実建値から即時全量トレール。同幅損切り、30/60分判断、予定場末判断。基準反転の即返済や途中追加玉なし。',
        会計='両側料金後の全決済黒字を利益、全赤字絶対額を損失として商品別に合計。TOP41.8円/NK11円片道枚、注文合計切捨て。気配差込み。',
        選定='前16だけ。共同の7機構それぞれ、両銘柄20取引・8活動場以上から最悪側金額損失割合、両割合合計、取引数、IDで1代表。未充足は比較例だけ。主3は最低数充足の機構代表を同採点で上位から選び、前16売買列が同一なら重複を除く。',
        確認='後13で両銘柄費用後黒字・平均勝ち/負け>1・最大黒字場除外黒字が有望条件。さらに同設定の自己証拠対照より1取引平均と金額損失割合が両商品で良いかを別判定。既知期間の再探索なので未見の証明ではない。',
        感度='選定後は7代表と対応自己対照の設定を変えず、両市場情報の遅延を1/15/60秒へ変更する。5秒で良いから同時取得可能とは結論しない。各遅延で再選定しない。',
        原本時計限界='板データに共通受信時刻なし。原本行の未来切断で検査できるのは代理時計とseq上の因果性であり、実配信遅延の上限や極短期先行を実証できない。',
        API取得=0,実注文=0,SHA256={str(p.relative_to(ROOT)):digest(p) for p in files},入力SHA256=meta['input_SHA256']))


def arguments(c: dict,key: tuple,ready: dict,book: dict,entry: dict,meta: dict) -> tuple:
    """機能: 疎な共同イベントを同一の全量追跡再生器へ渡す。

    引数: c/ready/book/entry/meta(dict)、key(tuple)。返り値: 固定再生引数(tuple)。
    """
    r,f=ready[key],book[key]
    direction=np.zeros(len(r['time_s']),dtype=np.int8)
    candidates=entry[c['signal_id']][key]['candidates']
    if len(candidates):
        direction[candidates[:,1].astype(int)]=candidates[:,2].astype(np.int8)
    quality=np.asarray(f['valid'] & (f['bid']>0) & (f['ask']>f['bid'])
        & (f['ask']-f['bid']<=2*r['tick']+1e-9),dtype=bool)
    opening=meta['references']['|'.join(key)]['ref_open']['value']
    width=max(2.,math.ceil(opening*c['width_fraction']/r['tick']-1e-10))*r['tick']
    qty,value,fee=(10,1000.,41.8) if key[1]=='TOPIX' else (20,10.,11.)
    return (r['time_s'],f['bid'],f['ask'],quality,f['reset'],direction,np.full(len(direction),-1,dtype=np.int64),
        r['tick'],r['start'],r['limit'],qty,value,fee,width,r['tick'],0,0,False,c['hold_seconds'],30.,30.)


def run_one(c: dict,ready: dict,book: dict,entry: dict,meta: dict,fixed: dict,delay: int) -> str:
    """機能: 固定入口と出口を全58口座で再生し、個別会計と台帳を保存する。

    引数: c/ready/book/entry/meta/fixed(dict)、delay(int)。返り値: 条件ID(str)。
    """
    base=HERE if delay==5 else HERE/'sensitivity'/f'delay{delay}'
    target=base/'results'/(c['id']+'.json')
    if target.exists():
        return c['id']
    rows,ledgers=[],{}
    front=hashlib.sha256()
    for key in sorted(ready):
        args=arguments(c,key,ready,book,entry,meta)
        output=engine.simulate(*args)
        row=accounting.account(c,key,args,output,False)
        row['candidate_count']=len(entry[c['signal_id']][key]['candidates'])
        rows.append(row)
        ledgers[key]=dict(orders=output[0],trades=output[1],pauses=output[3],stats=output[4],
            curve_hash=hashlib.sha256(output[2].tobytes()).hexdigest())
        if key[0] in fixed['前16']:
            front.update(str(key).encode('utf8'))
            front.update(output[0].tobytes())
    path=base/'ledgers'/(c['id']+'.pkl')
    save(path,ledgers)
    periods={name:{s:accounting.aggregate(rows,s,fixed[name]) for s in SYMBOLS} for name in ('前16','後13','全29')}
    save(target,dict(config=dict(c,delay=delay),rows=rows,periods=periods,delay=delay,
        ledger_SHA256=digest(path),front_orders_SHA256=front.hexdigest()))
    return c['id']


def score(r: dict) -> tuple:
    """機能: 同商品の金額損失割合を用い、両商品の悪い側から比較する。

    引数: r(dict)。返り値: 前半だけの昇順評価(tuple)。
    """
    a=[r['periods']['前16'][s] for s in SYMBOLS]
    shares=[x['money_loss_share'] if x['money_loss_share'] is not None else 1. for x in a]
    return max(shares),sum(shares),-sum(x['trades'] for x in a),r['config']['id']


def select() -> None:
    """機能: 前16で機構別7代表と、重複を除いた主3代表を固定する。

    引数: なし。返り値: なし(None)。後半又は遅延変更結果で選び直さない。
    """
    assert not (HERE/'前半選定.json').exists(),'選定済みを上書きしません'
    results=[load(p) for p in sorted((HERE/'results').glob('*.json'))]
    assert len(results)==336
    representatives=[]
    for family in range(1,8):
        pool=[r for r in results if r['config']['paired'] and r['config']['family']==family]
        qualified=[r for r in pool if all(r['periods']['前16'][s]['trades']>=20 and r['periods']['前16'][s]['active_sessions']>=8 for s in SYMBOLS)]
        eligible=bool(qualified)
        if not qualified:
            qualified=[r for r in pool if all(r['periods']['前16'][s]['trades']>0 for s in SYMBOLS)]
        if not qualified:
            qualified=pool
        chosen=min(qualified,key=score)
        follow=chosen['periods']['後13']
        passed=all(follow[s]['net']>0 and follow[s]['payoff'] is not None and follow[s]['payoff']>1
            and follow[s]['without_best_session']>0 for s in SYMBOLS)
        representatives.append(dict(id=chosen['config']['id'],family=family,eligible=eligible,
            score=score(chosen),後13有望条件=passed,front_orders_SHA256=chosen['front_orders_SHA256']))
    main=[]
    used=set()
    for r in sorted((r for r in representatives if r['eligible']),key=lambda r:r['score']):
        if r['front_orders_SHA256'] not in used:
            main.append(r['id'])
            used.add(r['front_orders_SHA256'])
        if len(main)==3:
            break
    save(HERE/'前半選定.json',dict(代表=representatives,主3=main,前16だけで選択=True,後13で変更なし=True))
    print(json.dumps(dict(代表=representatives,主3=main),ensure_ascii=False),flush=True)


def main() -> None:
    """機能: 事前固定、全336再生、代表選定、又は固定代表の遅延感度を実行する。

    引数: --freeze/--select(bool)、--delay/--workers(int)。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--freeze',action='store_true')
    parser.add_argument('--select',action='store_true')
    parser.add_argument('--delay',type=int,default=5)
    parser.add_argument('--workers',type=int,default=6)
    args=parser.parse_args()
    socket.socket.connect=prepare_signals.deny
    socket.create_connection=prepare_signals.deny
    if args.freeze:
        freeze()
        print('二市場336条件・対照・前後分割を固定しました',flush=True)
        return
    if args.select:
        select()
        return
    fixed=load(HERE/'事前固定.json')
    assert all(digest(ROOT/path)==expected for path,expected in fixed['SHA256'].items())
    assert args.delay in (1,5,15,60)
    configurations=fixed['条件']
    if args.delay!=5:
        selection=load(HERE/'前半選定.json')
        ids={x['id'] for x in selection['代表']}
        ids |= {'S'+x[1:] for x in ids.copy()}
        configurations=[c for c in configurations if c['id'] in ids]
    ready,book,sync,meta=prepare_signals.material()
    entry=load(HERE/'prepared'/f'signals_delay{args.delay}.pkl')
    base=HERE if args.delay==5 else HERE/'sensitivity'/f'delay{args.delay}'
    for name in ('results','ledgers'):
        (base/name).mkdir(parents=True,exist_ok=True)
    engine.simulate(*arguments(configurations[0],sorted(ready)[0],ready,book,entry,meta))
    with ThreadPoolExecutor(max_workers=max(1,min(12,args.workers))) as pool:
        tasks=[pool.submit(run_one,c,ready,book,entry,meta,fixed,args.delay) for c in configurations]
        for i,task in enumerate(as_completed(tasks),1):
            ident=task.result()
            if i%24==0 or i==len(tasks):
                print(f'遅延{args.delay}秒 {i}/{len(tasks)}条件完了（{ident}）',flush=True)


if __name__=='__main__':
    main()
