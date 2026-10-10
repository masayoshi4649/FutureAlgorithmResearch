"""直近846条件の敗組率を、全28場の個別口座行から独立集計する。"""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SYMBOLS = ("TOPIX", "NK225")


def read(path: Path) -> object:
    """機能: 保存済み資料を読取専用で取得する。

    引数: path(Path)。返り値: JSON又はpickle内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == ".pkl" else json.loads(path.read_text(encoding="utf8"))


def collect() -> list[dict]:
    """機能: 同じ既知28場だけを抜き出して846条件の商品別敗組率を作る。

    引数: なし。返り値: 出典・条件・商品別指標(list[dict])。
    """
    fixed = read(ROOT / "work/wave_v69/事前固定.json")
    sessions = set(fixed["全セッション"])
    assert len(sessions) == 28
    areas = ((69, "", 192), (70, "", 192), (70, "controls", 30), (71, "", 432))
    result = []
    for version, area, count in areas:
        folder = ROOT / f"work/wave_v{version}" / area
        paths = sorted((folder / "results").glob("*.json"))
        assert len(paths) == count
        for path in paths:
            packet = read(path)
            item = dict(版=version, 領域=area, ID=packet["config"]["id"], 出典=str(path.relative_to(ROOT)), 設定=packet["config"], 商品={})
            for symbol in SYMBOLS:
                rows = [r for r in packet["rows"] if r["symbol"] == symbol and r["session"] in sessions]
                assert len(rows) == 28 and {r["session"] for r in rows} == sessions
                names = ("trades", "losses", "wins", "flats", "profit", "loss") if version == 69 else (
                    "campaigns", "campaign_losses", "campaign_wins", "campaign_flats", "campaign_profit", "campaign_loss")
                total, losses, wins, flats, profit, loss = (sum(r[k] for r in rows) for k in names)
                net = sum(r["net"] for r in rows)
                assert total == wins + losses + flats and abs(profit - loss - net) < 1.e-6
                reported = packet["periods"]["全28"][symbol]
                for k in names + ("net", "fees"):
                    assert abs(sum(r[k] for r in rows) - reported[k]) < 1.e-6
                a = dict(組数=total, 負組数=losses, 勝組数=wins, 同値組数=flats,
                         敗率=losses / total if total else None,
                         勝率=wins / total if total else None,
                         活動場数=sum(r[names[0]] > 0 for r in rows),
                         収支=net, 勝組利益=profit, 負組損失=loss, 手数料=sum(r["fees"] for r in rows),
                         平均負組=loss / losses if losses else None,
                         最大負組=max(r["max_trade_loss" if version == 69 else "max_campaign_loss"] for r in rows),
                         平均勝組=profit / wins if wins else None,
                         平均勝負比=(profit / wins) / (loss / losses) if wins and losses and loss else None,
                         最大一場損失=min(r["net"] for r in rows))
                item["商品"][symbol] = a
            result.append(item)
    assert len(result) == 846
    return result


def rank(records: list[dict], minimum: int, active: int, symbol: str | None, profitable: bool = False) -> list[dict]:
    """機能: 無取引を除き、銘柄別又は弱い銘柄の敗率で順位を作る。

    引数: records(list[dict])、minimum/active(int)、symbol(str|None)、profitable(bool)。
    返り値: 丸め前の分数で敗率を昇順比較した順位(list[dict])。
    """
    def key(item: dict) -> tuple:
        """機能: 敗率と件数の比較値を返す。

        引数: item(dict)。返り値: 敗率、負組数、件数、識別子(tuple)。
        """
        values = [item["商品"][s] for s in ([symbol] if symbol else SYMBOLS)]
        rates = [Fraction(a["負組数"], a["組数"]) for a in values]
        return (max(rates), sum(a["負組数"] for a in values), -sum(a["組数"] for a in values), item["版"], item["ID"])

    chosen = []
    for item in records:
        values = [item["商品"][s] for s in ([symbol] if symbol else SYMBOLS)]
        if all(a["組数"] >= max(1, minimum) and a["活動場数"] >= active and (not profitable or a["収支"] > 0) for a in values):
            chosen.append(item)
    return sorted(chosen, key=key)


def verify_ledgers(items: list[dict]) -> dict:
    """機能: 最少敗率例の全28場を、cid別の全明細合計から再判定する。

    引数: items(list[dict])。返り値: 検算済み条件と口座数(dict)。
    """
    seen = set()
    checked = 0
    for item in items:
        identifier = (item["版"], item["領域"], item["ID"])
        if identifier in seen:
            continue
        seen.add(identifier)
        folder = ROOT / f"work/wave_v{item['版']}" / item["領域"]
        packet = read(folder / "results" / (item["ID"] + ".json"))
        ledger = read(folder / "ledgers" / (item["ID"] + ".pkl"))
        for row in packet["rows"]:
            if row["session"] == "2026-10-09_Day":
                continue
            key = (row["session"], row["symbol"])
            trades = ledger[key]["trades"]
            # ----------------------------------------
            # 別々の元玉・保険明細が勝っていても、cidの合計が赤字なら負組になる。
            by_id = defaultdict(float)
            for trade in trades:
                by_id[int(trade[0])] += float(trade[10])
            values = list(by_id.values())
            names = ("trades", "losses", "wins", "profit", "loss") if item["版"] == 69 else (
                "campaigns", "campaign_losses", "campaign_wins", "campaign_profit", "campaign_loss")
            expected = (len(values), sum(v < 0 for v in values), sum(v > 0 for v in values),
                        sum(v for v in values if v > 0), -sum(v for v in values if v < 0))
            for name, number in zip(names, expected):
                assert abs(row[name] - number) < 1.e-6, (identifier, key, name)
            assert abs(sum(values) - row["net"]) < 1.e-6
            assert abs(max((max(0., -v) for v in values), default=0.) - row["max_trade_loss" if item["版"] == 69 else "max_campaign_loss"]) < 1.e-6
            if item["版"] == 69:
                assert len(values) == len(trades)
            checked += 1
    return dict(合格=True, 条件数=len(seen), 口座数=checked, 取引組="決済明細をcidで合算。利益保険だけを勝利としない")


def main() -> None:
    """機能: 同場の最少敗率と件数除外の影響を監査領域へ保存する。

    引数: なし。返り値: なし(None)。
    """
    records = collect()
    rankings, leaders = {}, []
    for label, minimum, active in (("全有取引", 1, 0), ("20組以上", 20, 0), ("20組8場以上", 20, 8)):
        rankings[label] = {}
        for symbol in (*SYMBOLS, None):
            rows = rank(records, minimum, active, symbol)
            rows_positive = rank(records, minimum, active, symbol, True)
            name = symbol or "両銘柄共通_最大敗率を最小化"
            rankings[label][name] = dict(比較条件数=len(rows), 最小5条件=rows[:5], 黒字条件数=len(rows_positive), 黒字限定最小3条件=rows_positive[:3])
            leaders.extend(rows[:5] + rows_positive[:3])
    audit = verify_ledgers(leaders)
    value = dict(合格=True, 同場条件数=846, 対象="wave69の192、wave70の192+診断30、wave71の432。既知全28場だけ",
                 一組定義="v69は単玉1取引。v70/v71は初回から同cid管理終了まで。途中0枚・保険利確は成功終了にしない",
                 主指標="料金後の負組数/全組数。同値組も分母、無取引は率なし。商品共通は両商品の大きい敗率を最小化",
                 枚数差="v69初回TOP5/NK10単玉、v70/v71は初回TOP10/NK20。金額は同リスク量で比較していない",
                 全28外の追加デイ除外=True, 順位=rankings, 首位群台帳再検算=audit)
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE / "既存846条件の敗率独立比較.json").write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf8")
    for label, groups in rankings.items():
        for symbol, group in groups.items():
            leader = group["最小5条件"][0]
            print(label, symbol, leader["版"], leader["ID"], leader["商品"], flush=True)
    print(audit, flush=True)


if __name__ == "__main__":
    main()
