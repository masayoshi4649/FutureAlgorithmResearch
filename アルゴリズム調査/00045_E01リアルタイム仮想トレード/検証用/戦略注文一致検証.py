"""保存実データで、逐次E01注文器と過去402件の注文台帳を照合する。

この検証だけは、プロジェクト内のworkにある旧研究コード・保存入力・台帳と、
candle_1minの保存足に依存する。NumPy、pandas、Numba等の研究環境も必要。
通常の仮想運転からは読み込まれず、外部市場データの取得や実注文は行わない。
結果は00045_E01リアルタイム仮想トレード/戦略注文一致検証.jsonへ固定保存する。

実行例:
    python -X utf8 .\検証用\戦略注文一致検証.py
"""

from __future__ import annotations

import json
from pathlib import Path
import sys


TASK_ROOT = Path(__file__).resolve().parents[1]
RESULT = TASK_ROOT / "戦略注文一致検証.json"


def main() -> None:
    """機能: 検証専用の旧入力再生を実行し、全注文の一致証拠を保存する。

    引数: なし。返り値: なし(None)。不一致は例外で停止し成功資料を上書きしない。
    """
    sys.path.insert(0, str(TASK_ROOT))
    from papertrade.test_strategy import historical_parity

    results = historical_parity()
    value = {"全合格": True, "results": results}
    temporary = RESULT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(RESULT)
    print("照合完了: " + str(RESULT))


if __name__ == "__main__":
    main()
