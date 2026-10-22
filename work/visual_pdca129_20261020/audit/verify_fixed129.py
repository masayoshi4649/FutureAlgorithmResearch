"""指定巡の固定源・人工証明・入力・保存測定の指紋を照合する。"""

import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def read(path):
    """
    機能: 保存JSONを読む。
    引数: path(Path)は位置。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    """
    機能: 内容指紋を取得する。
    引数: path(Path)は位置。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    """
    機能: 固定した源と実行開始・会計の一致を確認し、全参照を現在実体と比較する。
    引数: argv[1](str)は巡のフォルダ名。
    返り値: None。数値計算をせず証拠だけ保存する。
    """
    name = sys.argv[1]
    folder = WORK/name
    fixed, results, started, registered = (
        read(folder/file) for file in ("固定計画.json", "全条件の会計.json", "金融実行開始.json", "登録.json"))
    assert registered["returncode"] == 0
    assert fixed["sources"] == results["sources"] == started["sources"]
    assert fixed["configs"] == results["configs"]
    refs = [dict(path=p, sha256=h) for p, h in fixed["sources"].items()]
    refs += fixed["artificial"] + fixed["input_references"] + results["cache"]
    for ref in refs:
        assert sha(ROOT/ref["path"]) == ref["sha256"], ref["path"]
    for ref in fixed["artificial"]:
        proof = read(ROOT/ref["path"])
        assert proof.get("passed", proof.get("全合格")), ref["path"]
    out = dict(passed=True, round=name, references_checked=len(refs),
               fixed_sha256=sha(folder/"固定計画.json"),
               result_sha256=sha(folder/"全条件の会計.json"),
               auditor_sha256=sha(Path(__file__)), financial_replays=0, references=refs)
    target = HERE/(name+"_固定源と人工及び測定指紋の独立照合.json")
    assert not target.exists()
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "references"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
