"""保存計画に従って小さなコミットを作り、通常のpushで順番に送信する。"""

import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess


def git(引数, 環境=None, 入力=None):
    """
    機能: Gitコマンドを実行し、失敗時には例外で処理を止める。
    引数: 引数 (list[str])、環境 (dict | None)、入力 (bytes | None)。
    返り値: bytes はコマンドの標準出力。
    """
    return subprocess.check_output(["git", *引数], env=環境, input=入力)


def 保存(パス, 内容):
    """
    機能: 再開に必要な状態を一時ファイルから置き換えて保存する。
    引数: パス (Path) は保存先、内容 (dict) は状態。
    返り値: None。
    """
    仮 = パス.with_suffix(".tmp")
    仮.write_text(json.dumps(内容, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    仮.replace(パス)


def 対象取得(ルート, 計画パス, 目録パス):
    """
    機能: 計画のソースと目録の圧縮ファイルを送信対象として列挙する。
    引数: ルート (Path)、計画パス (Path)、目録パス (Path)。
    返り値: list[str] はリポジトリ相対の送信対象パス。
    """
    計画 = json.loads(計画パス.read_text(encoding="utf-8"))
    目録 = json.loads(目録パス.read_text(encoding="utf-8"))
    対象 = set(計画["direct_paths"])
    群 = 目録["groups"]
    if isinstance(群, dict):
        群 = list(群.values())
    計画群 = {項["id"]: sorted(項["paths"]) for 項 in 計画["groups"]}
    保存群 = {項["id"]: sorted(資料["path"] for 資料 in 項["files"]) for 項 in 群}
    if 計画群 != 保存群:
        raise ValueError("保存計画と目録が一致しません。圧縮と検証を完了してから送信してください。")
    for 項 in 群:
        for 部 in 項["parts"]:
            パス = (目録パス.parent / 部["path"]).resolve()
            対象.add(パス.relative_to(ルート).as_posix())
    for ファイル in (計画パス, 目録パス, 計画パス.parent / "保存対象外.json"):
        対象.add(ファイル.resolve().relative_to(ルート).as_posix())
    対象.update({".gitignore", ".gitattributes", "README.md", "Git保存と復元.md"})
    対象.update(項.relative_to(ルート).as_posix() for 項 in (ルート / "管理ツール").glob("*.py"))
    for 名 in 対象:
        パス = (ルート / 名)
        if not パス.is_file() or パス.is_symlink() or not パス.resolve().is_relative_to(ルート):
            raise ValueError(f"送信対象の実ファイルを確認できません: {名}")
        if パス.stat().st_size > 48 * 1024**2:
            raise ValueError(f"48MiBを超えるため、圧縮計画を見直してください: {名}")
    return sorted(対象)


def 準備(引数, ルート, 作業):
    """
    機能: 実際の作業ツリーを保持したまま、別インデックスで分割コミットを作る。
    引数: 引数 (Namespace)、ルート (Path)、作業 (Path) は状態の保存先。
    返り値: dict は履歴、元HEAD、送信するコミット列。
    """
    元 = git(["rev-parse", "HEAD"]).decode().strip()
    枝 = git(["symbolic-ref", "HEAD"]).decode().strip()
    基点 = git(["rev-parse", f"{引数.remote}/{引数.branch}"]).decode().strip()
    if 枝 != f"refs/heads/{引数.branch}":
        raise ValueError("送信するブランチへ切り替えてから実行してください。")
    if 元 != 基点 and not 引数.rebuild_unpublished:
        raise ValueError("未送信の既存コミットがあります。小さいコミットは通常のgit pushで送信してください。")
    if 元 != 基点:
        git(["merge-base", "--is-ancestor", 基点, 元])
    対象 = 対象取得(ルート, 引数.plan.resolve(), 引数.manifest.resolve())
    批 = []
    現在 = []
    容量 = 0
    for 名 in 対象:
        数 = (ルート / 名).stat().st_size
        if 現在 and 容量 + 数 > 引数.batch_mib * 1024**2:
            批.append(現在)
            現在, 容量 = [], 0
        現在.append(名)
        容量 += 数
    if 現在:
        批.append(現在)
    print(f"送信対象 {len(対象):,} 件、分割 {len(批)} 回、各 {引数.batch_mib} MiB以下", flush=True)
    if 引数.dry_run:
        return {}

    # ----------------------------------------
    作業.mkdir(parents=True, exist_ok=False)
    退避 = f"refs/heads/保存前_{作業.name}"
    git(["update-ref", 退避, 元, "0" * 40])
    環境 = dict(os.environ, GIT_INDEX_FILE=str(作業 / "index"))
    git(["read-tree", 基点], 環境)
    既存 = set(git(["ls-tree", "-r", "--name-only", "-z", 基点]).decode("utf-8").split("\0")) - {""}
    不要 = sorted(既存 - set(対象))
    if 不要:
        git(["update-index", "--force-remove", "-z", "--stdin"], 環境, "".join(名 + "\0" for 名 in 不要).encode("utf-8"))
    状態 = {"original_head": 元, "local_ref": 枝, "base": 基点, "backup_ref": 退避, "progress_ref": f"refs/heads/保存送信_{作業.name}", "remote": 引数.remote, "branch": 引数.branch, "commits": []}
    親 = 基点
    前木 = git(["rev-parse", f"{親}^{{tree}}"]).strip()
    for 番号, ファイル群 in enumerate(批, 1):
        列挙 = 作業 / "対象.nul"
        列挙.write_bytes("".join(名 + "\0" for 名 in ファイル群).encode("utf-8"))
        git(["-c", "core.safecrlf=false", "add", "-f", f"--pathspec-from-file={列挙}", "--pathspec-file-nul"], 環境)
        木 = git(["write-tree"], 環境).strip()
        if 木 == 前木:
            continue
        文 = f"大量データの分割保存（{番号}/{len(批)}）\n".encode("utf-8")
        親 = git(["commit-tree", 木.decode(), "-p", 親], 入力=文).decode().strip()
        前木 = 木
        状態["commits"].append(親)
        git(["update-ref", 状態["progress_ref"], 親])
        保存(作業 / "state.json", 状態)
        print(f"コミット準備 {番号}/{len(批)}: {親[:10]}", flush=True)
    if not 状態["commits"]:
        状態["commits"] = [基点]
    状態["prepared_complete"] = True
    保存(作業 / "state.json", 状態)
    return 状態


def 送信(状態, 作業):
    """
    機能: 作成した履歴を強制更新せず順に送信し、ローカルの参照を整える。
    引数: 状態 (dict)、作業 (Path) は再開用状態のフォルダ。
    返り値: None。
    """
    if not 状態.get("prepared_complete"):
        raise ValueError("コミットの準備が途中です。送信を再開せず、保存計画から準備をやり直してください。")
    出力 = git(["ls-remote", 状態["remote"], f"refs/heads/{状態['branch']}"]).decode().strip()
    遠隔 = 出力.split()[0] if 出力 else ""
    履歴 = [状態["base"], *状態["commits"]]
    if 遠隔 not in 履歴:
        raise ValueError("送信先が別の履歴へ進んでいます。既存の履歴を確認してください。")
    始点 = max(番号 for 番号, 値 in enumerate(履歴) if 値 == 遠隔)
    for 番号 in range(始点 + 1, len(履歴)):
        print(f"GitHubへ分割送信 {番号}/{len(履歴) - 1}: {履歴[番号][:10]}", flush=True)
        subprocess.run(["git", "-c", "pack.threads=2", "-c", "pack.window=0", "push", 状態["remote"], f"{履歴[番号]}:refs/heads/{状態['branch']}"], check=True)
        状態["last_pushed"] = 履歴[番号]
        保存(作業 / "state.json", 状態)

    # ----------------------------------------
    最終 = 履歴[-1]
    現在 = git(["rev-parse", "HEAD"]).decode().strip()
    現在枝 = git(["symbolic-ref", "HEAD"]).decode().strip()
    if 現在枝 != 状態["local_ref"]:
        raise ValueError("作業中にブランチが変わりました。送信は完了しましたが参照更新は保留します。")
    if 現在 not in {状態["original_head"], 最終}:
        raise ValueError("ローカルのHEADが作業中に変わりました。送信は完了しましたが参照更新は保留します。")
    git(["update-ref", 状態["local_ref"], 最終, 現在])
    git(["read-tree", 最終])
    git(["update-ref", f"refs/remotes/{状態['remote']}/{状態['branch']}", 最終])
    状態["complete"] = True
    保存(作業 / "state.json", 状態)
    print(f"送信完了: {最終}。元ファイルは保持しました。", flush=True)


def main():
    """
    機能: 保存計画と容量指定から分割送信を行い、失敗後は状態から再開する。
    引数: なし。
    返り値: None。
    """
    解析 = argparse.ArgumentParser(description="保存計画のファイルを小分けにコミット・pushします。")
    解析.add_argument("--plan", type=Path, default=Path("保存データ/保存計画.json"))
    解析.add_argument("--manifest", type=Path, default=Path("保存データ/manifest.json"))
    解析.add_argument("--batch-mib", type=int, default=384)
    解析.add_argument("--remote", default="origin")
    解析.add_argument("--branch", default="main")
    解析.add_argument("--rebuild-unpublished", action="store_true", help="未送信履歴を退避し、送信先の履歴に続けて再構成")
    解析.add_argument("--resume-state", type=Path, help="中断したstate.jsonから送信を再開")
    解析.add_argument("--dry-run", action="store_true", help="送信対象と分割数のみ確認")
    引数 = 解析.parse_args()
    if 引数.resume_state and 引数.dry_run:
        解析.error("--resume-state と --dry-run は同時に指定できません。")
    if not 48 <= 引数.batch_mib <= 1024:
        解析.error("分割容量は48以上1024以下のMiBで指定してください。")
    ルート = Path(git(["rev-parse", "--show-toplevel"]).decode("utf-8").strip()).resolve()
    os.chdir(ルート)
    if 引数.resume_state:
        状態パス = 引数.resume_state.resolve()
        送信(json.loads(状態パス.read_text(encoding="utf-8")), 状態パス.parent)
        return
    git(["fetch", 引数.remote, 引数.branch])
    日付 = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    作業 = ルート / ".git" / "保存送信" / 日付
    状態 = 準備(引数, ルート, 作業)
    if not 引数.dry_run:
        print(f"再開用状態: {作業 / 'state.json'}", flush=True)
        送信(状態, 作業)


if __name__ == "__main__":
    main()
