"""一回の14対照の完成結果を事前登録へ結び、後続の重複を防ぐ。"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TRIAL = '107_E01保有容量三種類と実親出口四種類及び追加機会十四対照'
DATA = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data'
PUBLIC = ROOT/'アルゴリズム調査/00107_保有容量と一取引利益の再検証'


def read(path: Path) -> tuple[dict, bytes]:
    """
    機能: 保存した完成結果と登録資料を同じバイト列から指紋へ結ぶ。
    引数: path(Path) は完成結果・会計・固定・計画又は試行台帳。
    返り値: tuple[dict,bytes] は内容と保存バイト列。原金融入力は読まない。
    """
    saved = path.read_bytes()
    return json.loads(saved.decode('utf-8-sig')), saved


def main() -> None:
    """
    機能: 正式14条件と924口座の実行済み証拠を、保全履歴付きで登録する。
    引数: なし。新結果・固定・正式計画・公開会計だけを完成条件にする。
    返り値: None。検証合格を目標達成とは呼ばず、主条件の成否を別記する。
    """
    result_path = HERE/'engine/finance/結果.json'
    result, saved = read(result_path)
    fixed, _ = read(HERE/'engine/金融事前固定.json')
    plan, _ = read(HERE/'engine/試行計画.json')
    account, _ = read(PUBLIC/'容量別E01の一場平均と全場会計.json')
    assert result['全合格'] and result['source開始終端一致']
    assert len(result['configs']) == 14 and result['新account金融'] == 924
    assert result['configs'] == fixed['configs'] == plan['spec']['entry']['conditions']
    assert result['source_SHA256'] == fixed['source_SHA256'] == plan['spec']['implementation']
    assert account['全合格'] and account['金融source_SHA256'] == result['source_SHA256']
    table, previous = read(DATA/'trials.json')
    found = [r for r in table['trials'] if r['id'] == TRIAL]
    assert len(found) == 1 and found[0]['spec'] == plan['spec']
    row = found[0]
    evidence = dict(path=result_path.relative_to(ROOT).as_posix(),
        label='既知33場の正式14条件・924口座。旧GU金融の再利用なし。',
        sha256=hashlib.sha256(saved).hexdigest())
    if row.get('completed_result') == evidence:
        print('同じ完成結果を登録済み。追加更新0。')
        return
    assert row['status'] == '未実行'
    row['status'] = '検証済み'
    row['completed_result'] = evidence
    row.setdefault('evidence', []).append(evidence)
    top = account['pair']['metrics']['TOPIX']['full']
    nk = account['pair']['metrics']['NK225']['full']
    row['result'] = (
        f'数量3種類・出口4種類と共通全量2条件の14対照を一回再生。'
        f'TOPIX全場平均netは{top["mean_session_net"]}円、平均10万円を含む主条件は{top["primary_pass"]}。'
        f'日経の従来三基準は{nk["pass_all"]}、日経円額床は未指定。'
        '商品ごとの固定設定、実数量、全場、上位3除外、途中逆行を別記。')
    row['completion_limitations'] = (
        '同じ既知33場での探索・選択。旧P1小利益終了を解除し、後候補と実保有を再運転。'
        'ラージ気配を実商品の価格代理にした模型で、真受信順、実部分FAK、待ち順位、市場影響は未測。'
        '未知セッションの安定収益の証拠ではない。API・現在取得・実注文・ライブApp変更0。')

    # ----------------------------------------
    # 台帳の変更前を指紋で保存し、一時ファイルから置換する。
    table['updated_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    before = hashlib.sha256(previous).hexdigest()
    history = DATA/'history'/('trials_'+before+'.json')
    if not history.exists():
        history.write_bytes(previous)
    temporary = DATA/'trials_107_completion.tmp'
    temporary.write_text(json.dumps(table, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
        encoding='utf-8', newline='\n')
    temporary.replace(DATA/'trials.json')
    proof = dict(全合格=True, 完了ID=TRIAL, 元台帳SHA256=before,
        更新台帳SHA256=hashlib.sha256((DATA/'trials.json').read_bytes()).hexdigest(),
        完成結果=evidence, 金融再生=0, API=0, 大型入力読取=0)
    (HERE/'試行完了の登録.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n',
        encoding='utf-8', newline='\n')
    print('正式14条件を完了登録。目標達成は会計の別判定。金融再生0。')


if __name__ == '__main__':
    main()
