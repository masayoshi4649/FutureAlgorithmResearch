"""損失再入場の具体例を、保存結果の原行番号から生板へ照合する。"""

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path

from analyze153 import HERE, read, equal


def main() -> None:
    """既に選んだ具体例の原板だけを抜き、価格時計とBBOを確認する。

    引数: なし。
    返り値: None。原板の指標計算や売買条件の再評価はしない。
    """
    scenes = {scene["session"]: scene for scene in read(HERE/"data/入力目録153.json")["sessions"]}
    diagnosis = read(HERE/"loss_decomposition153.json")
    requests = defaultdict(lambda: defaultdict(list))
    for method in diagnosis["methods"]:
        if method["id"] != "M09":
            continue
        for example in method["examples"]:
            for role in ("previous", "next"):
                parent = example[role]
                key = (parent["session"], method["symbol"])
                for action in ("entry", "exit"):
                    reference = parent[action]
                    for moment in ("decision", "fill"):
                        requests[key][reference[moment+"_line"]].append({"role": role, "action": action, "moment": moment,
                                                                         "reference": reference})
    records = []
    checks = 0
    for (session, symbol), lines in requests.items():
        path = Path(scenes[session]["books"][symbol])
        wanted = set(lines)
        with path.open(encoding="utf-8-sig") as stream:
            for number, text in enumerate(stream, 1):
                if number not in wanted:
                    continue
                raw = json.loads(text)
                unix = datetime.fromisoformat(raw["CurrentPriceTime"]).timestamp()
                bid, ask = raw["Buy1"]["Price"], raw["Sell1"]["Price"]
                for check in lines[number]:
                    moment, reference = check["moment"], check["reference"]
                    equal(unix, reference[moment+"_time"], "原板価格時計")
                    equal(bid, reference[moment+"_bid"], "原板買い気配")
                    equal(ask, reference[moment+"_ask"], "原板売り気配")
                    checks += 1
                records.append({"session": session, "symbol": symbol, "line": number, "source": str(path), "references": lines[number], "raw": raw})
                wanted.remove(number)
                if not wanted:
                    break
        assert not wanted, (session, symbol, wanted)
    target = HERE/"examples_raw_verification153.json"
    target.write_text(json.dumps({"state": "全件一致", "checks": checks, "raw_lines": len(records), "definition": "具体損失例の価格時計・原行・判断/約定BBO照合のみ。金融再生なし。", "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"state": "全件一致", "checks": checks, "raw_lines": len(records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
