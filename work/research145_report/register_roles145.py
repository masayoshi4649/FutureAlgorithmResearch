"""役割別の出口と短期反発の誤認を、事前固定した第二段階で検証するため登録する。"""

import os
from pathlib import Path
import subprocess
import sys
import zipfile
from register145 import ROOT, HERE, TOOL, read, save, digest


def main():
    """
    機能: 担当別の保存注文合成を登録する。未評価の組合せ成績を先に読まない。
    引数: なし。返り値: None。旧登録・旧成果を変更しない。
    """
    receipt=HERE/'役割分離登録受領145.json'
    if receipt.exists() and read(receipt).get('returncode')==0:
        return
    directory=ROOT/'work/research145_roles'
    files=sorted(directory.glob('*.py'))+sorted(directory.glob('*.json'))
    assert files
    implementation={p.relative_to(ROOT).as_posix():digest(p) for p in files}
    archive=HERE/'役割分離実装145.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name in implementation:z.write(ROOT/name,name)
    evidence=HERE/'役割分離前の原因診断145.md'
    evidence.write_bytes((ROOT/'work/research145_residual/残玉改善の診断145.md').read_bytes())
    plan=read(HERE/'会計適合修正計画145.json')
    plan.update(id='145_担当別出口とドテンの中期支持確認',name='主担当と別入口の出口分離・ドテンの中期支持確認',
        question='担当ごとの出口分離と、短期反発をドテンと認める前の40分支持確認で、第一段階の増収と安定性を両立できるか。',
        change='D01〜D08の八構成とV16/V17。V16はV10のドテンだけ40分差の支持を必須とし、V17は40分平均の位置も要求する。他条件は維持。D群は保存された独立枠の全注文を合成し元の5/3/2枚枠と全損失を保持する。',
        repeat_reason='R01〜R11は全口座で元TG04より悪化したが、各条件のCGは全て改善、CSは全て悪化した。さらに10/16夜04:52の短期買い反転は40分下落中だった。10/8夜では40分反対からの有効な初動もあり、改善だけを期待せず両方全50場で検証する。',
        compares_to=['145_利益保護と回転再参加の三十改修条件','145_費用ゼロ会計への適合修正'])
    plan['configs']={'役割別構成':read(directory/'役割別構成145.json'),
        'ドテン確認の実設定':read(directory/'ドテン確認条件145.json'),
        'ドテン確認':{'V16':'V10のドテンだけ、新方向に公開40分差が正。',
            'V17':'V16に加え公開40分平均に対して新方向側に価格がある。',
            '変更範囲':'通常入口・数量・待機・損切り・利益回転はV10と同じ。未準備時は新ドテンだけ不許可。'}}
    plan['spec']['entry']={'条件':'V16/V17だけV10のドテンに公開40分情報を追加。D群は保存注文を担当単位で合成。当場終値・最終値幅による選別なし。',
        '配分':'D01〜08の昼夜固定の配分。独立枠間の貸借なし。'}
    plan['spec']['management']={'条件':plan['configs'],'条件内の裁量':'なし。明細の選択削除なし。'}
    plan['spec']['implementation'][archive.relative_to(ROOT).as_posix()]=digest(archive)
    plan['evidence'].append(dict(path=evidence.relative_to(ROOT).as_posix(),sha256=digest(evidence)))
    proposal=HERE/'役割分離計画145.json';save(proposal,plan)
    env=dict(os.environ,PYTHONIOENCODING='utf-8')
    for command in ('check','register'):
        outpath=HERE/f'roles_{command}145.json';errpath=HERE/f'roles_{command}145.stderr.txt'
        print(command+'を開始します。',flush=True)
        with outpath.open('wb') as out,errpath.open('wb') as err:
            result=subprocess.run([sys.executable,str(TOOL),command,'--proposal',str(proposal)],cwd=ROOT,env=env,stdout=out,stderr=err)
        if result.returncode:raise RuntimeError(errpath.read_text(encoding='utf-8'))
        if command=='check':assert read(outpath)['proposal_complete']
    save(receipt,dict(returncode=0,trial_id=plan['id'],proposal_sha256=digest(proposal),
        archive_sha256=digest(archive),implementation=implementation))
    print('役割分離の登録が完了しました。',flush=True)


if __name__=='__main__':main()
