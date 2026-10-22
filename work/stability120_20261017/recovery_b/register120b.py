"""建玉保存の人工反例を修正した別実行を、元停止と分けて登録する。"""

import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import plan120 as P
import catalog120


HERE=Path(__file__).resolve().parent


def main(auditpath: Path) -> None:
    """
    機能: 同じ経済関数の境界検査有効化と実行時同値guardを拘束する。
    引数: auditpath(Path)は修正源の独立人工監査。
    返り値: None。入力数値を読まず、正式登録完了まで金融を始めない。
    """
    auditpath=auditpath.resolve()
    audit=P.read(auditpath)
    assert audit['passed'] is True and audit['engine_sha256']==P.digest(HERE/'engine120b.py')
    sources={(HERE/name).relative_to(P.ROOT).as_posix():P.digest(HERE/name)
        for name in ('register120b.py','run120b.py','runtime120b.py','engine120b.py')}
    sources[(P.HERE/'catalog120.py').relative_to(P.ROOT).as_posix()]=P.digest(P.HERE/'catalog120.py')
    manifest=dict(path=(HERE/'入力目録.json').relative_to(P.ROOT).as_posix(),sha256=P.digest(HERE/'入力目録.json'))
    P.save(HERE/'固定計画.json',dict(sources=sources,input_manifest=manifest,
        specs=catalog120.specifications(),artificial_audit=dict(passed=True,
            path=auditpath.relative_to(P.ROOT).as_posix(),sha256=P.digest(auditpath))))
    proposal=copy.deepcopy(P.read(P.HERE/'試行計画.json'))
    proposal.update(id='120b_段階追尾の建玉保存反例を修正した境界検査付き再測定',
        name='段階追尾の建玉保存を通常実行と一致させた再測定',purpose='不具合修正',
        question='同じ売買条件を、全UIDと現金が保存される実行で測ると場内収支を安定させられるか',
        change='元engineの経済関数本体は同一。njit二箇所をcache=False,boundscheck=Trueへ変更し、毎回実測前に純人工のPython/JIT全配列一致とUID保存を検査。登録実体guardと停止時保存も追加。',
        repeat_reason='元120は一場48保存後、NK途中で会計assert停止。純人工の通常JITで新規UIDが返済/残玉へ残らずPythonとの差を再現した。空cacheでも反例があり古cacheだけと断定しない。120aは一場診断を登録したが、人工反例が確定したため実データ実行0。原120の不成立結果を完成成績へ使わず、修正後同80入力を全再測定する。新しい未知標本0。',
        compares_to=[P.TRIAL,'120a_段階追尾の停止した一場の現金会計を独立診断'],
        evidence=[dict(path=p) for p in (
            (P.HERE/'実行False.json').relative_to(P.ROOT).as_posix(),
            (P.HERE/'recovery_a/試行計画.json').relative_to(P.ROOT).as_posix(),
            auditpath.relative_to(P.ROOT).as_posix(),
            'work/stability120_20261017/diagnosis/追尾新規と利益玉回転の既試行差及び最小対照.md')])
    proposal['spec']['implementation']=sources
    proposal['spec']['data']['input_manifests']=[manifest]
    proposal['spec']['execution']['実行整合']='境界検査を有効にし、同じプロセスでPython/JITの純人工全配列一致・全UID保存を要求してから保存実入力を読む。'
    P.save(HERE/'試行計画.json',proposal)
    for command,name in (('check','事前照合の全出力.json'),('register','正式登録の全出力.json')):
        process=subprocess.run([sys.executable,'-B','-X','utf8',str(P.MANAGER),command,'--proposal',str(HERE/'試行計画.json')],
            cwd=P.ROOT,capture_output=True,text=True,encoding='utf-8')
        P.save(HERE/name,dict(終了コード=process.returncode,stdout=process.stdout,stderr=process.stderr))
        print(command,process.returncode,flush=True)
        assert process.returncode==0


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--audit',type=Path,required=True)
    main(parser.parse_args().audit)
