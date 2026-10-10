"""旧95%探索の25場会計を別集計し、直近28場と混同できない範囲を確認する。"""

from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SYMBOLS = ("TOPIX", "NK225")


def main() -> None:
    """機能: 旧375条件の全玉組会計を個別行から再集計して範囲別の最小敗率を保存する。

    引数: なし。返り値: なし(None)。旧成果は変更しない。
    """
    path = ROOT / "アルゴリズム調査/00060_決済勝率95パーセントの探索とPDCA/調査仕様と集計.json"
    source = json.loads(path.read_text(encoding="utf8"))
    assert source["meta"]["セッション数"] == 25
    records = []
    for method in source["methods"]:
        item = dict(枝=method["branch"], ID=method["id"], 約定仮定=method["mode"], 商品={})
        for symbol in SYMBOLS:
            rows = [a for a in method["accounts"] if a["symbol"] == symbol]
            assert len(rows) == len({a["session"] for a in rows}) == 25
            total, losses, wins, flats, net, profit, loss = (sum(a[k] for a in rows) for k in ("cycles", "losses", "wins", "flats", "net", "profit", "loss"))
            assert total == losses + wins + flats and abs(profit - loss - net) < 1.e-6
            reported = method["summary"][symbol]
            for key in ("cycles", "losses", "wins", "flats", "net", "profit", "loss", "fees"):
                assert abs(reported[key] - sum(a[key] for a in rows)) < 1.e-6
            item["商品"][symbol] = dict(組数=total, 負組数=losses, 勝組数=wins, 同値組数=flats,
                敗率=losses / total if total else None, 収支=net, 活動場数=sum(a["cycles"] > 0 for a in rows),
                平均勝負比=(profit / wins) / (loss / losses) if wins and losses and loss else None)
        records.append(item)
    assert len(records) == 375
    result = {}
    for name, reference in (("買ask売bidだけ", False), ("参考約定込み", True)):
        result[name] = {}
        for symbol in (*SYMBOLS, None):
            symbols = (symbol,) if symbol else SYMBOLS
            rows = [r for r in records if (reference or r["約定仮定"] == "quote")
                    and all(r["商品"][s]["組数"] >= 20 and r["商品"][s]["活動場数"] >= 8 for s in symbols)]
            rows.sort(key=lambda r: (max(Fraction(r["商品"][s]["負組数"], r["商品"][s]["組数"]) for s in symbols), r["枝"], r["ID"]))
            result[name][symbol or "両銘柄最大敗率"] = dict(比較条件数=len(rows), 最小3件=rows[:3])
    tiny = [r for r in records for s in SYMBOLS if r["商品"][s]["組数"] and r["商品"][s]["勝組数"] / r["商品"][s]["組数"] >= .95]
    assert len(tiny) == 5 and all(r["商品"]["TOPIX"]["組数"] == 1 and r["商品"]["NK225"]["組数"] == 0 for r in tiny)
    value = dict(合格=True, 旧条件数=375, 全個別口座数=18750, 対象場数=25,
        組会計="新規から両側全玉0まで。group_losses/group_profitがある枝はそれを正規化済み。利益玉だけを勝ちにしない",
        直近全28へ直接混ぜない理由="25場で終了し、新規指値仮定・中値・相手時計参考を含む。初回TOP5/NK10。実行価格仮定も枝別",
        最小敗率=result, 旧95パーセント以上の条件=tiny,
        結論="旧375条件の95%以上はTOPの1勝1組だけ。数を重ねる95%の証拠ではない。全研究を一括した最少敗率とは断定しない",
        旧資料_SHA256=hashlib.sha256(path.read_bytes()).hexdigest())
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE / "旧95パーセント探索の敗率と範囲監査.json").write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf8")
    print(json.dumps(result["買ask売bidだけ"], ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
