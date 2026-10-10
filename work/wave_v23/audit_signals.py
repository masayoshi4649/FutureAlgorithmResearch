"""入力を途中で切り、未来の相手銘柄を改変して方向判定の過去不変性を独立検算する。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

from audit_core import truncate_ready, check_accounting, check_execution_prefix
import engine
import managers
import signals

OUT = Path(__file__).resolve().parent


def source_checks(features: dict) -> dict:
    """機能: 全特徴の解放時刻と原本行が、参照したブロックより後か確認する。

    引数: features (dict)。返り値: 行数と参照順検査要約 (dict)。
    """
    count = 0
    for frame in features.values():
        assert (frame.source_first_seq <= frame.source_last_seq).all()
        assert (frame.source_last_seq < frame.seq).all()
        assert (frame.source_time_s < frame.time_s).all()
        assert (frame.seq.diff().dropna() > 0).all()
        assert (frame.time_s.diff().dropna() > 0).all()
        count += len(frame)
    return dict(特徴行数=count, 解放前のブロックのみ=True, 原本行順不変=True)


def mutate_future(features: dict, inputs: dict, cutoff: float, symbol: str) -> tuple[dict, dict]:
    """機能: 指定銘柄の未来特徴と価格だけを大きく反転した別入力を作る。

    引数: features/inputs (dict)、cutoff (float)、symbol (str)。返り値: 変更後特徴・入力 (tuple[dict,dict])。
    """
    changed_features, changed_inputs = dict(features), dict(inputs)
    for key, frame in features.items():
        if key[1] != symbol:
            continue
        frame = frame.copy()
        future = frame.time_s > cutoff
        for column in ('ofi_signed', 'quote_move_ticks', 'imb1', 'imb5', 'imb10', 'micro_bias',
                       'dflow_near', 'dflow_far', 'pressure_near', 'pressure_far'):
            if column in frame:
                frame.loc[future, column] = -frame.loc[future, column]
        for first, second in [('trade_pos', 'trade_neg'), ('quote_up', 'quote_down'),
                              ('added_bid', 'added_ask'), ('removed_bid', 'removed_ask'),
                              ('refill_bid', 'refill_ask'), ('bid_qty', 'ask_qty')]:
            if first in frame:
                original = frame.loc[future, [first, second]].to_numpy(copy=True)
                frame.loc[future, [first, second]] = original[:, ::-1]
        for column in ('source_mid_last', 'mid'):
            frame.loc[future, column] = 1000000. - frame.loc[future, column]
        for first, second in [('source_bid_last', 'source_ask_last'), ('bid', 'ask')]:
            original = frame.loc[future, [first, second]].to_numpy(copy=True)
            frame.loc[future, [first, second]] = 1000000. - original[:, ::-1]
        changed_features[key] = frame
        ready = {name: value.copy() if isinstance(value, np.ndarray) else value for name, value in inputs[key].items()}
        future_rows = ready['time_s'] > cutoff
        ready['last'][future_rows] = 1000000. - ready['last'][future_rows]
        ready['atr'][future_rows] = 12345.
        changed_inputs[key] = ready
    return changed_features, changed_inputs


def main() -> None:
    """機能: 全方向条件の複数切断、相手の未来改変、代表管理の詳細会計を監査する。

    引数: なし。返り値: なし (None)。入力原本を変更しない。
    """
    all_inputs = pickle.loads((OUT / 'inputs.pkl').read_bytes())
    all_features = pickle.loads((OUT / 'features_depth.pkl').read_bytes())
    specs = signals.catalog()
    prefix_records, peer_records, account_records = [], [], []
    for session in ['2026-09-22_Night', '2026-09-29_Day']:
        inputs = {key: value for key, value in all_inputs.items() if key[0] == session}
        features = {key: value for key, value in all_features.items() if key[0] == session}
        signals.clear_cache()
        full = {spec['id']: signals.build(spec, inputs, features) for spec in specs}
        primary = inputs[(session, 'NK225')]
        for fraction in (.27, .53, .81):
            primary_count = int(len(primary['last']) * fraction)
            cutoff = primary['time_s'][primary_count - 1]
            shortened = {}
            small_features = {}
            for key, ready in inputs.items():
                count = primary_count if key[1] == 'NK225' else np.searchsorted(ready['time_s'], cutoff, side='right')
                shortened[key] = truncate_ready(ready, int(count))
                small_features[key] = features[key].loc[(features[key].seq <= shortened[key]['seq'][-1]) & (features[key].time_s <= shortened[key]['time_s'][-1])].copy()
            signals.clear_cache()
            for spec in specs:
                partial = signals.build(spec, shortened, small_features)
                for key, direction in partial.items():
                    np.testing.assert_array_equal(direction, full[spec['id']][key][:len(direction)], err_msg=f'{spec["id"]} {key} {fraction}')
                    prefix_records.append(dict(信号ID=spec['id'], セッション=session, 銘柄=key[1], 切断行=len(direction), 過去不変=True))
        # ----------------------------------------
        # 相手の原本・板・確定足の未来を同時に改変する。過去の相手値は保持する。
        cutoff = primary['time_s'][int(len(primary['last']) * .53)]
        for peer in ['TOPIX', 'NK225']:
            altered_features, altered_inputs = mutate_future(features, inputs, cutoff, peer)
            original_read = signals.pd.read_csv

            def modified_read(path, *args, **kwargs):
                """機能: 監査対象の未来確定足だけをメモリ上で反転する。

                引数: path (Path|str)、args/kwargs (tuple/dict)。返り値: 変更した表 (DataFrame)。
                """
                frame = original_read(path, *args, **kwargs)
                if Path(path).parent.name == peer:
                    available = pd.to_datetime(frame.time).dt.as_unit('ns').astype('int64').to_numpy(float) / 1e9 + 120.
                    future = available > cutoff
                    for column in ('open', 'high', 'low', 'close'):
                        frame.loc[future, column] = 1000000. - frame.loc[future, column]
                    frame.loc[future, 'volume'] *= 10.
                return frame

            signals.pd.read_csv = modified_read
            try:
                signals.clear_cache()
                for spec in specs:
                    altered = signals.build(spec, altered_inputs, altered_features)
                    for key, ready in inputs.items():
                        count = int(np.searchsorted(ready['time_s'], cutoff, side='right'))
                        np.testing.assert_array_equal(altered[key][:count], full[spec['id']][key][:count], err_msg=f'相手未来改変 {spec["id"]} {peer} {key}')
                    peer_records.append(dict(信号ID=spec['id'], セッション=session, 未来変更銘柄=peer, 両銘柄の過去判定不変=True))
            finally:
                signals.pd.read_csv = original_read
        # ----------------------------------------
        # 順張りと板信号の代表を、管理思想の違う６条件で原本全行検算する。
        signals.clear_cache()
        selected_ids = {'G00', 'G02', 'G08', 'G11', 'G14', 'G18'}
        selected_specs = [specs[1], next(item for item in specs if item['params']['kind'] == 'ofi_peer')]
        for spec in selected_specs:
            directions = full[spec['id']]
            for manager in managers.manager_catalog():
                if manager['id'] not in selected_ids:
                    continue
                for key, ready in inputs.items():
                    config = managers.make_config(manager, key[1], ready)
                    result = engine.run(ready, directions[key], config, detail=True)
                    record = dict(信号ID=spec['id'], 管理ID=manager['id'], セッション=session, 銘柄=key[1])
                    record.update(check_accounting(ready, result, config))
                    record.update(check_execution_prefix(engine, ready, directions[key], config, result))
                    account_records.append(record)
        print(f'{session}: 信号と注文の独立照合合格', flush=True)
    report = dict(合格=True, 条件数=len(specs), 特徴解放監査=source_checks(all_features),
                  途中切断比較件数=len(prefix_records), 未来変更比較件数=len(peer_records),
                  注文詳細検算件数=len(account_records), 信号切断=prefix_records,
                  相手未来変更=peer_records, 詳細会計=account_records,
                  元データと成果は不変=True, 現在API取得数=0,
                  限界='データ期間全体は既読。実装の因果性確認であり、未見期間での利益を証明しない。')
    (OUT / '独立信号と会計監査.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
