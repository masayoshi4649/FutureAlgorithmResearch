"""00111の一回金融と保存経済同値を完成履歴へ接続する。"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data'
PUBLIC = ROOT / 'アルゴリズム調査/00111_少ない価格票で注文価格を追わない検証'


def read(path: Path) -> tuple[dict, bytes]:
    """
    機能: 小資料と保存バイトを読み指紋に接続する。
    引数: path(Path)は固定・小射影・公開会計の保存先。
    返り値: tuple[dict,bytes]は内容とバイト列。金融の再運転はしない。
    """
    content = path.read_bytes()
    return json.loads(content.decode('utf-8-sig')), content


def main() -> None:
    """
    機能: 新297口座・内部同値99・旧396保存の十二比較を完成登録する。
    引数: なし。固定、正式計画、小射影、公開会計で確認する。
    返り値: None。検証実行の完了と利益目標達成を別記する。
    """
    summary, _ = read(HERE / '十二比較の主判定と全場平均の小射影.json')
    fixed, _ = read(HERE / 'engine/金融事前固定.json')
    plan, _ = read(HERE / 'engine/試行計画.json')
    account, _ = read(PUBLIC / '価格票の最低数別E01の全場会計.json')
    result_path = HERE / 'engine/finance/結果.json'
    assert summary['全合格'] and account['全合格']
    assert summary['counts'] == {'既input一読': 33, '価格票準備口座': 66,
                                 '新account金融': 297, '内部同値会計再利用': 99}
    assert hashlib.sha256(result_path.read_bytes()).hexdigest() == summary['結果SHA256']
    assert len(fixed['configs']) == 12 and len(summary['cases']) == 6
    assert len(summary['保存経済同値']) == 6
    assert summary['比較場会計'] == 792 and summary['新場会計'] == 297
    assert summary['内部同値場会計'] == 99 and summary['保存場会計'] == 396
    assert summary['旧経済同値再金融'] == summary['内部同値再金融'] == 0
    assert fixed['configs'] == plan['spec']['entry']['conditions']
    assert summary['source_SHA256'] == fixed['source_SHA256'] == plan['spec']['implementation']
    assert len(fixed['source_SHA256']) == 17
    assert account['金融source_SHA256'] == summary['source_SHA256']
    table, previous = read(DATA / 'trials.json')
    found = [r for r in table['trials'] if r['id'] == plan['id']]
    assert len(found) == 1 and found[0]['spec'] == plan['spec']
    row = found[0]
    evidence = dict(path=result_path.relative_to(ROOT).as_posix(),
                    label='既知33場の十二比較。新297口座・内部同値99・旧経済396保存。',
                    sha256=summary['結果SHA256'])
    if row.get('completed_result') == evidence:
        print('同じ完成結果を登録済み。更新0。')
        return
    assert row['status'] == '未実行'
    row['status'] = '検証済み'
    row['completed_result'] = evidence
    row.setdefault('evidence', []).append(evidence)
    top = account['pair']['metrics']['TOPIX']['full']
    nk = account['pair']['metrics']['NK225']['full']
    row['result'] = (
        '不利1観測呼値の追随許可に両市場各2価格票を追加。新297口座は33場一回運転、'
        '内部同値99と旧396は保存引用。'
        f'事前順位参考のTOPIX全場平均net{top["mean_session_net"]}円、'
        f'主条件{top["primary_pass"]}。日経三基準{nk["pass_all"]}、円額床は未指定。'
        '全12両商品主合格0。旧負け回避・失った勝ち・共通出口差・費用差・新参加を分解。')
    row['completion_limitations'] = (
        '同じ既知33場での探索。保存6条件は経済・実注文同値で、拒否公開の許容表示は別。'
        '出来高は真攻撃量ではない。ラージ気配のmini/micro代理、価格時計模型。'
        '真受信順・実キュー・部分FAK・市場影響・未知新場の成功は未測。'
        '現在API・実注文・ライブApp変更0。')

    # ----------------------------------------
    # 正本の変更前を保全し、完成状態だけを更新する。
    table['updated_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    before = hashlib.sha256(previous).hexdigest()
    history = DATA / 'history' / ('trials_' + before + '.json')
    if not history.exists():
        history.write_bytes(previous)
    temporary = DATA / 'trials_111_completion.tmp'
    temporary.write_text(json.dumps(table, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                         encoding='utf-8', newline='\n')
    temporary.replace(DATA / 'trials.json')
    proof = dict(全合格=True, 完了ID=plan['id'], 元台帳SHA256=before,
                  更新台帳SHA256=hashlib.sha256((DATA / 'trials.json').read_bytes()).hexdigest(),
                  完成結果=evidence, 新金融=0, 原入力=0, API=0)
    (HERE / '試行完了の登録.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n',
                                             encoding='utf-8', newline='\n')
    print('00111の十二比較を完了登録。目標達成とは別。新金融0。')


if __name__ == '__main__':
    main()
