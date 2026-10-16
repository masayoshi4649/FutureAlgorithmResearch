"""登録の非空辞書形式だけを修正した草案を、実登録前に照合する。"""

import json
import subprocess
import sys

import plan


def main() -> None:
    """
    機能: 不受理だった計画の観測内容を維持し、八部品の完全性を確認する。
    引数: なし。
    返り値: None。正式固定・実登録・入力本文の読取は行わない。
    """
    proposal = plan.read(plan.HERE / 'archive/正式初版登録不適合/試行計画.json')
    proposal['spec']['allocation'] = dict(用途='売買なし', 集計='両商品を個別集計し、各場・方向・昼夜を併記')
    proposal['spec']['costs'] = dict(用途='売買なし', 未測='1T先着を手数料後利益と呼ばない')
    proposal['spec']['execution'] = dict(用途='注文・金融なし', 評価='ラージBBOと自身原seqによる価格応答のみ')
    proposal['spec']['implementation'] = plan.sources()
    target = plan.HERE / '辞書形式修正の照合草案.json'
    plan.write(target, proposal)
    manager = plan.ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(manager), 'check', '--proposal', str(target)],
                            text=True, encoding='utf-8', capture_output=True, cwd=plan.ROOT, check=False)
    plan.write(plan.HERE / '辞書形式修正の草案照合全出力.json',
               dict(終了コード=result.returncode, stdout=result.stdout, stderr=result.stderr, 入力本文=0))
    assert result.returncode == 0
    actual = json.loads(result.stdout)
    assert actual['proposal_complete']
    print(json.dumps(dict(全合格=True, 提案完全=actual['proposal_complete'], 実登録=0, 入力本文=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
