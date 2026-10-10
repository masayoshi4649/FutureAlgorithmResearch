"""全ての部分決済損失を相殺せず、二商品の金額順位を独立に再集計する。"""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SYMBOLS = ("TOPIX", "NK225")


def read(path: Path) -> object:
    """機能: 保存結果又は台帳を読取専用で取得する。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == ".pkl" else json.loads(path.read_text(encoding="utf8"))


def collect() -> tuple[list[dict], list[dict]]:
    """機能: 846条件全28と432条件全29を個別口座行から別々に集計する。

    引数: なし。返り値: 全28・全29の集計(tuple[list[dict],list[dict]])。
    """
    fixed = read(ROOT / "work/wave_v70/事前固定.json")
    sessions28 = set(fixed["全セッション"])
    sets = {"全28": sessions28, "全29": sessions28 | {"2026-10-09_Day"}}
    output = {"全28": [], "全29": []}
    for version, area, expected in ((69, "", 192), (70, "", 192), (70, "controls", 30), (71, "", 432)):
        folder = ROOT / f"work/wave_v{version}" / area
        paths = sorted((folder / "results").glob("*.json"))
        assert len(paths) == expected
        for path in paths:
            packet = read(path)
            for period in (("全28", "全29") if version == 71 else ("全28",)):
                record = dict(版=version, 領域=area, ID=packet["config"]["id"], 期間=period,
                    config=packet["config"], 結果=str(path.relative_to(ROOT)), 商品={})
                for symbol in SYMBOLS:
                    rows = [r for r in packet["rows"] if r["symbol"] == symbol and r["session"] in sets[period]]
                    assert len(rows) == len(sets[period]) and {r["session"] for r in rows} == sets[period]
                    fields = ("profit", "loss", "net", "fees", "wins", "losses", "trades", "winning_lots", "losing_lots", "flat_lots")
                    a = {field: sum(r[field] for r in rows) for field in fields}
                    for field, value in a.items():
                        assert abs(value - packet["periods"][period][symbol][field]) < 1.e-6
                    assert abs(a["profit"] - a["loss"] - a["net"]) < 1.e-6
                    groups_field = "trades" if version == 69 else "campaigns"
                    a.update(組数=sum(r[groups_field] for r in rows), 活動場数=sum(r[groups_field] > 0 for r in rows),
                        商品=symbol, 金額損失割合=a["loss"] / (a["profit"] + a["loss"]) if a["profit"] + a["loss"] else None,
                        PF=a["profit"] / a["loss"] if a["loss"] else None,
                        平均利益=a["profit"] / a["wins"] if a["wins"] else None,
                        平均損失=a["loss"] / a["losses"] if a["losses"] else None,
                        前16収支=packet["periods"]["前16"][symbol]["net"], 後12収支=packet["periods"]["後12"][symbol]["net"],
                        最大黒字場除外=a["net"] - max(r["net"] for r in rows),
                        含み込み最大下落=packet["periods"][period][symbol]["drawdown"])
                    campaign_profit = sum(r["campaign_profit"] for r in rows) if version != 69 else a["profit"]
                    campaign_loss = sum(r["campaign_loss"] for r in rows) if version != 69 else a["loss"]
                    assert abs(campaign_profit - campaign_loss - a["net"]) < 1.e-6
                    assert a["profit"] >= campaign_profit - 1.e-6 and a["loss"] >= campaign_loss - 1.e-6
                    assert abs((a["profit"] - campaign_profit) - (a["loss"] - campaign_loss)) < 1.e-6
                    a["一組内で相殺される明細損失額"] = a["loss"] - campaign_loss
                    if version == 71:
                        a["追加デイ収支"] = packet["periods"]["追加1"][symbol]["net"]
                    record["商品"][symbol] = a
                output[period].append(record)
    assert len(output["全28"]) == 846 and len(output["全29"]) == 432
    return output["全28"], output["全29"]


def key(record: dict) -> str:
    """機能: 期間・版・領域・IDを分離した識別子を作る。

    引数: record(dict)。返り値: 識別子(str)。
    """
    return f"{record['期間']}/v{record['版']}/{record['領域']}/{record['ID']}"


def ratio(record: dict, symbol: str) -> Fraction:
    """機能: 全明細の利益と損失から丸め前の比較値を作る。

    引数: record(dict)、symbol(str)。返り値: 正確な金額割合(Fraction)。
    """
    a = record["商品"][symbol]
    return Fraction(str(a["loss"])) / Fraction(str(a["profit"] + a["loss"]))


def ranking(records: list[dict], symbol: str | None, minimum: int, active: int) -> list[dict]:
    """機能: G3と無取引を除き、金額だけで順位を作る。

    引数: records(list[dict])、symbol(str|None)、minimum/active(int)。返り値: 順位(list[dict])。
    枚数や回数は得点・同率処理に使わず、件数条件は別の参考順位へ限定する。
    """
    symbols = (symbol,) if symbol else SYMBOLS
    chosen = [r for r in records if r["config"].get("gate_level", 0) != 3 and
              all(r["商品"][s]["組数"] >= minimum and r["商品"][s]["活動場数"] >= active for s in symbols)]
    return sorted(chosen, key=lambda r: (max(ratio(r, s) for s in symbols), r["版"], r["ID"]))


def short(record: dict, symbol: str) -> dict:
    """機能: 銘柄別主金額と件数情報を出典付きで短く保存する。

    引数: record(dict)、symbol(str)。返り値: 説明用指標(dict)。
    """
    return dict(識別子=key(record), ID=record["ID"], 版=record["版"], 領域=record["領域"], 期間=record["期間"],
        出典=record["結果"], 初回枚数=5 if record["版"] == 69 and symbol == "TOPIX" else 10 if record["版"] == 69 else 10 if symbol == "TOPIX" else 20,
        **record["商品"][symbol])


def verify_selected(records: list[dict]) -> dict:
    """機能: 上位台帳の全明細損益・費用・保有全返済を直接確認する。

    引数: records(list[dict])。返り値: 条件・口座・明細検査件数(dict)。
    """
    done, accounts, detail_count = set(), 0, 0
    for record in records:
        tag = key(record)
        if tag in done:
            continue
        done.add(tag)
        folder = ROOT / f"work/wave_v{record['版']}" / record["領域"]
        ledger = read(folder / "ledgers" / (record["ID"] + ".pkl"))
        packet = read(ROOT / record["結果"])
        for reported in packet["rows"]:
            if record["期間"] == "全28" and reported["session"] == "2026-10-09_Day":
                continue
            symbol = reported["symbol"]
            data = ledger[(reported["session"], symbol)]
            trades, orders = data["trades"], data["orders"]
            fees, held = 0, {1: 0, -1: 0}
            for order in orders:
                side, qty, new = int(order[3]), int(order[4]), int(order[7])
                held[side if new else -side] += qty if new else -qty
                assert min(held.values()) >= 0
                fees += qty * 418 // 10 if symbol == "TOPIX" else qty * 11
            assert held[1] == held[-1] == 0
            assert fees == int(trades[:, 7:9].sum()) == reported["fees"]
            nets = trades[:, 10]
            for field, number in (("profit", float(nets[nets > 0].sum())), ("loss", float(-nets[nets < 0].sum())),
                                  ("net", float(nets.sum())), ("wins", int((nets > 0).sum())),
                                  ("losses", int((nets < 0).sum())), ("trades", len(trades))):
                assert abs(reported[field] - number) < 1.e-6
            groups = defaultdict(float)
            for trade in trades:
                groups[int(trade[0])] += float(trade[10])
            assert abs(sum(groups.values()) - reported["net"]) < 1.e-6
            accounts += 1
            detail_count += len(trades)
    return dict(合格=True, 期間別条件数=len(done), 口座数=accounts, 全決済明細数=detail_count,
        全明細損失と新規返済手数料を算入=True, 一組収支と全明細収支一致=True, 残玉なし=True)


def main() -> None:
    """機能: 全明細を主指標として二つの期間を別集計し、新JSONだけ保存する。

    引数: なし。返り値: なし(None)。既存キャンペーン金額監査は変更しない。
    """
    a, b = collect()
    periods, selected = {}, []
    for name, records in (("全28_846条件", a), ("全29_wave71だけ432条件", b)):
        periods[name] = {}
        for label, minimum, active in (("主_1組以上", 1, 0), ("参考_20組8活動場以上", 20, 8)):
            symbol_rows = {}
            for symbol in SYMBOLS:
                rows = ranking(records, symbol, minimum, active)
                symbol_rows[symbol] = dict(対象条件数=len(rows), 最少金額損失割合上位5=[short(r, symbol) for r in rows[:5]],
                    PF最大は同じ順位=True)
                selected.extend(rows[:5])
            common = ranking(records, None, minimum, active)
            common_rows = [dict(ID=r["ID"], 版=r["版"], 領域=r["領域"], 最悪側金額損失割合=float(max(ratio(r, s) for s in SYMBOLS)),
                                商品別={s: short(r, s) for s in SYMBOLS}) for r in common[:3]]
            selected.extend(common[:3])
            periods[name][label] = dict(商品別=symbol_rows, 共通対象条件数=len(common), 最悪側最少上位3=common_rows,
                共通両黒字条件数=sum(all(r["商品"][s]["net"] > 0 for s in SYMBOLS) for r in common))
    proof = verify_selected(selected)
    value = dict(合格=True, 主指標="全ての部分決済明細の料金後損失/(料金後利益+料金後損失)。一組内で利益と損失を相殺しない",
        PF="全決済明細の料金後利益/料金後損失。損失割合=1/(1+PF)なので順位は同じ",
        主件数条件="1組以上。枚数と回数は順位得点に使わず表示。20組8場はユーザー要件でなく別参考",
        同期G3除外理由="原本に共通受信時計がなく、二市場の受信順同期を証明できない参考条件だから",
        商品を円合算しない=True, 全28と全29を混ぜない=True, 期間別=periods, 上位台帳監査=proof,
        総損失額だけの注意="枚数や取引数を減らすだけで総損失は下がるため、主順位は金額の利益対損失にする。無取引は順位外",
        数量差="wave69 TOP5/NK10、wave70/71 TOP10/NK20。銘柄間の円額単純比較はしない",
        範囲="旧CurrentPrice約定や指値仮定の別研究をここへ混ぜず、価格仮定別の参考とする",
        原本読取=False, API取得=0, 実注文=0)
    path = HERE / "全明細金額による全28と全29の独立再選定.json"
    assert not path.exists(), "過去監査を上書きしない"
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf8")
    print(proof, flush=True)
    print("全明細主指標の全28/846・全29/432を別集計: 合格", flush=True)


if __name__ == "__main__":
    main()
