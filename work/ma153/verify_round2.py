"""第二巡の登録成功と固定資料を確認する。金融再生は行わない。"""

import json
from pathlib import Path
from verify153 import digest, HERE, ROOT


def main():
    """追加8条件の内容指紋と原資料を再確認する。

    引数: なし。返り値: None。不一致時は追加再生へ進まない。
    """
    folder = HERE / "round2"
    receipt = json.loads((folder / "登録受領153r2.json").read_text(encoding="utf-8"))
    assert receipt["registered"] and receipt["returncode"] == 0
    for ref in [receipt["plan"], receipt["implementation"], *receipt["inputs"], *receipt["sources"]]:
        path = ROOT / ref["path"]
        assert path.stat().st_size == ref["bytes"] and digest(path) == ref["sha256"], str(path)
    first = json.loads((HERE / "登録受領153.json").read_text(encoding="utf-8"))
    for ref in [first["plan"], first["implementation"], *first["sources"]]:
        assert digest(ROOT / ref["path"]) == ref["sha256"], ref["path"]
    manifest = json.loads((HERE / "data/入力目録153.json").read_text(encoding="utf-8"))
    originals = {ref["path"]: ref for scene in manifest["sessions"] for ref in scene["fingerprints"]}
    for name, ref in originals.items():
        source = Path(name)
        before = source.stat()
        assert digest(source) == ref["sha256"], name
        after = source.stat()
        assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    record = {"registered": True, "first_round_unchanged": True, "second_implementation_matches": True, "originals_match": len(originals), "financial_replays": 0}
    (folder / "再生前指紋確認153r2.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
