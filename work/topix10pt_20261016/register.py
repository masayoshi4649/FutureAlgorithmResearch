"""非金融の十ポイント予兆探索を照合・登録し、読取へは自動進行しない。"""

import json
import subprocess
import sys

import plan


def main() -> None:
    """
    機能: 十源と八部品の計画完備を確認し、登録の終了コードを保存する。
    引数: なし。
    返り値: None。巨大stdoutを画面へ出さず、checkのproposal_completeも確認する。
    """
    assert (plan.HERE/'正式固定.json').exists()
    manager=plan.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    for command,label in (('check','正式照合'),('register','正式登録')):
        target=plan.HERE/(label+'の全出力.json');assert not target.exists()
        p=subprocess.run([sys.executable,'-B','-X','utf8',str(manager),command,'--proposal',str(plan.HERE/'試行計画.json')],
            cwd=plan.ROOT,text=True,encoding='utf-8',capture_output=True,check=False)
        plan.write(target,dict(終了コード=p.returncode,stdout=p.stdout,stderr=p.stderr,新金融=0,実入力=0))
        assert p.returncode==0
        if command=='check':assert json.loads(p.stdout)['proposal_complete'] is True
        print(json.dumps(dict(段階=label,終了コード=p.returncode,新金融=0),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
