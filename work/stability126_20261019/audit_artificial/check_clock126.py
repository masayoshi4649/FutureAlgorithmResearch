"""人工価格から原版の二つの影を再生成し、元の再参加時計を確かめる。"""

import hashlib
import importlib
import json
import sys

import numpy as np

from check126 import HERE, ENGINE, read_boundary, legacy126


def main():
    """
    機能: 上位再生で実玉の早期終了を通常影終了へ置き換えないことを検査する。
    引数: なし。
    返り値: None。全て人工の価格・状態で所有監査証拠を保存する。
    """
    sys.addaudithook(read_boundary)
    with legacy126.isolated():
        runtime = legacy126.runtime()
        module = importlib.import_module("policy126")
        reference = runtime["old"].base.integration.reference
        reference.old.FIXED = legacy126.read(ENGINE/"legacy_root/work/wave_v38/探索条件の固定.json")
        reference.FIXED = legacy126.read(ENGINE/"legacy_root/work/wave_v44/探索条件の固定.json")
        pattern = [100, 99, 100, 102, 106, 104, 104, 104, 104, 104, 104, 104, 104, 104, 104, 100, 99, 100, 102, 106]
        price = np.asarray(pattern*6, float)
        stamps = 1000.+np.arange(len(price))*30.
        n = len(price)
        inputs = {}
        for symbol in ("TOPIX", "NK225"):
            inputs[("人工", symbol)] = dict(symbol=symbol, session="人工", time_s=stamps.copy(),
                last=price.copy(), atr=np.full(n, 2.), seq=np.arange(n), tick=.5,
                start=1000., limit=stamps[-1]+30., session_close=stamps[-1]+630., us_open=np.inf)
        zero, source = np.zeros(n, np.int8), np.full(n, -1, np.int64)
        valid = np.zeros(n, bool)
        feature = dict(columns=(np.ones(n, np.int8), zero, source, zero, source, valid),
                       valid=valid, gate=np.ones(n, bool),
                       joint=dict(direction=zero, source=source, valid=valid),
                       ema=(zero, source, source, valid))
        market = module.make_market(inputs)
        namespace = {}
        path = HERE.parent/"design/catalog126.py"
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        records = []
        normal_settings, _ = runtime["old"].base.settings(dict(changes={}), inputs[("人工", "TOPIX")])
        normal_shadow = runtime["old"].shadow_run(inputs[("人工", "TOPIX")],
            feature["columns"][0], normal_settings, np.ones(n, bool), True)
        for config in (namespace["catalog"]()[0], namespace["catalog"]()[13]):
            result, settings = module.play(runtime, config, inputs[("人工", "TOPIX")], feature, market[("人工", "TOPIX")])
            encoded_settings = json.dumps(settings, ensure_ascii=False, allow_nan=False)
            assert json.loads(encoded_settings) == settings
            assert all(type(v) in (bool, int, float, str, type(None)) for v in settings.values())
            scheduler = result["shadow"]
            entries = result["orders"][result["orders"][:, 7] == 1]
            assert len(entries) >= 2, (config["id"], entries)
            shadow_cycles = normal_shadow["cycles"]
            events = result["prepare_events"]
            np.testing.assert_array_equal(events, normal_shadow["prepare_events"])
            for cid, entry, close, *_ in shadow_cycles:
                next_prepare = events[events[:, 1] > close]
                if len(next_prepare):
                    assert stamps[int(next_prepare[0, 1])] >= stamps[int(close)] + 300.
            assert result["stats"][9] == 0
            assert settings["cooldown_min"] == 5.
            assert scheduler["cycles"][0, 2] < shadow_cycles[0, 2], "実早期終了と通常影の差がない"
            assert events[1, 1] > scheduler["cycles"][0, 2] + 10, "実返済から五分で再準備していた"
            records.append(dict(id=config["id"], actual_entry_rows=entries[:, 0].astype(int).tolist(),
                                shadow_cycle_rows=shadow_cycles[:, [1, 2]].astype(int).tolist(),
                                exit_shadow_cycle_rows=scheduler["cycles"][:, [1, 2]].astype(int).tolist(),
                                prepare_rows=events[:, 1].astype(int).tolist(), flat=True,
                                settings_json_finite_scalar=True,
                                settings_types=sorted({type(v).__name__ for v in settings.values()})))
        proof = dict(全合格=True, 通常影終了から五分待つ上位人工=records,
                     新金融=0, 原本読取=0, 実市場配列読取=0,
                     source_sha256=hashlib.sha256((ENGINE/"policy126.py").read_bytes()).hexdigest())
    output = HERE/"通常影の五分待機と設定有限JSONの最終純人工監査.json"
    assert not output.exists()
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
