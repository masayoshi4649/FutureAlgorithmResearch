"""市場を読まず、119の条件展開・実行・選択・数量割当を接続する。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
OWNER = HERE.parent
ROOT = OWNER.parents[1]
sys.dont_write_bytecode = True
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit')
sys.path.insert(0, str(OWNER))
import run119 as subject
import artificial_catalog119 as material

CHECKS = []


def check(name: str, value: bool) -> None:
    """
    機能: 合成接続の成否を記録し、不成立を保存前に停止する。
    引数: name(str)、value(bool) は検査の内容と期待への一致。
    返り値: None。不成立ならAssertionError。
    """
    CHECKS.append(dict(項目=name, 合格=bool(value)))
    assert value, name


def fingerprint(path: Path) -> str:
    """
    機能: 参照した実装源だけの同一性を確認する。
    引数: path(Path) は市場値を含まない源。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(symbol: str, scene: str) -> tuple[dict, dict, dict]:
    """
    機能: 既人工の分足から、公開当行と直後行を持つ独立合成気配を作る。
    引数: symbol/scene(str) は契約と合成時計の起点。
    返り値: tuple[dict,dict,dict] は自己足・相手足・自己気配。
    """
    own = material.fixture(symbol, 'mixed', 410)
    other = material.fixture('NK225' if symbol == 'TOPIX' else 'TOPIX', 'trend', 410)
    start, _ = subject.input119.SOURCE.bounds(scene)
    for bars in (own, other):
        bars['t_s'] = start + 60 * np.arange(1, 411)
        bars['pub_price_time_s'] = bars['t_s'] + 1.
    tick = subject.catalog119.TICKS[symbol]
    rows = np.ravel(np.column_stack((own['pub_raw_row'], own['pub_raw_row'] + 1)))
    times = np.ravel(np.column_stack((own['pub_price_time_s'], own['pub_price_time_s'] + 1.)))
    center = np.repeat(own['anchor'], 2)
    quotes = dict(row=rows, seq=rows + 1, time=times, last=center,
                  bid=center - .5 * tick, ask=center + .5 * tick,
                  bq=np.full(len(rows), 100.), aq=np.full(len(rows), 100.))
    return own, other, quotes


def row(session: str, method: str, net: float, unclosed: int = 0) -> dict:
    """
    機能: 選択関数へ渡す市場と無関係な場会計を作る。
    引数: session/method(str)、net(float)、unclosed(int) は仮の識別子と集計。
    返り値: dict は選択に必要な人工項目。
    """
    return dict(session=session, method=method, net=net, profit=max(net, 0.), loss=max(-net, 0.),
                parents=2, wins=2 if net > 0 else 0, fills=4, fees=10., unclosed=unclosed)


def selection_checks() -> dict:
    """
    機能: 選択6場以外の未来損益と未清算による不正昇格を人工的に反証する。
    引数: なし。
    返り値: dict は固定三家族の人工選択結果。
    """
    scenes = [f'選択{i}' for i in range(6)]
    specs = [dict(id='A1', family='A'), dict(id='A2', family='A'),
             dict(id='B', family='B'), dict(id='C', family='C'),
             dict(id='OPEN', family='未清算')]
    values = dict(A1=40., A2=30., B=20., C=10., OPEN=1000000.)
    rows = [row(s, spec['id'], values[spec['id']], 10 if spec['id'] == 'OPEN' else 0)
            for s in scenes for spec in specs]
    before = subject.select(rows, specs, scenes)
    future = rows + [row('未来13', spec['id'], -1e12 if spec['id'] == 'A1' else 1e12)
                     for spec in specs]
    after = subject.select(future, specs, scenes)
    check('選択6以外の未来結果を変えても全順位不変', before == after)
    check('未清算は評価益が巨大でも昇格しない', 'OPEN' not in before['eligible_ids'])
    check('同家族重複を避ける固定三枠', before['chosen'] == ['A1', 'B', 'C'])
    zero = [dict(r, net=0., profit=0., loss=0., parents=0, wins=0, fills=0, unclosed=0) for r in rows]
    check('無取引は選択資格を持たない', not subject.select(zero, specs, scenes)['qualified'])
    for symbol, quantities, cap in (('TOPIX', (4, 3, 3), 10), ('NK225', (8, 6, 6), 20)):
        made = [subject.settings(symbol, '2026-10-16_Day', dict(exit_mode=0, entry_mode=0, guard=0), q)
                for q in quantities]
        check(symbol + '三枠の実発注数量合計は上限', sum(c['quantity'] for c in made) == cap)
        check(symbol + '枠毎に手数料を切捨てる', sum(math.floor(c['quantity'] * c['fee'] + 1e-9) for c in made)
              == (417 if symbol == 'TOPIX' else 220))
    return before


def edge_checks() -> None:
    """
    機能: 締切時刻とEOF参考評価が実完結へ化けないことを実行で確かめる。
    引数: なし。
    返り値: None。最小の足と気配だけを用いる。
    """
    spec = dict(exit_mode=0, entry_mode=0, guard=0)
    for symbol in ('TOPIX', 'NK225'):
        for scene, expected in (('2026-10-16_Day', ('15:00', '15:20')),
                                ('2026-10-16_Night', ('05:20', '05:40'))):
            made = subject.settings(symbol, scene, spec)
            check(symbol + scene + '実契約の注文刻みを接続',
                  made['order_tick'] == (.25 if symbol == 'TOPIX' else 5.))
            actual = tuple(datetime.fromtimestamp(made[k], timezone(timedelta(hours=9))).strftime('%H:%M')
                           for k in ('entry_end', 'close_time'))
            check(symbol + scene + '新規停止と強制判断の時刻', actual == expected)
    bars = dict(valid=np.ones(1, bool), anchor=np.array([1000.]), pub_raw_row=np.array([0], np.int64),
                pub_price_time_s=np.array([0.]), t_s=np.array([0.]))
    quotes = dict(row=np.array([0, 1], np.int64), time=np.array([0., 1.]),
                  bid=np.array([999., 1099.]), ask=np.array([1000., 1100.]))
    policy = dict(entry=np.array([1], np.int8), exit_long=np.array([False]), exit_short=np.array([False]),
                  width=np.array([1000.]), valid=np.array([True]))
    settings = dict(quantity=10, multiplier=1000., fee=41.8, exit_mode=1, entry_mode=0,
                    guard=0, entry_end=10., close_time=20.)
    result = subject.engine119.run_policy(bars, quotes, policy, settings)
    summary = result['summary']
    check('EOF保有は実返済明細を作らない', len(result['ledger']) == 0 and summary['unclosed'] == 10)
    check('EOFに予定料込み参考評価を返す', summary['net'] == -10836. and summary['realized'] == -418.)
    check('EOF未清算は完結親へ数えない', summary['parents'] == 0)


def main() -> None:
    """
    機能: 条件から実評価までの純接続と固定三枠の数量上限を検査する。
    引数: なし。市場入力又は既存の金融結果を読み込まない。
    返り値: None。完成源の指紋へ束縛した証跡一つを保存する。
    """
    before = subject.plan.sources()
    counts = {}
    for symbol in ('TOPIX', 'NK225'):
        bars, peer, quotes = fixture(symbol, '2026-10-16_Day')
        base = subject.variants(subject.catalog119.build(bars, peer, symbol, None))
        check(symbol + '単体18から216へ展開', len(base['specs']) == 216)
        rows, eq, pos, ledger = subject.evaluate(bars, quotes, base, symbol, '2026-10-16_Day')
        teacher = [i for i, spec in enumerate(base['specs']) if spec['entry_mode'] == 0 and spec['guard'] == 0]
        check(symbol + '成行場停止無し教師は54', len(teacher) == 54)
        width20 = base['width'][next(i for i, spec in enumerate(base['specs']) if spec['scale'] == 20)]
        roundtrip = 2 * math.floor(subject.CONTRACTS[symbol]['quantity'] * subject.CONTRACTS[symbol]['fee'] + 1e-9)
        selectors = subject.selector.build_selectors(eq[teacher], pos[teacher], width20,
                                                     [base['specs'][i]['family'] for i in teacher], roundtrip)
        auto = subject.variants(selectors, adaptive=True)
        check(symbol + '選択器6から36へ展開', len(selectors['specs']) == 6 and len(auto['specs']) == 36)
        auto_rows, ae, ap, al = subject.evaluate(bars, quotes, auto, symbol, '2026-10-16_Day')
        check(symbol + '252IDは一意', len({s['id'] for s in base['specs'] + auto['specs']}) == 252)
        for model, e, p in ((base, eq, pos), (auto, ae, ap)):
            k, n = len(model['specs']), len(bars['valid'])
            for key in ('entry', 'exit_long', 'exit_short', 'width', 'valid'):
                check(symbol + key + str(k) + '全shape', model[key].shape == (k, n))
            check(symbol + str(k) + '公開資産と方向shape', e.shape == p.shape == (k, n))
        check(symbol + '全252政策を実run_policyへ接続', len(rows) + len(auto_rows) == 252)
        for item in rows + auto_rows:
            check(symbol + item['method'] + '未清算ゼロなら親純損益一致',
                  item['unclosed'] != 0 or abs(item['net'] - item['profit'] + item['loss']) <= 1e-5)
        for source in (ledger, al):
            check(symbol + '全返済は新規原rowより後', bool(np.all(source[:, 3] > source[:, 2])))
            check(symbol + '返済料は実枚数各注文floor', bool(np.all(np.abs(source[:, 12]
                  - np.floor(source[:, 7] * subject.CONTRACTS[symbol]['fee'] + 1e-9)) <= 1e-8)))
        quantities = (4, 3, 3) if symbol == 'TOPIX' else (8, 6, 6)
        selected = [base['specs'][0], base['specs'][36], base['specs'][72]]
        held = []
        for spec, quantity in zip(selected, quantities):
            k = next(i for i, s in enumerate(base['specs']) if s['id'] == spec['id'])
            policy = {key: base[key][k] for key in ('entry', 'exit_long', 'exit_short', 'width', 'valid')}
            one = subject.engine119.run_policy(bars, quotes, policy,
                         subject.settings(symbol, '2026-10-16_Day', spec, quantity))
            held.append((np.abs(one['position']) > 0).astype(int) * quantity)
            check(symbol + spec['id'] + '枠の実返済枚数は割当以下',
                  len(one['ledger']) == 0 or bool(np.all(one['ledger'][:, 6] <= quantity)))
        check(symbol + '三枠同時保有合計の上限', bool(np.all(np.sum(held, axis=0) <= subject.CONTRACTS[symbol]['quantity'])))
        counts[symbol] = dict(単体=216, 教師=54, 選択器=6, 選択器派生=36, 一意ID=252,
                              合成足=len(bars['valid']), 合成正常気配=len(quotes['row']))
    selection = selection_checks()
    edge_checks()
    check('完成市場源は開始終端同一', before == subject.plan.sources())
    proof = dict(全合格=True, 原市場入力=0, 既金融結果=0, 新金融=0, API=0,
                 検査数=len(CHECKS), source_SHA256=before,
                 人工source_SHA256={Path(__file__).relative_to(ROOT).as_posix(): fingerprint(Path(__file__))},
                 内容=counts, 人工選択=selection['chosen'], 検査=CHECKS,
                 留保='全て自作又は既人工関数の合成素材。収益性や市場での活動率を測定した証跡ではない。正式固定・登録・金融は根担当。')
    target = HERE / '市場前の252政策接続と選択六場及び三枠数量の純人工_v2.json'
    assert not target.exists()
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査数=len(CHECKS), 証跡=str(target)), ensure_ascii=False))


if __name__ == '__main__':
    main()
