"""保険だけを外した追加診断対照の独立会計・集計・条件一致を照合する。"""

from __future__ import annotations

from audit_all import read, digest, ROOT, WORK, HERE
from combine import aggregate
from independent_account import near, save


def main() -> None:
    """機能: 追加30条件・1680口座の別会計と原因切分けの条件対応を照合する。

    引数: なし。返り値: なし(None)。
    """
    fixed = read(WORK / "事前固定.json")
    diagnostic = read(WORK / "追加対照の事前固定.json")
    selected_sha = digest(WORK / "前半選定.json")
    ready = read(ROOT / "work/wave_v69/prepared/inputs.pkl")
    configs = {c["id"]: c for c in fixed["条件"]}
    records = []
    for path in sorted(HERE.glob("保険なし独立監査_*of3.json")):
        packet = read(path)
        assert packet["合格"] and packet["条件数"] == 10 and packet["口座数"] == 560
        records.extend(packet["条件"])
    assert len(records) == len({r["ID"] for r in records}) == 30
    assert {r["ID"] for r in records} == {c["id"] for c in diagnostic["条件"]}
    relevant = ("source", "source_index", "stop", "activation", "trail", "hold_seconds", "basket_stop", "basket_activation", "basket_trail")
    summaries = []
    for record in records:
        packet = read(WORK / "controls/results" / (record["ID"] + ".json"))
        config = record["設定"]
        assert config["kind"] == 0 and config["control"] is True and config["paired"] is False
        for identifier in config["matched_Hids"]:
            assert all(config[field] == configs[identifier][field] for field in relevant), ("保険なしの条件対応", config["id"], identifier)
        periods = {}
        for name in ("前16", "後12", "全セッション"):
            label = "全28" if name == "全セッション" else name
            periods[label] = {}
            for symbol in ("TOPIX", "NK225"):
                a = aggregate(record["口座"], fixed[name], symbol, ready)
                for field, value in a.items():
                    reported = packet["periods"][label][symbol][field]
                    if value is None:
                        assert reported is None
                    else:
                        near(float(value), float(reported), "追加対照期間/" + field)
                periods[label][symbol] = a
        summaries.append(dict(ID=record["ID"], 同条件H=config["matched_Hids"], 期間=periods, 合格=True))
    fingerprints = {path: digest(ROOT / path) == value for path, value in diagnostic["SHA256"].items()}
    assert all(fingerprints.values())
    assert selected_sha == read(HERE / "実選定設定の因果検査と選定照合.json")["選定SHA256"]
    save(HERE / "追加診断対照の独立監査.json", dict(合格=True, 条件数=30, 口座数=1680,
        全原本行時価指紋一致口座=1680, 共通満額初回一致口座=1680, 期間集計一致数=180,
        元保険48条件の価格期限損失枠一致=True, 元192の凍結と選定保持=True,
        段階=diagnostic["段階"], 指紋=fingerprints, 条件=summaries))
    print("保険なし追加30条件・1680口座・180期間集計・48対応条件一致: 合格", flush=True)


if __name__ == "__main__":
    main()
