"""公開診断の気配差を全約定行の買気配・売気配から独立再計算する。"""

from __future__ import annotations

from pathlib import Path
import json

import numpy as np

from causality import study
from independent_account import near, save


HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: 固定代表の各期間について、売買気配差・広い気配の件数を照合する。

    引数: なし。返り値: なし(None)。約定時刻を固定する診断であり再注文ではない。
    """
    fixed = study.load(HERE.parent / "事前固定.json")
    selection = study.load(HERE.parent / "前半選定.json")
    diagnostic = study.load(HERE.parent / "analysis/気配差と出口の独立診断.json")
    ready, features, meta = study.material()
    checked = []
    for selected in selection["代表"]:
        ident = selected["id"]
        ledger = study.load(HERE.parent / "ledgers" / (ident + ".pkl"))
        for period in ("前16", "後13", "全29"):
            for symbol in ("TOPIX", "NK225"):
                entry_spreads, exit_spreads, fees, nets, total_drag = [], [], [], [], 0.
                for key, l in ledger.items():
                    if key[1] != symbol or key[0] not in fixed[period]:
                        continue
                    f, tick = features[key], ready[key]["tick"]
                    multiplier = 1000. if symbol == "TOPIX" else 10.
                    for trade in l["trades"]:
                        entry_i, exit_i = int(trade[1]), int(trade[2])
                        entry_spread = float(f["ask"][entry_i] - f["bid"][entry_i])
                        exit_spread = float(f["ask"][exit_i] - f["bid"][exit_i])
                        entry_spreads.append(entry_spread / tick)
                        exit_spreads.append(exit_spread / tick)
                        total_drag += (entry_spread + exit_spread) / 2. * trade[4] * multiplier
                        fees.append(trade[7] + trade[8])
                        nets.append(trade[10])
                asserted = dict(取引数=len(nets), 利益=sum(net for net in nets if net > 0), 損失=-sum(net for net in nets if net < 0),
                    収支=sum(nets), 手数料=sum(fees), 気配差負担=total_drag,
                    新規気配差平均呼値=float(np.mean(entry_spreads)) if entry_spreads else None,
                    返済気配差平均呼値=float(np.mean(exit_spreads)) if exit_spreads else None,
                    新規気配差二呼値超の数=sum(value > 2 + 1.e-8 for value in entry_spreads),
                    返済気配差二呼値超の数=sum(value > 2 + 1.e-8 for value in exit_spreads),
                    新規気配差最大呼値=max(entry_spreads, default=None), 返済気配差最大呼値=max(exit_spreads, default=None))
                actual = diagnostic["固定代表の会計診断"][ident][period][symbol]["全取引"]
                for field, value in asserted.items():
                    if value is None:
                        assert actual[field] is None
                    else:
                        near(float(actual[field]), float(value), str((ident, period, symbol, field)))
                checked.append(dict(ID=ident, 期間=period, 商品=symbol, **asserted))
    save(HERE / "気配差診断の独立照合.json", dict(合格=True, 照合期間商品数=len(checked), 記録=checked,
        解釈="新規判断は2ラージ呼値以内だが、条件成立後の次有効気配約定と返済には気配差上限を設けていない。これは事前実装通り。中値置換は同時点の診断のみで、実現可能な約定改善を証明しない。",
        原本取得=0, API取得=0, 実注文=0))
    print(json.dumps(dict(合格=True, 照合期間商品数=len(checked)), ensure_ascii=False))


if __name__ == "__main__":
    main()
