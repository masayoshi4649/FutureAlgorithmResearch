"""多数のファイルを検証可能な分割圧縮ファイルとして保存・復元する。"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile
import tempfile
from typing import BinaryIO, Callable
import zlib


CHUNK = 1024 * 1024
PART_PATTERN = re.compile(r"part-[0-9]{5,}\.tar\.gz\.part\Z")
RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.I)


def safe_relative(value: str) -> str:
    """
    機能: 安全な相対パスを検査し、共通形式の文字列を返す。
    引数: value (str) - 検査するスラッシュ区切りパス。
    返り値: str - 検査済みの相対パス。
    """
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"相対パスが不正です: {value!r}")
    components = value.split("/")
    if any(
        not name or name in (".", "..") or name.endswith((" ", "."))
        or any(ord(character) < 32 or character in '<>:"|?*' for character in name)
        or RESERVED.fullmatch(name)
        for name in components
    ) or PurePosixPath(value).is_absolute():
        raise ValueError(f"相対パスが不正です: {value!r}")
    return value


def checked_path(base: Path, relative: str) -> Path:
    """
    機能: 配下へのパスを生成し、リンクや接合点による迂回を拒否する。
    引数: base (Path) - 基準ディレクトリ、relative (str) - 相対パス。
    返り値: Path - 基準ディレクトリ配下の安全なパス。
    """
    relative = safe_relative(relative)
    current = base
    for name in relative.split("/"):
        current = current / name
        if os.path.lexists(current):
            information = current.lstat()
            if stat.S_ISLNK(information.st_mode) or (
                getattr(information, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                raise ValueError(f"リンク経由のパスは使用できません: {current}")
    if not current.resolve().is_relative_to(base.resolve()):
        raise ValueError(f"基準ディレクトリの外へ出るパスです: {current}")
    return current


def checked_directory(value: Path) -> Path:
    """
    機能: 絶対パスの全階層を検査して安全なディレクトリを取得する。
    引数: value (Path) - 検査するディレクトリ。
    返り値: Path - リンクを経由しない絶対パス。
    """
    absolute = Path(os.path.abspath(value))
    checked_path(Path(absolute.anchor), absolute.relative_to(absolute.anchor).as_posix())
    if absolute.exists() and not absolute.is_dir():
        raise ValueError(f"ディレクトリではありません: {absolute}")
    return absolute


def guard_write(path: Path) -> None:
    """
    機能: 現在のリポジトリにある読み取り専用データへの書き込みを拒否する。
    引数: path (Path) - 書き込み先。
    返り値: None - 許可された場合は何も返さない。
    """
    resolved = path.resolve()
    for name in ("book", "candle_1min", "candle_5min", ".git"):
        if resolved.is_relative_to((Path.cwd() / name).resolve()):
            raise ValueError(f"読み取り専用領域には書き込めません: {path}")


def hash_file(path: Path) -> tuple[str, int]:
    """
    機能: 通常ファイルの SHA256 と実際に読み取ったバイト数を計算する。
    引数: path (Path) - 読み取るファイル。
    返り値: tuple[str, int] - SHA256 とバイト数。
    """
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while data := source.read(CHUNK):
            digest.update(data)
            size += len(data)
    return digest.hexdigest(), size


def atomic_json(path: Path, value: dict) -> None:
    """
    機能: JSON を UTF-8 で一時ファイルへ書き込み、原子的に置き換える。
    引数: path (Path) - 保存先、value (dict) - 保存する内容。
    返り値: None - 保存結果はファイルへ反映する。
    """
    checked_path(path.parent, path.name)
    guard_write(path)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".manifest-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class HashReader:
    """読み取られた元ファイルの内容を同時に集計する。"""

    def __init__(self, source: BinaryIO) -> None:
        """
        機能: 元ファイル用の集計状態を初期化する。
        引数: source (BinaryIO) - 読み取り対象。
        返り値: None - インスタンスを初期化する。
        """
        self.source = source
        self.digest = hashlib.sha256()
        self.size = 0

    def read(self, size: int = -1) -> bytes:
        """
        機能: 指定量を読み取り、ハッシュとサイズへ加算する。
        引数: size (int) - 最大読み取り量。
        返り値: bytes - 読み取った内容。
        """
        data = self.source.read(size)
        self.digest.update(data)
        self.size += len(data)
        return data


class PartWriter:
    """連続した圧縮ストリームを上限サイズのファイルへ分割する。"""

    def __init__(self, output: Path, group_id: str, limit: int) -> None:
        """
        機能: 分割出力先と集計状態を初期化する。
        引数: output (Path) - 保存先、group_id (str) - グループ、limit (int) - 分割上限。
        返り値: None - インスタンスを初期化する。
        """
        self.output = output
        self.group_id = group_id
        self.limit = limit
        self.parts: list[dict] = []
        self.stream: BinaryIO | None = None
        self.temporary: Path | None = None
        self.size = 0
        self.total = 0
        self.digest = hashlib.sha256()
        self.directory = checked_path(output, group_id)
        guard_write(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _open(self) -> None:
        """
        機能: 新しい分割ファイルの一時出力を開始する。
        引数: なし。
        返り値: None - 一時出力を開始する。
        """
        descriptor, name = tempfile.mkstemp(prefix=".part-", suffix=".tmp", dir=self.directory)
        self.temporary = Path(name)
        self.stream = os.fdopen(descriptor, "wb")
        self.size = 0
        self.digest = hashlib.sha256()

    def _finish(self) -> None:
        """
        機能: 一時出力を確定して分割ファイルの検証情報を記録する。
        引数: なし。
        返り値: None - ファイルを確定する。
        """
        if self.stream is None:
            return
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.stream.close()
        self.stream = None
        relative = f"{self.group_id}/part-{len(self.parts) + 1:05d}.tar.gz.part"
        path = checked_path(self.output, relative)
        if path.exists() and not path.is_file():
            raise ValueError(f"分割ファイルの保存先が通常ファイルではありません: {path}")
        os.replace(self.temporary, path)
        self.temporary = None
        self.parts.append({"path": relative, "size": self.size, "sha256": self.digest.hexdigest()})

    def write(self, data: bytes) -> int:
        """
        機能: 圧縮済みの内容を上限以内に分割して書き込む。
        引数: data (bytes) - 書き込む内容。
        返り値: int - 書き込んだバイト数。
        """
        length = len(data)
        view = memoryview(data)
        while view:
            if self.stream is None:
                self._open()
            count = min(len(view), self.limit - self.size)
            piece = view[:count]
            self.stream.write(piece)
            self.digest.update(piece)
            self.size += count
            self.total += count
            view = view[count:]
            if self.size == self.limit:
                self._finish()
        return length

    def flush(self) -> None:
        """
        機能: 現在の分割出力のバッファを反映する。
        引数: なし。
        返り値: None - バッファを反映する。
        """
        if self.stream is not None:
            self.stream.flush()

    def tell(self) -> int:
        """
        機能: 全分割ファイルを通した出力位置を取得する。
        引数: なし。
        返り値: int - 出力済みバイト数。
        """
        return self.total

    def close(self) -> None:
        """
        機能: 最後の分割ファイルを確定する。
        引数: なし。
        返り値: None - 出力を終了する。
        """
        self._finish()

    def abort(self) -> None:
        """
        機能: 失敗時に開いている一時ファイルのみを片付ける。
        引数: なし。
        返り値: None - 一時ファイルを削除する。
        """
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        if self.temporary is not None:
            self.temporary.unlink(missing_ok=True)


class PartReader(io.RawIOBase):
    """分割ファイルを順番に連結して読み取る。"""

    def __init__(self, output: Path, parts: list[dict]) -> None:
        """
        機能: 分割ファイルの連結読み取りを初期化する。
        引数: output (Path) - 保存先、parts (list[dict]) - 順序付き分割情報。
        返り値: None - インスタンスを初期化する。
        """
        super().__init__()
        self.output = output
        self.parts = iter(parts)
        self.stream: BinaryIO | None = None

    def readable(self) -> bool:
        """
        機能: 読み取り可能であることを通知する。
        引数: なし。
        返り値: bool - 常に True。
        """
        return True

    def read(self, size: int = -1) -> bytes:
        """
        機能: 分割境界をまたいで指定量を読み取る。
        引数: size (int) - 最大読み取り量。
        返り値: bytes - 連結された内容。
        """
        pieces = []
        remaining = size
        while remaining != 0:
            if self.stream is None:
                part = next(self.parts, None)
                if part is None:
                    break
                self.stream = checked_path(self.output, part["path"]).open("rb")
            data = self.stream.read(remaining)
            if data:
                pieces.append(data)
                if remaining > 0:
                    remaining -= len(data)
            else:
                self.stream.close()
                self.stream = None
        return b"".join(pieces)

    def close(self) -> None:
        """
        機能: 開いている分割ファイルを閉じる。
        引数: なし。
        返り値: None - 読み取りを終了する。
        """
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        super().close()


def load_manifest(path: Path) -> dict:
    """
    機能: 保存情報を読み込み、形式・パス・重複・件数を検査する。
    引数: path (Path) - manifest.json の場所。
    返り値: dict - 検査済みの保存情報。
    """
    checked_path(checked_directory(path.parent), path.name)
    with path.open(encoding="utf-8") as source:
        manifest = json.load(source)
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or not isinstance(manifest.get("groups"), list):
        raise ValueError("保存情報の形式またはバージョンが不正です")
    group_ids, file_paths, part_paths = set(), set(), set()
    for group in manifest["groups"]:
        if not isinstance(group, dict):
            raise ValueError("保存情報のグループはオブジェクトで指定してください")
        group_id = safe_relative(group["id"])
        if group_id.casefold() in group_ids:
            raise ValueError(f"グループが重複しています: {group_id}")
        group_ids.add(group_id.casefold())
        if not group.get("parts") or not group.get("files"):
            raise ValueError(f"空のグループは復元できません: {group_id}")
        for position, part in enumerate(group["parts"], 1):
            expected = f"{group_id}/part-{position:05d}.tar.gz.part"
            if safe_relative(part["path"]) != expected or expected.casefold() in part_paths:
                raise ValueError(f"分割ファイルの順序またはパスが不正です: {part['path']}")
            part_paths.add(expected.casefold())
            check_record(part)
        for record in group["files"]:
            name = safe_relative(record["path"])
            if name.casefold() in file_paths:
                raise ValueError(f"元ファイルが重複しています: {name}")
            file_paths.add(name.casefold())
            check_record(record)
            if type(record.get("mtime_ns")) is not int:
                raise ValueError(f"更新時刻が不正です: {name}")
        if group.get("file_count") != len(group["files"]) or group.get("total_size") != sum(
            record["size"] for record in group["files"]
        ):
            raise ValueError(f"件数または総量が不正です: {group_id}")
    return manifest


def check_record(record: dict) -> None:
    """
    機能: 記録されたバイト数と SHA256 の形式を検査する。
    引数: record (dict) - ファイルの検証情報。
    返り値: None - 不正な場合は例外で通知する。
    """
    if type(record.get("size")) is not int or record["size"] < 0 or not re.fullmatch(
        r"[0-9a-f]{64}", str(record.get("sha256", ""))
    ):
        raise ValueError(f"検証情報が不正です: {record.get('path')}")


def verify_parts(output: Path, group: dict) -> None:
    """
    機能: グループの全分割ファイルのサイズと SHA256 を照合する。
    引数: output (Path) - 保存先、group (dict) - グループ保存情報。
    返り値: None - 全件一致した場合は何も返さない。
    """
    for part in group["parts"]:
        path = checked_path(output, part["path"])
        if not path.is_file():
            raise ValueError(f"分割ファイルがありません: {path}")
        digest, size = hash_file(path)
        if size != part["size"] or digest != part["sha256"]:
            raise ValueError(f"分割ファイルが破損しています: {path}")


def walk_group(output: Path, group: dict, consumer: Callable | None = None) -> None:
    """
    機能: 圧縮内容を読み取り、全メンバーのパス・サイズ・内容を照合する。
    引数: output (Path) - 保存先、group (dict) - 保存情報、consumer (Callable | None) - 復元処理。
    返り値: None - 全件一致した場合は何も返さない。
    """
    expected = {record["path"]: record for record in group["files"]}
    seen = set()
    with PartReader(output, group["parts"]) as parts, gzip.GzipFile(fileobj=parts, mode="rb") as compressed:
        with tarfile.open(fileobj=compressed, mode="r|", ignore_zeros=True) as archive:
            for member in archive:
                name = safe_relative(member.name)
                if member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE) or member.sparse:
                    raise ValueError(f"特殊な圧縮メンバーは使用できません: {name}")
                record = expected.get(name)
                if record is None or name in seen or member.size != record["size"]:
                    raise ValueError(f"圧縮メンバーが保存情報と一致しません: {name}")
                seen.add(name)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError(f"圧縮メンバーを読めません: {name}")
                with source:
                    reader = HashReader(source)
                    if consumer is None:
                        while reader.read(CHUNK):
                            pass
                    else:
                        consumer(record, reader)
                    if reader.size != record["size"] or reader.digest.hexdigest() != record["sha256"]:
                        raise ValueError(f"圧縮内容が破損しています: {name}")
        while compressed.read(CHUNK):
            pass
    if seen != set(expected):
        raise ValueError(f"圧縮内容のファイル件数が不足しています: {group['id']}")


def verify(manifest_path: Path) -> dict:
    """
    機能: 保存情報、全分割ファイル、展開内容を検証する。
    引数: manifest_path (Path) - manifest.json の場所。
    返り値: dict - 検証済みの保存情報。
    """
    manifest = load_manifest(manifest_path)
    output = checked_directory(manifest_path.parent)
    for group in manifest["groups"]:
        verify_parts(output, group)
    for group in manifest["groups"]:
        walk_group(output, group)
        print(f"検証完了: {group['id']}（{group['file_count']:,} ファイル）", flush=True)
    return manifest


def pack(plan_path: Path, output: Path, part_mib: float) -> None:
    """
    機能: 計画の元ファイルを決定的な tar.gz へ圧縮して分割保存する。
    引数: plan_path (Path) - 計画、output (Path) - 保存先、part_mib (float) - 分割上限 MiB。
    返り値: None - 保存情報と分割ファイルを出力する。
    """
    limit = int(part_mib * CHUNK)
    if limit < 1024:
        raise ValueError("分割サイズは 1024 バイト以上を指定してください")
    root = Path.cwd().resolve()
    output = checked_directory(output)
    guard_write(output)
    with plan_path.open(encoding="utf-8") as source:
        plan = json.load(source)
    if not isinstance(plan, dict) or not isinstance(plan.get("groups"), list):
        raise ValueError("計画の groups は配列で指定してください")
    all_files, all_groups = set(), set()
    for group in plan["groups"]:
        group_id = safe_relative(group["id"])
        if group_id.casefold() in all_groups or not isinstance(group.get("paths"), list) or not group["paths"]:
            raise ValueError(f"計画のグループが不正です: {group_id}")
        all_groups.add(group_id.casefold())
        for name in group["paths"]:
            path = checked_path(root, name)
            if name.casefold() in all_files or not path.is_file() or path.resolve().is_relative_to(output):
                raise ValueError(f"計画の元ファイルが不正です: {name}")
            all_files.add(name.casefold())

    # ----------------------------------------
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = checked_path(output, "manifest.json")
    manifest = load_manifest(manifest_path) if manifest_path.exists() else {"version": 1, "groups": []}
    current_groups = {group["id"]: group for group in manifest["groups"]}
    ordered_groups = []
    for position, planned in enumerate(plan["groups"], 1):
        group_id = planned["id"]
        paths = sorted(planned["paths"])
        previous = current_groups.get(group_id)
        unchanged = previous is not None and [record["path"] for record in previous["files"]] == paths and all(part["size"] <= limit for part in previous["parts"])
        if unchanged:
            for record in previous["files"]:
                information = checked_path(root, record["path"]).stat()
                if information.st_size != record["size"] or information.st_mtime_ns != record["mtime_ns"]:
                    unchanged = False
                    break
        if unchanged:
            try:
                verify_parts(output, previous)
            except (OSError, ValueError) as error:
                print(f"再圧縮: {group_id}（既存ファイルの検証失敗: {error}）", flush=True)
            else:
                ordered_groups.append(previous)
                print(f"再開済み: {position}/{len(plan['groups'])} {group_id}", flush=True)
                continue

        # ----------------------------------------
        print(f"圧縮開始: {position}/{len(plan['groups'])} {group_id}（{len(paths):,} ファイル）", flush=True)
        writer = PartWriter(output, group_id, limit)
        records = []
        try:
            with gzip.GzipFile(filename="", fileobj=writer, mode="wb", compresslevel=3, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                    for index, name in enumerate(paths, 1):
                        path = checked_path(root, name)
                        before = path.stat()
                        with path.open("rb") as source:
                            opened = os.fstat(source.fileno())
                            if (opened.st_size, opened.st_mtime_ns, opened.st_ino) != (before.st_size, before.st_mtime_ns, before.st_ino):
                                raise ValueError(f"圧縮開始時に元ファイルが変更されました: {name}")
                            reader = HashReader(source)
                            member = tarfile.TarInfo(name)
                            member.size = before.st_size
                            member.mode = 0o644
                            member.mtime = member.uid = member.gid = 0
                            archive.addfile(member, reader)
                            after = os.fstat(source.fileno())
                        current = path.stat()
                        if reader.size != before.st_size or (after.st_size, after.st_mtime_ns, after.st_ino) != (before.st_size, before.st_mtime_ns, before.st_ino) or (current.st_size, current.st_mtime_ns, current.st_ino) != (before.st_size, before.st_mtime_ns, before.st_ino):
                            raise ValueError(f"圧縮中に元ファイルが変更されました: {name}")
                        records.append({"path": name, "size": reader.size, "mtime_ns": before.st_mtime_ns, "sha256": reader.digest.hexdigest()})
                        if index % 1000 == 0:
                            print(f"圧縮中: {group_id} {index:,}/{len(paths):,}", flush=True)
            writer.close()
        except BaseException:
            writer.abort()
            raise
        completed = {"id": group_id, "files": records, "parts": writer.parts, "file_count": len(records), "total_size": sum(record["size"] for record in records)}
        ordered_groups.append(completed)
        current_groups[group_id] = completed
        manifest["groups"] = [current_groups[group["id"]] for group in plan["groups"] if group["id"] in current_groups]
        atomic_json(manifest_path, manifest)
        expected_parts = {Path(part["path"]).name for part in writer.parts}
        for existing in writer.directory.iterdir():
            if PART_PATTERN.fullmatch(existing.name) and existing.name not in expected_parts:
                checked_path(output, existing.relative_to(output).as_posix()).unlink()
        print(f"圧縮完了: {group_id}（{writer.total:,} バイト、{len(writer.parts)} 分割）", flush=True)
    manifest["groups"] = ordered_groups
    atomic_json(manifest_path, manifest)
    print(f"保存完了: {manifest_path}", flush=True)


def restore(manifest_path: Path, destination: Path) -> None:
    """
    機能: 保存内容を全件検証し、既存ファイルを保護しながら復元する。
    引数: manifest_path (Path) - 保存情報、destination (Path) - 復元先。
    返り値: None - ファイルを復元する。
    """
    destination = checked_directory(destination)
    guard_write(destination)
    output = checked_directory(manifest_path.parent)
    if destination.is_relative_to(output) or output.is_relative_to(destination):
        raise ValueError("復元先と圧縮ファイルの保存先は別のディレクトリにしてください")
    manifest = verify(manifest_path)
    for group in manifest["groups"]:
        for record in group["files"]:
            target = checked_path(destination, record["path"])
            if target.exists() and (not target.is_file() or hash_file(target) != (record["sha256"], record["size"])):
                raise ValueError(f"既存ファイルと内容が異なるため復元を中止しました: {target}")

    # ----------------------------------------
    def write_member(record: dict, reader: HashReader) -> None:
        """
        機能: メンバーを安全な一時ファイルへ復元して原子的に確定する。
        引数: record (dict) - 検証情報、reader (HashReader) - 内容の読み取り元。
        返り値: None - 復元または同一内容の読み飛ばしを行う。
        """
        target = checked_path(destination, record["path"])
        if target.exists():
            if not target.is_file() or hash_file(target) != (record["sha256"], record["size"]):
                raise ValueError(f"既存ファイルが変更されたため復元を中止しました: {target}")
            while reader.read(CHUNK):
                pass
            return
        guard_write(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        checked_path(destination, record["path"])
        descriptor, temporary_name = tempfile.mkstemp(prefix=".restore-", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as restored:
                while data := reader.read(CHUNK):
                    restored.write(data)
                restored.flush()
                os.fsync(restored.fileno())
            if reader.size != record["size"] or reader.digest.hexdigest() != record["sha256"]:
                raise ValueError(f"復元内容が破損しています: {record['path']}")
            checked_path(destination, record["path"])
            if target.exists():
                raise ValueError(f"復元中に保存先が作成されたため中止しました: {target}")
            # Windows の rename は既存ファイルを上書きしない。
            # 他の環境はハードリンクで同じ原子的な確定と上書き禁止を実現する。
            if os.name == "nt":
                os.rename(temporary, target)
            else:
                os.link(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    for group in manifest["groups"]:
        walk_group(output, group, write_member)
        print(f"復元完了: {group['id']}（{group['file_count']:,} ファイル）", flush=True)
    print(f"全件復元完了: {destination}", flush=True)


def main() -> int:
    """
    機能: コマンド行引数を処理し、圧縮・検証・復元を実行する。
    引数: なし。コマンド行引数を参照する。
    返り値: int - 成功時 0、失敗時 1、割り込み時 130。
    """
    parser = argparse.ArgumentParser(description="大量ファイルを分割圧縮し、検証・復元します。")
    commands = parser.add_subparsers(dest="command", required=True)
    pack_parser = commands.add_parser("pack", help="計画に従って分割圧縮する")
    pack_parser.add_argument("--plan", required=True, type=Path, help="保存計画 JSON")
    pack_parser.add_argument("--output", required=True, type=Path, help="分割ファイルの保存先")
    pack_parser.add_argument("--part-mib", type=float, default=48, help="分割上限 MiB（標準 48）")
    verify_parser = commands.add_parser("verify", help="分割ファイルと全展開内容を検証する")
    verify_parser.add_argument("--manifest", required=True, type=Path, help="保存情報 JSON")
    restore_parser = commands.add_parser("restore", help="検証して別のディレクトリへ復元する")
    restore_parser.add_argument("--manifest", required=True, type=Path, help="保存情報 JSON")
    restore_parser.add_argument("--destination", required=True, type=Path, help="復元先ディレクトリ")
    arguments = parser.parse_args()
    try:
        if arguments.command == "pack":
            pack(arguments.plan, arguments.output, arguments.part_mib)
        elif arguments.command == "verify":
            verify(arguments.manifest)
            print("全件検証に成功しました", flush=True)
        else:
            restore(arguments.manifest, arguments.destination)
        return 0
    except KeyboardInterrupt:
        print("中断しました。pack を再実行すると検証済みグループから再開します。", file=sys.stderr, flush=True)
        return 130
    except (OSError, ValueError, KeyError, TypeError, EOFError, tarfile.TarError, zlib.error) as error:
        print(f"処理に失敗しました: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
