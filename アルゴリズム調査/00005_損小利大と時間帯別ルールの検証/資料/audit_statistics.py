"""少数セッションの対応差に対する、独立した探索用統計診断を提供する。"""

from __future__ import annotations

from itertools import product
import json
import math
from pathlib import Path


def exact_signflip(differences: list[float], alternative: str = "two-sided") -> dict:
    """機能: 対応するセッション差の符号を全列挙し、帰無分布での比率を計算する。

    引数: differences (list[float]) は銘柄をまとめた各セッションの差、
        alternative (str) は two-sided または greater。
    返り値: dict。観測差・有効ブロック数・全列挙数・未補正比率と注意事項。
    """
    if alternative not in {"two-sided", "greater"}:
        raise ValueError("比較方向は two-sided または greater を指定してください。")
    values = [float(value) for value in differences]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("セッション差に欠測値または無限大が含まれています。")
    nonzero = [value for value in values if value != 0.0]
    if len(nonzero) > 20:
        raise ValueError("全列挙は２０有効ブロック以下に限定します。")
    observed = sum(nonzero)
    magnitude = sum(abs(value) for value in nonzero)
    tolerance = 1e-12 * max(1.0, magnitude)
    count = 0
    total = 2 ** len(nonzero)
    for signs in product((-1, 1), repeat=len(nonzero)):
        statistic = sum(sign * value for sign, value in zip(signs, nonzero))
        if alternative == "two-sided":
            count += abs(statistic) >= abs(observed) - tolerance
        else:
            count += statistic >= observed - tolerance
    return {
        "各セッション差": values,
        "セッション数": len(values),
        "差が非ゼロのセッション数": len(nonzero),
        "差合計": observed,
        "比較方向": alternative,
        "全符号パターン数": total,
        "該当パターン数": count,
        "未補正比率": count / total,
        "解釈": "セッションの独立性と帰無仮説下の対称性を仮定した探索診断。既知データに基づく設計の影響は補正しない。",
    }


def holm_adjust(values: dict[str, float]) -> dict[str, float]:
    """機能: 事前に列挙した全比較の比率に Holm の段階的補正を適用する。

    引数: values (dict[str, float]) は比較識別子と未補正比率の対応。
    返り値: dict[str, float]。入力の識別子順を保つ補正済み比率。
    """
    if not all(math.isfinite(value) and 0 <= value <= 1 for value in values.values()):
        raise ValueError("比率は０以上１以下の有限値を指定してください。")
    ranked = sorted(values.items(), key=lambda item: (item[1], item[0]))
    adjusted = {}
    previous = 0.0
    for index, (key, value) in enumerate(ranked):
        previous = max(previous, min(1.0, value * (len(ranked) - index)))
        adjusted[key] = previous
    return {key: adjusted[key] for key in values}


def main() -> None:
    """機能: 少数標本の既知の全列挙値と補正の手計算を照合する。

    引数: なし。
    返り値: None。独立した統計計算の単体監査記録を同じフォルダに保存する。
    """
    cases = [
        ([1, 1, 1, 1, 1], "greater", 1 / 32),
        ([1, 1, 1, 1, 1], "two-sided", 2 / 32),
        ([1, 1, 1], "greater", 1 / 8),
        ([1, 1], "greater", 1 / 4),
        ([1, -1], "two-sided", 1.0),
        ([0, 0], "greater", 1.0),
        ([1, 0, 1], "greater", 1 / 4),
    ]
    results = []
    for differences, alternative, expected in cases:
        result = exact_signflip(differences, alternative)
        assert result["未補正比率"] == expected
        results.append(result)

    # ----------------------------------------
    # 同率や入力順の変更でも補正値の大小関係が壊れないことを確認する。
    original = {"比較甲": 0.03, "比較乙": 0.08, "比較丙": 0.03}
    assert holm_adjust(original) == {"比較甲": 0.09, "比較乙": 0.09, "比較丙": 0.09}
    assert holm_adjust({}) == {}
    output = {
        "符号反転の手計算一致件数": len(results),
        "照合": results,
        "多重比較補正の手計算一致": True,
        "５セッション全て同符号でも両側最小値": 2 / 32,
        "時間順評価３セッションの片側最小値": 1 / 8,
        "注意": "この単体監査は損益の有意性を評価した結果ではない。",
    }
    path = Path(__file__).resolve().parent / "統計診断単体監査.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("符号反転の全列挙７例と多重比較補正の手計算が一致しました。", flush=True)


if __name__ == "__main__":
    main()
