"""初期気配差だけを加えた予算対照を、旧所有診断と完成注文から比較する。"""

from datetime import datetime
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OLD = ROOT / 'work/stability119_20261017/v8/diagnosis'
EXPECTED = '80bab7ec7f540e09bdfd31c9aa59318bcb448c24635086239dc98e4c3b47d814'
SYMBOLS = ('NK225', 'TOPIX')


def save(path: Path, value: dict) -> None:
    """
    機能: 診断所有域に標準JSONの新規証跡を保存する。
    引数: path(Path)は保存先、value(dict)は有限数値の診断値。
    返り値: None。旧成果や経済源を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')


def records(result: dict) -> list[dict]:
    """
    機能: 保存親の列名を明示して、注文と親会計を結ぶ。
    引数: result(dict)は解析済みの完成結果所有コピー。
    返り値: list[dict]は全完結親。金融を再計算しない。
    """
    columns = result['columns']
    parents = []
    for episode in result['episodes']:
        for row in episode['parents']:
            parent = dict(zip(columns['parents'], row))
            assert parent['complete'] == 1
            assert parent['gross_nk'] + parent['gross_top'] - parent['fees_nk'] - parent['fees_top'] == parent['net']
            orders = [dict(zip(columns['orders'], x)) for x in episode['orders'] if x[0] == parent['parent']]
            parent.update(method=episode['method'], session=episode['session'], orders=orders)
            parents.append(parent)
    return parents


def match_key(parent: dict) -> tuple:
    """
    機能: 親連番によらず、同じ公開予約と固定モデルを対応させる。
    引数: parent(dict)は保存実親。
    返り値: tupleは時計・方向・モデル・数量の完全一致キー。
    """
    fields = ('decision_time', 'prepare_time', 'side_nk', 'beta', 'center', 'sigma',
              'prepare_delta', 'extreme_delta', 'entry_delta', 'target_quantity_nk',
              'target_quantity_top', 'reserve_reference_nk', 'reserve_reference_top')
    return (parent['session'], parent['method'].removesuffix('_CB')) + tuple(parent[k] for k in fields)


def immediate(parent: dict) -> bool:
    """
    機能: 両脚の実新規約定完了時計と同じ時計のcash返済判断を識別する。
    引数: parent(dict)は完成親。
    返り値: bool。次quoteの実返済時計とは区別する。
    """
    return parent['filled_legs'] == 2 and parent['reason'] == 3 and parent['exit_decision_time'] == max(parent['entry_time_nk'], parent['entry_time_top'])


def iso(clock: float) -> str:
    """
    機能: 保存価格時計を日本時間の表示へ変換する。
    引数: clock(float)はepoch秒。
    返り値: str。現実の受信時刻や約定保証とは呼ばない。
    """
    return datetime.fromtimestamp(clock, ZoneInfo('Asia/Tokyo')).isoformat()


def initial(parent: dict, market: dict, new: bool) -> dict:
    """
    機能: 同時計共同snapshotの初期清算値と予約時の固定予算を検算する。
    引数: parent(dict)、market(dict)は親と二商品の既所有quotes、new(bool)は気配差込み予算の指定。
    返り値: dictは初期清算・予算・Last不変を分けた記述。
    """
    now = max(parent['entry_time_nk'], parent['entry_time_top'])
    points = {}
    for symbol in SYMBOLS:
        quote = market[symbol]
        i = int(np.searchsorted(quote['time'], now, side='right') - 1)
        assert i >= 0
        points[symbol] = {k: float(quote[k][i]) for k in ('row', 'time', 'last', 'bid', 'ask')}
        points[symbol]['age'] = now - points[symbol]['time']
    side = int(parent['side_nk'])
    qn, qt = int(parent['target_quantity_nk']), int(parent['target_quantity_top'])
    fees = 2 * (qn * 11 + qt * 209 // 5)
    gross = side * (points['NK225']['bid' if side > 0 else 'ask'] - parent['entry_nk']) * qn * 10
    gross += -side * (points['TOPIX']['ask' if side > 0 else 'bid'] - parent['entry_top']) * qt * 1000
    margin = -side * (parent['extreme_delta'] - parent['entry_delta'])
    nominal = parent['reserve_reference_nk'] * qn * 10
    spread = parent['estimated_roundtrip_cost'] - fees
    assert spread >= 0
    budget = margin * nominal + fees + (spread if new else 0)
    assert math.isclose(budget, parent['cash_loss_budget'], rel_tol=1e-9, abs_tol=1e-6)
    delta = math.log(points['NK225']['last']) - parent['beta'] * math.log(points['TOPIX']['last']) - parent['center']
    return dict(clock=now, time=iso(now), quotes=points, gross=gross, fees=fees, net=gross-fees,
                budget=budget, reserved_spread_cash=spread, fixed_extreme_margin_cash=margin*nominal,
                initial_breach=gross-fees <= -budget, delta=delta,
                same_Last_as_reserve=points['NK225']['last'] == parent['reserve_reference_nk'] and points['TOPIX']['last'] == parent['reserve_reference_top'])


def main() -> None:
    """
    機能: 全八条件の即停止と総額差を集計し、改善・悪化の共通親を一例ずつ残す。
    引数: なし。
    返り値: None。元結果再読・市場原本・新金融へ接続しない。
    """
    raw = (HERE / '完成結果の同bytes保全.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED
    new = json.loads(raw)
    old = json.loads((OLD / '完成結果の同bytes保全.json').read_text(encoding='utf8'))
    assert new['source_SHA256'] == new['source_end_SHA256']
    assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == sha for p, sha in new['source_SHA256'].items())
    op, np_ = records(old), records(new)
    oldmap, newmap = {match_key(p): p for p in op}, {match_key(p): p for p in np_}
    assert len(oldmap) == len(op) and len(newmap) == len(np_)
    summary = []
    matches = []
    for spec in new['specs']:
        n = [p for p in np_ if p['method'] == spec['id']]
        o = [p for p in op if p['method'] == spec['baseline_id']]
        nr = [r for r in new['runs'] if r['method'] == spec['id']]
        or_ = [r for r in old['runs'] if r['method'] == spec['baseline_id']]
        assert len(nr) == len(or_) == 40
        netnew, netold = sum(p['net'] for p in n), sum(p['net'] for p in o)
        assert netnew == sum(x['net'] for x in nr) and netold == sum(x['net'] for x in or_)
        common = [k for k in oldmap.keys() & newmap.keys() if k[1] == spec['baseline_id']]
        common_delta = sum(newmap[k]['net'] - oldmap[k]['net'] for k in common)
        oldextra = sum(p['net'] for p in o if match_key(p) not in newmap)
        newextra = sum(p['net'] for p in n if match_key(p) not in oldmap)
        assert common_delta + newextra - oldextra == netnew - netold
        oi, ni = [p for p in o if immediate(p)], [p for p in n if immediate(p)]
        summary.append(dict(method=spec['id'], old_method=spec['baseline_id'], old_net=netold, new_net=netnew,
                            change=netnew-netold, old_gross=sum(p['gross_nk']+p['gross_top'] for p in o),
                            new_gross=sum(p['gross_nk']+p['gross_top'] for p in n),
                            old_fees=sum(p['fees_nk']+p['fees_top'] for p in o), new_fees=sum(p['fees_nk']+p['fees_top'] for p in n),
                            old_parents=len(o), new_parents=len(n), old_paired=sum(p['filled_legs']==2 for p in o), new_paired=sum(p['filled_legs']==2 for p in n),
                            old_immediate=len(oi), new_immediate=len(ni), old_immediate_net=sum(p['net'] for p in oi), new_immediate_net=sum(p['net'] for p in ni),
                            old_cashstop=sum(p['reason']==3 for p in o), new_cashstop=sum(p['reason']==3 for p in n),
                            common_reservations=len(common), common_parent_delta=common_delta,
                            old_unmatched_parents=len(o)-len(common), old_unmatched_net=oldextra,
                            new_unmatched_parents=len(n)-len(common), new_unmatched_net=newextra,
                            new_black=sum(r['net']>0 for r in nr), new_red=sum(r['net']<0 for r in nr), new_no_trade=sum(r['net']==0 for r in nr)))
        matches.extend(dict(old=oldmap[k], new=newmap[k], change=newmap[k]['net']-oldmap[k]['net']) for k in common)
    candidates = {}
    for baseline, direction in (('OLS_MR_CONF_L60_X0', '改善'), ('OLS_MR_CONF_L30_X0', '悪化')):
        group = [m for m in matches if m['old']['method'] == baseline and m['old']['filled_legs'] == m['new']['filled_legs'] == 2]
        chosen = max(group, key=lambda m: m['change']) if direction == '改善' else min(group, key=lambda m: m['change'])
        assert chosen['change'] > 0 if direction == '改善' else chosen['change'] < 0
        candidates[direction] = chosen
    wanted = sorted({(m['old']['session'], symbol) for m in candidates.values() for symbol in SYMBOLS})
    oldplan = json.loads((OLD / '共同snapshotと全即停止親の必要quotes読取計画.json').read_text(encoding='utf8'))
    lookup = {(x['session'], x['symbol']): x for x in oldplan['inputs']}
    inputs = [{'session': scene, 'symbol': symbol, 'path': (OLD/'owned_inputs'/symbol/(scene+'.npz')).relative_to(ROOT).as_posix(),
               'SHA256': lookup[scene, symbol]['SHA256']} for scene, symbol in wanted]
    save(HERE/'改善悪化二親の所有quoteだけを読む計画.json', dict(全合格=True, inputs=inputs,各所有copy読取=1,原市場読取=0,原cache読取=0,金融再生=0,
         選択='先行計画のOLS60X0改善/OLS30X0悪化の共通予約でnet差最大各一例。',比較='親IDでなく予約と固定モデルの完全一致。'))
    market, logs = {}, []
    for item in inputs:
        p = ROOT/item['path']; data = p.read_bytes()
        assert hashlib.sha256(data).hexdigest() == item['SHA256']
        with np.load(BytesIO(data), allow_pickle=False) as saved:
            market[item['session'], item['symbol']] = {name: saved['quotes__'+name].copy() for name in ('row','time','last','bid','ask')}
        logs.append(dict(item, reads=1))
    examples = []
    for label, chosen in candidates.items():
        material = {symbol: market[chosen['old']['session'], symbol] for symbol in SYMBOLS}
        before, after = initial(chosen['old'], material, False), initial(chosen['new'], material, True)
        assert before['gross'] == after['gross'] and before['fees'] == after['fees']
        assert math.isclose(after['budget']-before['budget'], after['reserved_spread_cash'], abs_tol=1e-6)
        examples.append(dict(label=label, **chosen, old_initial=before, new_initial=after,
                             old_times={k:iso(chosen['old'][k]) for k in ('decision_time','entry_time_nk','entry_time_top','exit_decision_time','exit_time_nk','exit_time_top')},
                             new_times={k:iso(chosen['new'][k]) for k in ('decision_time','entry_time_nk','entry_time_top','exit_decision_time','exit_time_nk','exit_time_top')}))
    out = dict(全合格=True, 結果SHA256=EXPECTED, 比較元SHA256='2f7c15e27d7c0e20b6b14de8ab682ac62d49a55b6ba35d2079b6245d9699dcf4',
               source_SHA256=new['source_SHA256'], summary=summary, examples=examples, read_log=logs,
               結果原本読取=1,元結果追加読取=0,原市場読取=0,原cache読取=0,金融再生=0,
               留保='予算を変更した全経路の実対照。共通予約以外の新旧親差も分ける。先行したi即停止親だけを消した救済PLではない。全8は重複し独立標本へ合算しない。')
    save(HERE/'気配差予算の即停止差と改善悪化二親の限定診断.json', out)
    print(json.dumps({'summary':summary, 'examples':[{k:e[k] for k in ('label','change','old_times','new_times')} for e in examples], 'owned_copy_reads':len(logs)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
