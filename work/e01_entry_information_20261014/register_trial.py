"""正式な9新条件を金融前に照合・登録し、全出力を保存する。"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANAGE = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def invoke(command: str, plan: Path) -> bytes:
    """
    機能: 大きい試行照合の全出力を保存するため端末出力を抑えて実行する。
    引数: command(str)はcheck又はregister、plan(Path)は正式計画。
    返り値: bytesは成功時の出力。失敗を保存し、自動再試行しない。
    """
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(MANAGE), command,
                             '--proposal', str(plan)], cwd=ROOT, capture_output=True)
    if result.returncode:
        (HERE / (command + 'のFalse.log')).write_bytes(result.stdout + b'\n' + result.stderr)
        raise RuntimeError('照合CLIの失敗を保存。確認するまで再試行しない。')
    return result.stdout


def main() -> None:
    """
    機能: 正式固定した9新条件を先に照合し、完全同一でないものだけ登録する。
    引数: なし。engineの正式計画と固定源指紋を読み、金融素材は読まない。
    返り値: None。登録結果と未照合過去の留保を別の証拠へ保存する。
    """
    plan_path = HERE / 'engine/試行計画.json'
    proposal = json.loads(plan_path.read_text(encoding='utf-8-sig'))
    assert proposal['正式freeze']
    conditions = proposal['spec']['entry']['conditions']
    assert len(conditions) == 12
    assert sum(c['actual_financial'] is True for c in conditions) == 9
    assert sum(c['actual_financial'] is False for c in conditions) == 3
    assert sum(c['actual_financial_by_symbol']['TOPIX'] is True for c in conditions) == 9
    assert sum(c['actual_financial_by_symbol']['NK225'] is True for c in conditions) == 6
    for relative, expected in proposal['spec']['implementation'].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    check_path = HERE / '重複照合の全出力.json'
    register_path = HERE / '登録の全出力.json'
    assert not check_path.exists() and not register_path.exists(), '既照合を自動で反復しない。'
    checked_bytes = invoke('check', plan_path)
    check_path.write_bytes(checked_bytes)
    checked = json.loads(checked_bytes.decode('utf-8-sig'))
    assert checked['proposal_complete'], '不完全な八部品を登録しない。'
    assert not any(m['kind'] == '完全同一' for m in checked['matches'])

    # ----------------------------------------
    # 保存結果と同一の条件を新金融へ回さず、照合後だけ登録する。
    registered_bytes = invoke('register', plan_path)
    register_path.write_bytes(registered_bytes)
    registered = json.loads(registered_bytes.decode('utf-8-sig'))
    assert registered['id'] == proposal['id'] and registered['spec'] == proposal['spec']
    assert registered['status'] == '未実行' and registered['preflight']['proposal_complete']
    assert not any(m['kind'] == '完全同一' for m in registered['preflight']['matches'])
    proof = dict(全合格=True, 登録ID=registered['id'], 状態=registered['status'],
                 計画SHA256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                 照合SHA256=hashlib.sha256(checked_bytes).hexdigest(),
                 登録SHA256=hashlib.sha256(registered_bytes).hexdigest(),
                 未照合過去あり=bool(checked['incomplete_history']), 金融=0, 入力=0, API=0)
    (HERE / '金融前の照合と登録.json').write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
