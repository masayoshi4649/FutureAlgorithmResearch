"""00157の保存会計を集計する共通関数。売買条件・注文生成は含めない。"""

from collections import Counter
import math
import statistics


def finite(value: float, label: str) -> float:
    """欠測や非有限数値を損益0へ置き換えず、集計前に拒否する。

    引数: value(float)は対象数値、label(str)は識別名。
    返り値: floatは有限な入力。不正なら例外を返す。
    """
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"有限数値が必要: {label}: {value}")
    return float(value)


def summarize(rows: list[dict]) -> dict:
    """完了場の親会計と場内リスクを、収益と損失の両側から集計する。

    引数: rows(list[dict])は完了場のみ、損失は正数として保存する。
    返り値: dictは合計・赤字頻度と深さ・上位3除外・場内最悪値。
    """
    for row in rows:
        if row.get("partial"):
            raise ValueError("途中場を完了集計へ混ぜない")
        for key in ("profit", "loss", "net"):
            finite(row[key], f'{row["session"]}/{key}')
        if row["profit"] < 0 or row["loss"] < 0:
            raise ValueError("利益と損失は正額として分類する")
        if abs(row["profit"] - row["loss"] - row["net"]) > 1e-6:
            raise ValueError(f'親会計不一致: {row["session"]}')
    profit = sum(row["profit"] for row in rows)
    loss = sum(row["loss"] for row in rows)
    net = sum(row["net"] for row in rows)
    winners = sorted((row["net"] for row in rows if row["net"] > 0), reverse=True)
    losers = [-row["net"] for row in rows if row["net"] < 0]
    summary = {
        "sessions": len(rows), "profit": profit, "loss": loss, "net": net,
        "pf": profit / loss if loss else None,
        "profit_share": profit / (profit + loss) if profit + loss else None,
        "wins": len(winners), "losses": len(losers), "flat": sum(row["net"] == 0 for row in rows),
        "no_trade": sum(row["entries"] == 0 for row in rows),
        "maxloss": max(losers, default=0), "avgloss": statistics.mean(losers) if losers else 0,
        "medianloss": statistics.median(losers) if losers else 0,
        "ex3": net - sum(winners[:3]), "excluded_positive_sessions": min(3, len(winners)),
        "entries": sum(row["entries"] for row in rows),
    }
    if rows:
        worst = min(rows, key=lambda row: row["intraday_risk"]["min_equity"])
        drawdown = max(rows, key=lambda row: row["intraday_risk"]["max_drawdown"])
        realized = min(rows, key=lambda row: row["intraday_risk"]["min_realized"])
        summary.update({
            "min_equity": worst["intraday_risk"]["min_equity"], "min_equity_session": worst["session"],
            "max_drawdown": drawdown["intraday_risk"]["max_drawdown"],
            "max_drawdown_session": drawdown["session"],
            "min_realized": realized["intraday_risk"]["min_realized"],
            "min_realized_session": realized["session"],
        })
    return summary


def quantity_distribution(quantities: list[int]) -> dict:
    """初回に実約定した整数micro枚数の分布を整理する。

    引数: quantities(list[int])は採用親ごとの初回実約定数量。
    返り値: dictは分布、中央値・平均・最大最小。拒否親は別集計する。
    """
    if any(not isinstance(value, int) or value <= 0 for value in quantities):
        raise ValueError("採用親の初回数量は正の整数micro")
    return {"parents": len(quantities), "histogram": dict(sorted(Counter(quantities).items())),
            "minimum": min(quantities) if quantities else None,
            "maximum": max(quantities) if quantities else None,
            "mean": statistics.mean(quantities) if quantities else None,
            "median": statistics.median(quantities) if quantities else None}


def attach_cumulative(rows: list[dict]) -> list[dict]:
    """セッション順の確定収支を積み上げた新しい行配列を返す。

    引数: rows(list[dict])は完了場の会計。
    返り値: list[dict]は時系列整列・累計追加済み。元の配列は変更しない。
    """
    result, cumulative = [], 0.0
    for original in sorted(rows, key=lambda row: row["session"]):
        row = dict(original)
        cumulative += finite(row["net"], row["session"])
        row["cumulative"] = cumulative
        result.append(row)
    return result
