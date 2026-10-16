"""完成台帳の再生成と深い検査の大きい出力を資料として保存する。"""

import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main() -> None:
    """
    機能: 既存試行台帳のbuildまたはverifyを実行し、全出力を保存する。
    引数: sys.argv[1](str)はbuildまたはverify。
    返り値: None。終了コードを確認し金融処理は呼ばない。
    """
    assert len(sys.argv) == 2 and sys.argv[1] in ('build', 'verify')
    command = sys.argv[1]
    tool = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    completed = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(tool), command, '--deep'],
                               cwd=ROOT, capture_output=True, encoding='utf-8')
    (HERE / ('完成台帳_' + command + '_全出力.json')).write_text(
        json.dumps(dict(command=command, returncode=completed.returncode,
                        stdout=completed.stdout, stderr=completed.stderr), ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8', newline='\n')
    assert completed.returncode == 0, completed.stderr[-2000:]
    result = json.loads(completed.stdout)
    print(json.dumps(dict(処理=command, 終了コード=completed.returncode,
                          出力型=type(result).__name__, 項目=list(result) if isinstance(result, dict) else None,
                          新金融=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
