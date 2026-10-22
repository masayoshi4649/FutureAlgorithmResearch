"""119の保存済み台帳と資産だけを独立再集計し、市場・売買エンジンを再生しない。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
OWNER = HERE.parent
ROOT = OWNER.parents[1]
CHECKS = 0
READS = {"完成結果": 0, "prepared": 0, "portfolio": 0, "市場": 0, "再生": 0}
CONTRACTS = {"TOPIX": (10, 1000., 41.8, .25), "NK225": (20, 10., 11., 5.)}


# ----------------------------------------


def check(condition: bool, note: str) -> None:
    """
    機能: 保存値と独立期待値の一致を数え、不一致で停止する。
    引数: condition(bool) は条件、note(str) は検査内容。
    返り値: None。
    """
    global CHECKS
    assert bool(condition), note
    CHECKS += 1


def near(actual: object, expected: object, note: str) -> None:
    """
    機能: 有限数値・NaN・Noneを区別して独立期待値と比較する。
    引数: actual/expected(object) は数値又はNone、note(str) は説明。
    返り値: None。
    """
    if actual is None or expected is None:
        check(actual is None and expected is None, note)
    else:
        check(bool(np.allclose(actual, expected, atol=1e-5, rtol=1e-10, equal_nan=True)), note)


def sha(payload: bytes) -> str:
    """
    機能: 読み出した同一bytesの指紋を返す。
    引数: payload(bytes) は同じ読取の内容。
    返り値: str はSHA256。
    """
    return hashlib.sha256(payload).hexdigest()


def save(path: Path, value: dict) -> None:
    """
    機能: 新規の監査資料を有限JSONとして保存する。
    引数: path(Path)、value(dict) は所有領域と内容。
    返り値: None。既存の成功又はFalseを上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def own_cache(info: dict, group: str, destination: Path) -> dict:
    """
    機能: 許可済み保存cacheを一読し、同bytes保全と指紋照合後に配列を展開する。
    引数: info(dict) は固定cache目録、group(str) はprepared又はportfolio、destination(Path) は保全先。
    返り値: dict[str,ndarray]。原市場ファイルと売買エンジンは読まない。
    """
    source = (ROOT / info["path"]).resolve()
    check(source.is_relative_to(OWNER / "measurement" / group), "保存cacheの領域")
    payload = source.read_bytes()
    READS[group] += 1
    check(len(payload) == info["bytes"] and sha(payload) == info["SHA256"], "保存cache同bytes")
    destination.parent.mkdir(parents=True, exist_ok=True)
    assert not destination.exists()
    destination.write_bytes(payload)
    with np.load(BytesIO(payload), allow_pickle=False) as saved:
        arrays = {key: saved[key].copy() for key in saved.files}
    return arrays


def metrics(rows: list[dict]) -> dict:
    """
    機能: セッションと親取引を分け、独立した金額指標を計算する。
    引数: rows(list[dict]) は一商品・一手法・指定場の保存行。
    返り値: dict は黒字頻度・利益割合・分位・損失補填比など。
    """
    net = np.asarray([r["net"] for r in rows], dtype=float)
    positive = [float(x) for x in net if x > 1e-7]
    negative = [float(x) for x in net if x < -1e-7]
    profit, loss = sum(r["profit"] for r in rows), sum(r["loss"] for r in rows)
    parents, wins = sum(r["parents"] for r in rows), sum(r["wins"] for r in rows)
    mean_black = sum(positive) / len(positive) if positive else None
    return dict(sessions=len(rows), black=len(positive), red=len(negative), flat=len(rows) - len(positive) - len(negative),
        active=sum(r["fills"] > 0 for r in rows), net=float(sum(net)), profit=float(profit), loss=float(loss),
        profit_share=profit / (profit + loss) if profit + loss else None,
        mean=float(sum(net) / len(net)) if len(net) else None,
        median=float(np.percentile(net, 50)) if len(net) else None,
        q25=float(np.percentile(net, 25)) if len(net) else None,
        worst=float(min(net)) if len(net) else None, mean_black=mean_black,
        worst_to_mean_black=-min(negative) / mean_black if negative and positive else (0. if positive else None),
        without_top3_net=float(sum(net) - sum(sorted(positive, reverse=True)[:3])),
        parents=int(parents), wins=int(wins), trade_win_rate=wins / parents if parents else None,
        fees=float(sum(r["fees"] for r in rows)), unclosed=sum(r["unclosed"] for r in rows))


def selection(rows: list[dict], specs: list[dict], scenes: list[str]) -> dict:
    """
    機能: 指定された選択6場だけで固定の採用順位を独立再計算する。
    引数: rows(list[dict])、specs(list[dict])、scenes(list[str]) は当商品行・事前仕様・選択場。
    返り値: dict は順位・異家族最大三つ。後13場で勝手に再選択しない。
    """
    ranking = []
    for spec in specs:
        selected = [r for r in rows if r["session"] in scenes and r["method"] == spec["id"]]
        check(len(selected) == len(scenes), "選択場が6件揃う")
        m = metrics(selected)
        qualified = m["active"] >= 3 and m["parents"] >= 5 and m["net"] > 0 and m["unclosed"] == 0
        ranking.append(dict(id=spec["id"], family=spec["family"], eligible=qualified, metrics=m))
    def key(row: dict) -> tuple:
        """
        機能: 事前に固定された比較順を構成する。
        引数: row(dict) は一候補の選択6場集計。
        返り値: tuple は降順比較用のキー。
        """
        m = row["metrics"]
        ratio = m["worst_to_mean_black"]
        return row["eligible"], m["black"], m["q25"], m["median"], -(ratio if ratio is not None else 1e20), m["net"], row["id"]
    ranking.sort(key=key, reverse=True)
    chosen, families = [], set()
    for row in ranking:
        if row["eligible"] and row["family"] not in families:
            chosen.append(row["id"])
            families.add(row["family"])
            if len(chosen) == 3:
                break
    return dict(chosen=chosen, qualified=bool(chosen), eligible_ids=[r["id"] for r in ranking if r["eligible"]], ranking=ranking)


def accounting(ledger: np.ndarray, quantity: int, multiplier: float, fee: float, unclosed: int) -> dict:
    """
    機能: engine16列の保存返済台帳から親会計と現金を独立復元する。
    引数: ledger(float[:,16])、quantity(int)、multiplier/fee(float)、unclosed(int) は固定数量と費用・残玉。
    返り値: dict。未清算を黒字成功へ昇格させず、未清算親の参考評価は作らない。
    """
    check(ledger.ndim == 2 and ledger.shape[1] == 16 and np.isfinite(ledger).all(), "16列の有限台帳")
    check(0 <= unclosed <= quantity, "片方向残数量の上限")
    check(np.all(ledger[:, 2] > ledger[:, 1]) and np.all(ledger[:, 4] >= ledger[:, 3]), "原row先後と時計")
    check(np.isin(ledger[:, 5], (-1, 1)).all(), "売買方向")
    check(np.all((ledger[:, 6] > 0) & (ledger[:, 6] <= quantity)), "返済数量の範囲")
    near(ledger[:, 6], np.rint(ledger[:, 6]), "返済数量整数")
    near(ledger[:, 9], ledger[:, 5] * (ledger[:, 8] - ledger[:, 7]) * ledger[:, 6] * multiplier, "全明細のgross")
    infee = math.floor(quantity * fee + 1e-9)
    near(ledger[:, 10], infee * ledger[:, 6] / quantity, "新規費用の親内按分")
    near(ledger[:, 11], np.floor(ledger[:, 6] * fee + 1e-9), "返済注文別切捨て")
    near(ledger[:, 12], ledger[:, 9] - ledger[:, 10] - ledger[:, 11], "全明細の純損益")
    parent_ids = np.unique(ledger[:, 0]).astype(int)
    check(np.array_equal(parent_ids, np.arange(1, len(parent_ids) + 1)), "親IDは欠落なく一から")
    nets, partial = [], []
    for parent in parent_ids:
        legs = ledger[ledger[:, 0] == parent]
        check(np.all(legs[:, [1, 3, 5, 7, 14]] == legs[0, [1, 3, 5, 7, 14]]), "親の新規情報は不変")
        closed = int(sum(legs[:, 6]))
        check(closed <= quantity, "親の返済超過なし")
        if closed < quantity:
            partial.append((parent, quantity - closed))
        nets.append(float(sum(legs[:, 12])))
    if unclosed == 0:
        check(not partial, "清算済みは全親返済済み")
        entries = len(parent_ids)
    elif partial:
        check(partial == [(len(parent_ids), unclosed)], "未清算は末尾親の残数のみ")
        entries = len(parent_ids)
    else:
        check(unclosed == quantity, "台帳未登場の未清算親は全数量")
        entries = len(parent_ids) + 1
    fees = entries * infee + float(sum(ledger[:, 11]))
    cash = float(sum(ledger[:, 9])) - fees
    out = dict(realized=cash, profit=sum(max(x, 0.) for x in nets), loss=sum(max(-x, 0.) for x in nets),
               parents=len(parent_ids), wins=sum(x > 1e-7 for x in nets), losses=sum(x < -1e-7 for x in nets),
               closed_quantity=int(sum(ledger[:, 6])), fees=fees, unclosed=unclosed, fills=entries + len(ledger))
    if not unclosed:
        out["net"] = cash
    return out


def quote_account(ledger: np.ndarray, bars: dict, quotes: dict, quantity: int,
                  multiplier: float, fee: float, spec: dict, width: np.ndarray, valid: np.ndarray) -> dict:
    """
    機能: 保存約定だけから全気配時点の現金・建玉・清算資産を復元する。
    引数: ledger(float[:,16])、bars/quotes(dict)、数量・倍率・費用、固定spec(dict)、width/valid(配列)。
    返り値: dict は公開時資産・方向と全気配最大下落。売買ルールの再生や再選択は行わない。
    """
    n = len(quotes["row"])
    cash_delta = np.zeros(n)
    position_delta = np.zeros(n)
    basis_delta = np.zeros(n)
    infee = math.floor(quantity * fee + 1e-9)
    order_tick = .25 if multiplier == 1000. else 5.
    for parent in np.unique(ledger[:, 0]):
        legs = ledger[ledger[:, 0] == parent]
        leg = legs[0]
        erow, ebar = int(leg[1]), int(leg[14])
        eq = int(np.searchsorted(quotes["row"], erow))
        check(eq < n and quotes["row"][eq] == erow, "新規は保存正常BBOに存在")
        near(leg[3], quotes["time"][eq], "新規時計はBBO時計")
        check(0 <= ebar < len(bars["valid"]) and valid[ebar], "新規の当時資格")
        check(bars["pub_raw_row"][ebar] < erow, "公開判断の同row新規禁止")
        check(0 <= leg[3] - bars["pub_price_time_s"][ebar] <= (60. if spec["entry_mode"] == 0 else 180.), "新規期限")
        d, ep = int(leg[5]), leg[7]
        if spec["entry_mode"] == 0:
            near(ep, quotes["ask"][eq] if d == 1 else quotes["bid"][eq], "成行新規の反対BBO")
        else:
            raw = bars["anchor"][ebar] - d * .2 * width[ebar]
            limit = (math.floor(raw / order_tick) if d == 1 else math.ceil(raw / order_tick)) * order_tick
            near(ep, limit, "指値新規の実商品刻み")
            check((quotes["ask"][eq] <= limit) if d == 1 else (quotes["bid"][eq] >= limit), "指値の反対気配到達")
        cash_delta[eq] -= infee
        position_delta[eq] += d * quantity
        basis_delta[eq] += d * quantity * ep
        indexes = np.searchsorted(quotes["row"], legs[:, 2].astype(np.int64))
        check(np.all(indexes < n) and np.array_equal(quotes["row"][indexes], legs[:, 2]), "返済は正常BBOに存在")
        near(legs[:, 4], quotes["time"][indexes], "返済時計はBBO時計")
        near(legs[:, 8], quotes["bid"][indexes] if d == 1 else quotes["ask"][indexes], "返済の反対BBO")
        np.add.at(cash_delta, indexes, legs[:, 9] - legs[:, 11])
        np.add.at(position_delta, indexes, -d * legs[:, 6])
        np.add.at(basis_delta, indexes, -d * legs[:, 6] * ep)
    cash = np.cumsum(cash_delta)
    pos = np.cumsum(position_delta)
    basis = np.cumsum(basis_delta)
    check(np.all(np.abs(pos) <= quantity), "原rowごとの数量上限")
    check(not len(pos) or pos[-1] == 0, "再構成の末尾は全清算")
    liquidation = np.where(pos > 0, quotes["bid"], quotes["ask"])
    equity = cash + (pos * liquidation - basis) * multiplier - np.floor(np.abs(pos) * fee + 1e-9)
    high = np.maximum.accumulate(np.concatenate(([0.], equity)))[1:]
    dd = float(np.max(high - equity)) if n else 0.
    pr, pt = bars["pub_raw_row"], bars["pub_price_time_s"]
    good = bars["valid"] & np.isfinite(bars["anchor"]) & (pr >= 0)
    good &= (pt - bars["t_s"] >= 0) & (pt - bars["t_s"] <= 60)
    qi = np.searchsorted(quotes["row"], pr, side="right") - 1
    known = good & (qi >= 0)
    if n:
        known &= (pt - quotes["time"][np.maximum(qi, 0)] <= 60.)
    else:
        known[:] = False
    trace = np.full(len(pr), np.nan)
    direction = np.zeros(len(pr), dtype=np.int8)
    trace[known] = equity[qi[known]]
    direction[known] = np.sign(pos[qi[known]]).astype(np.int8)
    return dict(equity=trace, position=direction, max_drawdown=dd)


def compare_mapping(actual: dict, expected: dict, context: str) -> None:
    """
    機能: 独立に復元した全フィールドを保存集計へ照合する。
    引数: actual/expected(dict)、context(str) は照合対象と説明。
    返り値: None。
    """
    for key, value in expected.items():
        near(actual[key], value, context + ":" + key)


def main(expected_sha: str) -> None:
    """
    機能: 指定SHAの完成結果と各80cacheを各一読で監査する。
    引数: expected_sha(str) はrootが完成後に指定した結果指紋。
    返り値: None。金融再生を新しい有効性標本へ数えない。
    """
    check(len(expected_sha) == 64, "完成後指定SHA必須")
    destination = HERE / "owned"
    destination.mkdir(exist_ok=False)
    result_path = OWNER / "measurement/戦略自動選択と全四十場の結果.json"
    payload = result_path.read_bytes()
    READS["完成結果"] += 1
    check(sha(payload) == expected_sha, "完成結果同bytes")
    (destination / "完成結果.json").write_bytes(payload)
    result = json.loads(payload.decode("utf-8"))
    fixed = json.loads((OWNER / "正式固定.json").read_text(encoding="utf-8"))
    check(result["source_SHA256"] == fixed["source_SHA256"], "正式固定と結果の源束")
    for path, expected in fixed["source_SHA256"].items():
        check(sha((ROOT / path).read_bytes()) == expected, "凍結源不変")
    check(len(result["sessions"]) == 40 and len(set(result["sessions"])) == 40, "40場重複なし")
    check(len(result["cache"]) == len(result["portfolio_cache"]) == len(result["read_log"]) == 80, "各80入力・cache")
    check(len({r["path"] for r in result["read_log"]}) == 80 and all(r["reads"] == 1 for r in result["read_log"]), "市場各一読の記録")
    check(sum(r["kind"] == "old_npz" for r in result["read_log"]) == 66, "旧66入力")
    check(sum(r["kind"] == "jsonl" for r in result["read_log"]) == 14, "新14入力")
    check(result["API"] == 0 and result["実注文"] == 0, "APIと実注文なし")
    specs = result["specs"]
    check(len(specs) == len({s["id"] for s in specs}) == 252, "固定252政策")
    lookup = {(r["symbol"], r["session"], r["method"]): r for r in result["runs"]}
    check(len(lookup) == len(result["runs"]) == 80 * len(specs), "政策場行の重複なし")
    pc_lookup = {(r["symbol"], r["session"]): r for r in result["portfolio_cache"]}
    port_lookup = {(r["symbol"], r["session"]): r for r in result["portfolios"]}
    for symbol in CONTRACTS:
        independent = selection([r for r in result["runs"] if r["symbol"] == symbol], specs, result["splits"]["選択6"])
        check(independent["chosen"] == result["selection"][symbol]["chosen"], "選択6だけの異family三枠")
        check(independent["eligible_ids"] == result["selection"][symbol]["eligible_ids"], "選択6の資格順位")
        check([r["id"] for r in independent["ranking"]] == [r["id"] for r in result["selection"][symbol]["ranking"]], "選択6の全順位")
        for a, b in zip(result["selection"][symbol]["ranking"], independent["ranking"]):
            compare_mapping(a["metrics"], b["metrics"], "選択6の独立指標")
    unclosed_rows, portfolio_unclosed, audits = [], [], []
    for meta in result["cache"]:
        symbol, scene = meta["symbol"], meta["session"]
        arrays = own_cache(meta, "prepared", destination / "prepared" / symbol / (scene + ".npz"))
        pc = own_cache(pc_lookup[symbol, scene], "portfolio", destination / "portfolio" / symbol / (scene + ".npz"))
        bars = {key[6:]: value for key, value in arrays.items() if key.startswith("bars__")}
        quotes = {key[8:]: value for key, value in arrays.items() if key.startswith("quotes__")}
        policies = {key[10:]: value for key, value in arrays.items() if key.startswith("policies__")}
        all_ledger = arrays["ledger"]
        check(all_ledger.ndim == 2 and all_ledger.shape[1] == 17, "政策ID付き17列")
        check(np.isin(all_ledger[:, 0], np.arange(len(specs))).all(), "政策index範囲")
        quantity, multiplier, fee, tick = CONTRACTS[symbol]
        for k, spec in enumerate(specs):
            saved = lookup[symbol, scene, spec["id"]]
            ledger = all_ledger[all_ledger[:, 0] == k, 1:]
            account = accounting(ledger, quantity, multiplier, fee, saved["unclosed"])
            compare_mapping(saved, account, "単体の独立会計")
            if saved["unclosed"]:
                unclosed_rows.append(dict(symbol=symbol, session=scene, method=spec["id"], unclosed=saved["unclosed"]))
            else:
                trace = quote_account(ledger, bars, quotes, quantity, multiplier, fee, spec,
                                      policies["width"][k], policies["valid"][k])
                near(arrays["equity"][k], trace["equity"], "全公開足の費用後清算資産")
                near(arrays["position"][k], trace["position"], "全公開足の建玉方向")
                near(saved["max_drawdown"], trace["max_drawdown"], "全quote最大下落")

        chosen = result["selection"][symbol]["chosen"]
        check(pc["sleeve_equity"].shape == (len(chosen), len(bars["valid"])), "固定配分資産shape")
        check(pc["ledger"].shape[1] == 17 and np.isin(pc["ledger"][:, 0], np.arange(len(chosen))).all(), "配分slot範囲")
        saved_port = port_lookup[symbol, scene]
        if saved_port["unclosed"]:
            portfolio_unclosed.append(dict(symbol=symbol, session=scene, unclosed=saved_port["unclosed"]))
        else:
            sleeves = []
            dds = []
            for slot, mid in enumerate(chosen):
                k = next(j for j, spec in enumerate(specs) if spec["id"] == mid)
                qty = ((4, 3, 3) if symbol == "TOPIX" else (8, 6, 6))[slot]
                ledger = pc["ledger"][pc["ledger"][:, 0] == slot, 1:]
                account = accounting(ledger, qty, multiplier, fee, 0)
                trace = quote_account(ledger, bars, quotes, qty, multiplier, fee, specs[k], policies["width"][k], policies["valid"][k])
                near(pc["sleeve_equity"][slot], trace["equity"], "実数量slot資産")
                sleeves.append(account)
                dds.append(trace["max_drawdown"])
            total = {key: sum(sleeve[key] for sleeve in sleeves) for key in ("net", "realized", "profit", "loss", "parents", "wins", "losses", "closed_quantity", "fees", "unclosed", "fills")}
            compare_mapping(saved_port, total, "固定配分の実数量台帳和")
            near(saved_port["max_drawdown"], sum(dds), "配分DDはslot上界和")
            check(saved_port["max_drawdown_is_upper_bound"], "配分DD上界表記")
        audits.append(dict(symbol=symbol, session=scene, policies=len(specs), PORT未清算=saved_port["unclosed"]))
        print(json.dumps(dict(監査済みcache組=len(audits), symbol=symbol, session=scene, 検査数=CHECKS), ensure_ascii=False), flush=True)
    all_metrics = []
    for symbol in CONTRACTS:
        for mid in [spec["id"] for spec in specs] + ["PORT"]:
            rows = [r for r in (result["portfolios"] if mid == "PORT" else result["runs"]) if r["symbol"] == symbol and r["method"] == mid]
            check(len(rows) == 40, "全手法の40場指標")
            periods = {name: metrics([r for r in rows if r["session"] in scenes]) for name, scenes in result["splits"].items()}
            all_metrics.append(dict(symbol=symbol, method=mid, periods=periods))
    check(READS == dict(完成結果=1, prepared=80, portfolio=80, 市場=0, 再生=0), "許可された保存読取だけ")
    save(HERE / "四十場と指定期間の独立指標.json", dict(結果SHA256=expected_sha, metrics=all_metrics))
    proof = dict(全合格=True, 検査数=CHECKS, 完成結果SHA256=expected_sha, counts=READS,
                 未清算単体=unclosed_rows, 未清算配分=portfolio_unclosed, 未清算成功扱い=False,
                 全再構成可能=len(unclosed_rows) == 0 and len(portfolio_unclosed) == 0,
                 source_SHA256=result["source_SHA256"], 監査源SHA256=sha(Path(__file__).read_bytes()), cache組=audits,
                 位置づけ="同じ保存台帳の独立会計監査。金融再生0・新しい有効性標本0。",
                 未清算限界="返済台帳にない末尾新規はentryrowを確定できず、その未清算のMTM再構成は省略して成功扱い禁止。")
    save(HERE / "保存台帳と固定三枠及び全四十場指標の独立監査.json", proof)
    print(json.dumps(dict(全合格=True, 検査数=CHECKS, counts=READS, 未清算単体=len(unclosed_rows), 未清算配分=len(portfolio_unclosed)), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    try:
        main(args.expected_sha)
    except BaseException as exc:
        save(HERE / "False.json", dict(全合格=False, counts=READS, 検査数=CHECKS, 型=type(exc).__name__, 例外=str(exc)))
        raise
