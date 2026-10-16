"""往復の開始基準更新で活動が消えた理由と、逆方向の確認が遅れた具体例を整理する。"""

import importlib.util
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SPEC = importlib.util.spec_from_file_location('状態遅れ読取90', HERE/'独立選定と原因診断.py')
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def summary(values):
    """
    機能: エピソードの長さと移動幅を分布にする。
    引数: values(list[float])。
    返り値: dict は件数と分位値。
    """
    values = np.asarray(values, np.float64)
    return dict(count=len(values), median=float(np.median(values)) if len(values) else None,
                q90=float(np.quantile(values, .9)) if len(values) else None,
                maximum=float(values.max()) if len(values) else None)


def main():
    """
    機能: 第2段の保存台帳を診断し、新しい売買規則を作らず追加資料へ保存する。
    引数: なし。
    返り値: None。将来値は原因診断だけに使う。
    """
    fixed = R.read(WORK/'round2/事前固定.json')
    for relative, expected in fixed['SHA256'].items():
        assert R.digest(ROOT/relative) == expected
    prices = R.read(ROOT/'work/wave_v83/prepared/inputs.pkl')
    grids = R.read(ROOT/'work/wave_v77/inputs/grids_delay1.pkl')
    entries = R.read(ROOT/'work/wave_v77/prepared/signals_delay1.pkl')
    config = next(item for item in fixed['条件'] if item['id'] == 'D_C_QA')
    states = {session: R.state(grids[session], entries[session], config) for session in fixed['全30']}
    timelines = {key: R.timeline(record, states[key[0]]) for key, record in prices.items()}
    starts = {symbol: [] for symbol in R.SYMBOLS}
    records = R.read(WORK/'round2/ledgers/D_C_QA.pkl')
    for key, ledger in records.items():
        record, current = prices[key], timelines[key]
        ends = np.flatnonzero(current['mode'] != 2)
        reservations = ledger['events'][(ledger['events'][:, 2] == 1) & (ledger['events'][:, 3] == 1), 0]
        for event in ledger['events'][(ledger['events'][:, 2] == 1) & (ledger['events'][:, 3] == 11)]:
            row = int(event[0])
            assert current['mode'][row] == 2
            place = np.searchsorted(ends, row, side='right')
            stop = int(ends[place]) if place < len(ends) else len(record['price'])
            assert stop > row
            delta = np.abs(record['price'][row:stop]-event[7]) / record['tick']
            candidate = reservations[(reservations >= row) & (reservations < stop)]
            starts[key[1]].append(dict(session=key[0], time=R.stamp(record['time_s'][row]),
                start_row=row, end_time=R.stamp(record['time_s'][stop]) if stop<len(record['price']) else None,
                duration_seconds=float(record['time_s'][stop-1]-record['time_s'][row]),
                maximum_move_ticks=float(delta.max(initial=0)), reservations_inside_episode=len(candidate)))
    activation = {}
    for symbol, cases in starts.items():
        activation[symbol] = dict(activation_count=len(cases),
            no_reservation_episodes=sum(case['reservations_inside_episode']==0 for case in cases),
            fewer_than_8tick_episodes=sum(case['maximum_move_ticks']<8 for case in cases),
            episode_duration_seconds=summary([case['duration_seconds'] for case in cases]),
            episode_maximum_move_ticks=summary([case['maximum_move_ticks'] for case in cases]),
            longest_examples=sorted(cases, key=lambda case: case['duration_seconds'], reverse=True)[:5])

    # ----------------------------------------
    common_examples, common_counts = {}, {}
    for ident in ('D_C_QA', 'D_C_Q', 'M82_Q', 'J8_Q'):
        common_examples[ident], common_counts[ident] = {}, {}
        ledger = records if ident == 'D_C_QA' else R.read(WORK/'round2/ledgers'/f'{ident}.pkl')
        for symbol in R.SYMBOLS:
            candidates, count = [], dict(parents=0, opposite_common_during_hold=0,
                opposite_mode_during_hold=0, common_only_without_opposite_mode=0,
                eventual_positive_after_opposite_common=0, eventual_negative_after_opposite_common=0)
            for key, item in ledger.items():
                if key[1] != symbol:
                    continue
                record, current, grid_state = prices[key], timelines[key], states[key[0]]
                raw_common = np.zeros(len(record['price']), np.int8)
                good = current['fresh']
                raw_common[good] = grid_state['common'][current['latest'][good]]
                for parent in R.parents_from_orders(key, item):
                    count['parents'] += 1
                    common_row = R.first_row(raw_common == -parent['side'], parent['entry_row']+1, parent['exit_row']+1)
                    mode_row = R.first_row(current['mode'] == -parent['side'], parent['entry_row']+1, parent['exit_row']+1)
                    if mode_row is not None:
                        count['opposite_mode_during_hold'] += 1
                    if common_row is not None:
                        count['opposite_common_during_hold'] += 1
                        count['common_only_without_opposite_mode'] += int(mode_row is None)
                        count['eventual_positive_after_opposite_common'] += int(parent['net'] > 0)
                        count['eventual_negative_after_opposite_common'] += int(parent['net'] < 0)
                        case = dict(session=key[0], symbol=symbol, parent=parent,
                            first_opposite_common=R.snapshot_at(common_row, record, current, grid_state),
                            first_opposite_mode=R.snapshot_at(mode_row, record, current, grid_state) if mode_row is not None else None,
                            entry=R.snapshot_at(parent['entry_row'], record, current, grid_state),
                            actual_exit_time=R.stamp(parent['exit_time']))
                        candidates.append(case)
            common_examples[ident][symbol] = sorted(candidates, key=lambda case: case['parent']['net'])[:3]
            common_counts[ident][symbol] = count
    conclusion = [
        'Aの損失減少は、再基準と8tick移動を短い有効状態の中で求めた結果、多くの開始エピソードで新規に届かなかった効果を含む。29場無取引を安定化成功と呼ばない。',
        'ER高の追従modeを撤退にも要求すると、両市場が逆向きに進み始めても中間ER又は欠測でmode0となり、反対確認の出口が作動しない。入口での強い証拠と保有撤退に必要な証拠を同じものにする必要はない。',
        'ただし逆共同方向が一度出た後に最終利益になった親もある。全てを即時返済すれば良いという主張はできず、持続確認・初期損失予算・利益保護を一軸対照として新しく事前固定して検証する必要がある。',
        '既往v78等の板反対撤退・共同方向管理の検証を参照し、今回のcommon価格基準と高ERmode撤退の差を明確にする。未検証と既検証を混ぜない。']
    proof = dict(全合格=True, 主D_C_QAの開始エピソード=activation,
        逆共同方向と逆modeの成立件数=common_counts,
        逆共同方向が見えても高ERmodeを満たさなかった具体例=common_examples,
        結論=conclusion, 全期間既知=True, 事後診断のみ=True,
        新売買規則損益計算=0, API取得=0, 実注文=0, 凍結変更=0,
        SHA256={str(path.relative_to(ROOT)): R.digest(path) for path in
             [Path(__file__), HERE/'独立選定と原因診断.py', WORK/'round2/事前固定.json']})
    target = HERE/'往復開始の短命化と逆共同方向を見逃す閾値の独立診断.json'
    target.write_text(json.dumps(R.clean(proof), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(往復開始=activation, 主逆確認=common_counts['D_C_QA']), ensure_ascii=False))


if __name__ == '__main__':
    main()
