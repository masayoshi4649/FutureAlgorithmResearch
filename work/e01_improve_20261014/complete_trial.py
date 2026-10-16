"""正式一回の十八対照を登録済み履歴へ結び、保存結果の再利用を可能にする。"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TRIAL = '105_E01公開気配FAK二許容と票強度四条件の十八対照'
DATA = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data'


def read(path: Path) -> tuple[dict, bytes]:
    """
    機能: 小会計又は登録を同じバイト列で読み、履歴の指紋に結ぶ。
    引数: path(Path) は完成JSON又は共通試行台帳。
    返り値: tuple[dict,bytes] は辞書と原バイト列。金融入力を読まない。
    """
    saved = path.read_bytes()
    return json.loads(saved.decode('utf-8-sig')), saved


def main() -> None:
    """
    機能: 終了した十八条件の証拠を事前登録と結び、旧台帳を保全して更新する。
    引数: なし。金融結果・固定・計画・根が公開した小会計を扱う。
    返り値: None。既に同じ証拠なら追加更新せず、再生は行わない。
    """
    result_path = HERE/'engine/finance/結果.json'
    result, saved = read(result_path)
    fixed, _ = read(HERE/'engine/金融事前固定.json')
    plan, _ = read(HERE/'engine/試行計画.json')
    public = ROOT/'アルゴリズム調査/00105_公開価格を追わないE01の改善'
    account, _ = read(public/'公開価格を追わないE01の全比較と銘柄別固定会計.json')
    assert result['全合格'] and result['source開始終端一致']
    assert len(result['configs']) == 18 and result['会計口座数'] == 1188
    assert result['configs'] == fixed['configs'] == plan['spec']['entry']['conditions']
    assert result['source_SHA256'] == fixed['source_SHA256'] == plan['spec']['implementation']
    assert account['全合格'] and account['金融source_SHA256'] == result['source_SHA256']
    table, previous = read(DATA/'trials.json')
    found = [r for r in table['trials'] if r['id'] == TRIAL]
    assert len(found) == 1 and found[0]['spec'] == plan['spec']
    row = found[0]
    evidence = dict(path=result_path.relative_to(ROOT).as_posix(),
        label='既知33場の正式18条件・1188口座。旧6対照は保存再利用。',
        sha256=hashlib.sha256(saved).hexdigest())
    if row.get('completed_result') == evidence:
        print('同じ完成結果を登録済み。追加更新0。')
        return
    assert row['status'] == '未実行'
    row['status'] = '検証済み'
    row['completed_result'] = evidence
    row.setdefault('evidence', []).append(evidence)
    row['result'] = ('公開価格を追わないFAKと票条件の18対照を一回再生。'
        f'商品別固定選択は{account["pair"]["selected"]}。'
        f'主三基準合格{account["main_achieved_symbols"]}/2商品。'
        '活動数、赤字、上位3利益除外、途中逆行を別表に記録。')
    row['completion_limitations'] = ('同じ既知33場内での探索・選択。無取引は勝ちでない。'
        'ラージ最良気配の価格模型で、実商品の部分FAK、待ち順位、共通受信先後は未確認。'
        '未知セッションの成功の証拠ではない。API・現在入力・実注文・ライブApp変更0。')

    # ----------------------------------------
    # 変更前を指紋付き履歴へ保全してから、一時ファイルを置換する。
    table['updated_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    before = hashlib.sha256(previous).hexdigest()
    history = DATA/'history'/('trials_'+before+'.json')
    if not history.exists():
        history.write_bytes(previous)
    temporary = DATA/'trials_105_completion.tmp'
    temporary.write_text(json.dumps(table, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
        encoding='utf-8', newline='\n')
    temporary.replace(DATA/'trials.json')
    proof = dict(全合格=True, 完了ID=TRIAL, 元台帳SHA256=before,
        更新台帳SHA256=hashlib.sha256((DATA/'trials.json').read_bytes()).hexdigest(),
        完成結果=evidence, 金融再生=0, API=0, 大型入力読取=0)
    (HERE/'試行完了の登録.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n',
        encoding='utf-8', newline='\n')
    print('今回の正式18条件を完了登録。金融再生0。')


if __name__ == '__main__':
    main()
