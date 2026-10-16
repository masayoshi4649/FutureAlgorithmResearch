"""照合・登録の大きな出力を保存し、根のレビューに必要な要点だけを表示する。"""

import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
MANAGE = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def run(action: str, plan: Path, output: Path) -> None:
    """
    機能: 指定した一つの台帳操作を実行し、全出力と終了コードを保存する。
    引数: action(str)はcheck/register、plan(Path)は固定計画、output(Path)は未存在証跡。
    返り値: None。操作の失敗や完全な計画でない場合は停止し、自動再実行しない。
    """
    assert action in ('check', 'register')
    assert plan.resolve().is_relative_to(ROOT) and plan.is_file()
    assert output.resolve().is_relative_to(ROOT/'work') and not output.exists()
    process = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(MANAGE), action,
                              '--proposal', str(plan)], cwd=ROOT, capture_output=True,
                             text=True, encoding='utf8')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(process.stdout, encoding='utf8', newline='\n')
    if process.stderr:
        output.with_suffix('.stderr.txt').write_text(process.stderr, encoding='utf8')
    print('台帳操作', action, '終了コード', process.returncode, '保存文字数', len(process.stdout))
    if process.returncode:
        print(process.stderr[-2400:])
        raise SystemExit(process.returncode)
    value = json.loads(process.stdout)
    keys = ('判定', 'proposal_complete', '登録ID', 'registered_id', 'error', '完全一致数')
    print(json.dumps({key: value[key] for key in keys if key in value}, ensure_ascii=False))
    if action == 'check' and value.get('proposal_complete') is not True:
        print(json.dumps(value.get('提案不完全理由', []), ensure_ascii=False))
        raise SystemExit(2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='根の明示操作だけを一回実行する')
    parser.add_argument('action', choices=('check', 'register'))
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.action, args.plan, args.output)
