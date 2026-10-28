"""比較後に選んだ改善・悪化の例を原板の物理行へ照合する。"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

from diagnose163 import HERE, read, record, stamp


def source_rows(scene: dict):
    """隔離再生器と同じ価格時計採用条件で日経原行を数える。

    引数: scene(dict)。返り値: generatorは採用番号・物理番号・板・元行を返す。
    """
    previous, index = scene["start"], 0
    with Path(scene["books"]["NK225"]).open("rb") as stream:
        for line, raw in enumerate(stream, 1):
            b = json.loads(raw)
            value = b.get("CurrentPriceTime")
            if value is None:
                continue
            try:
                at = datetime.fromisoformat(value).timestamp()
            except (TypeError, ValueError):
                continue
            if at < scene["start"] or at > scene["end"] or at >= scene["cutoff"] or at < previous:
                continue
            last = b.get("CurrentPrice") or 0
            if not isinstance(last, (int, float)) or not math.isfinite(last) or last <= 0:
                continue
            previous = at
            yield index, line, at, b, raw
            index += 1


def main() -> None:
    """固定候補の代表的な改善と悪化を元BBOへ照合する。

    引数: なし。返り値: None。診断の例選びであり条件選択や金融再生をしない。
    """
    source = read(HERE/"diagnosis/具体親診断163.json")
    frozen = read(HERE/"results/selection_frozen163.json")
    manifest = read(HERE/"inputs163.json")
    selected = []
    seen = set()
    for kind, key in frozen["selected"].items():
        for effect in ("改善", "悪化"):
            for row in source[f"{key}_{kind}_{effect}"][:1]:
                selected.append(dict(row, example_reason=effect))
                seen.add((row["id"], row["session"], row["parent"]))
    # ----------------------------------------
    # 復元を加える案も、原板で説明できる対照として各昼夜の両面を残す。
    for key in ("R40", "E40"):
        for kind in ("Day", "Night"):
            for effect in ("改善", "悪化"):
                rows = source[f"{key}_{kind}_{effect}"]
                if rows:
                    row = rows[0]
                    identity = (row["id"], row["session"], row["parent"])
                    if identity not in seen:
                        selected.append(dict(row, example_reason=effect))
                        seen.add(identity)
    wanted = {}
    for p in selected:
        needs = wanted.setdefault(p["session"], {})
        for ev in p["baseline_events"]+p["revised_events"]:
            for label in ("decision", "fill"):
                idx = ev[label+"_index"]
                b = ev["bid" if label == "fill" else "decision_bid"]
                a = ev["ask" if label == "fill" else "decision_ask"]
                old = needs.setdefault(idx, (b, a))
                assert old == (b, a)
    evidence = []
    for scene in manifest["sessions"]:
        if scene["session"] not in wanted:
            continue
        needs, found = wanted[scene["session"]], {}
        for index, physical, at, board, raw in source_rows(scene):
            if index not in needs:
                continue
            bid, ask = board["Buy1"]["Price"], board["Sell1"]["Price"]
            assert (bid, ask) == needs[index], (scene["session"], index, bid, ask, needs[index])
            found[index] = dict(index=index, physical_line=physical, price_time=stamp(at),
                bid=bid, ask=ask, last=board["CurrentPrice"], line_sha256=hashlib.sha256(raw).hexdigest(), raw=board)
        assert set(found) == set(needs), "例の原板行が揃わない"
        evidence.append(dict(session=scene["session"], path=scene["books"]["NK225"], rows=list(found.values())))
    output = dict(examples=selected, raw=evidence, checked_rows=sum(len(r["rows"]) for r in evidence),
                  source=record(HERE/"diagnosis/具体親診断163.json"), implementation=record(Path(__file__)),
                  scope="保存会計の事後診断。戦略へ未来を渡さず、独立受信時刻を仮定しない。")
    path = HERE/"diagnosis/原板例照合163.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(dict(examples=len(selected), sessions=len(evidence), checked_rows=output["checked_rows"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
