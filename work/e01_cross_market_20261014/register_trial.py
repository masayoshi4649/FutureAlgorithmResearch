"""正式八部品の登録出力を保存し、大量の差分を端末へ流さず要点を報告する。"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main() -> None:
    """
    機能: 根の正式計画を既存照合CLIで一度登録し、全出力と小要約を保存する。
    引数: なし。正式計画はengine/試行計画.json、CLIは既存manage.py。
    返り値: None。実入力と金融には触れず、登録失敗時は再実行しない。
    """
    plan_path = HERE/'engine/試行計画.json'
    prepared = json.loads(plan_path.read_text(encoding='utf-8'))
    assert prepared['正式freeze'] and not (HERE/'登録の全出力.json').exists()
    command = [sys.executable, '-B', '-X', 'utf8',
        str(ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'),
        'register', '--proposal', str(plan_path)]
    finished = subprocess.run(command, cwd=ROOT, capture_output=True)
    if finished.returncode:
        (HERE/'登録False.log').write_bytes(finished.stdout+b'\n'+finished.stderr)
        raise RuntimeError('登録が失敗。保存ログを確認し、自動で再実行しない。')
    row = json.loads(finished.stdout.decode('utf-8'))
    assert row['id'] == prepared['id'] and row['spec'] == prepared['spec'] and row['status'] == '未実行'
    checked = row['preflight']
    assert checked['proposal_complete'] and not any(m['kind'] == '完全同一' for m in checked['matches'])
    (HERE/'登録の全出力.json').write_bytes(finished.stdout)
    proof = dict(全合格=True, 登録ID=row['id'], 状態=row['status'],
        計画SHA256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        登録出力SHA256=hashlib.sha256(finished.stdout).hexdigest(), 出力バイト数=len(finished.stdout),
        提案完全=True, 未照合過去あり=bool(checked['incomplete_history']),
        新金融=0, API=0, 原入力=0)
    (HERE/'金融前の試行登録.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
