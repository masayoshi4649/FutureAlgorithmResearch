"""既所有の入力と確定一分足だけから、Ｇの入口許可を非金融生成する。"""

import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np

from adapter126 import HERE, WORK, ENGINE, make_gate

ROOT = WORK.parents[1]
sys.path.insert(0, str(ENGINE))
import legacy126

CSV_READS = {}


def audit_reads(event, args):
    """
    機能: 所有一分足の実際のｏｐｅｎを記録し、二重読取と原本読取を拒否する。
    引数: event(str)、args(tuple)は標準監査イベント。
    返り値: None。源・所有素材以外の市場原本を開かない。
    """
    if event != "open" or not isinstance(args[0], (str, bytes, Path)):
        return
    path = Path(args[0]).resolve() if not isinstance(args[0], bytes) else Path(args[0].decode()).resolve()
    if not path.is_relative_to(ROOT):
        return
    assert not any(path.is_relative_to(ROOT/name) for name in ("book", "candle_1min", "candle_5min")), str(path)
    if path.is_relative_to(HERE/"consumer") and path.suffix == ".csv":
        name = path.relative_to(ROOT).as_posix()
        CSV_READS[name] = CSV_READS.get(name, 0)+1
        assert CSV_READS[name] == 1, name


def main():
    """
    機能: 追加十一場の元ＡＴＲと旧確定足函数で二十二のＧ許可列を保存する。
    引数: なし。
    返り値: None。売買判断・金融再生は行わない。
    """
    target = HERE/"追加十一場のＧ入口許可の非金融準備.json"
    assert not target.exists()
    material = json.loads((HERE/"Ｇ再評価の非金融素材準備.json").read_text(encoding="utf-8"))
    legacy126.CACHE = str(HERE/"jit_gateprepare")
    sys.addaudithook(audit_reads)
    arrays, summaries, packets = {}, [], []
    with legacy126.isolated():
        runtime = legacy126.runtime()
        for item in material["additional_packets"]:
            payload = (ROOT/item["path"]).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == item["sha256"]
            packet = pickle.loads(payload)
            assert packet["session"] == item["session"]
            features = make_gate(runtime, packet, ROOT/material["consumer"])
            for key, feature in features.items():
                permission = feature["gate"]
                arrays[key[1]+"_"+key[0]] = permission
                original = feature["columns"][0]
                summaries.append(dict(session=key[0], symbol=key[1], rows=len(permission),
                    allowed_rows=int(permission.sum()), active_direction_rows=int((original != 0).sum()),
                    kept_direction_rows=int((permission & (original != 0)).sum()),
                    atr_from_existing_ready=True))
            packets.append(dict(path=item["path"], sha256=item["sha256"], reads=1))
            print(item["session"]+" Ｇ入口許可を非金融保存", flush=True)
    assert len(arrays) == len(summaries) == len(CSV_READS) == 22
    cache = HERE/"追加十一場のＧ入口許可.npz"
    assert not cache.exists()
    np.savez_compressed(cache, **arrays)
    proof = dict(passed=True, cache=dict(path=cache.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(cache.read_bytes()).hexdigest()),
        rows=summaries, packet_reads=packets, owned_csv_reads=CSV_READS,
        new_financial_accounts=0, original_market_reads=0, API=0,
        clock="旧modelは確定1分足開始+120秒とready既存ATR。expandedが相手へさらに60秒。未公表はNaNから不許可。",
        source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (Path(__file__), HERE/"adapter126.py")})
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, gates=22, financial=0), ensure_ascii=False))


if __name__ == "__main__":
    main()
