"""最終JSONの型変換停止後、保存済み金融台帳から結果を復元する。金融再生は行わない。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import itertools
import json
import math
from pathlib import Path

import numpy as np

import saved_accounting as audit


HERE = Path(__file__).resolve().parent
OWNER = HERE.parent
ROOT = OWNER.parents[1]
RECOVERY = OWNER / "recovery119"
CACHE_SNAPSHOT = {}


# ----------------------------------------


def import_source(path: Path, name: str) -> object:
    """
    機能: 市場処理の副作用を持たない凍結された純信号源を固有名importする。
    引数: path(Path)、name(str) はcatalog又はselectorの位置と固有名。
    返り値: object は純信号モジュール。engineはimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_metadata(path: Path, destination: Path) -> tuple[object, dict]:
    """
    機能: 小さい固定・選択・読取証跡を一読して同bytes保全する。
    引数: path/destination(Path) は元の小資料と保全先。
    返り値: tuple はJSON値と同bytes指紋。
    """
    payload = path.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    assert not destination.exists()
    destination.write_bytes(payload)
    value = ([json.loads(line) for line in payload.decode("utf-8").splitlines()]
             if path.suffix == ".jsonl" else json.loads(payload.decode("utf-8")))
    return value, dict(path=path.relative_to(ROOT).as_posix(), bytes=len(payload), SHA256=audit.sha(payload))


def save_recovered(name: str, value: dict) -> dict:
    """
    機能: 元measurementと別の新規復元結果を有限JSONとして保存する。
    引数: name(str) は単一ファイル名、value(dict) は復元会計。
    返り値: dict は保存bytesのpath・SHA256・サイズ。
    """
    path = RECOVERY / name
    assert path.parent == RECOVERY and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.write_bytes(payload)
    return dict(path=path.relative_to(ROOT).as_posix(), bytes=len(payload), SHA256=audit.sha(payload))


def specifications() -> list[dict]:
    """
    機能: 凍結源へ全未知の人工足を渡し、値に依存しない252政策のメタ情報だけを再構成する。
    引数: なし。
    返り値: list[dict]。市場信号・売買・設定の再選択は行わない。
    """
    catalog = import_source(OWNER / "catalog119.py", "_recovery119_pure_catalog")
    selector = import_source(OWNER / "design/selector119.py", "_recovery119_pure_selector")
    artificial = {key: np.full(2, np.nan) for key in ("open", "high", "low", "close", "volume", "anchor", "pub_price_time_s")}
    artificial.update(t_s=np.asarray([60., 120.]), valid=np.zeros(2, dtype=bool),
                      volume_known=np.zeros(2, dtype=bool), pub_raw_row=np.full(2, -1, dtype=np.int64))
    base = catalog.build(artificial, artificial, "TOPIX", None)["specs"]
    out = []
    for original in base:
        for xm, em, guard in itertools.product(range(3), range(2), range(2)):
            s = dict(original)
            s.update(id=original["id"] + f"_X{xm}_E{em}_G{guard}", family=original["family"],
                     name=original.get("name", "全玉清算教師の自動選択"),
                     description=original.get("description", original.get("rule", "当時までの全玉清算資産から選択する。")),
                     exit_mode=xm, entry_mode=em, guard=guard, is_adaptive=False)
            out.append(s)
    teacher = [s for s in out if s["entry_mode"] == 0 and s["guard"] == 0]
    adaptive = selector.build_selectors(np.zeros((54, 2)), np.zeros((54, 2), dtype=np.int8),
        np.ones(2), [s["family"] for s in teacher], 0.)["specs"]
    for original in adaptive:
        for xm, guard in itertools.product(range(3), range(2)):
            s = dict(original)
            s.update(id=original["id"] + f"_X{xm}_E0_G{guard}", family="ADAPT",
                     name=original.get("name", "全玉清算教師の自動選択"),
                     description=original.get("description", original.get("rule", "当時までの全玉清算資産から選択する。")),
                     exit_mode=xm, entry_mode=0, guard=guard, is_adaptive=True)
            out.append(s)
    audit.check(len(out) == 252 and len({s["id"] for s in out}) == 252, "源から252IDと順序を復元")
    return out


def cutoff(scene: str) -> float:
    """
    機能: 凍結済みDay15:20又は翌05:40の返済判断締切を独立計算する。
    引数: scene(str) は開始日と場種。
    返り値: float は日本時間を表すepoch。
    """
    date, kind = scene.rsplit("_", 1)
    day = datetime.fromisoformat(date).replace(tzinfo=timezone(timedelta(hours=9)))
    end = day.replace(hour=15, minute=20) if kind == "Day" else (day + timedelta(days=1)).replace(hour=5, minute=40)
    return end.timestamp()


def flat_certificate(ledger: np.ndarray, quotes: dict, quantity: int, scene: str) -> dict:
    """
    機能: 凍結源の場末処理契約と保存台帳から、残玉ゼロを確認できるか分類する。
    引数: ledger(float[:,16])、quotes(dict)、quantity(int)、scene(str)。
    返り値: dict は保証の可否と理由。観測不足を架空の返済へ変換しない。
    """
    close_time = cutoff(scene)
    after = int(np.count_nonzero(quotes["time"] >= close_time))
    complete = all(abs(sum(ledger[ledger[:, 0] == parent, 6]) - quantity) <= 1e-9
                   for parent in np.unique(ledger[:, 0]))
    entry_before_end = bool(np.all(ledger[:, 3] < close_time - 1200.))
    return dict(保証=after >= 2 and complete and entry_before_end, 場末後正常気配=after,
                全親返済数量一致=complete, 全新規が新規締切前=entry_before_end,
                根拠="凍結源と2070純人工の契約：新規は締切20分前に停止し、close以後の正常2原rowで全残玉を返済する。")


def read_cache(path: Path, symbol: str, scene: str, group: str, destination: Path) -> tuple[dict, dict]:
    """
    機能: 保存cacheを各一読し、前後statとそのbytesの新規指紋を保全する。
    引数: path/destination(Path)、symbol/scene/group(str) は保存成果とその識別。
    返り値: tuple[dict,dict] は全配列と保全目録。作成時の未保存SHAを捏造しない。
    """
    before = path.stat()
    snapshot = CACHE_SNAPSHOT[path.relative_to(ROOT).as_posix()]
    audit.check((before.st_size, before.st_mtime_ns) == (snapshot["bytes"], snapshot["mtime_ns"]), "root事前目録とcache stat一致")
    payload = path.read_bytes()
    after = path.stat()
    audit.READS[group] += 1
    audit.check((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "cache読取前後stat一致")
    audit.check(len(payload) == before.st_size, "cacheサイズ一致")
    destination.parent.mkdir(parents=True, exist_ok=True)
    assert not destination.exists()
    destination.write_bytes(payload)
    from io import BytesIO
    with np.load(BytesIO(payload), allow_pickle=False) as saved:
        arrays = {key: saved[key].copy() for key in saved.files}
    return arrays, dict(path=path.relative_to(ROOT).as_posix(), symbol=symbol, session=scene,
                        bytes=len(payload), mtime_ns=before.st_mtime_ns, SHA256=audit.sha(payload),
                        指紋の意味="復元監査の一読bytesで初めて固定。元の最終JSONに保存された指紋ではない。")


def reconstruct(ledger: np.ndarray, bars: dict, quotes: dict, quantity: int, multiplier: float,
                fee: float, spec: dict, width: np.ndarray, valid: np.ndarray, scene: str,
                saved_equity: np.ndarray, saved_position: np.ndarray | None) -> tuple[dict, dict]:
    """
    機能: 保存台帳だけから会計とMTMを復元し、元cache資産と照合する。
    引数: ledger・bars・quotes・固定数量等と保存済み資産/方向。金融ルールの再生は行わない。
    返り値: tuple は復元summaryと残玉証明。保証不足は不明とし成功扱いしない。
    """
    certificate = flat_certificate(ledger, quotes, quantity, scene)
    if not certificate["保証"]:
        unknown = dict(net=None, realized=None, profit=None, loss=None, parents=None, wins=None,
                       losses=None, closed_quantity=None, fees=None, unclosed=None, max_drawdown=None,
                       canceled=None, fills=None, halted=None, 会計状態="未清算の有無を確定できず昇格不可")
        return unknown, certificate
    account = audit.accounting(ledger, quantity, multiplier, fee, 0)
    trace = audit.quote_account(ledger, bars, quotes, quantity, multiplier, fee, spec, width, valid)
    audit.near(saved_equity, trace["equity"], "元cacheの全公開資産と独立MTM")
    if saved_position is not None:
        audit.near(saved_position, trace["position"], "元cacheの全公開方向と独立建玉")
    account.update(max_drawdown=trace["max_drawdown"], canceled=None, halted=None,
                   会計状態="全玉返済を確認した保存台帳から復元", 未保存診断=["canceled", "halted"])
    return account, certificate


def main() -> None:
    """
    機能: rootの記録後にだけ保存160cacheを各一読し、完成JSONと独立監査を復元する。
    引数: なし。
    返り値: None。原市場再読・金融再生・追加の有効性標本は0。
    """
    destination = HERE / "recovered_owned"
    destination.mkdir(exist_ok=False)
    prior, prior_meta = read_metadata(OWNER / "保存型停止と台帳会計復元の事前記録.json", destination / "rootの復元事前記録.json")
    CACHE_SNAPSHOT.update({item["path"]: item for item in prior["規模"]})
    audit.check(len(CACHE_SNAPSHOT) == 160 and prior["完成処理原入力80"] == 80 and prior["初回初期化停止原入力2"] == 2
                and prior["合計原入力読取82"] == 82, "80完成入力と2初期化停止の由来を区別")
    inventory, inventory_meta = read_metadata(OWNER / "入力と時系列分割.json", destination / "入力と時系列分割.json")
    frozen, frozen_meta = read_metadata(OWNER / "正式固定.json", destination / "正式固定.json")
    selected, selected_meta = read_metadata(OWNER / "measurement/後十三場前の選択.json", destination / "27場時点の固定選択.json")
    read_log, read_meta = read_metadata(OWNER / "measurement/入力読取.jsonl", destination / "完成attemptの入力読取.jsonl")
    audit.check(selected["実測済み場数"] == 27 and selected["後十三場入力未読"], "27場で固定した選択")
    audit.check(len(inventory["sessions"]) == 40 and len(read_log) == 80, "完成attempt40場80入力")
    audit.check(len({row["path"] for row in read_log}) == 80 and all(row["reads"] == 1 for row in read_log), "完成attempt各一読")
    audit.check(sum(row["kind"] == "old_npz" for row in read_log) == 66 and sum(row["kind"] == "jsonl" for row in read_log) == 14, "完成attempt旧66新14")
    for path, expected in frozen["source_SHA256"].items():
        audit.check(audit.sha((ROOT / path).read_bytes()) == expected, "経済源は正式固定のまま")
    specs = specifications()
    runs, portfolios, caches, port_caches, certificates, unknown = [], [], [], [], [], []
    for scene in inventory["sessions"]:
        for symbol, (quantity, multiplier, fee, _) in audit.CONTRACTS.items():
            arrays, meta = read_cache(OWNER / "measurement/prepared" / symbol / (scene + ".npz"), symbol, scene,
                "prepared", destination / "prepared" / symbol / (scene + ".npz"))
            pc, pc_meta = read_cache(OWNER / "measurement/portfolio" / symbol / (scene + ".npz"), symbol, scene,
                "portfolio", destination / "portfolio" / symbol / (scene + ".npz"))
            caches.append(meta)
            port_caches.append(pc_meta)
            bars = {key[6:]: value for key, value in arrays.items() if key.startswith("bars__")}
            quotes = {key[8:]: value for key, value in arrays.items() if key.startswith("quotes__")}
            policies = {key[10:]: value for key, value in arrays.items() if key.startswith("policies__")}
            audit.check(arrays["ledger"].ndim == 2 and arrays["ledger"].shape[1] == 17, "保存policy付き17列")
            audit.check(arrays["equity"].shape == arrays["position"].shape == (252, len(bars["valid"])), "252政策の資産と方向")
            audit.check(np.isin(arrays["ledger"][:, 0], np.arange(252)).all(), "政策index範囲")
            for k, spec in enumerate(specs):
                ledger = arrays["ledger"][arrays["ledger"][:, 0] == k, 1:]
                summary, certificate = reconstruct(ledger, bars, quotes, quantity, multiplier, fee, spec,
                    policies["width"][k], policies["valid"][k], scene, arrays["equity"][k], arrays["position"][k])
                row = dict(session=scene, symbol=symbol, method=spec["id"], **summary)
                runs.append(row)
                if not certificate["保証"]:
                    unknown.append(dict(session=scene, symbol=symbol, method=spec["id"], **certificate))
            chosen = selected["selection"][symbol]["chosen"]
            audit.check(pc["sleeve_equity"].shape == (len(chosen), len(bars["valid"])), "配分slot資産shape")
            audit.check(pc["ledger"].ndim == 2 and pc["ledger"].shape[1] == 17 and np.isin(pc["ledger"][:, 0], np.arange(len(chosen))).all(), "配分slotの17列")
            sleeves = []
            for slot, mid in enumerate(chosen):
                k = next(j for j, spec in enumerate(specs) if spec["id"] == mid)
                qty = ((4, 3, 3) if symbol == "TOPIX" else (8, 6, 6))[slot]
                ledger = pc["ledger"][pc["ledger"][:, 0] == slot, 1:]
                summary, certificate = reconstruct(ledger, bars, quotes, qty, multiplier, fee, specs[k],
                    policies["width"][k], policies["valid"][k], scene, pc["sleeve_equity"][slot], None)
                sleeves.append(summary)
                if not certificate["保証"]:
                    unknown.append(dict(session=scene, symbol=symbol, method="PORT", slot=slot, **certificate))
            if any(sleeve["net"] is None for sleeve in sleeves):
                total = {key: None for key in ("net", "realized", "profit", "loss", "parents", "wins", "losses", "closed_quantity", "fees", "unclosed", "fills", "max_drawdown")}
            else:
                total = {key: sum(sleeve[key] for sleeve in sleeves) for key in ("net", "realized", "profit", "loss", "parents", "wins", "losses", "closed_quantity", "fees", "unclosed", "fills", "max_drawdown")}
            total.update(canceled=None, halted=None, max_drawdown_is_upper_bound=True, 未保存診断=["canceled", "halted"])
            portfolios.append(dict(session=scene, symbol=symbol, method="PORT", **total))
            certificates.append(dict(symbol=symbol, session=scene, 場末後正常気配=int(np.count_nonzero(quotes["time"] >= cutoff(scene))),
                                     全政策と配分の保証=not any(r["session"] == scene and r["symbol"] == symbol for r in unknown)))
            print(json.dumps(dict(保存会計復元済み組=len(caches), session=scene, symbol=symbol, 検査数=audit.CHECKS), ensure_ascii=False), flush=True)
    rebuilt_selection = {}
    all_metrics = []
    for symbol in audit.CONTRACTS:
        own = [row for row in runs if row["symbol"] == symbol]
        selection_rows = [row for row in own if row["session"] in inventory["splits"]["選択6"]]
        audit.check(all(row["net"] is not None for row in selection_rows), "選択6の会計を確定可能")
        rebuilt_selection[symbol] = audit.selection(own, specs, inventory["splits"]["選択6"])
        original_selection = selected["selection"][symbol]
        for key in ("chosen", "qualified", "eligible_ids"):
            audit.check(rebuilt_selection[symbol][key] == original_selection[key], "27場固定選択の完全一致:" + key)
        audit.check([row["id"] for row in rebuilt_selection[symbol]["ranking"]] == [row["id"] for row in original_selection["ranking"]], "選択6の全順位一致")
        for recovered, original in zip(rebuilt_selection[symbol]["ranking"], original_selection["ranking"]):
            audit.check(recovered["eligible"] == original["eligible"], "全資格一致")
            audit.compare_mapping(original["metrics"], recovered["metrics"], "元選択6の全数値")
        for mid in [spec["id"] for spec in specs] + ["PORT"]:
            rows = [row for row in (portfolios if mid == "PORT" else own) if row["symbol"] == symbol and row["method"] == mid]
            audit.check(len(rows) == 40, "各手法の全40場")
            periods = {name: audit.metrics([row for row in rows if row["session"] in scenes])
                       if all(row["net"] is not None for row in rows if row["session"] in scenes) else None
                       for name, scenes in inventory["splits"].items()}
            all_metrics.append(dict(symbol=symbol, method=mid, periods=periods))
    audit.check(audit.READS == dict(完成結果=0, prepared=80, portfolio=80, 市場=0, 再生=0), "最終結果なし・各160cache一読のみ")
    recovered = dict(sessions=inventory["sessions"], splits=inventory["splits"], specs=specs,
        runs=runs, portfolios=portfolios, selection=rebuilt_selection, cache=caches, portfolio_cache=port_caches,
        source_SHA256=frozen["source_SHA256"], read_log=read_log, API=0, 実注文=0,
        復元=dict(理由="40場の政策と実数量PORTのcache保存完了後、集約JSONのnp.int64がJSON非対応で保存停止。",
                  方法="保存台帳からgross/注文費用/親net/現金を復元し、全quote清算資産から保存公開eq/posへ照合。金融再生なし。",
                  新市場読取=0, 新金融再生=0, 新しい有効性標本=0,
                  未保存=["政策ごとのcanceled", "政策ごとのhalted", "入力診断のうちcache外だけにあった欄"],
                  実行由来="完成attemptは80原入力。別の初期化attemptで最初の2原入力読取後、金融明細0のNumba cache初期化停止。計82原読を80有効場へ水増ししない。",
                  未清算不明=len(unknown)),
        留保="ラージBBOと価格時計による小型契約代理約定。待ち順位/真受信順は未観測。canceled/haltedは未保存でnull。")
    result_output = save_recovered("戦略自動選択と全四十場の復元結果.json", recovered)
    metrics_output = save_recovered("復元会計による全四十場と指定期間指標.json", dict(metrics=all_metrics))
    proof = dict(全合格=True, 全会計確定=len(unknown) == 0, 検査数=audit.CHECKS, counts=audit.READS,
        未確定=unknown, 未清算成功扱い=False, 金融再生=0, 独立標本追加=0,
        source_SHA256=frozen["source_SHA256"], 復元源SHA256=audit.sha(Path(__file__).read_bytes()),
        算術監査源SHA256=audit.sha(Path(audit.__file__).read_bytes()),
        小資料=[prior_meta, inventory_meta, frozen_meta, selected_meta, read_meta], 場末確認=certificates,
        outputs=[result_output, metrics_output],
        留保="cacheのSHAは監査の一読時点で新規固定。元の集約JSONは未保存なので元SHAと一致したとは主張しない。")
    audit.save(HERE / "集約型停止後の保存会計復元と独立照合の証跡.json", proof)
    print(json.dumps(dict(全合格=True, 全会計確定=len(unknown) == 0, 検査数=audit.CHECKS, counts=audit.READS), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        audit.save(HERE / "復元False.json", dict(全合格=False, counts=audit.READS, 検査数=audit.CHECKS,
                                         型=type(exc).__name__, 例外=str(exc)))
        raise
