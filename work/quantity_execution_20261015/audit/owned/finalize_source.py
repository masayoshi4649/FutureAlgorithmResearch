"""SOURCE_ONLY の完成範囲と初版停止の理由を、小さな最終証跡へ結ぶ。"""

from __future__ import annotations

from pathlib import Path
from fractions import Fraction
import hashlib
import importlib
import json
import sys
import types

import numpy as np

from cash_reference import PRODUCTS
from connect_execution_v2 import materialize, select_config, EXPECTED

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]


def sha(path: Path) -> str:
    """
    機能: 小さい証跡と源を指紋化する。
    引数: path(Path) 所有領域のファイル。
    返り値: str SHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 実装状態key除去の同値と未測定境界を明記し、完成三源へ結ぶ。
    引数: なし。
    返り値: None。金融・実原本は読まない。
    """
    sources = {k: sha(SOURCE / k) for k in EXPECTED}
    assert sources == EXPECTED
    sys.path.insert(0, str(HERE / "完成三源の私有複製"))
    engine = importlib.import_module("engine")
    catalog = importlib.import_module("catalog")
    artifact = SOURCE / "数量公開からmarket全量と半分追尾へ接続する人工検査_v2.json"
    owner = json.loads(artifact.read_text(encoding="utf-8"))
    assert sha(artifact) == "59d1e51dce2bc599d7b403d7e122c65d74845cf4dd460146ea0c02c2618ceef8"
    assert owner["全合格"] and owner["source_SHA256"] == sources
    old_path = SOURCE / "archive" / "準備時状態keyを除去する前の成功初版" / "catalog.py"
    assert sha(old_path) == "504b1a57c336c53f9431b66755eab6db05a29e5ad4e35e90d78416be45dba2dd"
    old = types.ModuleType("旧catalogの純比較")
    exec(compile(old_path.read_text(encoding="utf-8"), str(old_path), "exec"), old.__dict__)
    assert catalog.configs() == [{k: v for k, v in c.items() if k != "financial_measured"} for c in old.configs()]
    assert sources == {k: sha(SOURCE / k) for k in EXPECTED}
    checks = 5
    # 価格既知・数量未知の保有行では判断でき、約定だけ次正常へ待つ。
    for product in PRODUCTS:
        for side in (1, -1):
            arrays, signal, policy = materialize(product.symbol, side, [-1, -1, 2, 1, 0, 0])
            arrays["best_quantity_valid"][2] = False
            out = engine.simulate(arrays, signal, product.symbol, 0.0, 2000.0, float(product.tick), policy, select_config(catalog, 0, 0))
            assert out["orders"][1, 1] == 2 and out["orders"][1, 0] == 3
            assert out["orders"][1, 9] == 140
            assert out["curve"][2, 14] == 1 and out["curve"][2, 15] == 0
            assert out["counts"]["holding_quantity_unknown_rows"] == 1
            # 最初の価格未知行に大きな気配を与えても場の基準へ使わない。
            arrays, signal, policy = materialize(product.symbol, side, [-1, -1, 2, 1, 0, 0])
            arrays["bid"][0] *= 2
            arrays["ask"][0] *= 2
            signal["price_valid_mask"][0] = False
            signal["events"][:, 2] = 1
            out = engine.simulate(arrays, signal, product.symbol, 0.0, 2000.0, float(product.tick), policy, select_config(catalog, 0, 0))
            expected_loss = float((product.base + product.tick / 2) * product.quantity * product.multiplier / 800)
            assert np.isnan(out["curve"][0, 12])
            assert abs(out["curve"][1, 12] - expected_loss) < 1e-8
            assert np.all(out["curve"][1:, 12] == out["curve"][1, 12])
            checks += 7
    base = HERE / "三入口四出口と次原行約定及び予約競合の独立SOURCE_ONLY接続_v2.json"
    scene = HERE / "場清算の等号と停止ラッチだけの独立純kernel補完_v2.json"
    first = json.loads(base.read_text(encoding="utf-8"))
    supplement = json.loads(scene.read_text(encoding="utf-8"))
    assert first["全合格"] and first["source_SHA256"] == sources and supplement["全合格"]
    assert supplement["core_SHA256"] == sources["engine.py"]
    checks += 2
    proof = {
        "全合格": True,
        "source_SHA256": sources,
        "独立接続確認数": first["確認数"],
        "場境界だけの料金ゼロ純kernel確認数": supplement["確認数"],
        "最後の源接続と保有数量未知の補完確認数": checks,
        "証拠": [{"path": str(p.relative_to(HERE)), "sha256": sha(p)} for p in (base, scene, HERE / "cash_reference.py", HERE / "execution_expectations.py", Path(__file__))],
        "owner人工": {"path": str(artifact.relative_to(SOURCE)), "sha256": sha(artifact), "引用であり独立確認数へ加算": False},
        "初版の停止": [
            {"保存": "archive/catalog状態key修正中の指紋guard停止", "理由": "ownerのmetadata修正と指紋照合が重なり、importより前で停止。engine/artificialは不変。v2で状態keyだけの除去を独立照合。", "経済源不備の判定": False},
            {"保存": "archive/場境界人工の後続新規を混同した初版False", "理由": "初回境界と後続新親の追加損失を混同したcheckerの人工設定を訂正。経済源不変更。", "経済源不備の判定": False}
        ],
        "実行順": "古い返済→既受理新規の直後raw→場制御→親制御→当行候補。quiet/forceは新規fill前取消、entry_endは新公開締切。",
        "範囲": "完成三源と純人工だけ。正式計画の八部品・登録・33×2実入力guardの最終接続はrootの源が完成してから別に行う。",
        "未測定": ["実際のmini/microの約定数量と待ち順位", "真の受信順と発注応答時間", "全33場の金融結果", "新しい未知データの有効性"],
        "読取": {"原入力": 0, "NPZ": 0, "保存114事象": 0, "過去金融結果": 0, "台帳": 0, "API": 0},
        "source最終一致": sources == {k: sha(SOURCE / k) for k in EXPECTED}
    }
    assert proof["source最終一致"]
    output = HERE / "完成三源と純会計及び場境界の独立接続まとめ.json"
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"全合格": True, "補完確認数": checks, "path": str(output), "sha256": sha(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
