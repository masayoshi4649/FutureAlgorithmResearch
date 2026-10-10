"""観測解析の現在情報と将来ラベルの分離を、独立に点検する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent/'theory/analyze.py'
SPEC = importlib.util.spec_from_file_location('analysis_independent_review', SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def main() -> None:
    """機能: 実データ6口座の現在観測を未来切断・改変し、固定学習を確認する。

    引数: なし。返り値: なし(None)。結果は独立監査領域だけに保存する。
    """
    frames = pickle.loads((HERE.parent/'measurement/features.pkl').read_bytes())
    ready = MODULE.load_ready()
    checks = []
    keys = [(session, symbol) for session in ('2026-09-21_Day', '2026-09-24_Day', '2026-10-06_Day')
            for symbol in ('TOPIX', 'NK225')]
    for key in keys:
        frame = frames[key]
        full, labels, quality = MODULE.build_account(frame, ready[key])
        assert len(full) > 0
        for fraction in (.35, .70):
            cutoff = float(frame.time_s.iloc[int(len(frame)*fraction)])
            cutframe = frame.loc[frame.time_s <= cutoff].copy()
            partial, _, _ = MODULE.build_account(cutframe, ready[key])
            # 現在価格が古くなるまで切断後にも観測起点が作られ得るため、既知範囲のみ比較する。
            known = full.loc[full.time_s <= cutoff].reset_index(drop=True)
            got = partial.loc[partial.time_s <= cutoff].reset_index(drop=True)
            pd.testing.assert_frame_equal(got, known, check_exact=True)
            changed = frame.copy()
            future = changed.time_s > cutoff
            for col in ('bid', 'ask', 'mid', 'last', 'atr', 'exec_buy', 'exec_sell',
                        'noexec_ask_remove', 'noexec_bid_remove', 'supply_bid_near', 'supply_ask_near'):
                changed.loc[future, col] = changed.loc[future, col]*1.5+17.
            altered, _, _ = MODULE.build_account(changed, ready[key])
            pd.testing.assert_frame_equal(altered.loc[altered.time_s <= cutoff].reset_index(drop=True), known, check_exact=True)
            checks.append(dict(口座=list(key), 切断時刻=cutoff, 一致観測数=len(known), 未来切断=True, 未来改変=True))
        # ----------------------------------------
        # 将来端点を原本公開列のループで求め、分析ラベルと別計算で照合する。
        manual = 0
        for index in np.linspace(0, len(full)-1, min(12, len(full)), dtype=int):
            observation, label = full.iloc[index], labels.iloc[index]
            for horizon in MODULE.HORIZONS:
                value = label[f'y{horizon}']
                if not np.isfinite(value):
                    continue
                eligible = frame.loc[frame.time_s <= observation.time_s+horizon]
                final = eligible.iloc[-1]
                expected = (final.mid-observation.mid)/observation.atr
                assert value == expected
                manual += 1
        checks.append(dict(口座=list(key), 将来端点別計算一致件数=manual,
                           現在特徴にy列なし=not any(col.startswith('y') for col in full.columns)))

    # ----------------------------------------
    # 後半の結果だけを変更しても、先頭期間の係数と分位境界が変わらない。
    observations = pickle.loads((HERE.parent/'theory/観測.pkl').read_bytes())
    labels = pickle.loads((HERE.parent/'theory/将来ラベル.pkl').read_bytes())
    actual = json.loads((HERE.parent/'theory/観測結果.json').read_text(encoding='utf8'))
    changed_labels = labels.copy()
    training_sessions = set(observations.loc[observations.period == MODULE.PERIODS[0], 'session'])
    later = ~changed_labels.session.isin(training_sessions)
    for col in changed_labels:
        if col.startswith(('y', 'up', 'down')):
            finite = later & np.isfinite(changed_labels[col])
            changed_labels.loc[finite, col] += 173.
    altered_result = MODULE.analyze_joint(observations, changed_labels)
    for key in ('分位境界', '価格対照'):
        assert actual[key] == altered_result[key], key
    baseline_train = [item for item in actual['指標別'] if item['period'] == MODULE.PERIODS[0]]
    altered_train = [item for item in altered_result['指標別'] if item['period'] == MODULE.PERIODS[0]]
    assert baseline_train == altered_train
    result = dict(合格=True, 解析コードSHA256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                  実データ未来監査=checks, 後半ラベル変更でも先頭係数と分位は固定=True,
                  後半ラベル変更でも先頭集計は不変=True,
                  注意='特徴量と学習の未来混入の監査。市場の因果や将来の利益を証明するものではない。')
    (HERE/'観測解析の独立因果監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
