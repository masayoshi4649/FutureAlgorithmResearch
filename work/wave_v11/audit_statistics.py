"""少数既知セッションに対する、選択後の探索用多重比較診断を記録する。"""

from __future__ import annotations

import importlib.util
from itertools import product
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('既存符号反転監査', OUT.parent/'wave_v10/audit_statistics.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)


def max_search_diagnostic(matrix: np.ndarray, ids: list[str]) -> dict:
    """機能: 全候補で同じセッション符号を反転し、最大平均利益の探索基準を得る。

    引数: matrix (ndarray、候補×セッション)、ids (list[str])。
    返り値: dict。片側最大平均の全列挙比率。未見検定を意味しない。
    """
    observed = matrix.mean(axis=1)
    signs = np.array(list(product((-1, 1), repeat=matrix.shape[1])))
    null_maximum = np.max(matrix@signs.T/matrix.shape[1], axis=0)
    winner = int(np.argmax(observed))
    exceed = null_maximum >= observed[winner]-1e-12
    adjusted = np.mean(null_maximum[:, None] >= observed[None, :]-1e-12, axis=0)
    return dict(候補数=len(ids), ブロック数=matrix.shape[1], 符号パターン数=len(signs),
                基準='両銘柄平均の費用倍ATR収支÷設定最大枚数。全候補で同じセッション符号を反転。',
                比較方向='正の平均収支に対する片側。実運用のDD減点選択得点とは異なる。',
                最高平均の方式=ids[winner], 最高平均=float(observed[winner]),
                最大値探索込み比率=float(exceed.mean()), 各符号下の最大平均=null_maximum.tolist(),
                全条件=[dict(方式=key, 平均=float(score), 最大値補正比率=float(ratio))
                         for key, score, ratio in zip(ids, observed, adjusted)])


def main() -> None:
    """機能: ３時間順評価の Holm 診断と５セッション全候補の最大値診断を保存する。

    引数: なし。返り値: None。探索用統計 JSON と簡潔な解説を作成する。
    """
    from audit_results import COMPLETE
    walk = pd.read_csv(OUT/'時間順評価.csv')
    walk['選択方針'] = '共通条件'
    symbol_path = OUT/'銘柄別時間順評価.csv'
    if symbol_path.exists():
        added = pd.read_csv(symbol_path)
        added['選択方針'] = '銘柄別条件・探索後追加'
        walk = pd.concat([walk, added], ignore_index=True)
    walk['比較収支'] = walk['費用倍ATR収支']/walk['設定最大枚数']
    diagnostics = {}
    for labels, group in walk.groupby(['選択方針', '思想'], sort=False):
        name = '／'.join(labels)
        values = group.groupby('セッション').比較収支.mean().reindex(COMPLETE[2:]).to_numpy()
        assert np.isfinite(values).all()
        diagnostics[name] = previous.exact_signflip(values.tolist(), 'two-sided')
    holm = previous.holm_adjust({name:item['未補正比率'] for name,item in diagnostics.items()})
    for name, item in diagnostics.items():
        item['全政策のHolm補正比率'] = holm[name]
    frame = pd.read_csv(OUT/'全条件_セッション集計.csv')
    subset = frame[frame.セッション.isin(COMPLETE)].copy()
    subset['比較収支'] = subset['費用倍ATR収支']/subset['設定最大枚数']
    matrix = subset.pivot_table(index='方式', columns='セッション', values='比較収支', aggfunc='mean').reindex(columns=COMPLETE)
    assert matrix.notna().all().all()
    maximum = max_search_diagnostic(matrix.to_numpy(), matrix.index.to_list())
    separate = subset.pivot_table(index=['方式', '銘柄'], columns='セッション', values='比較収支').reindex(columns=COMPLETE)
    separate_maximum = max_search_diagnostic(separate.to_numpy(), ['／'.join(x) for x in separate.index])
    separate_maximum['基準'] = '銘柄別の費用倍ATR収支÷設定最大枚数。候補と銘柄をまとめて探索し、同じセッション符号を両銘柄へ適用。'
    record = dict(位置付け='結果を選び直さない探索用の補助診断。事前の有意性検定ではない。',
        仮定='セッションごとの共同成績が独立で帰無仮説下に符号対称という強い仮定。銘柄と全候補の同一セッション依存は維持する。',
        限界='全５セッションは過去研究で既知。時間順３段も設計前の完全未見標本ではなく、過去を共有する選択規則である。この比率は継続的な収益性や予測可能性の証明ではない。',
        時間順全政策=diagnostics, 全政策数=len(diagnostics), 完全５セッション全候補探索=maximum,
        完全５セッション銘柄別全候補探索=separate_maximum,
        最小分解能={'３ブロック両側':.25, '５ブロック両側':.0625, '５ブロック片側':.03125})
    (OUT/'独立統計診断.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = ['# 少数セッションの独立統計診断', '',
            'この診断は選択結果を変えない補助資料です。既知５セッションから条件を研究しているため、完全未見の検証としては扱いません。', '',
            '| 選択方針・思想 | 時間順３セッションの費用倍・枚数調整 ATR 平均 | 両側符号反転 | 全政策 Holm 補正 |',
            '| --- | ---: | ---: | ---: |']
    for name, item in diagnostics.items():
        rows.append(f"| {name} | {np.mean(item['各セッション差']):.3f} | {item['未補正比率']:.3f} | {holm[name]:.3f} |")
    rows += ['', '銘柄別条件は共通条件の結果を見た後に追加した探索方針です。６政策の補正比率も、この方針追加そのものや過去研究全体の選択を補正できません。', '',
             f"完全５セッションの {len(matrix):,} 条件を一緒に符号反転した最大平均収支の片側探索比率は {maximum['最大値探索込み比率']:.4f} です。全候補で同じセッション符号を反転し、NK225 と TOPIX の組を保持しています。候補ごとの取引を独立な標本とは数えていません。", '',
             f"銘柄別に有利な候補を選ぶ探索も含めた {len(separate):,} 個の『条件×銘柄』の最大平均診断は {separate_maximum['最大値探索込み比率']:.4f} です。銘柄ごとに独立な符号を与えず、同じセッションの NK225 と TOPIX を一緒に反転させます。", '',
             '時間順３ブロックの両側比率は、全て同じ方向でも最小 0.25。５ブロックでも最小 0.0625 です。上の片側最大値診断は利益の正方向を調べる別の診断で、最小分解能は 1/32 です。', '',
             'セッションの独立性・符号対称性は検証できません。夜間は２本のみであり、米国開始時間による優劣の統計的断定にも使えません。多重候補を考慮しても、既知データを繰り返し見た設計変更や未知の市場への外挿は補正できません。', '',
             '根拠: [White (2000), A Reality Check for Data Snooping](https://users.ssc.wisc.edu/~behansen/718/White2000.pdf) はモデル探索を含めて比較する必要性を示します。今回の符号反転は同論文の bootstrap を再現したものではありません。[Bailey ほか, The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) も、既知の保留標本と多重探索による評価の歪みを扱っています。']
    (OUT/'独立統計診断.md').write_text('\n'.join(rows)+'\n', encoding='utf-8')
    print(json.dumps(dict(時間順Holm=holm, 最大値探索込み比率=maximum['最大値探索込み比率'],
                          銘柄別最大値探索込み比率=separate_maximum['最大値探索込み比率']), ensure_ascii=False))


if __name__ == '__main__':
    main()
