"""統合29場の注文と五期間の金額集計を、旧28場・追加場の独立会計へ照合する。"""

from __future__ import annotations

import hashlib

import numpy as np

from r01_money_audit import ROOT, HERE, SYMBOLS, read, save_new, audit_packet, indicators


def main() -> None:
    """機能: 統合JSONと全台帳の58口座・五期間を検算し、新しい監査を保存する。

    引数: なし。返り値: なし(None)。原本/APIは使用しない。
    """
    folder = ROOT / "work/wave_v72/replay"
    result_path = folder / "T1L1_R01_全セッション.json"
    ledger_path = folder / "T1L1_R01_全台帳.pkl"
    packet, ledger = read(result_path), read(ledger_path)
    old = read(ROOT / "work/wave_v70/results/T1L1_R01.json")
    old_ledger = read(ROOT / "work/wave_v70/ledgers/T1L1_R01.pkl")
    extra = read(folder / "T1L1_R01_追加セッション.json")
    extra_ledger = read(folder / "T1L1_R01_追加台帳.pkl")
    assert packet["config"] == old["config"] == extra["config"]
    assert packet["rows"] == old["rows"] + extra["rows"]
    assert set(ledger) == set(old_ledger) | set(extra_ledger) and not set(old_ledger) & set(extra_ledger)
    for key, account in {**old_ledger, **extra_ledger}.items():
        for field in ("orders", "trades", "counters"):
            np.testing.assert_array_equal(ledger[key][field], account[field])
        assert ledger[key]["curve_hash"] == account["curve_hash"]
    assert packet["ledger_SHA256"] == hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    rows = audit_packet(packet, ledger)
    assert len(rows) == 58
    fixed = read(ROOT / "work/wave_v70/事前固定.json")
    extra_sessions = sorted({r["session"] for r in extra["rows"]})
    periods = {"前16": fixed["前16"], "後12": fixed["後12"], "全28": fixed["全セッション"],
               "追加1": extra_sessions, "全29": fixed["全セッション"] + extra_sessions}
    assert set(packet["periods"]) == set(periods)
    sums = {}
    for period, sessions in periods.items():
        selected = [r for r in rows if r["session"] in sessions]
        sums[period] = {}
        for symbol in SYMBOLS:
            amount = indicators(selected, symbol)
            reported = packet["periods"][period][symbol]
            for field, value in amount.items():
                if field in reported:
                    assert abs(value - reported[field]) < 1.e-6, (period, symbol, field)
            if amount["trades"]:
                assert abs(amount["wins"] / amount["trades"] - reported["campaign_win_rate"]) < 1.e-10
            else:
                assert reported["campaign_win_rate"] is None
            if amount["平均勝負比"] is None:
                assert reported["campaign_payoff"] is None
            else:
                assert abs(amount["平均勝負比"] - reported["campaign_payoff"]) < 1.e-10
            denominator = 5000 if symbol == "TOPIX" else 2000
            assert abs(amount["net"] / denominator - reported["net_ticks"]) < 1.e-9
            sums[period][symbol] = amount
    assert sums["全28"] == read(HERE / "R01既存28場の金額会計独立監査.json")["商品別全28"]
    assert sums["全29"] == read(HERE / "R01追加1場と全29場の金額会計独立監査.json")["全場商品別"]
    save_new(HERE / "R01全29場統合結果の金額独立照合.json", dict(合格=True,
        ID="T1L1_R01", セッション数=29, 独立会計口座数=58, 五期間商品別一致数=10,
        旧28場と追加場の台帳完全一致=True, 商品別五期間金額会計=sums,
        商品別のみ円集計=True, 原本読取=False, API取得=0, 実注文=0,
        統合結果_SHA256=hashlib.sha256(result_path.read_bytes()).hexdigest(),
        統合台帳_SHA256=hashlib.sha256(ledger_path.read_bytes()).hexdigest()))
    print("R01統合29場・58口座・旧追加全台帳・五期間10集計: 合格", flush=True)


if __name__ == "__main__":
    main()
