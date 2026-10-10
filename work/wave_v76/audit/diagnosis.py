"""途中返済の支持消失分類と全取引内訳を、損益を使わない過去ラベルで独立検算する。"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from account_parts import study, ROOT
from independent_account import near, save
from input_oracle import digest
from model_oracle import mapping


HERE = Path(__file__).resolve().parent
REASONS = {1: "保険の初期損切り", 2: "保険のトレーリング", 3: "保有時間上限",
    4: "場内全返済", 6: "両市場の反対合意", 7: "両市場の支持消失"}


def label(c: dict, session: str, symbol: str, side: int, decision: int,
        ready: dict, states: dict, grids: dict, mapped: np.ndarray) -> tuple:
    """機能: 返済判断までの弱支持と短期証拠だけで支持消失箇所を分類する。

    引数: c/ready/states/grids(dict)、session/symbol(str)、side/decision(int)、mapped(ndarray)。
    返り値: 支持消失ラベル、少数零OFIラベル(tuple)。出口価格と将来損益を引数に取らない。
    """
    st = states[c["signal_id"]][session]
    g = int(mapped[decision])
    assert g >= 0 and st["valid"][g]
    assert st["grid"][g] <= ready[(session, symbol)]["time_s"][decision] <= st["grid"][g] + 10.
    lost = [int(st[name][g]) != side for name in ("own_weak", "peer_weak")]
    support = "両市場" if all(lost) else "TOPIXのみ" if lost[0] else "NK225のみ" if lost[1] else "両市場支持あり"
    for s, field in (("TOPIX", "source_top"), ("NK225", "source_nk")):
        row = int(st[field][g])
        time = ready[(session, s)]["time_s"][row]
        assert time < st["grid"][g] - 5. and st["grid"][g] - 5. - time <= 30.
    poor_label = "対象外"
    if c["kind"] in ("F", "FD"):
        poor = []
        for s in ("TOPIX", "NK225"):
            w = grids[session]["markets"][s]["windows"][c["window"]]
            known = w["source_valid"][g] and not w["missing_ofi"][g]
            poor.append(bool(known and (w["zero_ofi_denominator"][g] or w["nonzero_ofi_count"][g] < 3)))
        poor_label = "両市場" if all(poor) else "TOPIXのみ" if poor[0] else "NK225のみ" if poor[1] else "少数零OFIなし"
    return support, poor_label


def summary(rows: list[dict]) -> dict:
    """機能: 全決済損失・料金・気配差・保有秒を分類群ごとに別集計する。

    引数: rows(list[dict])。返り値: 分類群会計(dict)。
    """
    count = len(rows)
    positive = [r["net"] for r in rows if r["net"] > 0]
    negative = [-r["net"] for r in rows if r["net"] < 0]
    p, loss = sum(positive), sum(negative)
    wins, loses = len(positive), len(negative)
    return dict(取引数=count, 勝数=wins, 負数=loses, 利益=p, 損失=loss, 収支=p - loss,
        平均一取引収支=(p - loss) / count if count else None, 勝率=wins / count if count else None,
        金額損失割合=loss / (p + loss) if p + loss else None,
        平均利益=p / wins if wins else None, 平均負け=loss / loses if loses else None,
        手数料=sum(r["fees"] for r in rows), 気配差負担=sum(r["spread"] for r in rows),
        平均保有分=sum(r["hold"] for r in rows) / count / 60. if count else None)


def compare(actual: dict, expected: dict) -> int:
    """機能: 分類会計の全数値を円演算誤差だけ許して照合する。

    引数: actual/expected(dict)。返り値: 比較項目数(int)。
    """
    for field, value in expected.items():
        if value is None:
            assert actual[field] is None
        else:
            near(actual[field], value, field)
    return len(expected)


def main() -> None:
    """機能: 六代表の59固定対照の全台帳分類と三期間群会計を独立検算する。

    引数: なし。返り値: なし(None)。新しいアルゴリズムや代表を作らない。
    """
    path = HERE.parent / "analysis/板支持による途中判断の効果と限界.json"
    sha = digest(path)
    diagnosis = study.load(path)
    fixed = study.load(HERE.parent / "事前固定.json")
    ready, books, states, maps, legacy, meta = study.material(5)
    grids = study.load(HERE.parent / "inputs/grids.pkl")[5]
    identities = set()
    for representative in diagnosis["固定代表"].values():
        identities.update(representative["途中と出口の内訳"])
    map_cache = {key: mapping(states["Q10"][key[0]]["grid"], r["time_s"]) for key, r in ready.items()}
    records = {}
    management_labels = details = field_checks = groups = 0
    for ident in sorted(identities):
        packet = study.load(HERE.parent / "results" / f"{ident}.json")
        c = packet["config"]
        archive = study.load(HERE.parent / "ledgers" / f"{ident}.pkl")
        rows = []
        for key, ledger in archive.items():
            session, symbol = key
            entry = {int(o[2]): o for o in ledger["orders"] if o[7] == 1}
            exits = {int(o[2]): o for o in ledger["orders"] if o[7] == 0}
            for t in ledger["trades"]:
                cid, side, qty = int(t[0]), int(t[3]), int(t[4])
                ei, xi = int(t[1]), int(t[2])
                en, ex = entry[cid], exits[cid]
                reason = int(ex[6])
                support = poor = "対象外"
                if reason in (6, 7):
                    support, poor = label(c, session, symbol, side, int(ex[1]), ready, states, grids, map_cache[key])
                    assert reason != 7 or support != "両市場支持あり"
                    management_labels += 1
                price_entry = books[key]["ask"][ei] if side == 1 else books[key]["bid"][ei]
                price_exit = books[key]["bid"][xi] if side == 1 else books[key]["ask"][xi]
                fee_one = qty * 418 // 10 if symbol == "TOPIX" else qty * 11
                value = 1000. if symbol == "TOPIX" else 10.
                gross = side * qty * value * (price_exit - price_entry)
                near(t[10], gross - 2 * fee_one, "独立明細損益")
                spread = .5 * qty * value * ((books[key]["ask"][ei] - books[key]["bid"][ei])
                    + (books[key]["ask"][xi] - books[key]["bid"][xi]))
                rows.append(dict(session=session, symbol=symbol, reason=reason, flipped=int(en[6]) == 12,
                    support=support, poor=poor, net=gross - 2 * fee_one, fees=2 * fee_one,
                    spread=spread, hold=ready[key]["time_s"][xi] - ready[key]["time_s"][ei]))
                details += 1
        records[ident] = rows
    for representative in diagnosis["固定代表"].values():
        for ident, periods in representative["途中と出口の内訳"].items():
            for period, symbols in periods.items():
                for symbol, actual in symbols.items():
                    selected = [r for r in records[ident] if r["symbol"] == symbol and r["session"] in fixed[period]]
                    for reason, text in REASONS.items():
                        field_checks += compare(actual["返済理由別"][text], summary([r for r in selected if r["reason"] == reason]))
                        groups += 1
                    for flag, text in ((True, "反転新規"), (False, "通常新規")):
                        field_checks += compare(actual[text], summary([r for r in selected if r["flipped"] == flag]))
                        groups += 1
                    for name in ("TOPIXのみ", "NK225のみ", "両市場"):
                        field_checks += compare(actual["支持消失返済の箇所別"][name],
                            summary([r for r in selected if r["reason"] == 7 and r["support"] == name]))
                        groups += 1
                    for name in ("TOPIXのみ", "NK225のみ", "両市場", "少数零OFIなし", "対象外"):
                        field_checks += compare(actual["支持消失判断時の少数零OFI"][name],
                            summary([r for r in selected if r["reason"] == 7 and r["poor"] == name]))
                        groups += 1
    assert digest(path) == sha
    save(HERE / "途中支持消失分類と反転全明細の独立監査.json", dict(合格=True,
        固定代表数=6, 独立対照台帳数=len(identities), 全決済明細数=details,
        過去管理状態ラベル数=management_labels, 商品期間分類群比較数=groups, 金額等項目比較数=field_checks,
        分類に未来損益を渡さない=True, 原本seq最新格子とstrictpast双方参照を確認=True,
        分析SHA256=sha, 代表変更なし=True, 条件追加なし=True,
        限界="管理時点の過去状態による記述的内訳。返済理由別や反転玉の利益を因果効果・対照差額と解釈しない。",
        原本取得=0, API取得=0, 実注文=0))
    print(f"{len(identities)}固定台帳・{management_labels:,}過去ラベル・{groups:,}群会計が独立一致しました", flush=True)


if __name__ == "__main__":
    main()
