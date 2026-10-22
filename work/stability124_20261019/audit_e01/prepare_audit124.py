"""既監査の保存会計算術だけを独立所有し、金融実行前に同値性を固定する。"""

import ast
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / "work/stability119_20261017/v6_resume/audit_result"
NAMES = ("fee", "compare", "reconstruct", "metrics")


def main() -> None:
    """
    機能: 旧119h会計関数の構文同一コピーと、1020人工検査の委譲根拠を保存する。
    引数: なし。
    返り値: None。市場・新結果・新入力・新台帳を読まない。
    """
    source_path = OLD / "audit_result_v6_resume.py"
    original = source_path.read_bytes()
    proof_path = OLD / "h保存監査と旧1020人工算術の同一拘束.json"
    proof_raw = proof_path.read_bytes()
    proof = json.loads(proof_raw)
    assert proof["全合格"] and proof["監査源SHA256"] == hashlib.sha256(original).hexdigest()
    artificial_path = Path(proof["旧1020人工委譲"]["path"])
    artificial_raw = artificial_path.read_bytes()
    assert hashlib.sha256(artificial_raw).hexdigest() == proof["旧1020人工委譲"]["SHA256"]
    artificial = json.loads(artificial_raw)
    assert artificial["全合格"] and artificial["検査数"] == 1020
    # ----------------------------------------
    header = '''"""旧119hの独立保存会計四関数だけを、構文不変で所有する。"""

from decimal import Decimal, ROUND_FLOOR

import hashlib
import numpy as np


MULTIPLIERS = {"TOPIX": 1000., "NK225": 10.}
FEES = {"TOPIX": "41.8", "NK225": "11"}
CAPS = {"TOPIX": 10, "NK225": 20}


class ArithmeticChecks:
    """独立会計の有限比較と検査件数だけを保持する。"""

    def __init__(self) -> None:
        """
        機能: 独立検査件数をゼロで初期化する。
        引数: なし。
        返り値: None。
        """
        self.CHECKS = 0

    def check(self, condition: bool, note: str) -> None:
        """
        機能: 独立期待値の一致を検査する。
        引数: condition (bool) 条件、note (str) 検査内容。
        返り値: None。
        """
        assert bool(condition), note
        self.CHECKS += 1

    def near(self, actual: object, expected: object, note: str) -> None:
        """
        機能: 未知と有限値を分け、旧検査と同じ許容差で比較する。
        引数: actual/expected (object) 比較対象、note (str) 検査内容。
        返り値: None。
        """
        if actual is None or expected is None:
            self.check(actual is None and expected is None, note)
        else:
            self.check(np.allclose(actual, expected, atol=1e-5, rtol=1e-10, equal_nan=True), note)

    def sha(self, payload: bytes) -> str:
        """
        機能: 所有資料の同一性を求める。
        引数: payload (bytes) 内容。
        返り値: str SHA256。
        """
        return hashlib.sha256(payload).hexdigest()


audit = ArithmeticChecks()


'''
    text = original.decode("utf-8")
    tree = ast.parse(text)
    functions = {item.name: item for item in tree.body if isinstance(item, ast.FunctionDef)}
    target = HERE / "accounting_source.py"
    content = header + "\n\n\n".join(ast.get_source_segment(text, functions[name]) for name in NAMES) + "\n"
    if target.exists():
        assert target.read_bytes() == content.encode("utf-8"), "既存の監査算術を変更しない"
    else:
        target.write_text(content, encoding="utf-8", newline="\n")
    copied = {item.name: item for item in ast.parse(content).body if isinstance(item, ast.FunctionDef)}
    for name in NAMES:
        assert ast.dump(copied[name], include_attributes=False) == ast.dump(functions[name], include_attributes=False)
    result = {"passed": True, "原会計源": {"path": source_path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(original).hexdigest()}, "旧h同一拘束": {"path": proof_path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(proof_raw).hexdigest()}, "旧1020人工": {"path": artificial_path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(artificial_raw).hexdigest()}, "accounting_source_sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "構文不変関数": list(NAMES), "補助比較": "旧saved_accounting.check/near/shaと同じ有限比較と許容差。売買source importなし。", "金融再生": 0, "原市場": 0, "新保存結果": 0, "新保存入力": 0, "新保存台帳": 0}
    output = HERE / "独立会計算術の旧人工への拘束.json"
    raw = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if output.exists():
        assert output.read_bytes() == raw
    else:
        output.write_bytes(raw)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
