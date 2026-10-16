"""少数の手算親と二候補だけで、参考選定の会計・順位・段階ガードを確認する。"""

import copy
import json
import math
from pathlib import Path

import numpy as np

import selection


def simple(ident: str, **changes: object) -> dict:
    """
    機能: 順位の各要素を手算で試す二商品同条件の小さな候補を作る。
    引数: ident(str)、changes(dict[str,object])は変更する固定指標。
    返り値: dictは人工候補。正式損益は参照しない。
    """
    periods = dict(campaigns=20, active_sessions=8, net=1., payoff=2., without_best_day=dict(net=1.), profit_share=.7)
    stable = dict(downside_rms_units=.1, positive_session_rate=.8, worst_session_loss_units=.2, active_net_q25_units=.3)
    for name, value in changes.items():
        if name in periods:
            periods[name] = value
        else:
            stable[name] = value
    return dict(config=dict(id=ident), periods={s: copy.deepcopy(periods) for s in selection.SYMBOLS},
                stability={s: copy.deepcopy(stable) for s in selection.SYMBOLS})


def financial() -> dict:
    """
    機能: 買い勝ち・売り負けと三赤字場・一無取引場を手算期待値へ一致させる。
    引数: なし。
    返り値: dictは少数親の金額・全16分母・無取引除外の検査結果。
    """
    sessions = [f'2000-01-{day:02d}_Day' for day in range(1, 17)]
    rows = []
    first_prices = {}
    for symbol in selection.SYMBOLS:
        base, q, fee = (4000., 8, 334) if symbol == 'TOPIX' else (50000., 16, 176)
        positive = np.zeros((2, 16), float)
        negative = np.zeros((1, 16), float)
        positive[0] = [1, 0, 0, 1, 1, q, base, base + (2. if symbol == 'TOPIX' else 100.),
                       fee, fee, 16000., 16000. - 2*fee, 10, 2, 1, 0]
        positive[1] = [2, 0, 2, 3, -1, q, base, base + (.5 if symbol == 'TOPIX' else 25.),
                       fee, fee, -4000., -4000. - 2*fee, 10, 1, 2, 2]
        negative[0] = [1, 0, 0, 1, -1, q, base, base + (1. if symbol == 'TOPIX' else 50.),
                       fee, fee, -8000., -8000. - 2*fee, 10, 1, 1, 0]
        for day, session in enumerate(sessions):
            trades = positive if day < 12 else negative if day < 15 else np.zeros((0, 16), float)
            totals = selection.parent_totals(trades, symbol)
            rows.append(dict(session=session, symbol=symbol, **totals))
            first_prices[session, symbol] = base
    summary = selection.summarize(dict(id='二候補用の手算', trend_budget=8), rows, sessions, first_prices)
    for symbol, profit, loss, worst, unit in (
            ('TOPIX', 183984., 82020., 8668., 40000.), ('NK225', 187776., 77280., 8352., 10000.)):
        period = summary['periods'][symbol]
        stable = summary['stability'][symbol]
        assert period['profit'] == profit and period['loss'] == loss and period['net'] == profit-loss
        assert period['campaigns'] == 27 and period['active_sessions'] == 15
        assert stable['session_count'] == 16 and stable['no_trade_sessions'] == 1
        assert stable['positive_session_rate'] == 12/15 and stable['worst_session_loss_yen'] == worst
        selection.close(stable['downside_rms_units'], math.sqrt(3*(worst/unit)**2/16), '手算RMS')
        selection.close(stable['active_net_q25_units'], (16000. - 4000. - (4*334 if symbol == 'TOPIX' else 4*176))/unit, '手算q25')
    return dict(二商品の親会計手算一致=True, 共通上限と全16分母=True, 無取引を黒字扱いしない=True)


def rank_cases() -> int:
    """
    機能: 二候補ずつで固定採点の各優先要素と集合段階を確認する。
    引数: なし。
    返り値: intは手書き期待値へ一致した少数比較の件数。
    """
    cases = [(dict(downside_rms_units=.05, net=1.), dict(downside_rms_units=.1, net=100000.)),
             (dict(positive_session_rate=.9), dict(positive_session_rate=.8)),
             (dict(worst_session_loss_units=.1), dict(worst_session_loss_units=.2)),
             (dict(active_net_q25_units=.4), dict(active_net_q25_units=.3)),
             (dict(profit_share=.75), dict(profit_share=.7)), ({}, {})]
    for preferred, other in cases:
        assert selection.choose([simple('B', **other), simple('A', **preferred)])['selected'] == 'A'
    for level, change in ((0, dict(profit_share=.8)), (1, {}), (2, dict(without_best_day=dict(net=0.))),
                          (3, dict(payoff=1.)), (4, dict(net=0.)), (5, dict(campaigns=19))):
        assert selection.choose([simple('A', **change)])['level'] == level
    assert selection.choose([simple('A', active_sessions=7)])['level'] == 5
    assert selection.choose([simple('A', payoff=None)])['level'] == 3
    return len(cases) + 8


def stages() -> tuple:
    """
    機能: 損益なしの小さなファイル名資料で未完前16と既存後15を拒否する。
    引数: なし。
    返り値: tuple[int,list[Path]]は拒否件数と人工資料位置。正式front/backへ書かない。
    """
    generation = 1
    base = selection.HERE / f'段階人工_{generation:05d}'
    while base.exists():
        generation += 1
        base = selection.HERE / f'段階人工_{generation:05d}'
    assert base.resolve().is_relative_to(selection.HERE.resolve())
    fixed = dict(条件=[dict(id=f'人工{number:02d}') for number in range(34)],
                 前16=[f'2000-01-{day:02d}_Day' for day in range(1, 17)])

    def rejected() -> bool:
        """
        機能: 段階ガードの拒否を実例へ適用する。
        引数: なし。
        返り値: boolは予定どおり拒否された場合にTrue。
        """
        try:
            selection.guard(base, fixed)
        except AssertionError:
            return True
        return False

    assert rejected()
    paths = []
    for config in fixed['条件']:
        for sub, suffix in (('results', '.json'), ('ledgers', '.pkl')):
            path = base / 'front' / sub / (config['id'] + suffix)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'null' if suffix == '.json' else b'')
            paths.append(path)
    selection.guard(base, fixed)
    back = base / 'back/results/後15未許可の人工.json'
    back.parent.mkdir(parents=True, exist_ok=True)
    back.write_text('{"人工": true}\n', encoding='utf-8')
    assert rejected()
    paths.append(back)
    return 2, paths


def main() -> None:
    """
    機能: 少数親と採点順だけを検査し正式99結果を一切読まず準備証跡を保存する。
    引数: なし。
    返り値: Noneは本体不変更の独立選定準備証跡。
    """
    totals = financial()
    rank = rank_cases()
    reject, paths = stages()
    paths += [Path(__file__), Path(selection.__file__), selection.WORK/'research.py',
              selection.WORK/'セッション安定性の事前評価.json']
    proof = dict(全合格=True, **totals, 採点順及び候補段階の少数比較=rank, 段階不正拒否=reject,
                 根score及びselect呼出=0, 正式99結果閲覧=0, 正式99売買実行=0, API取得=0, 実注文=0,
                 SHA256={str(path.relative_to(selection.ROOT)): selection.sha(path) for path in paths})
    path = selection.HERE/'二候補と少数親の独立前16選定準備検査.json'
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in proof.items() if key != 'SHA256'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
