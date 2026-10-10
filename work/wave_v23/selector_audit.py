"""新しい選択器の途中切断・将来セッション削除・未来価格改変を独立検算する。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import pickle

import numpy as np

from audit_core import truncate_ready
from audit_signals import mutate_future
import signals

OUT = Path(__file__).resolve().parent


def subset_directions(directions: dict, inputs: dict) -> dict:
    """機能: 基礎信号を指定入力のキーと行数へ切り詰める。

    引数: directions/inputs (dict)。返り値: 元データを変更しない方向辞書 (dict)。
    """
    return {identifier: {key: values[key][:len(ready['last'])].copy() for key, ready in inputs.items()}
            for identifier, values in directions.items()}


def compare_outputs(full: dict, partial: dict) -> int:
    """機能: 共通する選択器・期間・銘柄の全行方向が先頭から不変か照合する。

    引数: full/partial (dict)。返り値: 比較したセル件数 (int)。
    """
    count = 0
    for identifier, by_key in partial.items():
        assert identifier in full
        for key, value in by_key.items():
            np.testing.assert_array_equal(value, full[identifier][key][:len(value)], err_msg=f'{identifier} {key}')
            count += 1
    return count


def event_signature(event: dict) -> tuple:
    """機能: 時刻と選択結果を順序に依存しない比較キーへ変換する。

    引数: event (dict)。返り値: 選択内容のキー (tuple)。
    """
    names = ['selector_id', 'session', 'symbol', 'time_s', 'seq', 'row_index',
             'selected_signal_id', 'proposed_signal_id', 'reason', 'confirmations', 'direction_at_selection']
    return tuple(event.get(name) for name in names)


def inspect_market(module, inputs: dict, features: dict, directions: dict) -> dict:
    """機能: 当時の市場状態による選択器を、原本途中切断と相手未来改変で検査する。

    引数: module (module)、inputs/features/directions (dict)。返り値: 検算結果 (dict)。
    """
    cases, event_cases = [], []
    for session in ['2026-09-22_Night', '2026-09-29_Day']:
        own_inputs = {key: value for key, value in inputs.items() if key[0] == session}
        own_features = {key: value for key, value in features.items() if key[0] == session}
        own_directions = subset_directions(directions, own_inputs)
        signals.clear_cache()
        specs, full, events = module.build_all(own_inputs, own_features, own_directions)
        primary = own_inputs[(session, 'NK225')]
        for fraction in [.27, .53, .81]:
            count = int(len(primary['last']) * fraction)
            cutoff = primary['time_s'][count - 1]
            partial_inputs, partial_features = {}, {}
            for key, ready in own_inputs.items():
                n = count if key[1] == 'NK225' else int(np.searchsorted(ready['time_s'], cutoff, side='right'))
                partial_inputs[key] = truncate_ready(ready, n)
                partial_features[key] = own_features[key].loc[(own_features[key].seq <= ready['seq'][n - 1]) & (own_features[key].time_s <= ready['time_s'][n - 1])].copy()
            signals.clear_cache()
            _, partial, part_events = module.build_all(partial_inputs, partial_features, subset_directions(directions, partial_inputs))
            cells = compare_outputs(full, partial)
            expected = [event_signature(event) for event in events if event['seq'] <= partial_inputs[(event['session'], event['symbol'])]['seq'][-1]]
            observed = [event_signature(event) for event in part_events]
            if observed != expected:
                mismatch = next((i for i, pair in enumerate(zip(observed, expected)) if pair[0] != pair[1]), min(len(observed), len(expected)))
                raise AssertionError(dict(セッション=session, 割合=fraction, 実件数=len(observed), 期待件数=len(expected),
                                          不一致位置=mismatch, 実値=observed[mismatch] if mismatch < len(observed) else None,
                                          期待値=expected[mismatch] if mismatch < len(expected) else None))
            cases.append(dict(検査='原本途中切断', セッション=session, 割合=fraction, 比較セル数=cells))
            event_cases.append(dict(検査='選択イベント途中切断', セッション=session, 割合=fraction, 比較判断数=len(part_events)))
        cutoff = primary['time_s'][int(len(primary['last']) * .53)]
        for symbol in ['TOPIX', 'NK225']:
            changed_features, changed_inputs = mutate_future(own_features, own_inputs, cutoff, symbol)
            changed_directions = subset_directions(directions, changed_inputs)
            for values in changed_directions.values():
                key = (session, symbol)
                values[key][changed_inputs[key]['time_s'] > cutoff] *= -1
            signals.clear_cache()
            _, modified, changed_events = module.build_all(changed_inputs, changed_features, changed_directions)
            cells = 0
            for identifier, values in full.items():
                for key, direction in values.items():
                    count = int(np.searchsorted(own_inputs[key]['time_s'], cutoff, side='right'))
                    np.testing.assert_array_equal(modified[identifier][key][:count], direction[:count])
                    cells += 1
            before = [event_signature(event) for event in events if event['time_s'] <= cutoff]
            after = [event_signature(event) for event in changed_events if event['time_s'] <= cutoff]
            assert before == after
            cases.append(dict(検査='相手未来原本・板・基礎方向の反転', セッション=session, 変更銘柄=symbol, 比較セル数=cells))
            event_cases.append(dict(検査='相手未来反転時の選択不変', セッション=session, 変更銘柄=symbol, 比較判断数=len(before)))
    return dict(選択器数=len(specs), 方向比較=cases, 選択判断比較=event_cases,
                方向比較セル合計=sum(row['比較セル数'] for row in cases),
                選択判断比較合計=sum(row['比較判断数'] for row in event_cases))


def inspect_past(module, inputs: dict, features: dict, directions: dict) -> dict:
    """機能: 完了区間実績の選択が現在以後の損益やデータに依存しないか検算する。

    引数: module (module)、inputs/features/directions (dict)。返り値: 検査要約 (dict)。
    変更する実績表は新規監査領域のコピーに限定する。
    """
    source = module.RESULTS_PATH
    table = json.loads(source.read_text(encoding='utf-8'))
    specs, full, events = module.build_all(inputs, features, directions)
    sessions = sorted({key[0] for key in inputs})
    case_dir = OUT / 'selector_audit_cases'
    case_dir.mkdir(exist_ok=True)
    records = []
    try:
        for count in [3, 6, 10, 12]:
            kept = set(sessions[:count])
            shortened = {key: value for key, value in inputs.items() if key[0] in kept}
            rows = [row for row in table if row['session'] in sessions[:count - 1]]
            target = case_dir / f'過去実績_{count}区間目直前まで.json'
            target.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
            module.RESULTS_PATH = target
            _, partial, partial_events = module.build_all(shortened, {}, subset_directions(directions, shortened))
            cells = compare_outputs(full, partial)
            expected = [event for event in events if event['適用セッション'] in kept]
            assert partial_events == expected
            records.append(dict(検査='未来入力削除・評価当区間以後の実績削除', 保持区間数=count,
                                比較セル数=cells, 選択判断数=len(partial_events)))
        # 現在以降の損益を大幅に変えても、現在開始時までの選択と方向は同じ。
        for target_index in [5, 9, 12]:
            altered = []
            for row in table:
                row = dict(row)
                if row['session'] >= sessions[target_index]:
                    for name in ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'cycle_profit_yen',
                                 'cycle_loss_yen', 'net_r', 'drawdown_yen', 'min_equity_yen', 'max_equity_yen']:
                        row[name] = float(row[name]) * (13. if row['id'].startswith('F32_') else .03)
                altered.append(row)
            target = case_dir / f'未来損益改変_{target_index}.json'
            target.write_text(json.dumps(altered, ensure_ascii=False), encoding='utf-8')
            module.RESULTS_PATH = target
            _, changed, changed_events = module.build_all(inputs, {}, directions)
            kept = set(sessions[:target_index + 1])
            before = {identifier: {key: value for key, value in values.items() if key[0] in kept} for identifier, values in full.items()}
            after = {identifier: {key: value for key, value in values.items() if key[0] in kept} for identifier, values in changed.items()}
            cells = compare_outputs(before, after)
            expected = [event for event in events if event['適用セッション'] in kept]
            actual = [event for event in changed_events if event['適用セッション'] in kept]
            assert actual == expected
            records.append(dict(検査='現在以後の実績を大幅改変', 適用区間=sessions[target_index],
                                比較セル数=cells, 選択判断数=len(actual)))
        module.RESULTS_PATH = source
        last = sessions[-1]
        for fraction in [.25, .61, .83]:
            shortened = {key: (truncate_ready(ready, int(len(ready['last']) * fraction)) if key[0] == last else ready)
                         for key, ready in inputs.items()}
            _, partial, partial_events = module.build_all(shortened, {}, subset_directions(directions, shortened))
            cells = compare_outputs(full, partial)
            assert partial_events == events
            records.append(dict(検査='評価当区間の途中切断', セッション=last, 割合=fraction,
                                比較セル数=cells, 選択判断数=len(events)))
    finally:
        module.RESULTS_PATH = source
    return dict(選択器数=len(specs), 検査=records, 方向比較セル合計=sum(row['比較セル数'] for row in records),
                選択判断比較合計=sum(row['選択判断数'] for row in records),
                現在以後の実績不使用=True, 原本の実績表不変=True)


def main() -> None:
    """機能: 指定された選択器監査を行い、旧凍結結果へ触れず別記録に保存する。

    引数: なし。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=['market', 'past'])
    args = parser.parse_args()
    inputs = pickle.loads((OUT / 'inputs.pkl').read_bytes())
    features = pickle.loads((OUT / 'features_depth.pkl').read_bytes())
    directions = pickle.loads((OUT / 'directions.pkl').read_bytes())
    if args.kind == 'market':
        import selector_signals
        result = inspect_market(selector_signals, inputs, features, directions)
    else:
        import selector_past
        result = inspect_past(selector_past, inputs, features, directions)
    result.update(合格=True, 現在API取得数=0, 元入力と旧凍結条件不変=True,
                  限界='全13セッションは既読。追加選択器を保存済み現在セッションへ適用する場合も後付け診断であり、未見照合ではない。')
    (OUT / f'selector_{args.kind}_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key not in ['方向比較', '選択判断比較']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
