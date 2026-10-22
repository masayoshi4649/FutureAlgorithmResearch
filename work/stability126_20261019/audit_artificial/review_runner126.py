"""金融実行器を起動せず、保存列の正規化だけを人工の現金算術と比べる。"""

import ast
import hashlib
import importlib
import json
from pathlib import Path
import sys

from check126 import HERE, ENGINE, read_boundary, legacy126, artificial, run, mirror


def main():
    """
    機能: 金融実行器の正規化純関数だけを抽出し、返済脚正負と円倍率を確認する。
    引数: なし。
    返り値: None。市場・金融保存会計を読み込まず監査ＪＳＯＮを作る。
    """
    sys.addaudithook(read_boundary)
    source = HERE.parent/"run126.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "normalize")
    with legacy126.isolated():
        legacy126.runtime()
        core = importlib.import_module("last_core126")
        policy = importlib.import_module("policy126")
        namespace = dict(policy=policy)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(source), "exec"), namespace)
        records = []
        for symbol, quantity, mult, profit, loss in (("TOPIX", 5, 1000., 12000., 18000.), ("NK225", 10, 10., 300., 300.)):
            case = artificial([100, 100, 103, 106, 110, 108, 113, 112, 111, 108, 106, 104, 102, 100, 98, 94], quantity=quantity)
            for reflected in (False, True):
                values = run(core, mirror(case) if reflected else case, [0., .5, 0., 0.])
                names = core.FIELDS + ("control_curve", "slot_curve", "slot_events", "adjustment_events",
                    "budget_events", "branch_events", "branch_curve", "risk_events", "guard_curve",
                    "guard_events", "block_events", "time_events", "policy_curve126", "policy_events126")
                result = dict(zip(names, values))
                row = namespace["normalize"](result, dict(symbol=symbol), "人工", "人工")
                assert (row["profit"], row["loss"], row["net"]) == (profit, loss, profit-loss)
                assert row["parent_profit"] == 0 and row["parent_loss"] == loss-profit
                assert row["entry_quantity"] == row["closed_quantity"] == quantity
                assert row["long_net"] == (0 if reflected else profit-loss)
                assert row["short_net"] == (profit-loss if reflected else 0)
                assert row["fees"] == 0 and row["unclosed"] == 0
                json.dumps(row, ensure_ascii=False, allow_nan=False)
                records.append(dict(symbol=symbol, reflected=reflected, profit=profit, loss=loss, net=profit-loss, multiplier=mult))
        proof = dict(passed=True, 人工による正規化=records,
                     旧六十の引用分類="旧00081の観測現在値E01のgross脚だけを料金零へ再集計。指定線約定版や後期少額版と分離。",
                     新金融件数="十五改修×八十二商品場＋原版追加十一場×二商品＝千二百五十二。旧六十と合わせ表示千三百十二。",
                     分類の用途="上昇下落は採点metadataだけ。policy.playへの条件選択には入力しない。",
                     新金融=0, 市場原本読取=0, 実市場配列読取=0,
                     runner_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    path = HERE/"保存列の正規化と旧六十引用の独立レビュー.json"
    assert not path.exists()
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
