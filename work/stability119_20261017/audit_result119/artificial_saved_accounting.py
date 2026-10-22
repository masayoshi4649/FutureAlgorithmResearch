"""保存台帳監査器自身を、市場又は売買エンジンなしの手計算fixtureで検査する。"""

import hashlib
import json
from pathlib import Path

import numpy as np

import saved_accounting as audit


HERE = Path(__file__).resolve().parent


# ----------------------------------------


def main() -> None:
    """
    機能: 独立手計算の台帳と固定6場で監査器を検査する。
    引数: なし。
    返り値: None。市場入力、保存市場cache、engineを読み込まない。
    """
    ledger = np.asarray([
        [1, 1, 3, 1., 3., 1, 1, 1000., 1011., 11000., 125. / 3, 41., 11000. - 125. / 3 - 41., 8, 0, 1.],
        [1, 1, 4, 1., 4., 1, 2, 1000., 1012., 24000., 250. / 3, 83., 24000. - 250. / 3 - 83., 4, 0, 1.],
    ])
    bars = dict(valid=np.ones(2, dtype=bool), anchor=np.asarray([1000., 1012.]),
                pub_raw_row=np.asarray([0, 3], dtype=np.int64),
                pub_price_time_s=np.asarray([0., 3.]), t_s=np.asarray([0., 3.]))
    quotes = dict(row=np.arange(5), time=np.arange(5, dtype=float),
                  bid=np.asarray([999., 999.5, 1010., 1011., 1012.]),
                  ask=np.asarray([1000., 1000., 1011., 1012., 1013.]))
    result = audit.accounting(ledger, 3, 1000., 41.8, 0)
    for key, value in dict(net=34751., realized=34751., fees=249., parents=1, wins=1,
                           losses=0, closed_quantity=3, unclosed=0, fills=3).items():
        audit.near(result[key], value, "独立手計算親会計")
    mark = audit.quote_account(ledger, bars, quotes, 3, 1000., 41.8, dict(entry_mode=0),
                               np.asarray([10., 10.]), np.ones(2, dtype=bool))
    audit.near(mark["equity"], [0., 32751.], "独立手計算の公開時清算資産")
    audit.near(mark["position"], [0, 1], "独立手計算の公開方向")
    audit.near(mark["max_drawdown"], 1750., "気配直後費用とDD")
    mirrored = ledger.copy()
    mirrored[:, 5] *= -1
    mirrored[:, 7:9] = 2000. - mirrored[:, 7:9]
    mirror_quotes = dict(quotes, bid=2000. - quotes["ask"], ask=2000. - quotes["bid"])
    mirror = audit.quote_account(mirrored, bars, mirror_quotes, 3, 1000., 41.8,
                                 dict(entry_mode=0), np.asarray([10., 10.]), np.ones(2, dtype=bool))
    audit.near(mirror["equity"], mark["equity"], "監査器も売買鏡像")
    audit.near(mirror["max_drawdown"], mark["max_drawdown"], "鏡像DD")
    partial = audit.accounting(ledger[:1], 3, 1000., 41.8, 2)
    audit.near(partial["realized"], 10834., "部分返済では未配分の新規費用も現金負担")
    audit.near(partial["fees"], 166., "部分返済の実支払費用")
    audit.check("net" not in partial, "未清算の参考評価を捏造しない")
    opened = audit.accounting(np.empty((0, 16)), 3, 1000., 41.8, 3)
    audit.near(opened["realized"], -125., "返済台帳未登場の新規費用")
    audit.near(opened["fills"], 1, "未清算新規の約定一回")
    idle = audit.accounting(np.empty((0, 16)), 3, 1000., 41.8, 0)
    audit.near(idle["net"], 0., "無取引は0円")
    corruptions = [(9, 1.), (10, 1.), (11, 1.), (12, 1.), (2, -10.)]
    for column, shift in corruptions:
        broken = ledger.copy()
        broken[0, column] += shift
        rejected = False
        try:
            audit.accounting(broken, 3, 1000., 41.8, 0)
        except AssertionError:
            rejected = True
        audit.check(rejected, "壊れた保存台帳を拒否")

    # ----------------------------------------
    # 後期場を追加しても選択6場の順位と採用が変わらない。
    scenes = ["人工" + str(i) for i in range(6)]
    specs = [dict(id="A1", family="A"), dict(id="A2", family="A"), dict(id="B1", family="B")]
    rows = []
    for spec, net in zip(specs, (10., 20., 15.)):
        for scene in scenes:
            rows.append(dict(method=spec["id"], session=scene, net=net, profit=net, loss=0., fills=2,
                             parents=1, wins=1, fees=2., unclosed=0))
    selected = audit.selection(rows, specs, scenes)
    audit.check(selected["chosen"] == ["A2", "B1"], "異family最大三枠")
    future = [dict(r, session="未来", net=1e9 if r["method"] == "A1" else -1e9) for r in rows]
    audit.check(audit.selection(rows + future, specs, scenes) == selected, "後期の大勝ち大負けは選択へ混ぜない")
    source = Path(audit.__file__)
    proof = dict(全合格=True, 検査数=audit.CHECKS, 市場読取=0, cache読取=0, 金融再生=0,
                 読取記録=audit.READS, 監査源SHA256=hashlib.sha256(source.read_bytes()).hexdigest(),
                 人工源SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    destination = HERE / "保存台帳監査器の独立手計算による純人工検査.json"
    assert not destination.exists()
    destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
