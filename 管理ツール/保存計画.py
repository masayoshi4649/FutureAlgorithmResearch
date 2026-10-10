"""大量データの保存計画を作り、直接登録する資料と圧縮する資料を列挙する。"""

import argparse
import collections
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess

上限 = 40 * 1024 * 1024
直接拡張子 = {".py", ".ps1", ".go", ".js", ".mjs", ".bat", ".cmd", ".sh", ".md", ".html", ".css", ".yaml", ".yml", ".toml"}
生成拡張子 = {".pyc", ".pyo", ".nbc", ".nbi"}
実行拡張子 = {".exe", ".dll", ".so", ".dylib", ".test"}


def 一覧取得(ルート):
    """
    機能: Gitの対象とローカルの作業データを読み取り、保存対象を列挙する。
    引数: ルート (Path) はリポジトリの絶対パス。
    返り値: tuple[list[str], list[dict]] は候補パスと対象外フォルダの明細。
    """
    結果 = set()
    for 引数 in (["git", "ls-files", "-z"], ["git", "ls-files", "--others", "--exclude-standard", "-z"]):
        出力 = subprocess.check_output(引数, cwd=ルート)
        結果.update(出力.decode("utf-8").split("\0"))
    結果.discard("")
    以前 = subprocess.run(["git", "show", "HEAD:保存データ/保存計画.json"], cwd=ルート, capture_output=True)
    if 以前.returncode == 0:
        以前の計画 = json.loads(以前.stdout.decode("utf-8"))
        結果.update(以前の計画.get("direct_paths", []))
        for 群 in 以前の計画.get("groups", []):
            for 名 in 群["paths"]:
                if not (ルート / 名).is_file():
                    raise ValueError(f"保存済みの原本がありません。復元してから計画を更新してください: {名}")
                結果.add(名)
    対象外 = []
    除外根 = {".playwright-mcp"}
    for 起点 in ("work", "book", "candle_1min", "candle_5min"):
        if not (ルート / 起点).exists():
            continue
        for 現在, ディレクトリ, ファイル in os.walk(ルート / 起点):
            パス = Path(現在)
            相対 = パス.relative_to(ルート).as_posix()
            理由 = None
            if "Local State" in ファイル and "Default" in ディレクトリ:
                理由 = "ブラウザのCookie・履歴・実行用プロファイル"
            elif "pyvenv.cfg" in ファイル:
                理由 = "再作成できるPython仮想環境"
            elif パス.name == "__pycache__":
                理由 = "再生成できるコンパイル済みキャッシュ"
            if 理由:
                除外根.add(相対)
                明細 = {"path": 相対, "reason": 理由}
                if "pyvenv.cfg" in ファイル:
                    配布 = importlib.metadata.distributions(path=[str(パス / "Lib" / "site-packages")])
                    明細["packages"] = sorted(f"{項.metadata['Name']}=={項.version}" for 項 in 配布)
                対象外.append(明細)
                ディレクトリ.clear()
                continue
            ディレクトリ[:] = [名 for 名 in ディレクトリ if 名 not in {".git", "node_modules"}]
            結果.update((パス / 名).relative_to(ルート).as_posix() for 名 in ファイル)

    # ----------------------------------------
    集計 = collections.defaultdict(lambda: {"files": 0, "bytes": 0})
    採用 = []
    for 名 in sorted(結果):
        パス = Path(名)
        根 = next((祖.as_posix() for 祖 in (パス, *パス.parents) if 祖.as_posix() in 除外根), None)
        if 名.startswith(("保存データ/", "管理ツール/", ".git/")):
            continue
        if 根 or パス.suffix in 生成拡張子 or パス.suffix in 実行拡張子 or パス.name == ".env":
            分類 = 根 or "コンパイル済みキャッシュ・実行ファイル・環境設定"
            集計[分類]["files"] += 1
            if (ルート / パス).is_file():
                集計[分類]["bytes"] += (ルート / パス).stat().st_size
            continue
        if (ルート / パス).is_symlink():
            raise ValueError(f"シンボリックリンクは自動保存しません: {名}")
        if (ルート / パス).is_file():
            採用.append(名)
    for 明細 in 対象外:
        明細.update(集計.pop(明細["path"], {"files": 0, "bytes": 0}))
    対象外.extend({"path": 根, "reason": "ローカルの実行用ファイル", **数値} for 根, 数値 in 集計.items())
    return 採用, 対象外


def 計画作成(ルート, 出力先):
    """
    機能: 大容量ファイルを復元可能な単位に分け、計画と除外理由を保存する。
    引数: ルート (Path) はリポジトリ、出力先 (Path) は保存計画JSON。
    返り値: dict は直接保存パスと圧縮グループを含む計画。
    """
    候補, 対象外 = 一覧取得(ルート)
    直接 = []
    グループ = collections.defaultdict(list)
    合計 = 0
    for 名 in 候補:
        パス = Path(名)
        容量 = (ルート / パス).stat().st_size
        合計 += 容量
        if パス.suffix == ".html" and 容量 < 48 * 1024**2:
            直接.append(名)
            continue
        if 名.startswith("book/"):
            グループ[名].append(名)
        elif 名.startswith("work/"):
            依存定義 = パス.name.startswith(("requirements", "Pipfile", "package")) or パス.name in {"go.mod", "go.sum", "poetry.lock"}
            if 容量 < 上限 and (パス.suffix in 直接拡張子 or 依存定義):
                直接.append(名)
            else:
                グループ["/".join(名.split("/")[:2])].append(名)
        elif 容量 >= 上限:
            グループ["資料/" + 名].append(名)
        else:
            直接.append(名)
    計画 = {"version": 1, "direct_paths": 直接, "groups": [{"id": 名, "paths": 群} for 名, 群 in sorted(グループ.items())], "source_files": len(候補), "source_bytes": 合計}
    出力先.parent.mkdir(parents=True, exist_ok=True)
    出力先.write_text(json.dumps(計画, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (出力先.parent / "保存対象外.json").write_text(json.dumps({"説明": "元ファイルはローカルに保持し、Git送信だけ対象外とする。", "items": 対象外}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    開始 = "# 圧縮原本の対象（保存計画ツールで更新）"
    終了 = "# 圧縮原本の対象ここまで"
    無視 = ルート / ".gitignore"
    元 = 無視.read_text(encoding="utf-8")
    if 開始 in 元 and 終了 in 元:
        前, 残り = 元.split(開始, 1)
        _, 後 = 残り.split(終了, 1)
        元 = 前.rstrip() + "\n" + 後.lstrip("\n")
    原本 = sorted(名 for 群 in グループ.values() for 名 in 群 if not 名.startswith(("book/", "work/")))
    行 = [開始, *("/" + 名 for 名 in 原本), 終了]
    無視.write_text(元.rstrip() + "\n\n" + "\n".join(行) + "\n", encoding="utf-8")
    print(f"保存計画: 元ファイル {len(候補):,} 件 / {合計 / 1024**3:.2f} GiB、直接 {len(直接):,} 件、圧縮 {len(グループ):,} グループ", flush=True)
    print(f"送信対象外: {sum(項['files'] for 項 in 対象外):,} 件（元ファイルは保持）", flush=True)
    return 計画


def main():
    """
    機能: コマンド引数を読み、リポジトリの保存計画を生成する。
    引数: なし。
    返り値: None。
    """
    解析 = argparse.ArgumentParser(description="元データを変更せず、Git保存計画を作成します。")
    解析.add_argument("--output", type=Path, default=Path("保存データ/保存計画.json"), help="計画JSONの保存先")
    引数 = 解析.parse_args()
    ルート = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode("utf-8").strip()).resolve()
    計画作成(ルート, 引数.output.resolve())


if __name__ == "__main__":
    main()
