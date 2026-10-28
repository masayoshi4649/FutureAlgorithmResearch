"""配布Windows版を全商品OFF・ローカル模擬controllerで隔離検査する。"""

from datetime import datetime
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
APP = ROOT / "App/SessionTrader"
EXPECTED_PRODUCTS = {"NK225": 2, "NK225mini": 10, "NK225micro": 20, "TOPIX": 2, "TOPIXmini": 10}
EXPECTED_RULES = {
    "NK225_S01", "NK225_P05", "NK225_D07", "NK225_TG04", "NK225_PG04",
    "NK225_T06", "NK225_U06", "TOPIX_T06", "TOPIX_T04",
}


def digest(path: Path) -> str:
    """ファイルの内容指紋を計算する。

    引数: path(Path)は読取対象。返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def relative(path: Path) -> str:
    """成果物の場所をプロジェクト相対表記へ変換する。

    引数: path(Path)は内部資料。返り値: strは相対パス。
    """
    return path.relative_to(ROOT).as_posix()


def set_scalar(source: str, section: str, key: str, value: object) -> str:
    """単一TOML表の値だけを置換し、ない場合はその表へ追加する。

    引数: source/section/key(str)とvalue(object)は保存元・表・項目・値。
    返り値: strは更新した本文。配列表や重複項目へは適用しない。
    """
    encoded = json.dumps(value, ensure_ascii=False)
    heading = re.compile(r"(?m)^\[" + re.escape(section) + r"\]\s*$")
    match = heading.search(source)
    if match is None:
        return source + f"\n[{section}]\n{key} = {encoded}\n"
    start = match.end()
    following = re.search(r"(?m)^\[", source[start:])
    end = start + following.start() if following else len(source)
    block = source[start:end]
    pattern = re.compile(r"(?m)^" + re.escape(key) + r"\s*=.*$")
    assert len(pattern.findall(block)) <= 1, "同じ設定項目が重複している"
    if pattern.search(block):
        block = pattern.sub(lambda _: f"{key} = {encoded}", block, count=1)
    else:
        block += f"\n{key} = {encoded}\n"
    return source[:start] + block + source[end:]


class MockController(BaseHTTPRequestHandler):
    """外部へ転送せず、アプリから来た全要求を記録して拒否する模擬接続先。"""

    def log_message(self, format: str, *args: object) -> None:
        """要求本文を端末へ流さない。

        引数: format(str)、args(tuple)は標準HTTPの表示情報。返り値: None。
        """

    def record(self) -> None:
        """想定外のcontroller要求を証跡へ残し、503を返す。

        引数: なし。返り値: None。市場データ・注文受付は提供しない。
        """
        row = {"method": self.command, "path": self.path, "at": datetime.now().astimezone().isoformat()}
        with self.server.records_lock:
            self.server.records.append(row)
        body = "全商品OFFの確認中です".encode("utf-8")
        self.send_response(503)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = record
    do_POST = record
    do_PUT = record
    do_DELETE = record
    do_PATCH = record
    do_HEAD = record
    do_OPTIONS = record
    do_CONNECT = record


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """ローカル画面から外部への転送を追跡しない。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """転送先へ接続しない。

        引数: req/fp/headersはHTTP情報、code(int)、msg/newurl(str)。返り値: None。
        """
        return None


def fetch_json(opener, origin: str, path: str) -> dict:
    """隔離Webの読み取りRESTだけを呼ぶ。

    引数: opener(OpenerDirector)、origin/path(str)はloopback画面の場所。
    返り値: dictはJSON応答。実サービスや書込APIを呼ばない。
    """
    assert urllib.parse.urlsplit(origin).hostname == "127.0.0.1"
    assert path in {"/api/settings", "/api/rules", "/api/state"}
    with opener.open(origin + path, timeout=1) as response:
        assert response.status == 200
        return json.load(response)


def check_settings(settings: dict) -> None:
    """全商品の標準手法・数量・OFFと日経の時間枠を照合する。

    引数: settings(dict)はGET応答又はTOML本文。返り値: None。不一致はAssertionError。
    """
    items = settings["instruments"]
    assert len(items) == 5 and {item["product"] for item in items} == set(EXPECTED_PRODUCTS)
    expected_windows = [
        ("Day", "SESSION_START", "SESSION_END", "NK225_S01"),
        ("Night", "SESSION_START", "US_OPEN-00:15", "NK225_P05"),
        ("Night", "US_OPEN-00:15", "US_OPEN+00:15", ""),
        ("Night", "US_OPEN+00:15", "SESSION_END", "NK225_D07"),
    ]
    for item in items:
        product = item["product"]
        assert item["mode"] == "off", f"OFFではない: {product}"
        assert item["max_per_side"] == EXPECTED_PRODUCTS[product], product
        if product.startswith("NK225"):
            assert item["day"] == "NK225_S01" and item["night"] == "NK225_D07", product
            windows = [(w["session"], w["start"], w["end"], w["method"]) for w in item["windows"]]
            assert windows == expected_windows, (product, windows)
        else:
            assert item["day"] == "TOPIX_T06" and item["night"] == "TOPIX_T04", product
            assert not item.get("windows"), product


def check_catalog(catalog: dict) -> None:
    """9実ルールとS01の日中限定・P05の夜間枠限定を照合する。

    引数: catalog(dict)はGET応答。返り値: None。不一致はAssertionError。
    """
    rows = catalog["rules"]
    assert len(rows) == 9 and {row["name"] for row in rows} == EXPECTED_RULES
    assert all(row["supported"] for row in rows)
    by_name = {row["name"]: row for row in rows}
    s01, p05, d07 = [by_name[key] for key in ("NK225_S01", "NK225_P05", "NK225_D07")]
    assert s01["reference"] == "NK225" and s01["day"] and not s01["night"] and not s01["window_only"]
    assert p05["reference"] == "NK225" and not p05["day"] and p05["night"] and p05["window_only"]
    assert d07["day"] and d07["night"]


def force_off(source: str) -> str:
    """商品のモードだけを隔離試験用OFFへ固定する。

    引数: source(str)はTOML本文。返り値: strは全商品OFFの本文。
    元の数量・手法・時間帯は変更せず、元ファイルへも書き込まない。
    """
    pattern = re.compile(r"(?m)^\[\[instruments\]\]\s*$")
    for match in reversed(list(pattern.finditer(source))):
        start = match.end()
        following = re.search(r"(?m)^\[", source[start:])
        end = start + following.start() if following else len(source)
        block = source[start:end]
        mode = re.compile(r"(?m)^mode\s*=.*$")
        if mode.search(block):
            block = mode.sub('mode = "off"', block)
        else:
            block += '\nmode = "off"\n'
        block = re.sub(r"(?m)^enabled\s*=.*$", "enabled = false", block)
        source = source[:start] + block + source[end:]
    assert all(row["mode"] == "off" for row in tomllib.loads(source).get("instruments", []))
    return source


def named_method(reference: str, value: str) -> str:
    """短い旧手法IDを公開表記へ揃える。

    引数: reference/value(str)は市場と旧値。返り値: strは銘柄付きID又は静観の空文字。
    """
    return value if not value or "_" in value else reference + "_" + value


def expected_existing_items(original: dict, standard_d07: bool) -> tuple[list, list]:
    """旧実設定から仕様上認める移行だけを独立に組み立てる。

    引数: original(dict)は元の実効設定、standard_d07(bool)はD07共通式が標準か。
    返り値: tuple[list,list]は期待商品一覧と移行内容。数量・独自枠は推測で変更しない。
    """
    items = copy.deepcopy(original["instruments"])
    transitions = []
    custom = bool(original.get("rule_engine", {}).get("file")) or bool(original.get("algorithm"))
    for item in items:
        ref = "NK225" if item["product"].startswith("NK225") else "TOPIX"
        item["day"] = named_method(ref, item["day"])
        item["night"] = named_method(ref, item["night"])
        item["mode"] = "off"
        for window in item.get("windows", []):
            window["method"] = named_method(ref, window["method"])
        if ref != "NK225" or custom:
            continue
        windows = item.get("windows")
        old_pair = bool(windows and len(windows) == 2 and {w["session"] for w in windows} == {"Day", "Night"} and all(w["start"] == "SESSION_START" and w["end"] == "SESSION_END" and w["method"] == (item["day"] if w["session"] == "Day" else "NK225_D07") for w in windows))
        if (windows is None and item["night"] == "NK225_D07") or old_pair:
            item["windows"] = [
                {"id": "Day", "session": "Day", "start": "SESSION_START", "end": "SESSION_END", "method": item["day"]},
                {"id": "NightPreUS", "session": "Night", "start": "SESSION_START", "end": "US_OPEN-00:15", "method": "NK225_P05"},
                {"id": "NightUSQuiet", "session": "Night", "start": "US_OPEN-00:15", "end": "US_OPEN+00:15", "method": ""},
                {"id": "NightPostUS", "session": "Night", "start": "US_OPEN+00:15", "end": "SESSION_END", "method": "NK225_D07"},
            ]
            transitions.append({"product": item["product"], "change": "旧標準の夜間をP05・静観・D07へ"})
        expected = {
            ("Day", "SESSION_START", "SESSION_END", "NK225_D07"),
            ("Night", "SESSION_START", "US_OPEN-00:15", "NK225_P05"),
            ("Night", "US_OPEN-00:15", "US_OPEN+00:15", ""),
            ("Night", "US_OPEN+00:15", "SESSION_END", "NK225_D07"),
        }
        actual = {(w["session"], w["start"], w["end"], w["method"]) for w in item.get("windows", [])}
        if original.get("settings_version", 0) == 0 and standard_d07 and item["day"] == "NK225_D07" and len(item.get("windows", [])) == 4 and actual == expected:
            item["day"] = "NK225_S01"
            for window in item["windows"]:
                if window["session"] == "Day":
                    window["method"] = "NK225_S01"
            transitions.append({"product": item["product"], "change": "旧標準の日中D07をS01へ"})
    return items, transitions


def check_existing_configuration(base: Path, clone: Path, mock_url: str, server) -> dict:
    """既存distの実設定を別コピーで検査し、標準移行と独自値の保持を確認する。

    引数: base/clone(Path)は配布元と隔離先、mock_url(str)とserverは模擬接続先。
    返り値: dictは元設定・期待する移行・実観測・終了記録。
    実設定そのものは変更せず、試験コピーだけを全OFF・loopback・専用保存先へ固定する。
    """
    clone.mkdir(exist_ok=False)
    (clone / "conf").mkdir()
    shutil.copy2(base / "sessiontrader.exe", clone / "sessiontrader.exe")
    shutil.copytree(base / "conf/rules", clone / "conf/rules")
    shutil.copytree(base / "conf", clone / "original-conf")
    sources = {path.name: path.read_text(encoding="utf-8-sig") for path in sorted((base / "conf").glob("*.toml"))}
    source = "\n".join(body for name, body in sources.items() if name != "web-ui.toml")
    original = tomllib.loads(source)
    assert "web" in original, "既存の実設定はWeb版である必要がある"
    overlay = sources.get("web-ui.toml")
    if overlay is not None:
        prior = tomllib.loads(overlay)
        original.update(prior)
        original["settings_version"] = prior.get("settings_version", 0)
    assert original.get("rule_engine", {}).get("directory", "conf/rules") == "conf/rules", "独自ルール保存先の隔離は手動確認が必要"
    assert not original.get("rule_engine", {}).get("file"), "旧単一外部式はこのWeb配布スモークの対象外"
    baseline = tomllib.loads((APP / "conf/rules/NK225_D07.toml").read_text(encoding="utf-8"))["expressions"]
    current = tomllib.loads((base / "conf/rules/NK225_D07.toml").read_text(encoding="utf-8"))["expressions"]
    expected, transitions = expected_existing_items(original, baseline == current)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    source = force_off(source)
    safety = [("controller", "base_url", mock_url), ("web", "host", "127.0.0.1"), ("web", "port", port), ("runtime", "data_directory", "data"), ("runtime", "log_directory", "log")]
    for section, key, value in safety + [("trading", "dryrun", True), ("startup", "action", "check")]:
        source = set_scalar(source, section, key, value)
    if overlay is not None:
        overlay = force_off(overlay)
        for section, key, value in safety:
            overlay = set_scalar(overlay, section, key, value)
        (clone / "conf/web-ui.toml").write_text(overlay, encoding="utf-8")
    config_path = clone / "conf/settings.toml"
    config_path.write_text(source, encoding="utf-8")
    flags = subprocess.CREATE_NO_WINDOW
    checked = subprocess.run([str(clone / "sessiontrader.exe")], cwd=clone, stdin=subprocess.DEVNULL, capture_output=True, creationflags=flags, timeout=30)
    (clone / "設定検査.txt").write_bytes(checked.stdout + checked.stderr)
    assert checked.returncode == 0, "既存実confの隔離checkに失敗"
    expected_s01 = sum(item["day"] == "NK225_S01" for item in expected)
    assert checked.stdout.count(b"NK225_S01") >= expected_s01
    assert not server.records, "既存実confのcheck中にcontrollerへ要求が出た"
    runtime = set_scalar(set_scalar(source, "startup", "action", "run"), "startup", "duration_seconds", 10)
    config_path.write_text(runtime, encoding="utf-8")
    isolated_sources = {p.name: digest(p) for p in (clone / "conf").glob("*.toml")}
    process = None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    origin = f"http://127.0.0.1:{port}"
    try:
        with (clone / "Web検査.txt").open("wb") as output:
            process = subprocess.Popen([str(clone / "sessiontrader.exe")], cwd=clone, stdin=subprocess.DEVNULL, stdout=output, stderr=output, creationflags=flags)
            deadline = time.monotonic() + 6
            while True:
                assert process.poll() is None, "既存実confのREST起動前に終了"
                try:
                    settings = fetch_json(opener, origin, "/api/settings")
                    break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() >= deadline:
                        raise AssertionError("既存実confのWebが起動しない")
                    time.sleep(0.1)
            got = {item["product"]: item for item in settings["instruments"]}
            assert set(got) == {item["product"] for item in expected} and len(got) == 5
            for item in expected:
                actual = got[item["product"]]
                for key in ("day", "night", "max_per_side", "mode"):
                    assert actual[key] == item[key], (item["product"], key, actual[key], item[key])
                assert (actual.get("windows") or []) == (item.get("windows") or []), item["product"]
            # 安全のため差し替えた項目以外の明示された公開設定は保持されることを確認する。
            changed = {(section, key) for section, key, _ in safety}
            for section in ("controller", "schedule", "runtime", "web"):
                for key, value in original.get(section, {}).items():
                    if (section, key) not in changed and key in settings[section]:
                        assert settings[section][key] == value, (section, key)
            assert settings["controller"]["base_url"] == mock_url
            catalog = fetch_json(opener, origin, "/api/rules")
            check_catalog(catalog)
            state = fetch_json(opener, origin, "/api/state")
            assert all(p["mode"] == "off" and p["active_mode"] == "off" and not p["enabled"] and not p["pending"] and p["snapshot"] is None for p in state["products"])
            state.pop("csrf_token", None)
            exit_code = process.wait(timeout=18)
            assert exit_code == 0, "既存実confの隔離運転が正常終了しなかった"
        assert not server.records
        assert all(digest(clone / "conf" / name) == sha for name, sha in isolated_sources.items()), "Loadだけで隔離実confが書換わった"
        return {"passed": True, "isolation": relative(clone), "configuration_exit_code": checked.returncode, "exit_code": exit_code, "source_files": list(sources), "original_settings": original, "allowed_migrations": transitions, "original_custom_values_preserved_except_safety_overrides": True, "safety_overrides": safety + [("trading", "dryrun", True), ("startup", "action", "check/run"), ("startup", "duration_seconds", 10), ("instruments", "mode", "off")], "settings": settings, "state": state, "configuration_unchanged_during_load": True}
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def save_result(result: dict, result_path: Path) -> None:
    """実行成否と限界をJSON・簡潔な日本語MDへ保存する。

    引数: result(dict)は検査結果、result_path(Path)はJSON保存先。
    返り値: None。未実行や異常終了を成功と表示しない。
    """
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    checks = result.get("checks", {})
    lines = ["# Windows配布版の隔離確認", "", "結果: " + ("成功" if result["passed"] else "失敗"), ""]
    labels = {"configuration": "標準sampleの設定検査", "standard_settings": "全5商品の標準設定", "existing_configuration": "既存実confの隔離checkと許可された移行・独自値の保持", "catalog": "S01を含む9実ルールのREST", "all_off": "全5商品OFF", "graceful_exit": "期限到達で正常終了", "zero_controller_requests": "ローカル模擬controllerへの要求0件", "source_unchanged": "配布元の実行ファイル・設定・ルールを変更しない"}
    for key, label in labels.items():
        lines.append(f"- {label}: {'確認済み' if checks.get(key) else '未確認又は不合格'}")
    lines += ["", "実サービスへの接続先を設定せず、API書込も行っていません。売買・実約定・市場接続の確認ではありません。", "Linux実行ファイルはこのWindows環境では実行していません。", "", f"詳細: [{result_path.name}]({result_path.name})"]
    if result.get("error"):
        lines += ["", "失敗理由: " + result["error"]]
    result_path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """配布済みWindowsバイナリを新しい隔離フォルダで確認する。

    引数: なし。返り値: None。ビルドや金融再生を行わず、全商品OFFの読み取りだけを行う。
    実行は親担当の配布ビルド完了通知後に限る。既存実行資料は上書きしない。
    """
    assert os.name == "nt", "Windows配布版だけを実行する検査です"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    clone = HERE / ("binary_smoke_" + stamp)
    result_path = HERE / ("配布確認155_" + stamp + ".json")
    result = {"passed": False, "started_at": datetime.now().astimezone().isoformat(), "checks": {}, "linux_execution": "未実行", "external_service_configured": False, "api_writes": 0, "isolation": relative(clone)}
    process, server, thread = None, None, None
    try:
        base = APP / "dist/windows-amd64/Web"
        executable, template = base / "sessiontrader.exe", base / "conf/settings.toml.sample"
        assert executable.is_file() and template.is_file(), "先に配布ビルドが必要です"
        protected_paths = [executable] + sorted((base / "conf").rglob("*.toml")) + [template]
        protected = {relative(path): digest(path) for path in protected_paths}
        result["source_sha256"] = protected
        source = template.read_text(encoding="utf-8-sig")
        original = tomllib.loads(source)
        check_settings(original)
        assert original["settings_version"] == 1
        clone.mkdir(exist_ok=False)
        (clone / "conf").mkdir()
        shutil.copy2(executable, clone / "sessiontrader.exe")
        shutil.copytree(base / "conf/rules", clone / "conf/rules")
        assert not (clone / "conf/web-ui.toml").exists()
        assert digest(clone / "sessiontrader.exe") == protected[relative(executable)]

        # ----------------------------------------
        server = ThreadingHTTPServer(("127.0.0.1", 0), MockController)
        server.records, server.records_lock = [], threading.Lock()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        mock_url = f"http://127.0.0.1:{server.server_port}"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        for section, key, value in [
            ("controller", "base_url", mock_url), ("web", "host", "127.0.0.1"), ("web", "port", port),
            ("runtime", "data_directory", "data"), ("runtime", "log_directory", "log"),
            ("trading", "dryrun", True), ("startup", "action", "check"),
        ]:
            source = set_scalar(source, section, key, value)
        isolated = tomllib.loads(source)
        check_settings(isolated)
        assert isolated["controller"]["base_url"] == mock_url and isolated["web"]["host"] == "127.0.0.1"
        assert isolated["trading"]["dryrun"] is True
        config_path = clone / "conf/settings.toml"
        config_path.write_text(source, encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW
        checked = subprocess.run([str(clone / "sessiontrader.exe")], cwd=clone, stdin=subprocess.DEVNULL, capture_output=True, creationflags=flags, timeout=30)
        (clone / "設定検査.txt").write_bytes(checked.stdout + checked.stderr)
        assert checked.returncode == 0, "配布exeの設定検査失敗"
        assert checked.stdout.count(b"NK225_S01") >= 3 and checked.stdout.count(b"NK225_P05") >= 3
        result["checks"]["configuration"] = True
        assert not server.records, "設定検査中にcontrollerへ要求が出た"

        # ----------------------------------------
        runtime = set_scalar(source, "startup", "action", "run")
        runtime = set_scalar(runtime, "startup", "duration_seconds", 10)
        config_path.write_text(runtime, encoding="utf-8")
        result["isolation_config_sha256"] = digest(config_path)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        origin = f"http://127.0.0.1:{port}"
        with (clone / "Web検査.txt").open("wb") as output:
            process = subprocess.Popen([str(clone / "sessiontrader.exe")], cwd=clone, stdin=subprocess.DEVNULL, stdout=output, stderr=output, creationflags=flags)
            deadline = time.monotonic() + 6
            while True:
                assert process.poll() is None, "REST起動前にプロセスが終了した"
                try:
                    settings = fetch_json(opener, origin, "/api/settings")
                    break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() >= deadline:
                        raise AssertionError("配布Webが制限時間内に起動しない")
                    time.sleep(0.1)
            check_settings(settings)
            assert settings["controller"]["base_url"] == mock_url
            result["checks"]["standard_settings"] = True
            catalog = fetch_json(opener, origin, "/api/rules")
            check_catalog(catalog)
            result["checks"]["catalog"] = True
            state = fetch_json(opener, origin, "/api/state")
            assert len(state["products"]) == 5
            assert all(p["mode"] == "off" and p["active_mode"] == "off" and not p["enabled"] and not p["pending"] and p["snapshot"] is None for p in state["products"])
            result["checks"]["all_off"] = True
            state.pop("csrf_token", None)
            result["settings"], result["catalog"], result["state"] = settings, catalog, state
            result["exit_code"] = process.wait(timeout=18)
            assert result["exit_code"] == 0, "通常の期限到達で正常終了しなかった"
            result["checks"]["graceful_exit"] = True
        assert not server.records, "全商品OFFにもかかわらずcontrollerへ要求が出た"
        result["existing_configuration"] = check_existing_configuration(base, HERE / ("existing_conf_smoke_" + stamp), mock_url, server)
        result["checks"]["existing_configuration"] = True
        result["checks"]["zero_controller_requests"] = True
        assert all(digest(ROOT / path) == sha for path, sha in protected.items()), "配布元が検査中に変更された"
        result["checks"]["source_unchanged"] = True
        result["passed"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
            result["forced_termination"] = True
        if server is not None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            result["controller_requests"] = server.records
        result["finished_at"] = datetime.now().astimezone().isoformat()
        save_result(result, result_path)
    print(json.dumps({"passed": result["passed"], "result": relative(result_path), "controller_request_count": len(result.get("controller_requests", [])), "linux_execution": "未実行"}, ensure_ascii=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
