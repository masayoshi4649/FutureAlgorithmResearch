"""売買条件を変えない費用0会計への適合修正を追補登録する。"""

import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
from register145 import ROOT, HERE, TOOL, read, save, digest


def main():
    """
    機能: 会計修正の実装を固定し、同じ条件の比較再開前に正式登録する。
    引数: なし。返り値: None。元登録と元実装のZIPは変更しない。
    """
    receipt = HERE / '会計修正登録受領145.json'
    if receipt.exists() and read(receipt).get('returncode') == 0:
        return
    original = read(HERE / '登録受領145.json')
    files = [ROOT / 'work/research145_engine' / name for name in
             ['account145.py', 'test_account145.py', 'run145.py']]
    files += [ROOT / 'work/research145_residual/run_residual145.py']
    implementation = {str(p.relative_to(ROOT)).replace('\\', '/'): digest(p) for p in files}
    archive = HERE / '会計適合修正145.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in implementation:
            z.write(ROOT / name, name)
    plan = read(HERE / '固定計画145.json')
    plan.update(id='145_費用ゼロ会計への適合修正', name='利益回転研究の会計費用固定値を修正',
        question='既に登録した費用0注文を、元会計の固定費用assertを変更して全約定の会計へ正しく通せるか。',
        change='売買条件・特徴・約定・候補数は元登録から変更しない。元会計の費用定義だけを0にした互換会計と二driverの呼出先を修正する。',
        repeat_reason='第一場で全約定の次正常気配と基準同値検査は通ったが、元会計の385固定assertで集計前に停止。結果未出力。成績による条件修正ではない。',
        compares_to=[original['trial_id']])
    plan['spec']['implementation'][str(archive.relative_to(ROOT)).replace('\\', '/')] = digest(archive)
    proposal = HERE / '会計適合修正計画145.json'
    save(proposal, plan)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    for command in ('check', 'register'):
        outpath = HERE / f'account_fix_{command}145.json'
        errpath = HERE / f'account_fix_{command}145.stderr.txt'
        print(command + 'を開始します。', flush=True)
        with outpath.open('wb') as out, errpath.open('wb') as err:
            result = subprocess.run([sys.executable, str(TOOL), command, '--proposal', str(proposal)],
                cwd=ROOT, env=env, stdout=out, stderr=err)
        if result.returncode:
            raise RuntimeError(errpath.read_text(encoding='utf-8'))
        if command == 'check':
            assert read(outpath)['proposal_complete']
    combined = dict(original['implementation'])
    combined.update(implementation)
    save(receipt, dict(returncode=0, trial_id=plan['id'], proposal_sha256=digest(proposal),
        archive_sha256=digest(archive), original_registration_sha256=digest(HERE/'登録受領145.json'),
        implementation=combined))
    print('会計修正の登録が完了しました。', flush=True)


if __name__ == '__main__':
    main()
