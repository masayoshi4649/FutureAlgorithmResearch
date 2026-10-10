"""取得済み現在データへ追加選択器を適用する、未見検証ではない事後診断。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import numpy as np

from current_check import partial_accounting
import engine
import learned_flow
import managers
import selector_past
import selector_signals
import signals

OUT = Path(__file__).resolve().parent
LIVE = OUT / 'live'
DEST = LIVE / 'selector_diagnostic'


def main() -> None:
    """機能: 保存済みナイトを再取得せず、上位選択器５候補の確定・含みを再生する。

    引数: なし。返り値: なし (None)。既存の現在照合と旧研究記録を書き換えない。
    """
    DEST.mkdir(exist_ok=True)
    selection = json.loads((OUT / '選択統合の結果.json').read_text(encoding='utf-8'))
    specifications = {item['id']: item for item in json.loads((OUT / '選択統合の全条件.json').read_text(encoding='utf-8'))}
    source = json.loads((LIVE / 'current_result.json').read_text(encoding='utf-8'))
    inputs = pickle.loads((OUT / 'inputs.pkl').read_bytes())
    features = pickle.loads((OUT / 'features_depth.pkl').read_bytes())
    directions = pickle.loads((OUT / 'directions.pkl').read_bytes())
    live_inputs = pickle.loads((LIVE / 'inputs.pkl').read_bytes())
    live_features = pickle.loads((LIVE / 'features_depth.pkl').read_bytes())
    combined_inputs, combined_features = {**inputs, **live_inputs}, {**features, **live_features}
    manifest = dict(実行時刻=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 最終候補=selection['finalists'],
                    元取得締切=source['共通締切'], 追加取得回数=0,
                    位置付け='現在セッションの結果を既に見た後で追加した選択器。保存済み同じ25分の事後診断であり未見検証ではない。',
                    SHA256={name: hashlib.sha256((OUT / name).read_bytes()).hexdigest() for name in
                            ['selector_signals.py', 'selector_past.py', 'signals.py', 'engine.py', 'managers.py', 'learned_flow.py']})
    (DEST / '診断条件.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    original_root, original_out = signals.ROOT, learned_flow.OUT
    try:
        signals.ROOT = LIVE
        signals.clear_cache()
        live_directions = {spec['id']: signals.build(spec, live_inputs, live_features) for spec in signals.catalog()}
        learned_flow.OUT = DEST
        _, learned = learned_flow.build_all(combined_inputs, combined_features)
        for identifier, values in learned.items():
            for key in inputs:
                np.testing.assert_array_equal(values[key], directions[identifier][key])
            live_directions[identifier] = {key: values[key] for key in live_inputs}
        combined_directions = {identifier: {**values, **live_directions[identifier]} for identifier, values in directions.items()}
        _, market_values, market_events = selector_signals.build_all(live_inputs, live_features, live_directions)
        _, past_values, past_events = selector_past.build_all(combined_inputs, combined_features, combined_directions)
        saved_past = pickle.loads((OUT / 'selector_past_directions.pkl').read_bytes())
        for identifier, values in saved_past.items():
            for key, value in values.items():
                np.testing.assert_array_equal(value, past_values[identifier][key])
        selector_values = {**market_values, **past_values}
        results, ledgers = [], {}
        for identifier in selection['finalists']:
            spec = specifications[identifier]
            for key, ready in live_inputs.items():
                config = managers.make_config(spec['manager'], key[1], ready)
                direction = selector_values[spec['signal_id']][key]
                replay = engine.run(ready, direction, config, detail=True)
                row = dict(手法ID=identifier, 手法名=spec['name'], セッション=key[0], 銘柄=key[1])
                row.update(partial_accounting(ready, replay, config))
                row['信号買い行数'] = int((direction > 0).sum())
                row['信号売り行数'] = int((direction < 0).sum())
                results.append(row)
                ledgers[(identifier, key[1])] = dict(config=config, **replay)
        current_sessions = {key[0] for key in live_inputs}
        picked_events = dict(市場状態の選択=market_events,
                             完了実績の選択=[event for event in past_events if event['適用セッション'] in current_sessions])
        (DEST / '選択履歴.json').write_text(json.dumps(picked_events, ensure_ascii=False, indent=2), encoding='utf-8')
        (DEST / 'replay.pkl').write_bytes(pickle.dumps(ledgers, pickle.HIGHEST_PROTOCOL))
        record = dict(合格=True, 主候補=selection['primary'], 対象=selection['finalists'],
                      セッション=source['セッション'], 共通締切=source['共通締切'], セッション途中=True,
                      追加API取得回数=0, 既存入力と既存結果不変=True, 過去学習と選択の既知13区間不変=True,
                      未見検証ではない=True, 位置付け=manifest['位置付け'], 結果=results)
        (DEST / 'current_result.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(record, ensure_ascii=False, indent=2))
    finally:
        signals.ROOT, learned_flow.OUT = original_root, original_out
        signals.clear_cache()


if __name__ == '__main__':
    main()
