"""独立した反復点検を共通台帳へ追加し、初回正本を履歴に残す。"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = ROOT/'アルゴリズム調査/共通/知見台帳/data'


def evidence(name: str) -> dict:
    """
    機能: 点検元の相対パスと指紋を対応させる。
    引数: name(str)は保存された根拠。
    返り値: dictは出典参照。
    """
    path = ROOT/name.replace('\\', '/')
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest(), label='点検の根拠')


def main() -> None:
    """
    機能: 6分類と名目数の注意を共通正本へ移し、旧版を保持する。
    引数: なし。
    返り値: None。保存された金融値や旧資料を書き換えない。
    """
    audit_path = HERE/'repetition_audit.json'
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    assert audit['全合格'] and audit['新金融再生'] == 0
    path = DATA/'trials.json'
    previous = path.read_bytes()
    table = json.loads(previous)
    assert not table['repetition_audit'], '反復点検は既に取り込み済みです'
    source = audit_path.relative_to(ROOT).as_posix()
    for number, row in enumerate(audit['根拠付き分類'], 1):
        table['repetition_audit'].append(dict(id=f'R{number:02}', title=row['分類'], status=row['分類'],
            finding=row['事実'], action=row['目的'], scope=audit['scope'],
            evidence=[evidence(source)]+[evidence(name) for name in row['根拠']]))
    count = audit['名目条件数と同値族']
    table['repetition_audit'].append(dict(id='R07', title='名目の条件数と独立した仮説の数は別', status='部分的重複',
        finding=count['例'], action=count['注意'], scope='work/wave_v96の事前固定で確認。', evidence=[evidence(source), evidence(count['根拠'])]))
    table['repetition_audit'].append(dict(id='R08', title='全履歴に無駄がなかったとは確認していない', status='未確認範囲あり',
        finding=audit['結論']['無目的完全再試行の全否定は不可'],
        action='未整理の試行を「存在しない」とせず、次の研究で関連する過去条件を先に調べる。',
        scope='\n'.join(audit['未確認']), evidence=[evidence(source)]))
    for row in table['trials']:
        if row['id'].startswith('105_'):
            row['limitations'] += ' R型の価格発動は費用回収幅F＋αR。損失帯の中心は旧支持価格。'
    table['updated_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    history = DATA/'history'
    history.mkdir(exist_ok=True)
    snapshot = history/('trials_'+hashlib.sha256(previous).hexdigest()+'.json')
    assert not snapshot.exists()
    snapshot.write_bytes(previous)
    path.write_text(json.dumps(table, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print('重複点検8件を追加。旧正本は履歴へ保持しました。')


if __name__ == '__main__':
    main()
