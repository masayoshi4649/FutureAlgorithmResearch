"""正式計画の重複照合と登録を、全出力保存・小要約だけで実行する。"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANAGE = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def invoke(command: str, plan: Path) -> bytes:
    """
    機能: 既存の試行照合CLIをUTF-8で呼び、巨大出力を端末へ流さない。
    引数: command(str)、plan(Path) はcheck又はregisterと正式提案。
    返り値: bytes は成功した全JSON出力。失敗は保存し自動再実行しない。
    """
    finished = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(MANAGE), command,
        '--proposal', str(plan)], cwd=ROOT, capture_output=True)
    if finished.returncode:
        (HERE/(command+'のFalse.log')).write_bytes(finished.stdout+b'\n'+finished.stderr)
        raise RuntimeError('試行CLIが失敗。ログを保存し、自動再実行しない。')
    return finished.stdout


def main() -> None:
    """
    機能: 根の正式18計画をcheckしてから一度登録し、実行前証跡を残す。
    引数: なし。engine/試行計画.jsonと既存共通台帳を扱う。
    返り値: None。金融入力・APIを読まず、旧台帳の登録前履歴はmanageが保持する。
    """
    plan_path = HERE/'engine/試行計画.json'
    proposal = json.loads(plan_path.read_text(encoding='utf-8'))
    assert proposal['正式freeze'] and not (HERE/'登録の全出力.json').exists()
    assert not (HERE/'重複照合の全出力.json').exists()
    checked_bytes = invoke('check', plan_path)
    checked = json.loads(checked_bytes.decode('utf-8'))
    (HERE/'重複照合の全出力.json').write_bytes(checked_bytes)
    assert checked['proposal_complete']
    assert not any(v['kind'] == '完全同一' for v in checked['matches'])

    # ----------------------------------------
    # 照合の後だけ登録する。保存済み完全同一は新規再生へ回さない。
    registered_bytes = invoke('register', plan_path)
    row = json.loads(registered_bytes.decode('utf-8'))
    assert row['id'] == proposal['id'] and row['spec'] == proposal['spec'] and row['status'] == '未実行'
    assert row['preflight']['proposal_complete']
    assert not any(v['kind'] == '完全同一' for v in row['preflight']['matches'])
    (HERE/'登録の全出力.json').write_bytes(registered_bytes)
    proof = dict(全合格=True, 登録ID=row['id'], 状態=row['status'],
        計画SHA256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        照合SHA256=hashlib.sha256(checked_bytes).hexdigest(),
        登録SHA256=hashlib.sha256(registered_bytes).hexdigest(),
        未照合過去あり=bool(checked['incomplete_history']), 金融=0, 入力=0, API=0)
    (HERE/'金融前の照合と登録.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n',
        encoding='utf-8', newline='\n')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
