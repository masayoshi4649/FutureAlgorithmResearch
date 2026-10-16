"""前半で安定赤字手法を選び、買い・売りを入れ替えて注文から再生する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = ROOT / 'work/wave_v81'
sys.path.insert(0, str(PREVIOUS))
import numpy as np
import pdca as previous

SYMBOLS = ('TOPIX', 'NK225')


def load(path: Path) -> object:
    """機能: 保存済み素材を読む。

    引数: path(Path)。返り値: 内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def save(path: Path, value: object) -> None:
    """機能: 今回の調査領域だけへ保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.pkl':
        path.write_bytes(pickle.dumps(value, protocol=5))
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def parent_results() -> list:
    """機能: 前調査188条件の前16だけを読む。

    引数: なし。返り値: 元条件・前半結果・保存場所の一覧(list)。
    """
    values = []
    for stage in ('first', 'improved'):
        for path in sorted((PREVIOUS / stage / 'results').glob('*.json')):
            result = load(path)
            values.append(dict(path=str(path.relative_to(ROOT)), result=result))
    assert len(values) == 188
    return values


def metrics(result: dict) -> dict:
    """機能: 元の赤字を方向損益と費用へ分け、前半の安定性を測る。

    引数: result(dict)。返り値: 商品別指標と場別符号の辞書(dict)。
    反転余地は同時刻約定が成り立つ成行の選択だけに用いる。
    """
    out = {}
    for symbol in SYMBOLS:
        rows = sorted([r for r in result['rows'] if r['symbol'] == symbol], key=lambda r:r['session'])
        assert len(rows) == 16
        a = result['periods']['前16'][symbol]
        cost = np.array([r['spread_drag'] + r['fees'] for r in rows])
        net = np.array([r['net'] for r in rows])
        direction = net + cost
        reverse_margin = -net - 2 * cost
        out[symbol] = dict(trades=a['trades'], active=a['active_sessions'], loss_count=int((net < 0).sum()),
            loss_share=a['loss'] / (a['profit'] + a['loss']) if a['profit'] + a['loss'] else 0.,
            midpoint_loss_count=int((direction < 0).sum()), midpoint_negative_ratio=float(-direction.sum() / max(1., cost.sum())),
            inverse_profit_count=int((reverse_margin > 0).sum()), inverse_worst_ratio=float((reverse_margin / np.maximum(cost, 1.)).min()),
            inverse_total_ratio=float(reverse_margin.sum() / max(1., cost.sum())),
            cost=float(cost.sum()), net=float(net.sum()), midpoint=float(direction.sum()), same_path_inverse=float(reverse_margin.sum()),
            loss_flags=(net < 0).tolist(), midpoint_loss_flags=(direction < 0).tolist(), inverse_profit_flags=(reverse_margin > 0).tolist())
    return out


def score(result: dict, label: str) -> tuple:
    """機能: 元前半の赤字安定・方向外れ・費用超過余地の3観点で順位付けする。

    引数: result(dict)、label(str:A/B/C)。返り値: 大きい順の順位(tuple)。
    無取引は赤字にも黒字にも数えず、円金額を商品間で合算しない。
    """
    m = metrics(result); a = [m[s] for s in SYMBOLS]
    enough = all(v['trades'] >= 20 and v['active'] >= 8 for v in a)
    identifier = result['config']['id']
    if label == 'A':
        return (enough, min(v['loss_count'] for v in a), sum(x and y for x,y in zip(a[0]['loss_flags'], a[1]['loss_flags'])),
            min(v['loss_share'] for v in a), sum(v['loss_share'] for v in a)/2, identifier)
    if label == 'B':
        return (enough, min(v['midpoint_loss_count'] for v in a), sum(x and y for x,y in zip(a[0]['midpoint_loss_flags'], a[1]['midpoint_loss_flags'])),
            min(v['midpoint_negative_ratio'] for v in a), sum(v['midpoint_negative_ratio'] for v in a)/2, identifier)
    return (enough, min(v['inverse_profit_count'] for v in a), sum(x and y for x,y in zip(a[0]['inverse_profit_flags'], a[1]['inverse_profit_flags'])),
        min(v['inverse_worst_ratio'] for v in a), min(v['inverse_total_ratio'] for v in a), identifier)


def config(parent: dict, reverse: bool) -> dict:
    """機能: 元条件を保ち、反転の有無と追跡IDを付ける。

    引数: parent(dict)、reverse(bool)。返り値: 再生条件(dict)。
    """
    return dict(parent, parent_id=parent['id'], id=('R__' if reverse else 'F__') + parent['id'], polarity=-1 if reverse else 1)


def arguments(c: dict, key: tuple, data: tuple, delay: int) -> tuple:
    """機能: 入口・出口の自己/相手方向を反転し、実際の売買側気配へ発注する。

    引数: c(dict)、key/data(tuple)、delay(int)。返り値: エンジン引数(tuple)。
    価格・有効性・時刻・枚数・料金は反転しない。入口条件の整合判定後に適用する。
    """
    a = list(previous.arguments(c, key, data, delay))
    if c['polarity'] == -1:
        for i in (7, 26, 32, 33):
            a[i] = -a[i]
    return tuple(a)


def run_one(c: dict, data: tuple, sessions: list, base: Path, delay: int, fixed: dict) -> str:
    """機能: 元又は反転の新規・返済を最初から再生する。

    引数: c/fixed(dict)、data(tuple)、sessions(list)、base(Path)、delay(int)。返り値: ID(str)。
    指値上限は反転側で再計算し、不成立の違いと後続注文を全て残す。
    """
    target = base / 'results' / (c['id'] + '.json')
    if target.exists():
        return c['id']
    rows, ledgers, durations = [], {}, {}
    for key in sorted(data[0]):
        if key[0] not in sessions:
            continue
        a = arguments(c, key, data, delay)
        out = previous.study.engine.simulate(*a)
        rows.append(previous.study.accounting.account(key, a, out))
        durations[key] = a[0][out[1][:,2].astype(np.int64)] - a[0][out[1][:,1].astype(np.int64)]
        ledgers[key] = dict(orders=out[0].copy(), trades=out[1].copy(), curve_hash=hashlib.sha256(out[2].tobytes()).hexdigest(),
            stats=out[3].copy(), events=out[4].copy())
    periods = {}
    for name, subset in (('対象', sessions), ('前16', fixed['前16']), ('後14', fixed['後14'])):
        periods[name] = {}
        for symbol in SYMBOLS:
            a = previous.study.accounting.aggregate(rows, symbol, subset)
            parts = [v for k,v in durations.items() if k[0] in subset and k[1] == symbol]
            holds = np.concatenate(parts) if parts else np.zeros(0)
            a['hold_median'] = float(np.median(holds)) if len(holds) else None
            a['hold_max'] = float(holds.max()) if len(holds) else None
            periods[name][symbol] = a
    path = base / 'ledgers' / (c['id'] + '.pkl')
    save(path, ledgers)
    save(target, dict(config=dict(c, latency=delay), rows=rows, periods=periods, ledger_SHA256=previous.study.digest(path)))
    return c['id']


def freeze() -> None:
    """機能: 反転損益の再生前に元前半だけで3つの選択枠を固定する。

    引数: なし。返り値: なし(None)。既存固定記録は上書きしない。
    """
    assert not (HERE / '事前固定.json').exists()
    original = load(PREVIOUS / '初回事前固定.json')
    parents = parent_results()
    expected = set(original['前16'])
    assert all({r['session'] for r in p['result']['rows']} == expected for p in parents)
    common = [p for p in parents if not p['result']['config']['solo']]
    assert len(common) == 180
    pairs, rankings = [], {}
    names = {'A':'赤字の安定性', 'B':'価格方向の外れの安定性', 'C':'費用を超える反転余地'}
    for label in ('A', 'B', 'C'):
        choices = [p for p in common if label == 'A' or p['result']['config']['entry_mode'] == 0]
        ranked = sorted(choices, key=lambda p:score(p['result'], label), reverse=True)
        winner = ranked[0]; parent = winner['result']['config']
        pairs.append(dict(label=label, name=names[label], parent_id=parent['id'], original=config(parent,False), reverse=config(parent,True),
            source=winner['path'], score=score(winner['result'], label), metrics=metrics(winner['result'])))
        rankings[label] = [dict(id=p['result']['config']['id'], score=score(p['result'], label), metrics=metrics(p['result'])) for p in ranked]
    files = [ROOT/p['path'] for p in parents]
    files += [HERE/'research.py'] + [PREVIOUS/n for n in ('engine.py','accounting.py','study.py','pdca.py','signals.py','extensions.py','extended/signals.pkl','extended/metadata.json','初回事前固定.json','改修前固定.json')]
    save(HERE / '事前固定.json', dict(pairs=pairs, parents=[dict(path=p['path'], config=p['result']['config']) for p in parents],
        全30=original['全30'], 前16=original['前16'], 後14=original['後14'],
        課題='上下にかかわらず安定して負ける手法の新規と返済を売買反転し、毎場の黒字性を確認する。',
        選定='元188の前16だけを参照。単独対照8を選定対象から除く。Aは180、B/Cは同時刻反転式が成り立つ成行のみ。各枠1位が重複しても共有し、無理に3つへ分けない。反転再生後は選び直さない。',
        活動条件='各商品20決済・8活動場以上を順位先頭で優先。黒字/赤字場の分母は全16で、無取引を勝ちや負けに数えない。',
        A順位='最小赤字場数→両方赤字場数→最小金額損失割合→平均金額損失割合→ID。',
        B順位='最小中値赤字場数→両方中値赤字場数→最小(-中値損益/C)→平均同比率→ID。C=気配差負担+料金。',
        C順位='元成行の各場-net-2Cを前半の反転余地として、最小黒字場数→両方黒字場数→全場商品の最悪余地/max(C,1)→最小合計余地/C→ID。前半結果からの探索である。',
        反転='自己/相手の入口・出口方向の符号を反転。価格、有効性、時刻、料金、枚数は変更しない。支持消失・反対の判定、再準備も対称反転。通常の保有期限なし、全返済は場内。',
        再生='前半反転188を全件開示するが代表は固定済み。固定ペアのみ全30、待ち0/1/5秒。反転代表は相手鮮度3秒でも比較する。',
        注意='全30は旧研究から既知。新しい反転後半結果を選定に用いないだけで、未知期間での検証ではない。真の板受信時計なし、ラージ板で小型商品を代用。',
        同時刻恒等式='R逆=−R元−2C。成行の同時刻同枚数約定の場合だけ。上限付き新規は経路が変わるため再生で判定。',
        相場分類='始終の有効中値の変化率±0.1%で上昇/下落/横ばい。全セッション終了後の説明にのみ使用し、入口/出口/選択には使わない。',
        現在API取得=0, 実注文=0, SHA256={str(p.relative_to(ROOT)):previous.study.digest(p) for p in files}))
    save(HERE / '元前半の選定順位.json', rankings)


def main() -> None:
    """機能: 事前選定、前半反転、全30固定比較、情報鮮度感度を実行する。

    引数: --freeze/--final/--quality(bool)、--workers(int)。返り値: なし(None)。
    """
    p = argparse.ArgumentParser()
    for flag in ('freeze','final','quality'):
        p.add_argument('--'+flag, action='store_true')
    p.add_argument('--workers', type=int, default=3)
    args = p.parse_args()
    socket.socket.connect = previous.study.deny; socket.create_connection = previous.study.deny
    if args.freeze:
        freeze(); print('反転損益の計算前に元前半から3枠を固定しました。'); return
    fixed = load(HERE/'事前固定.json')
    assert all(previous.study.digest(ROOT/n)==h for n,h in fixed['SHA256'].items())
    data = previous.material()
    if args.final:
        selected = {c['id']:c for pair in fixed['pairs'] for c in (pair['original'],pair['reverse'])}
        jobs = [(c,d,HERE/'final'/f'delay{d}') for d in (0,1,5) for c in selected.values()]
        sessions = fixed['全30']
    elif args.quality:
        selected = {p['reverse']['id']:dict(p['reverse'],freshness=3) for p in fixed['pairs']}
        jobs = [(c,5,HERE/'quality3') for c in selected.values()]
        sessions = fixed['全30']
    else:
        jobs = [(config(p['config'],True),5,HERE/'first') for p in fixed['parents']]
        sessions = fixed['前16']
    previous.study.engine.simulate(*arguments(jobs[0][0],(sessions[0],'TOPIX'),data,jobs[0][1]))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks = [pool.submit(run_one,c,data,sessions,base,d,fixed) for c,d,base in jobs]
        for i,task in enumerate(as_completed(tasks),1):
            identifier=task.result()
            if i%12==0 or i==len(tasks): print(f'売買反転 {i}/{len(tasks)} {identifier}',flush=True)


if __name__ == '__main__':
    main()
