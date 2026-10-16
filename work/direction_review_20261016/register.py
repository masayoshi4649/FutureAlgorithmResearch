"""非金融十八採点を照合し、正式登録の終端を保存する。"""

import json
import subprocess
import sys

import plan


def main() -> None:
    """
    機能: 八部品の完備性を照合し、登録後も実測を自動実行しない。
    引数: なし。
    返り値: None。checkの終了コードとproposal_completeをともに確認する。
    """
    assert (plan.HERE/'実測前の正式固定.json').exists()
    manager=plan.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    proposal=plan.HERE/'試行計画.json'
    for command,label in (('check','正式照合'),('register','正式登録')):
        target=plan.HERE/(label+'の全出力.json')
        assert not target.exists()
        result=subprocess.run([sys.executable,'-B','-X','utf8',str(manager),command,'--proposal',str(proposal)],
            cwd=plan.ROOT,text=True,encoding='utf-8',capture_output=True,check=False)
        plan.write(target,dict(終了コード=result.returncode,stdout=result.stdout,stderr=result.stderr,新金融=0,原NPZ=0))
        assert result.returncode==0,label
        if command=='check':assert json.loads(result.stdout)['proposal_complete'] is True
        print(json.dumps(dict(段階=label,終了コード=result.returncode,新金融=0),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
