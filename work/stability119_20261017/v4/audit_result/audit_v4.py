"""119v4の保存会計だけを、既監査の算術源と所有済み気配で独立照合する。"""

from __future__ import annotations

import argparse
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np


HERE = Path(__file__).resolve().parent
V4 = HERE.parent
BASE = V4.parent
ROOT = BASE.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(BASE / "audit_result119"))
import saved_accounting as audit
import recover_saved as recovery

HELPER_PATH = BASE / "v2/audit_result/audit_v2.py"
HELPER_SPEC = importlib.util.spec_from_file_location("independent_saved_v2_accounting_for_v4", HELPER_PATH)
helper = importlib.util.module_from_spec(HELPER_SPEC)
HELPER_SPEC.loader.exec_module(helper)

ARITHMETIC_SHA = "2513dee4689ca5650e579e707f05a7e3e97b5af5d54f1d358fef99eb261732a8"
HELPER_SHA = "88ed70651a7d839b8ad89618161e064ef9a18b2524ffe174ded719695032f17f"
READS = dict(結果=0, v4cache=0, 既所有v1cache=0, 原市場=0, 原cache追加=0, 金融再実行=0)
POLICY_KEYS = ("entry", "exit_long", "exit_short", "width", "valid")


# ----------------------------------------


def write(path: Path, value: dict) -> dict:
    """
    機能: 所有監査領域に新しい有限JSONを保存し指紋を返す。
    引数: path(Path) は新規保存先、value(dict) は監査資料。
    返り値: dict はpath・bytes・SHA256。既存証跡は上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return dict(path=path.relative_to(ROOT).as_posix(), bytes=len(payload), SHA256=audit.sha(payload))


def expected_quiet(publication_times: np.ndarray) -> np.ndarray:
    """
    機能: 固定された日本及び米国の時刻窓を公開時計から独立に構成する。
    引数: publication_times(ndarray[float]) は公開価格時計のepoch秒。
    返り値: ndarray[bool]。休日例外なし、夏時間はIANAのAmerica/New_York。
    """
    quiet = np.zeros(len(publication_times), bool)
    tokyo, new_york = ZoneInfo("Asia/Tokyo"), ZoneInfo("America/New_York")
    for i, epoch in enumerate(publication_times):
        if not np.isfinite(epoch):
            continue
        jp = datetime.fromtimestamp(float(epoch), tokyo)
        ny = datetime.fromtimestamp(float(epoch), new_york)
        jp_clock = (jp.hour, jp.minute, jp.second, jp.microsecond)
        ny_clock = (ny.hour, ny.minute, ny.second, ny.microsecond)
        quiet[i] = ((8, 45, 0, 0) <= jp_clock < (9, 15, 0, 0)
                    or (8, 15, 0, 0) <= ny_clock < (8, 45, 0, 0)
                    or (9, 15, 0, 0) <= ny_clock < (9, 45, 0, 0))
    return quiet


def expected_specs(source_specs: list[dict]) -> list[dict]:
    """
    機能: 事前に固定した三入口から48条件の識別子と接続指定を独立に列挙する。
    引数: source_specs(list[dict]) は入力目録の三つの元入口。
    返り値: list[dict] は結果specで必ず一致すべき欄。金融値を使わない。
    """
    families = ("COMMON", "OPEN", "LAG")
    audit.check([s["id"] for s in source_specs] == [f"{f}_L20_X0_E0_G0" for f in families], "元三入口固定")
    specs = []
    for family, source in zip(families, source_specs):
        for direction, suffix in (("direct", "DIR"), ("reverse", "REV")):
            for exit_mode in (5, 4):
                for execution in (0, 3):
                    for time_mode in (0, 1):
                        specs.append(dict(id=f"{family}20_{suffix}_X{exit_mode}_P{execution}_T{time_mode}",
                            family=family + "20", entry_id=family + "20", source_policy_id=source["id"],
                            direction_mode=direction, exit_mode=exit_mode, execution_mode=execution,
                            time_mode=time_mode, guard=2))
    return specs


def transformed_policy(previous: dict, source_index: int, spec: dict, quiet: np.ndarray) -> dict:
    """
    機能: 元保存方針の順逆及び時刻窓の単純変換だけを独立に構成する。
    引数: previous(dict) は既所有の元配列、source_index(int)、spec(dict)、quiet(bool配列)。
    返り値: dict[str,ndarray]。入口検知及び金融再生を行わず、元配列を上書きしない。
    """
    reverse = spec["direction_mode"] == "reverse"
    out = {}
    for key in POLICY_KEYS:
        source_key = {"exit_long": "exit_short", "exit_short": "exit_long"}.get(key, key) if reverse else key
        out[key] = previous["policies__" + source_key][source_index].copy()
    if reverse:
        out["entry"] = -out["entry"]
    if spec["time_mode"]:
        out["entry"][quiet] = 0
        out["valid"][quiet] = False
        out["exit_long"][quiet] = True
        out["exit_short"][quiet] = True
    return out


# ----------------------------------------


def pure() -> None:
    """
    機能: 新adapterの時刻境界及び保存方針変換だけを小人工素材で検査する。
    引数: なし。市場、元cache、結果本文は読まない。
    返り値: None。旧会計源の再試験を新しい有効性標本には数えない。
    """
    audit.check(audit.sha(Path(audit.__file__).read_bytes()) == ARITHMETIC_SHA, "旧算術源不変")
    audit.check(audit.sha(HELPER_PATH.read_bytes()) == HELPER_SHA, "旧v2監査補助源不変")
    fixtures = [("2026-10-16T08:44:59.999999+09:00", False), ("2026-10-16T08:45:00+09:00", True),
                ("2026-10-16T09:14:59+09:00", True), ("2026-10-16T09:15:00+09:00", False),
                ("2026-10-16T08:14:59-04:00", False), ("2026-10-16T08:15:00-04:00", True),
                ("2026-10-16T08:45:00-04:00", False), ("2026-10-16T09:15:00-04:00", True),
                ("2026-10-16T09:45:00-04:00", False), ("2026-12-16T08:15:00-05:00", True),
                ("2026-12-16T08:45:00-05:00", False)]
    times = np.asarray([datetime.fromisoformat(clock).timestamp() for clock, _ in fixtures] + [np.nan])
    audit.check(np.array_equal(expected_quiet(times), [value for _, value in fixtures] + [False]), "JP/NY境界と冬夏時刻及び未知時計")
    source = {"policies__entry": np.asarray([[1, 0, -1]], np.int8),
              "policies__exit_long": np.asarray([[False, True, False]]),
              "policies__exit_short": np.asarray([[True, False, False]]),
              "policies__width": np.asarray([[2., np.nan, 3.]]),
              "policies__valid": np.asarray([[True, False, True]])}
    before = {key: value.copy() for key, value in source.items()}
    policy = transformed_policy(source, 0, dict(direction_mode="reverse", time_mode=1), np.asarray([False, False, True]))
    audit.check(policy["entry"].tolist() == [-1, 0, 0], "反対方向と警戒窓の新規抑制")
    audit.check(policy["exit_long"].tolist() == [True, False, True]
                and policy["exit_short"].tolist() == [False, True, True], "退出方向交換と警戒窓の退出独立")
    audit.check(policy["valid"].tolist() == [True, False, False], "警戒窓の入口資格無効")
    audit.near(policy["width"], source["policies__width"][0], "risk幅は順逆でも不変")
    audit.check(all(np.array_equal(value, before[key], equal_nan=True) for key, value in source.items()), "元配列不変")
    specs = expected_specs([dict(id=f"{family}_L20_X0_E0_G0") for family in ("COMMON", "OPEN", "LAG")])
    audit.check(len(specs) == len({s["id"] for s in specs}) == 48, "3入口×2方向×2出口×2執行×2時刻")
    write(HERE / "adapterだけの時刻境界と順逆保存配列の純人工.json", dict(全合格=True,
        検査数=audit.CHECKS, 市場読取=0, 結果読取=0, cache読取=0, 金融再実行=0,
        監査源SHA256=audit.sha(Path(__file__).read_bytes()), 算術源SHA256=ARITHMETIC_SHA,
        v2補助源SHA256=HELPER_SHA, 留保="新しい効果検証ではなく、保存台帳監査adapterのみの純人工確認。"))
    print(json.dumps(dict(全合格=True, 検査数=audit.CHECKS), ensure_ascii=False))


def main(expected_sha: str) -> None:
    """
    機能: root指定の完成結果と80小cacheを各一読保全し、3840場会計を独立照合する。
    引数: expected_sha(str) はrootが完成後に指定した結果指紋。
    返り値: None。元市場と旧原cacheを読まず、金融再実行及び候補の再選択は0。
    """
    audit.check(len(expected_sha) == 64, "完成後指定SHA必須")
    audit.check(audit.sha(Path(audit.__file__).read_bytes()) == ARITHMETIC_SHA, "旧算術源不変")
    audit.check(audit.sha(HELPER_PATH.read_bytes()) == HELPER_SHA, "旧v2監査補助源不変")
    owned = HERE / "owned"
    owned.mkdir(exist_ok=False)
    path = V4 / "measurement/広い進行条件の順逆比較と全四十場.json"
    payload = path.read_bytes()
    READS["結果"] += 1
    audit.check(audit.sha(payload) == expected_sha, "完成結果同bytes")
    (owned / "完成結果.json").write_bytes(payload)
    result = json.loads(payload.decode("utf-8"))
    fixed = json.loads((V4 / "固定計画.json").read_text(encoding="utf-8"))
    manifest_bytes = (ROOT / fixed["input_manifest"]["path"]).read_bytes()
    audit.check(audit.sha(manifest_bytes) == fixed["input_manifest"]["sha256"], "固定入力目録不変")
    (owned / "事前入力目録.json").write_bytes(manifest_bytes)
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    audit.check(result["source_SHA256"] == fixed["sources"], "結果と固定経済源一致")
    for source_path, sha in fixed["sources"].items():
        audit.check(audit.sha((ROOT / source_path).read_bytes()) == sha, "凍結経済源不変")
    audit.check(result["sessions"] == manifest["sessions"] and len(set(result["sessions"])) == 40, "固定40場")
    audit.check(result["splits"] == manifest["splits"], "事前期間区分不変")
    specs = result["specs"]
    expected = expected_specs(manifest["source_specs"])
    audit.check(len(specs) == len({spec["id"] for spec in specs}) == 48, "48政策識別子")
    for spec, keys in zip(specs, expected):
        audit.check(all(spec[key] == value for key, value in keys.items()), "48政策の固定順と元三入口接続")
    audit.check(len(result["runs"]) == len(result["episodes"]) == 3840 and len(result["cache"]) == len(result["reads"]) == 80, "3840場と80保存入力")
    audit.check(result["原市場追加読取"] == result["API"] == result["実注文"] == 0, "市場/API/実注文0")
    pairs = {(symbol, scene) for symbol in audit.CONTRACTS for scene in result["sessions"]}
    lookup = {(r["symbol"], r["session"], r["method"]): r for r in result["runs"]}
    episode_lookup = {(r["symbol"], r["session"], r["method"]): r for r in result["episodes"]}
    cache_lookup = {(r["symbol"], r["session"]): r for r in result["cache"]}
    input_lookup = {(r["symbol"], r["session"]): r for r in manifest["inputs"]}
    read_lookup = {(r["symbol"], r["session"]): r for r in result["reads"]}
    audit.check(len(lookup) == len(episode_lookup) == 3840, "会計と親診断重複なし")
    audit.check(set(cache_lookup) == set(input_lookup) == set(read_lookup) == pairs, "全80場商品に欠落重複なし")
    certificates = []
    for cache in result["cache"]:
        symbol, scene = cache["symbol"], cache["session"]
        source_path = ROOT / cache["path"]
        audit.check(source_path.resolve().is_relative_to(V4 / "measurement"), "v4小cache所有領域")
        audit.check(source_path.parent.name == symbol and source_path.stem == scene, "小cache識別一致")
        arrays = helper.load_arrays(source_path, cache["SHA256"], owned / "v4cache" / symbol / (scene + ".npz"))
        READS["v4cache"] += 1
        prior = input_lookup[symbol, scene]
        old_path = ROOT / prior["owned_path"]
        audit.check(old_path.resolve().is_relative_to(BASE / "audit_result119/recovered_owned/prepared"), "気配は既所有copyだけ")
        read_log = read_lookup[symbol, scene]
        audit.check(read_log["source"] == prior["owned_path"] and read_log["SHA256"] == prior["SHA256"]
                    and read_log["bytes"] == prior["bytes"] and read_log["original_market_reads"] == 0, "保存入力読取由来")
        previous = helper.load_arrays(old_path, prior["SHA256"])
        READS["既所有v1cache"] += 1
        bars = {key[6:]: value for key, value in previous.items() if key.startswith("bars__")}
        quotes = {key[8:]: value for key, value in previous.items() if key.startswith("quotes__")}
        audit.check(arrays["ledger"].ndim == 2 and arrays["ledger"].shape[1] == 17
                    and np.isin(arrays["ledger"][:, 0], np.arange(48)).all(), "17列台帳と政策index範囲")
        audit.check(arrays["equity"].shape == arrays["position"].shape == (48, len(bars["valid"])), "公開資産shape")
        quiet = expected_quiet(bars["pub_price_time_s"])
        audit.check(np.array_equal(arrays["time_quiet"], quiet), "公開時計の固定窓")
        audit.check(all(arrays["policies__" + key].shape == (48, len(quiet)) for key in POLICY_KEYS), "保存方針shape")
        quantity, multiplier, fee, _ = audit.CONTRACTS[symbol]
        for k, spec in enumerate(specs):
            source_index = manifest["source_indexes"][manifest["source_ids"].index(spec["source_policy_id"])]
            policy = transformed_policy(previous, source_index, spec, quiet)
            for key in POLICY_KEYS:
                audit.near(arrays["policies__" + key][k], policy[key], "元保存方針との順逆・時刻変換:" + key)
            saved = lookup[symbol, scene, spec["id"]]
            ledger = arrays["ledger"][arrays["ledger"][:, 0] == k, 1:]
            audit.check(saved["unclosed"] == 0, "未返済を成功扱いしない")
            certificate = recovery.flat_certificate(ledger, quotes, quantity, scene)
            audit.check(certificate["保証"], "閉場後2正常原row及び全親返済数量")
            account = audit.accounting(ledger, quantity, multiplier, fee, saved["unclosed"])
            audit.compare_mapping(saved, account, "v4全場の親net・費用・現金")
            audit.near(saved["signals"], np.count_nonzero(policy["entry"]), "入口事象数")
            for parent in np.unique(ledger[:, 0]):
                first = ledger[ledger[:, 0] == parent][0]
                audit.check(policy["entry"][int(first[14])] == first[5], "約定方向は当時の保存入口方向")
            mark = audit.quote_account(ledger, bars, quotes, quantity, multiplier, fee, dict(spec, entry_mode=0), policy["width"], policy["valid"])
            audit.near(arrays["equity"][k], mark["equity"], "公開時の費用後清算資産")
            audit.near(arrays["position"][k], mark["position"], "公開時保有方向")
            audit.near(saved["max_drawdown"], mark["max_drawdown"], "全気配の最大資産下落")
            helper.entry_protection(ledger, bars, quotes, symbol, spec["execution_mode"])
            helper.episodes(ledger, quotes, bars, multiplier, episode_lookup[symbol, scene, spec["id"]]["parents"])
        certificates.append(dict(symbol=symbol, session=scene, 全48政策未返済なし=True))
        print(json.dumps(dict(cache組=len(certificates), symbol=symbol, session=scene, 検査数=audit.CHECKS), ensure_ascii=False), flush=True)
    all_metrics = []
    for symbol in audit.CONTRACTS:
        for spec in specs:
            rows = [lookup[symbol, scene, spec["id"]] for scene in result["sessions"]]
            all_metrics.append(dict(symbol=symbol, method=spec["id"], periods={name: audit.metrics([r for r in rows if r["session"] in scenes])
                for name, scenes in result["splits"].items()}))
    audit.check(READS == dict(結果=1, v4cache=80, 既所有v1cache=80, 原市場=0, 原cache追加=0, 金融再実行=0), "許可範囲だけの一読")
    metrics_meta = write(HERE / "四十八政策と全四十場の独立指標.json", dict(結果SHA256=expected_sha, metrics=all_metrics))
    write(HERE / "四十八政策の保存親会計と全場資産の独立監査.json", dict(全合格=True,
        検査数=audit.CHECKS, counts=READS, 結果SHA256=expected_sha, source_SHA256=fixed["sources"],
        全3840場会計=True, 未返済=[], 未返済成功扱い=False, 旧BASELINE同値要求=False,
        監査源SHA256=audit.sha(Path(__file__).read_bytes()), 算術源SHA256=ARITHMETIC_SHA,
        v2補助源SHA256=HELPER_SHA, outputs=[metrics_meta], 場別確認=certificates,
        限界="同じ保存会計の独立整合監査。金融再生0、未知データ及び新しい有効性標本0。取消等未保存情報は補完しない。"))
    print(json.dumps(dict(全合格=True, 検査数=audit.CHECKS, counts=READS, 未返済=0), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pure", action="store_true")
    parser.add_argument("--expected-sha")
    args = parser.parse_args()
    try:
        if args.pure:
            pure()
        else:
            assert args.expected_sha, "完成後の結果SHA通知が必要です。"
            main(args.expected_sha)
    except BaseException as exc:
        write(HERE / "False.json", dict(全合格=False, 検査数=audit.CHECKS, counts=READS,
                                         型=type(exc).__name__, 例外=str(exc)))
        raise
