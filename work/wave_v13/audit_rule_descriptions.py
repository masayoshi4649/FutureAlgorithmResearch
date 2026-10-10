"""主候補の説明値と固定設定・途中評価の対応を照合する。"""

from pathlib import Path
import json

import pandas as pd

import current_check
import exact_engine

OUT = Path(__file__).resolve().parent


def main() -> None:
    """機能: 主候補と比較候補の説明値、返済済み・未返済の会計を確認する。

    引数: なし。返り値: なし (None)。保存応答だけを読み通信しない。
    """
    frozen = current_check.freeze_check()
    configs = {row['id']: row for row in frozen['selected_configs']}
    expected = {
        'N10_R1_E3_X2_U0': dict(entry_mode='stop', entry_atr=.25, initial_stop_atr=.75,
            trail_atr=2., trail_start_atr=1., signal_multiplier=1, max_legs=1, us_pause=False, max_age_min=2.),
        'P12_R-1_E0_X2_U0': dict(entry_mode='market', entry_atr=0., initial_stop_atr=.75,
            trail_atr=2., trail_start_atr=1., signal_multiplier=-1, max_legs=1, us_pause=False, max_age_min=2.),
        'N03_R-1_A3_U0': dict(entry_mode='limit', entry_atr=.5, initial_stop_atr=1.5,
            trail_atr=None, target_atr=2.5, signal_multiplier=-1, max_legs=1, us_pause=False, max_age_min=10.),
        'P16_R1_E1_X5_U0': dict(entry_mode='trail', entry_atr=.25, initial_stop_atr=1.5,
            trail_atr=2., trail_start_atr=0., weak_width_atr=.5, state_trigger_atr=.5,
            signal_multiplier=1, max_legs=1, us_pause=False, max_age_min=2.)}
    for identifier, values in expected.items():
        for key, value in values.items():
            assert configs[identifier][key] == value, (identifier, key)
    cells = pd.read_csv(OUT / '現在照合_セッション集計.csv')
    trades = json.loads((OUT / '現在照合_全取引.json').read_text(encoding='utf-8'))
    observations = []
    for identifier in expected:
        for symbol in current_check.SYMBOLS:
            rows = [row for row in trades if row['方式'] == identifier and row['銘柄'] == symbol]
            cell = cells[cells['方式'].eq(identifier) & cells['銘柄'].eq(symbol)].iloc[0]
            closed = [row for row in rows if row['返済済み']]
            opened = [row for row in rows if not row['返済済み']]
            assert sum(row['収支円'] for row in closed) == cell['closed_net_yen']
            assert sum(row['収支円'] for row in opened) == cell['open_yen']
            assert cell['closed_net_yen'] + cell['open_yen'] == cell['net_yen']
            assert len(opened) == cell['open_count']
            observations.append(dict(方式=identifier, 銘柄=symbol, 確定収支円=cell['closed_net_yen'],
                含み損益円=cell['open_yen'], 全建玉評価円=cell['net_yen'], 未返済数=len(opened),
                未返済脚=[{key: row[key] for key in ['新規価格', '返済評価価格', '方向', '固定ATR',
                                                     '最終ストップ', '収支円', '新規時刻', '返済評価時刻']}
                            for row in opened]))
    record = dict(合格=True, 条件値照合数=sum(map(len, expected.values())),
                  凍結ファイル数=len(frozen['files_sha256']), 現在照合８セル=observations,
                  原本再取得=0, 説明補足='主候補の条件と機械実行の補足.md')
    (OUT / '主候補の説明値照合.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False))


if __name__ == '__main__':
    main()
