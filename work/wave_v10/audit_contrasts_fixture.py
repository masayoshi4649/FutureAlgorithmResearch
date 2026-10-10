"""既知の加算効果だけを持つ架空の全条件表で、対応差の集約を手計算照合する。"""

from __future__ import annotations

from itertools import product
import json
from pathlib import Path

import pandas as pd

from audit_contrasts import FULL_SESSIONS, SYMBOLS, calculate


def main() -> None:
    """機能: 両銘柄の尺度を変えた既知差分から、全２２比較の集約・補正を検査する。

    引数: なし。
    返り値: None。架空表による単体監査結果のみを保存する。
    """
    rows = []
    for signal, entry, exit_id, time_id, session, symbol in product(
            range(1, 21), range(8), range(12), range(5), FULL_SESSIONS, SYMBOLS):
        scale = 1 if symbol == "NK225" else 3
        rows.append(dict(方式=f"S{signal:02d}_E{entry:02d}_X{exit_id:02d}_Z{time_id:02d}",
                         セッション=session, 銘柄=symbol, 費用倍ATR収支=float(scale * (entry + exit_id + time_id)),
                         取引数=1, 約定遅延="次行"))
    diagnostics, sessions = calculate(pd.DataFrame(rows))
    for row in diagnostics:
        expected = 2.0 * (int(row["変更"][1:]) - int(row["基準"][1:]))
        assert row["各セッション差"] == [expected] * len(row["対象セッション"])
        assert row["未補正比率"] == (0.5 if row["因子"] == "時間帯" else 2 / 32)
        assert row["全22比較Holm補正比率"] == 1.0
        assert row["片方以上取引あり改善割合"] == float(expected > 0)
        assert row["片方以上取引あり組合せ総数"] == row["対応組合せ総数"]
    output = dict(架空入力行数=len(rows), 手計算一致比較数=len(diagnostics),
                  セッション銘柄別要約数=len(sessions),
                  両銘柄を一つのセッション差へまとめた計算一致=True,
                  全22比較Holm補正一致=True,
                  注意="損益が既知の架空表による集計機能の監査であり、実相場の成績ではない。")
    (Path(__file__).resolve().parent / "対応差分集約単体監査.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("架空の全９６０００行からの２２対応差分が手計算と一致しました。", flush=True)


if __name__ == "__main__":
    main()
