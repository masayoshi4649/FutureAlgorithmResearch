"""同じ既知28場・商品別金額で846条件を再集計し、少数条件と主比較を分離する。"""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "work/wave_v72/audit"))
import loss_rank

SYMBOLS = ("TOPIX", "NK225")


def read(path: Path) -> object:
    """機能: 結果又は台帳を読取専用で取得する。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == ".pkl" else json.loads(path.read_text(encoding="utf8"))


def token(record: dict) -> str:
    """機能: 過去作業を区別した一意の設定識別子を作る。

    引数: record(dict)。返り値: 版・領域・ID(str)。
    """
    return f"v{record['版']}/{record['領域']}/{record['ID']}"


def share(record: dict, symbol: str) -> Fraction:
    """機能: 丸め前の金額から損失割合を作る。

    引数: record(dict)、symbol(str)。返り値: 絶対損失/(利益+絶対損失)(Fraction)。
    """
    a = record["商品"][symbol]
    p, l = Fraction(str(a["勝組利益"])), Fraction(str(a["負組損失"]))
    assert p + l > 0
    return l / (p + l)


def metrics(record: dict, symbol: str) -> dict:
    """機能: 金額主指標と前半・後半・大勝ち依存を銘柄別に提示する。

    引数: record(dict)、symbol(str)。返り値: 出典付き集計(dict)。
    """
    a = record["商品"][symbol]
    packet = read(ROOT / record["出典"])
    out = dict(識別子=token(record), 版=record["版"], 領域=record["領域"], ID=record["ID"], 商品=symbol,
        利益=a["勝組利益"], 損失=a["負組損失"], 収支=a["収支"], 手数料=a["手数料"],
        金額損失割合=float(share(record, symbol)), PF=a["勝組利益"] / a["負組損失"] if a["負組損失"] else None,
        組数=a["組数"], 活動場数=a["活動場数"], 負組数=a["負組数"], 勝組数=a["勝組数"], 敗率=a["敗率"],
        平均勝ち=a["平均勝組"], 平均負け=a["平均負組"], 平均勝負比=a["平均勝負比"], 最大負組=a["最大負組"],
        初回枚数=5 if record["版"] == 69 and symbol == "TOPIX" else 10 if record["版"] == 69 else 10 if symbol == "TOPIX" else 20,
        前半収支=packet["periods"]["前16"][symbol]["net"], 後半収支=packet["periods"]["後12"][symbol]["net"],
        最大黒字場除外=packet["periods"]["全28"][symbol]["without_best_session"],
        含み込み最大下落=packet["periods"]["全28"][symbol]["drawdown"])
    if "追加1" in packet["periods"]:
        p = packet["periods"]["追加1"][symbol]
        out["追加10月09日参考"] = {k: p[k] for k in ("net", "campaign_profit", "campaign_loss", "campaigns", "active_sessions")}
    return out


def rank(records: list[dict], symbol: str | None, minimum: int, active: int) -> list[dict]:
    """機能: 無取引を除外し、同銘柄又は両銘柄の悪い側の金額割合で並べる。

    引数: records(list[dict])、symbol(str|None)、minimum/active(int)。返り値: 順位(list[dict])。
    """
    symbols = (symbol,) if symbol else SYMBOLS
    rows = [r for r in records if all(r["商品"][s]["組数"] >= minimum and r["商品"][s]["活動場数"] >= active for s in symbols)]
    return sorted(rows, key=lambda r: (max(share(r, s) for s in symbols), r["版"], r["ID"]))


def path_hash(record: dict, symbol: str) -> str:
    """機能: 原本に触れず、同商品28場の経済的に同じ注文経路を識別する。

    引数: record(dict)、symbol(str)。返り値: 理由番号を除く注文指紋(str)。
    """
    folder = ROOT / f"work/wave_v{record['版']}" / record["領域"]
    ledger = read(folder / "ledgers" / (record["ID"] + ".pkl"))
    h = hashlib.sha256()
    for key, data in sorted(ledger.items()):
        if key[1] != symbol or key[0] == "2026-10-09_Day":
            continue
        orders = data["orders"]
        if orders.shape[1] == 8:
            orders = np.column_stack((orders, np.zeros(len(orders))))
        h.update(key[0].encode("utf8"))
        h.update(np.asarray(orders[:, [0, 1, 2, 3, 4, 5, 7, 8]], dtype="<f8").tobytes())
    return h.hexdigest()


def check_ledgers(records: list[dict]) -> dict:
    """機能: 上位と少数首位の全玉損益をcidで再合算し、隠れた損失と料金を検査する。

    引数: records(list[dict])。返り値: 再会計検査件数(dict)。
    """
    seen, count = set(), 0
    for record in records:
        tag = token(record)
        if tag in seen:
            continue
        seen.add(tag)
        packet = read(ROOT / record["出典"])
        folder = ROOT / f"work/wave_v{record['版']}" / record["領域"]
        ledger = read(folder / "ledgers" / (record["ID"] + ".pkl"))
        for row in packet["rows"]:
            if row["session"] == "2026-10-09_Day":
                continue
            symbol = row["symbol"]
            cap = 5 if record["版"] == 69 and symbol == "TOPIX" else 10 if record["版"] == 69 else 10 if symbol == "TOPIX" else 20
            data = ledger[(row["session"], symbol)]
            orders, trades = data["orders"], data["trades"]
            groups = defaultdict(float)
            fees = 0
            held = {1: 0, -1: 0}
            for order in orders:
                side, qty, new = int(order[3]), int(order[4]), int(order[7])
                fees += qty * 418 // 10 if symbol == "TOPIX" else qty * 11
                held[side if new else -side] += qty if new else -qty
                assert all(0 <= q <= cap for q in held.values())
            assert held[1] == held[-1] == 0
            assert fees == row["fees"] == int(trades[:, 7:9].sum())
            for trade in trades:
                groups[int(trade[0])] += float(trade[10])
            p = sum(v for v in groups.values() if v > 0)
            l = -sum(v for v in groups.values() if v < 0)
            names = ("profit", "loss", "trades") if record["版"] == 69 else ("campaign_profit", "campaign_loss", "campaigns")
            for name, value in zip(names, (p, l, len(groups))):
                assert abs(row[name] - value) < 1.e-6
            assert abs(p - l - row["net"]) < 1.e-6
            count += 1
    return dict(合格=True, 条件数=len(seen), 口座数=count, 一組="全明細のcid合計。保険利益だけでは勝ちにしない", 全玉返済と注文料金一致=True)


def main() -> None:
    """機能: 主順位と少標本順位を分離した短い独立監査JSONを新領域へ保存する。

    引数: なし。返り値: なし(None)。旧監査や原本を変更しない。
    """
    old_check = read(ROOT / "work/wave_v72/audit/R01金額損失割合順位の独立確認.json")
    assert old_check["合格"] and old_check["条件数"] == 846
    original = loss_rank.collect()
    records = [r for r in original if r["設定"].get("gate_level", 0) != 3]
    assert len(original) == 846 and len(records) == 738
    result, candidates = {}, []
    for symbol in SYMBOLS:
        limited, unlimited = rank(records, symbol, 20, 8), rank(records, symbol, 1, 0)
        by_pf = sorted(limited, key=lambda r: (-Fraction(str(r["商品"][symbol]["勝組利益"])) / Fraction(str(r["商品"][symbol]["負組損失"])), r["版"], r["ID"]))
        assert [token(r) for r in limited] == [token(r) for r in by_pf]
        top = [metrics(r, symbol) for r in limited[:5]]
        hashes = [path_hash(r, symbol) for r in limited[:5]]
        unique, known = [], set()
        for r in limited:
            fingerprint = path_hash(r, symbol)
            if fingerprint not in known:
                unique.append(metrics(r, symbol))
                candidates.append(r)
                known.add(fingerprint)
                if len(unique) == 5:
                    break
        totals_min = sorted(unlimited, key=lambda r: (r["商品"][symbol]["負組損失"], r["版"], r["ID"]))[0]
        totals_limited = sorted(limited, key=lambda r: (r["商品"][symbol]["負組損失"], r["版"], r["ID"]))[0]
        small_reference = next(r for r in records if r["版"] == 71 and r["ID"] == "T3L1_G1_W4_D")
        r = share(small_reference, symbol)
        ref = metrics(small_reference, symbol)
        ref.update(無制限同率最前順位=1 + sum(share(m, symbol) < r for m in unlimited),
                   主件数条件充足=small_reference["商品"][symbol]["組数"] >= 20 and small_reference["商品"][symbol]["活動場数"] >= 8)
        result[symbol] = dict(主対象条件数=len(limited), 同期除外有取引条件数=len(unlimited),
            金額損失割合最少上位5=top, PF最大上位5=top, 上位5の経済経路指紋=hashes,
            同一経路を一つに数えた上位5=unique, 件数制限なし首位=metrics(unlimited[0], symbol),
            参考T3広幅無保険=ref, 絶対損失総額最少_無制限=metrics(totals_min, symbol),
            絶対損失総額最少_件数条件あり=metrics(totals_limited, symbol))
        candidates.extend(limited[:5] + [unlimited[0], totals_min, totals_limited, small_reference])
    common = rank(records, None, 20, 8)
    common_top = [dict(識別子=token(r), 最悪側金額損失割合=float(max(share(r, s) for s in SYMBOLS)),
                       商品別={s: metrics(r, s) for s in SYMBOLS}) for r in common[:3]]
    candidates.extend(common[:3])
    checked = check_ledgers(candidates)
    value = dict(合格=True, 既存条件数=846, 同期G3除外後条件数=738, 同一対象場数=28,
        主件数条件="商品別20組・8活動場以上。共通では両商品が満たす", 同期G3除外=True,
        金額主指標="料金後の全玉組損失/(組利益+組損失)", PF最大と同じ順位="損失割合=1/(1+PF)。新しい独立根拠ではない",
        二商品円合算=False, 商品別=result, 両商品共通対象条件数=len(common), 共通上位3=common_top,
        両商品共通両黒字条件数=sum(all(r["商品"][s]["収支"] > 0 for s in SYMBOLS) for r in common),
        件数影響="絶対損失総額は枚数・入口数・観測期間を減らすだけでも下がる。無取引は首位に含めず、件数制限なしと20組8場の金額比を分離",
        枚数差="wave69はTOP5/NK10、wave70/71はTOP10/NK20。金額倍率で銘柄を直接比較しない。割合でも条件の資金リスクは別途見る",
        追加デイ="全条件へ揃っていないため主順位から除外。既存wave71にある追加1だけ参考表示",
        上位台帳検算=checked, 範囲外="旧25場、CurrentPrice約定、指値仮定、中値などを統合して歴代最良と断定しない",
        原本読取=False, API取得=0, 実注文=0)
    HERE.mkdir(parents=True, exist_ok=True)
    path = HERE / "同28場846条件の金額主指標による独立再選定.json"
    assert not path.exists(), "過去監査の上書き禁止"
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf8")
    print(json.dumps({s: dict(主首位=result[s]["金額損失割合最少上位5"][0], 件数制限なし=result[s]["件数制限なし首位"]) for s in SYMBOLS}, ensure_ascii=False, indent=2), flush=True)
    print(checked, flush=True)


if __name__ == "__main__":
    main()
