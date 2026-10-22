"""119v2の保存台帳を独立会計し、既所有の気配だけで実約定と資産を照合する。"""

from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
V2 = HERE.parent
BASE = V2.parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE / "audit_result119"))
import saved_accounting as audit
import recover_saved as recovery

READS = dict(結果=0, v2cache=0, 既所有v1cache=0, 原市場=0, 原cache追加=0, 金融再実行=0)


# ----------------------------------------


def write(path: Path, value: dict) -> dict:
    """
    機能: 新規監査の有限JSONを保存し、同bytes指紋を返す。
    引数: path(Path)、value(dict) は所有監査資料。
    返り値: dict はpath・bytes・SHA256。既存結果を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return dict(path=path.relative_to(ROOT).as_posix(), bytes=len(payload), SHA256=audit.sha(payload))


def load_arrays(path: Path, expected_sha: str, destination: Path | None = None) -> dict:
    """
    機能: 保存cacheを一読し、同bytes指紋・前後statを検査する。
    引数: path(Path)、expected_sha(str)、destination(Path|None) は許可された保存入力と新保全先。
    返り値: dict[str,ndarray]。元市場データ又は売買エンジンを再実行しない。
    """
    before = path.stat()
    payload = path.read_bytes()
    after = path.stat()
    audit.check((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "読取前後cache不変")
    audit.check(audit.sha(payload) == expected_sha, "保存cache同bytes")
    if destination is not None:
        assert not destination.exists()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    with np.load(BytesIO(payload), allow_pickle=False) as saved:
        return {name: saved[name].copy() for name in saved.files}


def entry_protection(ledger: np.ndarray, bars: dict, quotes: dict, symbol: str, mode: int) -> None:
    """
    機能: 新規保護bitのある保存約定が、判断時審査と固定上限内であることを照合する。
    引数: ledger(float[:,16])、bars/quotes(dict)、symbol(str)、mode(int)。
    返り値: None。未約定注文の取消数を台帳から捏造しない。
    """
    if not (mode & 1):
        return
    tick, order_tick = (.5, .25) if symbol == "TOPIX" else (10., 5.)
    for parent in np.unique(ledger[:, 0]):
        first = ledger[ledger[:, 0] == parent][0]
        b, d = int(first[14]), int(first[5])
        decision_row = bars["pub_raw_row"][b]
        q = int(np.searchsorted(quotes["row"], decision_row, side="right")) - 1
        audit.check(q >= 0 and quotes["row"][q] <= decision_row, "新規審査は判断以前の気配")
        audit.check(0 <= bars["pub_price_time_s"][b] - quotes["time"][q] <= 60., "判断気配の鮮度")
        anchor = bars["anchor"][b]
        side = quotes["ask"][q] if d == 1 else quotes["bid"][q]
        audit.check(quotes["ask"][q] - quotes["bid"][q] <= 2. * tick + 1e-9, "新規審査の気配幅")
        audit.check(abs(side - anchor) <= 2. * tick + 1e-9, "新規審査のLast距離")
        raw = anchor + d * 2. * tick
        limit = (math.floor(raw / order_tick) if d == 1 else math.ceil(raw / order_tick)) * order_tick
        audit.check(first[7] <= limit + 1e-9 if d == 1 else first[7] >= limit - 1e-9, "実約定は当初固定上限内")


def episodes(ledger: np.ndarray, quotes: dict, bars: dict, multiplier: float, saved: list[dict]) -> None:
    """
    機能: 保存した各親のLast分解と実気配経路が返済台帳と一致するか確認する。
    引数: ledger(float[:,16])、quotes/bars(dict)、multiplier(float)、saved(list[dict])。
    返り値: None。事後極値を利益へ転用せず、同時刻の費用分解だけを照合する。
    """
    ids = np.unique(ledger[:, 0]).astype(int)
    audit.check([episode["parent"] for episode in saved] == ids.tolist(), "親診断の対象一致")
    for parent, episode in zip(ids, saved):
        legs = ledger[ledger[:, 0] == parent]
        first, final = legs[0], legs[-1]
        a, z = np.searchsorted(quotes["row"], [int(first[1]), int(final[2])])
        d, qty = int(first[5]), float(sum(legs[:, 6]))
        own_side = quotes["bid"][a:z + 1] if d == 1 else quotes["ask"][a:z + 1]
        path = d * (own_side - first[7])
        gl = ea = xa = 0.
        for leg in legs:
            q = int(np.searchsorted(quotes["row"], int(leg[2])))
            units = leg[6] * multiplier
            gl += d * (quotes["last"][q] - quotes["last"][a]) * units
            ea += d * (leg[7] - quotes["last"][a]) * units
            xa += d * (quotes["last"][q] - leg[8]) * units
        b = int(first[14])
        expected = dict(direction=d, quantity=qty, entry_raw=int(first[1]), entry_time=first[3], entry=first[7],
            entry_last=quotes["last"][a], entry_bid=quotes["bid"][a], entry_ask=quotes["ask"][a],
            signal_bar=b, prior20_change=bars["close"][b] - bars["close"][b - 20] if b >= 20 else None,
            final_time=final[4], MFE_observed=float(max(path)), MAE_observed=float(min(path)),
            gross_last_same_times=gl, entry_adverse=ea, exit_adverse=xa,
            fees=float(sum(legs[:, 10]) + sum(legs[:, 11])), net=float(sum(legs[:, 12])))
        audit.compare_mapping(episode, expected, "各親のLastと気配差分解")
        audit.near(gl - ea - xa - expected["fees"], expected["net"], "Last分解恒等式")
        audit.check(len(episode["legs"]) == len(legs), "親内の返済明細数")
        for given, leg in zip(episode["legs"], legs):
            q = int(np.searchsorted(quotes["row"], int(leg[2])))
            audit.compare_mapping(given, dict(exit_raw=int(leg[2]), exit_time=leg[4], quantity=leg[6], exit=leg[8],
                bid=quotes["bid"][q], ask=quotes["ask"][q], last=quotes["last"][q],
                reason=int(leg[13]), net=leg[12], decision_to_fill=leg[15]), "親内全返済明細")


def main(expected_sha: str) -> None:
    """
    機能: root指定SHAの完成結果と80小cacheを各一読し、2880場会計を独立照合する。
    引数: expected_sha(str) は完成後に指定された結果指紋。
    返り値: None。原市場・旧cache原本・金融ルールの追加再実行は0。
    """
    audit.check(len(expected_sha) == 64, "完成後指定SHA")
    owned = HERE / "owned"
    owned.mkdir(exist_ok=False)
    path = V2 / "measurement/復帰確認と執行保護の全四十場.json"
    payload = path.read_bytes()
    READS["結果"] += 1
    audit.check(audit.sha(payload) == expected_sha, "結果同bytes")
    (owned / "完成結果.json").write_bytes(payload)
    result = json.loads(payload.decode("utf-8"))
    fixed = json.loads((V2 / "固定計画.json").read_text(encoding="utf-8"))
    manifest_path = ROOT / fixed["input_manifest"]["path"]
    manifest_bytes = manifest_path.read_bytes()
    audit.check(audit.sha(manifest_bytes) == fixed["input_manifest"]["sha256"], "事前入力目録")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    (owned / "事前入力目録.json").write_bytes(manifest_bytes)
    audit.check(result["source_SHA256"] == fixed["sources"], "結果と固定源一致")
    for p, expected in fixed["sources"].items():
        audit.check(audit.sha((ROOT / p).read_bytes()) == expected, "凍結経済源不変")
    audit.check(result["sessions"] == manifest["sessions"] and len(result["sessions"]) == 40, "固定40場")
    audit.check(len(result["specs"]) == len({r["id"] for r in result["specs"]}) == 36, "36政策")
    audit.check(len(result["runs"]) == 2880 and len(result["cache"]) == len(result["reads"]) == 80, "2880会計と80cache")
    audit.check(result["原市場追加読取"] == result["API"] == result["実注文"] == 0, "原市場/API/注文なし")
    lookup = {(r["symbol"], r["session"], r["method"]): r for r in result["runs"]}
    episode_lookup = {(r["symbol"], r["session"], r["method"]): r for r in result["episodes"]}
    audit.check(len(lookup) == len(episode_lookup) == 2880, "重複又は診断欠落なし")
    prior_inputs = {(r["symbol"], r["session"]): r for r in manifest["inputs"]}
    prior_nets = {(r["symbol"], r["session"]): r["net"] for r in manifest["old_main_runs"]}
    audit.check(len(prior_nets) == 80 and manifest["result_SHA256"] == "13bdd30ecf5ad8dd12ce4d8f0aec96a025e7bd1bb36e33fa8b30bc02de0d2c15", "旧選択80行の比較元固定")
    unclosed = []
    certificates = []
    for cache in result["cache"]:
        source_path = ROOT / cache["path"]
        symbol, scene = source_path.parent.name, source_path.stem
        audit.check(source_path.resolve().is_relative_to(V2 / "measurement"), "v2cache所有領域")
        arrays = load_arrays(source_path, cache["SHA256"], owned / "v2cache" / symbol / (scene + ".npz"))
        READS["v2cache"] += 1
        prior = prior_inputs[symbol, scene]
        old_path = ROOT / prior["owned_path"]
        audit.check(old_path.resolve().is_relative_to(BASE / "audit_result119/recovered_owned/prepared"), "気配は既所有copyだけ")
        previous = load_arrays(old_path, prior["SHA256"])
        READS["既所有v1cache"] += 1
        bars = {key[6:]: value for key, value in previous.items() if key.startswith("bars__")}
        quotes = {key[8:]: value for key, value in previous.items() if key.startswith("quotes__")}
        audit.check(arrays["ledger"].shape[1] == 17 and np.isin(arrays["ledger"][:, 0], np.arange(36)).all(), "17列と政策index")
        audit.check(arrays["equity"].shape == arrays["position"].shape == (36, len(bars["valid"])), "公開資産shape")
        qty, multiplier, fee, _ = audit.CONTRACTS[symbol]
        all_flat = True
        for k, spec in enumerate(result["specs"]):
            saved = lookup[symbol, scene, spec["id"]]
            ledger = arrays["ledger"][arrays["ledger"][:, 0] == k, 1:]
            certificate = recovery.flat_certificate(ledger, quotes, qty, scene)
            audit.check(certificate["保証"], "閉場後2原rowと全親返済数量")
            if saved["unclosed"]:
                unclosed.append(dict(symbol=symbol, session=scene, method=spec["id"], unclosed=saved["unclosed"]))
                all_flat = False
            account = audit.accounting(ledger, qty, multiplier, fee, saved["unclosed"])
            audit.compare_mapping(saved, account, "v2全会計の親net/費用/現金")
            audit.near(saved["signals"], np.count_nonzero(arrays["policies__entry"][k]), "入口事象数")
            if saved["unclosed"] == 0:
                mark = audit.quote_account(ledger, bars, quotes, qty, multiplier, fee, dict(spec, entry_mode=0),
                    arrays["policies__width"][k], arrays["policies__valid"][k])
                audit.near(arrays["equity"][k], mark["equity"], "公開時清算資産")
                audit.near(arrays["position"][k], mark["position"], "公開時保有方向")
                audit.near(saved["max_drawdown"], mark["max_drawdown"], "全quote最大資産下落")
            entry_protection(ledger, bars, quotes, symbol, spec["execution_mode"])
            episodes(ledger, quotes, bars, multiplier, episode_lookup[symbol, scene, spec["id"]]["parents"])
            if spec["id"] == "BASELINE_P0":
                audit.near(saved["net"], prior_nets[symbol, scene], "旧選択単体80netの完全同値")
        certificates.append(dict(symbol=symbol, session=scene, 全36政策未返済なし=all_flat))
        print(json.dumps(dict(cache組=len(certificates), symbol=symbol, session=scene, 検査数=audit.CHECKS), ensure_ascii=False), flush=True)
    all_metrics = []
    for symbol in audit.CONTRACTS:
        for spec in result["specs"]:
            rows = [lookup[symbol, scene, spec["id"]] for scene in result["sessions"]]
            all_metrics.append(dict(symbol=symbol, method=spec["id"], periods={name: audit.metrics([r for r in rows if r["session"] in scenes])
                               for name, scenes in result["splits"].items()}))
    audit.check(READS == dict(結果=1, v2cache=80, 既所有v1cache=80, 原市場=0, 原cache追加=0, 金融再実行=0), "許可範囲だけの一読")
    metrics_meta = write(HERE / "三十六政策と全四十場の独立指標.json", dict(結果SHA256=expected_sha, metrics=all_metrics))
    proof = dict(全合格=True, 検査数=audit.CHECKS, counts=READS, 結果SHA256=expected_sha,
                 未返済=unclosed, 未返済成功扱い=False, 旧単体BASELINE_P0比較=80, 全2880場会計=True,
                 source_SHA256=fixed["sources"], 監査源SHA256=audit.sha(Path(__file__).read_bytes()),
                 算術源SHA256=audit.sha(Path(audit.__file__).read_bytes()), outputs=[metrics_meta], 場別確認=certificates,
                 限界="保存会計の独立照合。金融再実行0・独立標本追加0。未約定の取消/保護待機回数は台帳だけで再生成しない。")
    write(HERE / "三十六政策の会計と旧単体同値及び全場資産の独立監査.json", proof)
    print(json.dumps(dict(全合格=True, 検査数=audit.CHECKS, counts=READS, 未返済=len(unclosed)), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    try:
        main(args.expected_sha)
    except BaseException as exc:
        write(HERE / "False.json", dict(全合格=False, 検査数=audit.CHECKS, counts=READS,
                                         型=type(exc).__name__, 例外=str(exc)))
        raise
