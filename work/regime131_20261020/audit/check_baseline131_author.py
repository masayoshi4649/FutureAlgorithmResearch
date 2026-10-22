"""旧核接続の作者会計検査。売買判断の再生は行わない。"""

import hashlib
import json
from pathlib import Path
import pickle
import sys
import time
import numpy as np

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
sys.path.insert(0,str(HERE))
import baseline131


def main():
    """
    機能: 手数料端数・両建て・既存107商品場の注文会計を確認する。
    引数: なし。
    返り値: None。新規証跡のみ保存する。
    """
    count = 0
    times = np.arange(5,dtype=float)
    bid = np.array([99.,99.,500.,103.,98.])
    ask = bid+1.
    qok = np.array([True,True,False,True,True])
    orders = np.array([[1,0,0,1,5,100,90,1],[3,1,0,-1,2,103,70,0],[4,3,0,-1,3,98,93,0]],dtype=float)
    value = baseline131.revalue(times,bid,ask,qok,orders,1000.,41.8)
    assert value["gross"] == 0 and value["fees"] == 417 and value["net"] == -417
    assert np.array_equal(value["estimated_close_fee"],[0.,209.,209.,125.,0.])
    assert np.array_equal(value["entries_so_far"],[0,1,1,1,1])
    assert value["liquidation_equity"][1] == value["liquidation_equity"][2] == -5418.
    assert value["parents"][0]["quantity"] == 5 and value["parents"][0]["exit_row"] == 4
    count += 5
    hedge = np.array([[1,0,0,1,5,100,90,1],[1,0,1,-1,5,99,90,1],
                      [3,1,0,-1,5,103,70,0],[3,1,1,1,5,104,70,0]],dtype=float)
    value = baseline131.revalue(times,bid,ask,qok,hedge,1000.,41.8)
    assert value["position"][1] == 0 and value["long_quantity"][1] == value["short_quantity"][1] == 5
    assert value["liquidation_equity"][1] == -10836.
    assert value["net"] == -10836.
    count += 3
    rejected = 0
    for broken in (np.array([[2,0,0,1,5,501,90,1],[4,3,0,-1,5,98,93,0]],float),
                   np.array([[1,0,0,1,5,99,90,1],[4,3,0,-1,5,98,93,0]],float),
                   np.array([[3,0,0,1,5,104,90,1],[4,3,0,-1,5,98,93,0]],float)):
        try:
            baseline131.revalue(times,bid,ask,qok,broken,1000.,41.8)
        except AssertionError:
            rejected += 1
    assert rejected == 3
    count += 3
    manifest = json.loads((ROOT/"work/daynight128_20261020/入力準備.json").read_text(encoding="utf-8-sig"))
    cases = []
    for ref in manifest["packets"]:
        data = (ROOT/ref["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == ref["sha256"]
        packet = pickle.loads(data)
        for symbol in ("TOPIX","NK225"):
            variants = (0,1) if ref["session"].endswith("_Night") and symbol == "TOPIX" else (0,)
            for variant in variants:
                core = baseline131.load_core(ref["session"],symbol,variant)
                key = ref["session"],symbol
                ready,q = packet["inputs"][key],packet["quotes"][key]
                value = baseline131.revalue(ready["time_s"],q["bid"],q["ask"],q["quote_valid"],
                                           core["orders"],core["multiplier"],core["fee"])
                for field in ("net","gross","fees","profit","loss","entries","quantity","parent_wins","parent_losses"):
                    assert np.isclose(value[field],core["summary"][field]), (key,variant,field)
                    count += 1
                assert max(value["max_long"],value["max_short"]) <= (5 if symbol=="TOPIX" else 10)
                assert value["entries_so_far"][-1] == value["entries"]
                count += 2
                cases.append(dict(session=key[0],symbol=symbol,variant=variant,method=core["method"],
                                  orders=len(core["orders"]),net=value["net"],parents=len(value["parents"])))
    assert len(cases) == 107
    path = HERE/"baseline131.py"
    proof = dict(passed=True,金融意思決定再生数=0,保存会計照合数=len(cases),実測検査数=count,cases=cases,
                 sources=[dict(path=path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest())],
                 旧会計指紋=baseline131.source_map,
                 未返済費用="各親の残枚数を一注文で返済すると仮定しfloor(残枚数×片道単価)。親間の合算丸めはしない。")
    target = Path(__file__).parent/f"旧核円会計接続の作者人工と107商品場_{time.time_ns()}.json"
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"passed":True,"checks":count,"proof":target.relative_to(ROOT).as_posix()},ensure_ascii=False))


if __name__ == "__main__":
    main()
