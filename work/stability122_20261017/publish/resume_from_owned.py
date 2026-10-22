"""表示側schema想定を訂正後、一読保全済みの同一結果だけで生成を完了する。"""

import json
from pathlib import Path

import render122 as R


HERE=Path(__file__).resolve().parent
EXPECTED='ea3632b2e7bf2e9eb3e73addfede7f87deda0069efb30e4a3fd2647550dbab72'
AUDIT_SHA='91702da0011b1283746812e9487eeac45264346c3aa4e791ba8203d345829913'


def main() -> None:
    """
    機能: 元金融結果を再読せず、所有copyのSHAと独立監査を再結合して表示する。
    引数: なし。根指定SHAと私有receivedだけを対象にする。
    返り値: None。新HTMLと生成証跡を保存し、金融・市場・台帳は触らない。
    """
    proofpath=HERE/'正式表示の生成証跡.json';assert not R.OUTPUT.exists() and not proofpath.exists()
    owned=HERE/'received/途中利確なしと引け一括の全四十場.json'
    payload=owned.read_bytes();assert R.digest(payload)==EXPECTED
    auditpath=HERE.parent/'audit/result/八十通常及び代理終端会計の独立監査.json'
    auditraw=auditpath.read_bytes();assert R.digest(auditraw)==AUDIT_SHA
    audit=json.loads(auditraw);assert audit['passed'] is True and R.contains(audit,EXPECTED)
    data=json.loads(payload);doc,metrics=R.render(data,EXPECTED)
    R.OUTPUT.parent.mkdir(parents=True,exist_ok=True);html=doc.encode('utf8');R.OUTPUT.write_bytes(html)
    proof=dict(passed=True,result_path='work/stability122_20261017/途中利確なしと引け一括の全四十場.json',
        result_sha256=EXPECTED,original_source_reads=1,own_copy_reads=1,
        audit=dict(path=str(auditpath),SHA256=AUDIT_SHA),output=dict(path=str(R.OUTPUT),SHA256=R.digest(html)),
        report_sha256=R.digest((HERE/'render122.py').read_bytes()),metrics=metrics,
        financial_accounts=80,reused_baseline_accounts=40,fixture=False,
        表示訂正='metadataのmethod有無への誤った依存を削除し、baseline.rows全40のmethodを直接確認。初回停止源とFalseを保全。',
        market_reads=0,NPZ_reads=0,financial_replay=0,registry_reads=0,API=0,実注文=0)
    proofpath.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,HTML_SHA256=R.digest(html),proof_SHA256=R.digest(proofpath.read_bytes())),ensure_ascii=False))


if __name__=='__main__':
    main()
