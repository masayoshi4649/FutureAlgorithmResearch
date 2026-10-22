"""経済源を変えず、実際の事前照合・登録内容を確認してから一回実行する。"""

import json
from pathlib import Path
import subprocess
import sys

import plan120 as P


def main() -> None:
    """
    機能: 登録成功コードだけでなく、提案・実登録・固定源の完全一致を要求する。
    引数: なし。固定済み源・監査・実登録の保存stdoutだけを使う。
    返り値: None。パラメータや約定規則を追加せず、合格後だけ金融driverを呼ぶ。
    """
    proposal = P.read(P.HERE / '試行計画.json')
    fixed = P.read(P.HERE / '固定計画.json')
    checked = P.read(P.HERE / '事前照合の全出力.json')
    registered = P.read(P.HERE / '正式登録の全出力.json')
    assert checked['終了コード'] == registered['終了コード'] == 0
    comparison = json.loads(checked['stdout'])
    actual = json.loads(registered['stdout'])
    assert comparison['提案完全'] is True and not comparison['提案不完全理由']
    assert actual['id'] == proposal['id'] == P.TRIAL
    assert actual['spec'] == proposal['spec']
    assert actual['spec']['implementation'] == fixed['sources']
    assert actual['spec']['data']['input_manifests'] == [fixed['input_manifest']]
    assert actual['name'] == proposal['name']
    for path, sha in fixed['sources'].items():
        assert P.digest(P.ROOT/path) == sha
    assert P.digest(P.HERE/'入力目録.json') == fixed['input_manifest']['sha256']
    reference = fixed['artificial_audit']
    assert reference['passed'] and P.digest(P.ROOT/reference['path']) == reference['sha256']
    audit = P.read(P.ROOT/reference['path'])
    assert audit['passed'] is True and audit['engine_sha256'] == P.digest(P.HERE/'engine120.py')
    P.save(P.HERE/'実行前の登録実体結合.json',dict(passed=True,id=P.TRIAL,
        proposal_complete=True,registered_spec_equal=True,registered_sources_equal=True,
        registered_manifest_equal=True,artificial_passed=True,
        sources=fixed['sources'],gate_sha256=P.digest(Path(__file__)),
        変更='経済源・数値条件変更0。登録実体を照合する起動側の非経済guard。',
        原市場読取=0,金融再生=0))
    process = subprocess.run([sys.executable,'-B','-u','-X','utf8',str(P.HERE/'run120.py')],cwd=P.ROOT)
    P.save(P.HERE/('実行終了.json' if process.returncode==0 else '実行False.json'),
        dict(終了コード=process.returncode,guard_passed=True,source_SHA256=fixed['sources']))
    assert process.returncode == 0


if __name__ == '__main__':
    main()
