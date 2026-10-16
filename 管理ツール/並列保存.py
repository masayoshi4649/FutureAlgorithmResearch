"""既存の保存形式と検証処理を再利用して、グループ単位で並列処理する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import threading
from types import ModuleType
from typing import Callable
import zlib


def load_base() -> ModuleType:
    """
    機能: 同じディレクトリの既存保存ツールを変更せず読み込む。
    引数: なし。
    返り値: ModuleType - 既存の保存・検証関数を持つモジュール。
    """
    source = Path(__file__).with_name("git保存.py")
    specification = importlib.util.spec_from_file_location("_既存Git保存", source)
    if specification is None or specification.loader is None:
        raise ValueError(f"既存の保存ツールを読み込めません: {source}")
    module = importlib.util.module_from_spec(specification)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        specification.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


BASE = load_base()


class ParallelStopped(RuntimeError):
    """既存の再開処理による再圧縮を誘発せずに並列作業を中止する。"""


def validate_plan(plan: dict, output: Path, part_mib: float) -> dict[str, dict]:
    """
    機能: 全グループをまとめて検査し、元ファイルの更新情報を収集する。
    引数: plan (dict) - 保存計画、output (Path) - 保存先、part_mib (float) - 分割上限。
    返り値: dict[str, dict] - 元パスをキーとするサイズ・更新時刻の記録。
    """
    if not math.isfinite(part_mib) or int(part_mib * BASE.CHUNK) < 1024:
        raise ValueError("分割サイズは有限の値で、1024 バイト以上を指定してください")
    if not isinstance(plan, dict) or not isinstance(plan.get("groups"), list):
        raise ValueError("計画の groups は配列で指定してください")
    root = Path.cwd().resolve()
    group_ids, file_ids = set(), set()
    snapshots = {}
    for group in plan["groups"]:
        if not isinstance(group, dict):
            raise ValueError("計画のグループはオブジェクトで指定してください")
        group_id = BASE.safe_relative(group["id"])
        if group_id.casefold() in group_ids or not isinstance(group.get("paths"), list) or not group["paths"]:
            raise ValueError(f"計画のグループが不正です: {group_id}")
        group_ids.add(group_id.casefold())
        for name in group["paths"]:
            path = BASE.checked_path(root, name)
            information = path.stat()
            if name.casefold() in file_ids or not stat.S_ISREG(information.st_mode) or path.resolve().is_relative_to(output):
                raise ValueError(f"計画の元ファイルが不正です: {name}")
            file_ids.add(name.casefold())
            snapshots[name] = {"size": information.st_size, "mtime_ns": information.st_mtime_ns}

    # ----------------------------------------
    # 片方の分割ファイルが別グループのディレクトリになる配置を拒否する。
    for group_id in group_ids:
        components = group_id.split("/")
        for index in range(1, len(components)):
            if "/".join(components[:index]) in group_ids and BASE.PART_PATTERN.fullmatch(components[index]):
                raise ValueError(f"グループの出力先が分割ファイルと衝突します: {group_id}")
    return snapshots


def assign_groups(plan: dict, previous: dict, snapshots: dict, workers: int, limit: int) -> list[list[dict]]:
    """
    機能: 再利用できるグループを軽量とみなし、容量の大きい順に担当を割り当てる。
    引数: plan (dict) - 計画、previous (dict) - 保存情報、snapshots (dict) - 元情報、
          workers (int) - 並列数、limit (int) - 分割上限バイト数。
    返り値: list[list[dict]] - 各担当に割り当てるグループの配列。
    """
    prior = {group["id"]: group for group in previous["groups"]}
    weighted = []
    for position, group in enumerate(plan["groups"]):
        record = prior.get(group["id"])
        unchanged = record is not None and [item["path"] for item in record["files"]] == sorted(group["paths"])
        if unchanged:
            unchanged = all(part["size"] <= limit for part in record["parts"]) and all(
                snapshots[item["path"]] == {"size": item["size"], "mtime_ns": item["mtime_ns"]}
                for item in record["files"]
            )
        size = sum(snapshots[name]["size"] for name in group["paths"])
        weight = 1 if unchanged else max(size, 1)
        weighted.append((weight, position, group))
    assignments = [[] for _ in range(min(workers, max(len(weighted), 1)))]
    totals = [0] * len(assignments)
    for weight, position, group in sorted(weighted, key=lambda value: (-value[0], value[1])):
        target = min(range(len(assignments)), key=lambda index: (totals[index], len(assignments[index]), index))
        assignments[target].append((position, group))
        totals[target] += weight
    result = [[group for _, group in sorted(items)] for items in assignments if items]
    for number, groups in enumerate(result, 1):
        amount = sum(snapshots[name]["size"] for group in groups for name in group["paths"])
        print(f"担当 {number}: {len(groups)} グループ、元容量 {amount / 1024**3:.2f} GiB", flush=True)
    return result


class CancellationIO:
    """他の担当が失敗した場合に、読み取り中の担当も次のブロックで停止する。"""

    def __init__(self, stopped: threading.Event) -> None:
        """
        機能: 中止通知と既存の読み取り関数を記録する。
        引数: stopped (threading.Event) - 全担当共通の中止通知。
        返り値: None - インスタンスを初期化する。
        """
        self.stopped = stopped
        self.original_reader = BASE.HashReader
        self.original_hash = BASE.hash_file

    def check(self) -> None:
        """
        機能: 共通の中止通知を検査する。
        引数: なし。
        返り値: None - 中止通知があれば ParallelStopped を送出する。
        """
        if self.stopped.is_set():
            raise ParallelStopped("別の担当の失敗または割り込みにより処理を中止しました")

    def install(self) -> None:
        """
        機能: このプロセスで読み込んだ既存モジュールに中止可能な読み取りを設定する。
        引数: なし。
        返り値: None - 元のソースファイルには書き込まない。
        """
        owner = self

        class CheckedReader(owner.original_reader):
            """元ファイルと展開内容のブロック読み取りに中止検査を加える。"""

            def read(self, size: int = -1) -> bytes:
                """
                機能: 中止要求を検査してから元の読み取りを実行する。
                引数: size (int) - 最大読み取り量。
                返り値: bytes - 読み取った内容。
                """
                owner.check()
                return super().read(size)

        def checked_hash(path: Path) -> tuple[str, int]:
            """
            機能: 分割ファイルを中止可能なブロック単位でハッシュ化する。
            引数: path (Path) - 読み取るファイル。
            返り値: tuple[str, int] - SHA256 と実際のバイト数。
            """
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as source:
                while True:
                    owner.check()
                    data = source.read(BASE.CHUNK)
                    if not data:
                        break
                    digest.update(data)
                    size += len(data)
            return digest.hexdigest(), size

        BASE.HashReader = CheckedReader
        BASE.hash_file = checked_hash

    def restore(self) -> None:
        """
        機能: 全担当の停止後に読み取り関数を元へ戻す。
        引数: なし。
        返り値: None - 読み込んだモジュールの設定を復元する。
        """
        BASE.HashReader = self.original_reader
        BASE.hash_file = self.original_hash


def execute_parallel(tasks: list, action: Callable, workers: int, stopped: threading.Event) -> None:
    """
    機能: 担当を並列実行し、失敗時は全担当の終了を待って元の失敗を通知する。
    引数: tasks (list) - 担当一覧、action (Callable) - 処理、workers (int) - 並列数、
          stopped (threading.Event) - 中止通知。
    返り値: None - 全担当が正常終了した場合に返る。
    """
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="保存担当")
    futures = []
    try:
        futures = [executor.submit(action, task) for task in tasks]
        for future in as_completed(futures):
            future.result()
    except BaseException:
        stopped.set()
        for future in futures:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def pack(plan_path: Path, output: Path, part_mib: float = 48, workers: int = 8) -> None:
    """
    機能: グループを分担して既存の pack を実行し、保存情報を安全に統合する。
    引数: plan_path (Path) - 計画、output (Path) - 保存先、part_mib (float) - 分割上限 MiB、
          workers (int) - 並列数。この保存先で別の pack が動作していないことを前提とする。
    返り値: None - 全グループの保存が正常終了した場合に返る。
    """
    if workers < 1:
        raise ValueError("並列数は 1 以上を指定してください")
    output = BASE.checked_directory(output)
    BASE.guard_write(output)
    with plan_path.open(encoding="utf-8") as source:
        plan = json.load(source)
    snapshots = validate_plan(plan, output, part_mib)
    output.mkdir(parents=True, exist_ok=True)
    for group in plan["groups"]:
        directory = BASE.checked_path(output, group["id"])
        BASE.guard_write(directory)
        directory.mkdir(parents=True, exist_ok=True)
    manifest_path = BASE.checked_path(output, "manifest.json")
    previous = BASE.load_manifest(manifest_path) if manifest_path.exists() else {"version": 1, "groups": []}
    assignments = assign_groups(plan, previous, snapshots, workers, int(part_mib * BASE.CHUNK))
    ordered_ids = [group["id"] for group in plan["groups"]]
    ordered_set = set(ordered_ids)
    latest = {group["id"]: group for group in previous["groups"]}
    prior_order = [group["id"] for group in previous["groups"] if group["id"] not in ordered_set]
    lock = threading.Lock()
    local = threading.local()
    stopped = threading.Event()
    original_atomic = BASE.atomic_json
    original_load = BASE.load_manifest
    cancellation = CancellationIO(stopped)

    # ----------------------------------------
    def merged_atomic(path: Path, value: dict) -> None:
        """
        機能: 担当内の保存情報だけをロック内で統合して原子的に保存する。
        引数: path (Path) - 保存先、value (dict) - その担当の保存情報。
        返り値: None - 他の担当と旧グループの記録を保持する。
        """
        if path != manifest_path:
            raise ValueError(f"想定外の保存情報の出力先です: {path}")
        assigned = getattr(local, "assigned", set())
        incoming = value["groups"]
        if any(group["id"] not in assigned for group in incoming):
            raise ValueError("担当外のグループを書き込もうとしました")
        with lock:
            candidate = dict(latest)
            candidate.update((group["id"], group) for group in incoming)
            merged = {**previous, "groups": [candidate[name] for name in ordered_ids + prior_order if name in candidate]}
            original_atomic(path, merged)
            latest.clear()
            latest.update(candidate)

    def locked_load(path: Path) -> dict:
        """
        機能: Windows での読取中の置換を避け、保存情報をロック内で読む。
        引数: path (Path) - 保存情報の場所。
        返り値: dict - 検査済みの保存情報。
        """
        with lock:
            return original_load(path)

    def run_worker(task: tuple[Path, set[str]]) -> None:
        """
        機能: 所有するグループを固定して既存の圧縮処理を実行する。
        引数: task (tuple[Path, set[str]]) - 担当用計画と所有するグループ名。
        返り値: None - 全担当グループが保存された場合に返る。
        """
        local.assigned = task[1]
        BASE.pack(task[0], output, part_mib)

    # ----------------------------------------
    try:
        BASE.atomic_json = merged_atomic
        BASE.load_manifest = locked_load
        cancellation.install()
        with tempfile.TemporaryDirectory(prefix="並列保存計画-") as temporary:
            tasks = []
            for number, groups in enumerate(assignments, 1):
                path = Path(temporary) / f"担当-{number}.json"
                path.write_text(json.dumps({"groups": groups}, ensure_ascii=False), encoding="utf-8")
                tasks.append((path, {group["id"] for group in groups}))
            print(f"並列保存開始: {len(tasks)} 担当、{len(ordered_ids)} グループ", flush=True)
            execute_parallel(tasks, run_worker, workers, stopped)
        if any(name not in latest for name in ordered_ids):
            raise ValueError("正常終了後の保存情報に不足したグループがあります")
        for group in plan["groups"]:
            if [record["path"] for record in latest[group["id"]]["files"]] != sorted(group["paths"]):
                raise ValueError(f"保存情報と最終計画の元ファイルが一致しません: {group['id']}")
        final = {**previous, "groups": [latest[name] for name in ordered_ids]}
        original_atomic(manifest_path, final)
        checked = original_load(manifest_path)
        if [group["id"] for group in checked["groups"]] != ordered_ids:
            raise ValueError("保存情報と最終計画のグループ順が一致しません")
        print(f"並列保存完了: {len(ordered_ids)} グループ、{manifest_path}", flush=True)
    finally:
        BASE.atomic_json = original_atomic
        BASE.load_manifest = original_load
        cancellation.restore()


def verify(manifest_path: Path, workers: int = 8) -> dict:
    """
    機能: 全分割ファイルと全展開内容の検証をグループ単位で並列実行する。
    引数: manifest_path (Path) - 保存情報、workers (int) - 並列数。
    返り値: dict - 全グループを検証した保存情報。
    """
    if workers < 1:
        raise ValueError("並列数は 1 以上を指定してください")
    manifest = BASE.load_manifest(manifest_path)
    output = BASE.checked_directory(manifest_path.parent)
    stopped = threading.Event()
    cancellation = CancellationIO(stopped)

    def verify_group(group: dict) -> None:
        """
        機能: そのグループの全分割と元ファイル内容を既存の関数で検証する。
        引数: group (dict) - グループの保存情報。
        返り値: None - 全項目が一致した場合に返る。
        """
        cancellation.check()
        BASE.verify_parts(output, group)
        BASE.walk_group(output, group)
        print(f"検証完了: {group['id']}（{group['file_count']:,} ファイル）", flush=True)

    try:
        cancellation.install()
        groups = sorted(manifest["groups"], key=lambda group: -group["total_size"])
        execute_parallel(groups, verify_group, workers, stopped)
    finally:
        cancellation.restore()
    print(f"全件並列検証に成功しました: {len(manifest['groups'])} グループ", flush=True)
    return manifest


def main() -> int:
    """
    機能: コマンド行から並列保存または並列検証を実行する。
    引数: なし。コマンド行引数を使用する。
    返り値: int - 成功時 0、失敗時 1、割り込み時 130。
    """
    parser = argparse.ArgumentParser(description="既存形式を維持してグループ単位で並列保存・検証します。")
    commands = parser.add_subparsers(dest="command", required=True)
    pack_parser = commands.add_parser("pack", help="既存の保存処理を並列実行する")
    pack_parser.add_argument("--plan", type=Path, required=True, help="保存計画 JSON")
    pack_parser.add_argument("--output", type=Path, required=True, help="分割ファイルの保存先")
    pack_parser.add_argument("--part-mib", type=float, default=48, help="分割上限 MiB（標準 48）")
    pack_parser.add_argument("--workers", type=int, default=8, help="並列数（標準 8）")
    verify_parser = commands.add_parser("verify", help="分割ファイルと内容を並列検証する")
    verify_parser.add_argument("--manifest", type=Path, required=True, help="保存情報 JSON")
    verify_parser.add_argument("--workers", type=int, default=8, help="並列数（標準 8）")
    arguments = parser.parse_args()
    try:
        if arguments.command == "pack":
            pack(arguments.plan, arguments.output, arguments.part_mib, arguments.workers)
        else:
            verify(arguments.manifest, arguments.workers)
        return 0
    except KeyboardInterrupt:
        print("中断しました。保存済みグループを保持して終了します。", file=sys.stderr, flush=True)
        return 130
    except (OSError, ValueError, KeyError, TypeError, EOFError, RuntimeError, tarfile.TarError, zlib.error) as error:
        print(f"並列処理に失敗しました: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
