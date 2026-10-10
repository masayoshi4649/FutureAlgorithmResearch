"""最悪方式の選択を独立集計と未来改変により検証する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import selection

OUT = Path(__file__).resolve().parent


def main() -> None:
    """機能: 全選択を過去だけから独立集計し、未来改変の不変性を確認する。

    引数: なし。返り値: なし (None)。
    """
    base = pd.read_csv(OUT.parent/'wave_v11'/'全条件_セッション集計.csv')
    own = pd.read_csv(OUT/'監査_独立反転集計.csv')
    midpoint = own[['方式', 'セッション', '銘柄', '元値動き円']].rename(columns={'元値動き円': '元mid値動き益円'})
    base = base.merge(midpoint, on=['方式', 'セッション', '銘柄'], how='left', validate='one_to_one')
    base['元mid値動き益円'] = base['元mid値動き益円'].fillna(0)
    choices = json.loads((OUT/'反転_全選択記録.json').read_text(encoding='utf-8'))
    checked = 0
    for choice in choices:
        symbols = selection.SYMBOLS if choice['対象'] == '両銘柄' else [choice['対象']]
        use = base[base.セッション.isin(choice['学習']) & base.銘柄.isin(symbols)]
        if choice['思想'] != '全方式':
            use = use[use.思想 == choice['思想']]
        counts = use.pivot_table(index='方式', columns='銘柄', values='取引数', aggfunc='sum', fill_value=0)
        eligible = counts.index[(counts.reindex(columns=symbols, fill_value=0) >= 1).all(axis=1)]
        use = use[use.方式.isin(eligible)].copy()
        use['独立得点'] = use[choice['選択列']]
        if choice['枚数上限換算']:
            use['独立得点'] /= use.設定最大枚数
        scores = use.groupby('方式').独立得点.sum().sort_index().sort_values(kind='stable')
        assert scores.index[0] == choice['選択']['方式']
        assert np.isclose(scores.iloc[0], choice['選択']['得点'])
        assert len(scores) == choice['候補数']
        checked += 1
    # ----------------------------------------
    mutations = 0
    for size in (2, 3, 4):
        train = selection.COMPLETE[:size]
        for target in ('両銘柄', 'NK225'):
            changed = base.copy()
            outside = ~changed.セッション.isin(train)
            if target == 'NK225':
                outside |= changed.銘柄 != 'NK225'
            changed.loc[outside, ['収支円', '元mid値動き益円']] = 1e30
            changed.loc[outside, '取引数'] = 0
            for field, normalize in [('収支円', True), ('収支円', False), ('元mid値動き益円', True)]:
                expected = selection.choose_worst(base, train, target, '全方式', field, normalize)
                actual = selection.choose_worst(changed, train, target, '全方式', field, normalize)
                assert actual == expected
                mutations += 1
    # ----------------------------------------
    source = pd.read_csv(OUT/'反転_全条件セッション集計.csv')
    aggregate_count = 0
    fields = [prefix+field for prefix in ('元', '理論反転', '容量反転', '次行反転')
              for field in ('取引数', '未返済数', '利益円', '損失円', '収支円', '評価損益円',
                            '総評価円', '費用倍収支円', '費用倍総評価円')]
    for filename, fitted in [('反転_時間順選択評価.csv', False), ('反転_５完全探索代表.csv', True),
                              ('反転_既知ナイト00時02分参考.csv', False)]:
        table = pd.read_csv(OUT/filename)
        for record in table.to_dict('records'):
            symbols = selection.SYMBOLS if record['対象'] == '両銘柄' else [record['対象']]
            sessions = selection.COMPLETE if fitted else [record['評価セッション']]
            part = source[(source.方式 == record['方式']) & source.銘柄.isin(symbols) & source.セッション.isin(sessions)]
            for name in fields:
                assert np.isclose(part[name].sum(), record[name]), (filename, record['方式'], name)
                aggregate_count += 1
            for prefix in ('元', '理論反転', '容量反転', '次行反転'):
                for metric in ('収支円', '費用倍収支円', '総評価円'):
                    value = (part[prefix+metric]/part.設定最大枚数).sum()
                    assert np.isclose(value, record[prefix+'設定上限換算'+metric])
                    aggregate_count += 1
    tests = pd.read_csv(OUT/'反転_時間順選択評価.csv')
    summary = pd.read_csv(OUT/'反転_選択方針要約.csv')
    for record in summary.to_dict('records'):
        part = tests[(tests.選び方 == record['選び方']) & (tests.対象 == record['対象']) & (tests.思想 == record['思想'])]
        assert len(part) == 3
        for name in fields:
            assert np.isclose(part[name].sum(), record[name])
            aggregate_count += 1
    report = dict(独立最悪選択照合数=checked, 未来または他銘柄の改変比較数=mutations,
                  時間順探索代表と方針要約の照合値数=aggregate_count,
                  注記='独立mid分解の元値動きは未返済評価込み。選択に使う完全セッションは全返済済み。',
                  選択コードSHA256=hashlib.sha256((OUT/'selection.py').read_bytes()).hexdigest(), 合格=True)
    (OUT/'最悪方式選択の独立監査.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
