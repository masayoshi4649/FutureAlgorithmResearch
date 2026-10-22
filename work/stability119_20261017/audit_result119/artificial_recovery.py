"""最終保存型停止後の復元計画を、純人工の場末と未保存診断で検査する。"""

import hashlib
import json
from pathlib import Path

import numpy as np

import recover_saved as recovery


def main() -> None:
    """
    機能: メタ情報252条件、場末2観測、数量、未知診断の純人工期待値を確認する。
    引数: なし。
    返り値: None。cache・市場・売買エンジンを読まない。
    """
    audit = recovery.audit
    specs = recovery.specifications()
    audit.check(len(specs) == 252 and specs[0]["id"] == "COMMON_L10_X0_E0_G0", "252メタの先頭順序")
    audit.check(specs[-1]["id"] == "S119_H120_distinct_family_consensus_X2_E0_G1", "252メタの末尾順序")
    scene = "2026-10-16_Day"
    close = recovery.cutoff(scene)
    ledger = np.zeros((1, 16))
    ledger[0, 0] = 1
    ledger[0, 3] = close - 1201.
    ledger[0, 6] = 3
    audit.check(recovery.flat_certificate(ledger, dict(time=np.asarray([close, close + 1.])), 3, scene)["保証"], "場末2正常原rowと全返済")
    audit.check(not recovery.flat_certificate(ledger, dict(time=np.asarray([close])), 3, scene)["保証"], "場末1原rowでは保証しない")
    audit.check(not recovery.flat_certificate(ledger, dict(time=np.asarray([])), 3, scene)["保証"], "場末正常原rowなし")
    partial = ledger.copy()
    partial[0, 6] = 1
    audit.check(not recovery.flat_certificate(partial, dict(time=np.asarray([close, close + 1.])), 3, scene)["保証"], "未返済親を保証しない")
    late = ledger.copy()
    late[0, 3] = close
    audit.check(not recovery.flat_certificate(late, dict(time=np.asarray([close, close + 1.])), 3, scene)["保証"], "締切後新規の異常を保証しない")
    unknown, certificate = recovery.reconstruct(np.empty((0, 16)), {}, dict(time=np.asarray([])), 3, 1000., 41.8,
        {}, np.empty(0), np.empty(0, dtype=bool), scene, np.empty(0), None)
    audit.check(not certificate["保証"] and unknown["net"] is None and unknown["unclosed"] is None, "未清算不明は0円へ化けない")
    audit.check(unknown["canceled"] is None and unknown["halted"] is None, "未保存診断を捏造しない")
    audit.check(audit.READS == dict(完成結果=0, prepared=0, portfolio=0, 市場=0, 再生=0), "純人工読取0")
    here = Path(__file__).resolve().parent
    proof = dict(全合格=True, 検査数=audit.CHECKS, counts=audit.READS,
                 復元源SHA256=hashlib.sha256(Path(recovery.__file__).read_bytes()).hexdigest(),
                 算術監査源SHA256=hashlib.sha256(Path(audit.__file__).read_bytes()).hexdigest(),
                 人工源SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    path = here / "保存会計復元の型と場末観測保証の純人工検査.json"
    assert not path.exists()
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
