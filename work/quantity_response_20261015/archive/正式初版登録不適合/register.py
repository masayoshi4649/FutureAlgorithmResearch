"""非金融の観測計画を照合し、終端成功を確かめてから登録する。"""

import json
import subprocess
import sys

import plan


def main() -> None:
    """
    機能: 正式固定後の計画を共通の試行照合へ渡し、全出力と終了コードを残す。
    引数: なし。
    返り値: None。実測・金融・原入力読取は開始しない。
    """
    assert (plan.HERE / '実測前の正式固定.json').exists()
    manager = plan.ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    proposal = plan.HERE / '試行計画.json'
    for command, label in (('check', '正式照合'), ('register', '正式登録')):
        target = plan.HERE / (label + 'の全出力.json')
        assert not target.exists()
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(manager), command,
                                 '--proposal', str(proposal)], cwd=plan.ROOT,
                                text=True, encoding='utf-8', capture_output=True, check=False)
        plan.write(target, dict(終了コード=result.returncode, stdout=result.stdout, stderr=result.stderr,
                                金融=0, 実測=0))
        assert result.returncode == 0, label + 'が失敗したため実測を開始しない'
        print(json.dumps(dict(段階=label, 終了コード=result.returncode, 実測=0), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
