"""同じS1実新規の相手確認ラベルと全料金後二群会計を独立確認する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

from independent_account import fee, near, save
from model_synthetic import oracle_features
from real_signals import load_material


HERE = Path(__file__).resolve().parent


def money(records: list[dict]) -> dict:
    """機能: 全決済の損失を相殺せずに二群金額を独立集計する。

    引数: records(list[dict])。返り値: 料金後の件数・金額・比率(dict)。
    """
    nets = [record["収支"] for record in records]
    profit, loss = sum(max(net, 0.) for net in nets), sum(max(-net, 0.) for net in nets)
    wins, defeats = sum(net > 0 for net in nets), sum(net < 0 for net in nets)
    count = len(nets)
    return dict(取引数=count, 勝数=wins, 負数=defeats, 同値数=count - wins - defeats,
        勝率=wins / count if count else None, 利益=profit, 損失=loss, 収支=profit - loss,
        平均一取引収支=(profit - loss) / count if count else None,
        平均利益=profit / wins if wins else None, 平均負け=loss / defeats if defeats else None,
        金額損失割合=loss / (profit + loss) if profit + loss else None,
        手数料=sum(record["手数料"] for record in records), 活動場数=len({record["セッション"] for record in records}))


def label(candidate: np.ndarray, r: dict, peer: dict, own: dict, other: dict, grid: np.ndarray) -> dict:
    """機能: 返済結果を引数に取らず、当時の価格進行条件から相手確認を分類する。

    引数: candidate(np.ndarray)、r/peer/own/other(dict)、grid(np.ndarray)。
    返り値: 過去参照証跡と確認ラベル(dict)。S1の自状態は事前条件として検査する。
    """
    g, decision, side, own_row, peer_row = map(int, candidate)
    assert own["valid"][g] and other["valid"][g]
    assert own["confirmation"][g] == side and side * own["ret"][g] >= 3.
    assert own_row == own["now"][g] and peer_row == other["now"][g] and own_row < decision
    stamp = float(grid[g])
    assert r["time_s"][own_row] < stamp - 5. and peer["time_s"][peer_row] < stamp - 5.
    assert stamp - 5. - r["time_s"][own_row] <= 30. and stamp - 5. - peer["time_s"][peer_row] <= 30.
    assert stamp <= r["time_s"][decision] <= stamp + 10.
    confirmed = side * other["ret"][g] >= 3. and side * other["short_ret"][g] >= 0
    joint_side = side if confirmed else 0
    return dict(相手確認="相手確認あり" if confirmed else "相手確認なし", 共通判断行=g,
        共通代理時計=stamp, 発注判断行=decision, 発注判断連番=int(r["seq"][decision]), 発注代理時計=float(r["time_s"][decision]),
        建玉方向=side, 自参照行=own_row, 自参照連番=int(r["seq"][own_row]), 自参照代理時計=float(r["time_s"][own_row]),
        相手参照行=peer_row, 相手参照連番=int(peer["seq"][peer_row]), 相手参照代理時計=float(peer["time_s"][peer_row]),
        単独当時状態=side, 共同当時状態=joint_side)


def main() -> None:
    """機能: 142新規を漏れなく過去条件で分類し、元の返済価格・料金で全群を検算する。

    引数: なし。返り値: なし(None)。追加戦略再生・選定変更は行わない。
    """
    source = HERE.parent / "analysis/同じ新規機会での相手確認診断.json"
    diagnostic = json.loads(source.read_text(encoding="utf-8"))
    fixed = json.loads((HERE.parent / "事前固定.json").read_text(encoding="utf-8"))
    ident = "S1_W300_L0_T40_H30"
    ledger = pickle.loads((HERE.parent / "ledgers" / (ident + ".pkl")).read_bytes())
    entry = pickle.loads((HERE.parent / "prepared/signals_delay5.pkl").read_bytes())
    ready, book, sync, meta = load_material()
    records = []
    states = {}
    for session in sorted(sync):
        grid = sync[session]["grid"]
        for symbol in ("TOPIX", "NK225"):
            key = session, symbol
            states[key] = oracle_features(grid, 5, 300, dict(book[key], tick=ready[key]["tick"]), 30)
    for key in sorted(ledger):
        r, f = ready[key], book[key]
        peer_key = (key[0], "NK225" if key[1] == "TOPIX" else "TOPIX")
        candidates = {int(candidate[1]): candidate for candidate in entry["S1_W300_L0"][key]["candidates"]}
        assert len(candidates) == len(entry["S1_W300_L0"][key]["candidates"])
        opens = {int(order[2]): order for order in ledger[key]["orders"] if order[7] == 1}
        assert len(opens) == len(ledger[key]["trades"])
        for trade in ledger[key]["trades"]:
            cid, new_i, exit_i, side, qty = (int(trade[column]) for column in range(5))
            decision = int(opens[cid][1])
            classification = label(candidates[decision], r, ready[peer_key], states[key], states[peer_key], sync[key[0]]["grid"])
            assert classification["建玉方向"] == side and int(opens[cid][0]) == new_i
            assert new_i > decision and exit_i > new_i
            entry_price = float(f["ask"][new_i] if side == 1 else f["bid"][new_i])
            exit_price = float(f["bid"][exit_i] if side == 1 else f["ask"][exit_i])
            fees = 2 * fee(key[1], qty)
            net = side * (exit_price - entry_price) * qty * (1000 if key[1] == "TOPIX" else 10) - fees
            near(net, float(trade[10]), "S1元決済の独立会計")
            records.append(dict(**classification, セッション=key[0], 銘柄=key[1], 取引番号=cid, 実新規行=new_i,
                実返済行=exit_i, 実新規価格=entry_price, 実返済価格=exit_price, 手数料=float(fees), 収支=float(net)))
    assert records == diagnostic["明細"] and len(records) == diagnostic["全明細数"] == 142
    for period in ("前16", "後13", "全29"):
        for symbol in ("TOPIX", "NK225"):
            saved = diagnostic["比較"][period][symbol]
            subset = [r for r in records if r["セッション"] in fixed[period] and r["銘柄"] == symbol]
            for group in ("全S1", "相手確認あり", "相手確認なし"):
                members = subset if group == "全S1" else [r for r in subset if r["相手確認"] == group]
                assert money(members) == saved[group]
            for field in ("取引数", "利益", "損失", "収支", "手数料"):
                near(float(saved["相手確認あり"][field] + saved["相手確認なし"][field]), float(saved["全S1"][field]), str((period, symbol, field)))
    save(HERE / "同じ新規機会の過去確認分類と金額の独立監査.json", dict(合格=True, 実新規全明細数=142,
        分類条件="当時の自価格300秒進行3bpと両気配確認に加え、相手の300秒進行が同方向3bp以上かつ15秒変化非逆行。J1pulseは使わない。",
        過去ラベル完全一致=True, 新規漏れ及び重複=0, 期間商品群会計比較数=18,
        全29二群={symbol: {group: diagnostic["比較"]["全29"][symbol][group] for group in ("相手確認あり", "相手確認なし")} for symbol in ("TOPIX", "NK225")},
        診断SHA256=hashlib.sha256(source.read_bytes()).hexdigest(),
        限界="元S1新規と既存返済を固定した記述的な二群比較。除外後の新たな入場機会や保有経路を再計算しておらず、新しい運用アルゴリズムの成績・純粋な因果効果・将来確率の証明ではない。",
        選定変更なし=True, 追加戦略再生数=0, 原本取得=0, API取得=0, 実注文=0))
    print("S1全142新規の過去分類・全18二群会計が独立一致しました", flush=True)


if __name__ == "__main__":
    main()
