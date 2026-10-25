"""旧47場の原本指紋を世代別の保存証拠から集め、移動後の全素材と照合する。"""

import re
from pathlib import Path

from prepare140 import ROOT, HERE, DATA, read, save, digest


SOURCES = (
    "work/wave_v85/prepared/入力準備の事前固定.json",
    "work/wave_v106/e01_reference/prepared/追加素材抽出前の固定.json",
    "work/stability119_20261017/v6_resume/原本の一回複写履歴.json",
    "work/stability124_20261019/追加原本入力目録.json",
    "work/stability126_20261019/update_20261020/追加二場の非金融入力準備.json",
    "work/update132_20261021/inputs_v1/input_manifest.json",
    "work/tranche139_20261022/extra_inputs/input_manifest.json",
    "work/update134_20261022/inputs/input_manifest.json",
)
PATTERN = re.compile(r"^(book|candle_1min|candle_5min)/(NK225|TOPIX)/(\d{4}-\d{2}-\d{2}_(?:Day|Night))\.(?:jsonl|csv)$")


def collect():
    """
    機能: 旧原本の期待指紋を原登録と非金融準備履歴から取得する。
    引数: なし。
    返り値: tuple[dict,list]は旧パス別の期待指紋と証拠資料の指紋一覧。
    """
    expected, proofs = {}, []

    def add(path, sha, source):
        """
        機能: 正式な旧原本名だけを期待指紋へ登録する。
        引数: path/sha/source(str)は原本名・指紋・証拠位置。
        返り値: None。証拠間の不一致は停止する。
        """
        path = path.replace("\\", "/")
        if not PATTERN.fullmatch(path) or not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
            return
        if path in expected:
            assert expected[path]["sha256"] == sha, (path, expected[path], sha)
            if source not in expected[path]["evidence"]:
                expected[path]["evidence"].append(source)
        else:
            expected[path] = dict(sha256=sha, evidence=[source])

    def walk(value, source):
        """
        機能: 世代別JSONの辞書形式と行形式から原本証拠だけを拾う。
        引数: value(object)、source(str)はJSON部分木と証拠位置。
        返り値: None。
        """
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, str):
                    add(key, item, source)
            if "kind" in value and "symbol" in value and "session" in value:
                suffix = ".jsonl" if value["kind"] == "book" else ".csv"
                name = f"{value['kind']}/{value['symbol']}/{value['session']}{suffix}"
                sha = value.get("source_sha256") or value.get("SHA256") or value.get("sha256")
                if sha:
                    add(name, sha, source)
            for item in value.values():
                walk(item, source)
        elif isinstance(value, list):
            for item in value:
                walk(item, source)

    for relative in SOURCES:
        path = ROOT / relative
        proofs.append(dict(path=relative, sha256=digest(path)))
        walk(read(path), relative)
    return expected, proofs


def main():
    """
    機能: 移動後の旧47場・282素材を実読し、原本と保存packetの利用資格を確認する。
    引数: なし。
    返り値: None。照合不一致も報告に残し、成功と偽らない。金融再生は行わない。
    """
    known = read(HERE / "known_manifest140.json")
    expected, proofs = collect()
    wanted = {f"{kind}/{symbol}/{scene}{'.jsonl' if kind == 'book' else '.csv'}"
              for scene in known["sessions"] for symbol in ("NK225", "TOPIX")
              for kind in ("book", "candle_1min", "candle_5min")}
    missing = sorted(wanted - set(expected))
    assert not missing, missing
    rows = []
    for index, relative in enumerate(sorted(wanted)):
        match = PATTERN.fullmatch(relative)
        kind, symbol, scene = match.groups()
        actual_path = DATA / "future" / symbol / scene / ("book.jsonl" if kind == "book" else kind + ".csv")
        before = actual_path.stat()
        actual = digest(actual_path)
        after = actual_path.stat()
        assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        evidence = expected[relative]
        rows.append(dict(legacy_path=relative, path=actual_path.as_posix(), sha256=actual,
                         expected_sha256=evidence["sha256"], evidence=evidence["evidence"],
                         bytes=after.st_size, mtime_ns=after.st_mtime_ns, matches=actual == evidence["sha256"]))
        if index % 20 == 0:
            print("移動原本の内容照合", index + 1, "/", len(wanted), flush=True)
    mismatches = [row for row in rows if not row["matches"]]
    save(HERE / "moved_materials140.json", dict(passed=not mismatches, materials=rows,
         checked_materials=len(rows), checked_sessions=len(known["sessions"]), evidence=proofs,
         mismatches=mismatches, financial_replays=0, API=0, real_orders=0,
         scope="旧47場の原板・1分足・5分足すべてを移動先から実読し、当時固定されたSHA256と照合。"))
    print("原本照合完了", len(rows), "素材 / 不一致", len(mismatches), flush=True)


if __name__ == "__main__":
    main()
