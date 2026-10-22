"""無取引の五候補に対応する原板行を確認する。新金融再生は行わない。"""

import hashlib
import json
import pickle
from datetime import datetime
from pathlib import Path
import numpy as np


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def main():
    """
    機能: 保存候補と厳密過去の相手原行を、元JSONLの同じ行番号へ照合する。
    引数: なし。
    返り値: None。原板の必要な接頭だけを読み、前後二行を診断資料へ保存する。
    """
    observed=json.loads((HERE/"無取引と上昇日弱さの保存観測.json").read_text(encoding="utf-8"))
    manifest=json.loads((ROOT/"work/daynight128_20261020/入力準備.json").read_text(encoding="utf-8"))
    refs={r["session"]:r for r in manifest["packets"]}
    demands={};events=[]
    for scene in observed["scenes"]:
        if scene["entries"]!=0:
            continue
        ref=refs[scene["scene"]]
        raw=(ROOT/ref["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==ref["sha256"]
        packet=pickle.loads(raw)
        symbol=scene["symbol"];peer="NK225" if symbol=="TOPIX" else "TOPIX"
        own=packet["inputs"][scene["scene"],symbol];other=packet["inputs"][scene["scene"],peer]
        for c in scene["candidates"]:
            row=c["row"];now=own["time_s"][row]
            j=int(np.searchsorted(other["time_s"],now,side="left")-1)
            item=dict(scene=scene["scene"],symbol=symbol,time=c["time"],side=c["side"],self={},peer={})
            for name,product,rd,position in (("self",symbol,own,row),("peer",peer,other,j)):
                seq=int(rd["seq"][position]);path=ROOT/"book"/product/(scene["scene"]+".jsonl")
                q=packet["quotes"][scene["scene"],product]
                expected=dict(seq=seq,time=float(rd["time_s"][position]),last=float(rd["last"][position]),
                              bid=float(q["bid"][position]),ask=float(q["ask"][position]))
                item[name]=dict(product=product,expected=expected)
                demands.setdefault(path,{})[seq]=expected
            events.append(item)
    extracted={};sources=[]
    for path,targets in demands.items():
        wanted={i for seq in targets for i in range(max(0,seq-2),seq+3)}
        prefix=hashlib.sha256();found={}
        with path.open("rb") as handle:
            for index,line in enumerate(handle):
                prefix.update(line)
                if index in wanted:
                    value=json.loads(line)
                    found[index]={k:value.get(k) for k in ("CurrentPrice","CurrentPriceTime","TradingVolume",
                        "TradingVolumeTime","Buy1","Buy2","Buy3","Sell1","Sell2","Sell3")}
                if index>=max(wanted):
                    break
        assert wanted.issubset(found)
        for seq,expected in targets.items():
            value=found[seq]
            assert np.isclose(value["CurrentPrice"],expected["last"])
            assert datetime.fromisoformat(value["CurrentPriceTime"]).timestamp()==expected["time"]
            assert value["Buy1"]["Price"]==expected["bid"]
            assert value["Sell1"]["Price"]==expected["ask"]
        key=path.relative_to(ROOT).as_posix()
        extracted[key]={str(k):v for k,v in found.items()}
        sources.append(dict(path=key,prefix_inclusive_last_seq=max(wanted),prefix_sha256=prefix.hexdigest(),
                            note="必要な原行までの接頭SHA。全ファイルSHAではない。"))
    output=dict(passed=True,events=events,raw_context=extracted,sources=sources,
        financial_replays=0,
        conclusion="五候補の自己及び厳密過去の相手Last・時計・最良気配は保存packetと原JSONLで一致。",
        limitation="CurrentPriceTimeは約定価格時計。真の受信時計がないため、価格時計の古さだけで通信切断と呼ばない。",
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/"無取引五候補の原板行照合.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("五候補・自己相手10点の原板一致。金融0。")


if __name__=="__main__":
    main()
