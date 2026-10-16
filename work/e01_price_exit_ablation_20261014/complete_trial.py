"""反票OFFの一回金融と公開結果を完成履歴へ結ぶ。"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data'
PUBLIC = ROOT / 'アルゴリズム調査/00109_二市場の逆票返済を外した継続検証'


def read(path: Path) -> tuple[dict, bytes]:
    """
    機能: 登録・固定・会計・小射影を同じバイト列から読み指紋へ結ぶ。
    引数: path(Path)は保存済みのJSON資料。
    返り値: tuple[dict,bytes]は内容と保存バイト列。原金融入力は読まない。
    """
    content = path.read_bytes()
    return json.loads(content.decode('utf-8-sig')), content


def main() -> None:
    """
    機能: OFF12条件・792口座の完成を履歴保全して事前登録へ結ぶ。
    引数: なし。小射影と公開会計から完成を確認する。
    返り値: None。検査合格と利益目標の達成を別記し、金融を再運転しない。
    """
    summary, _ = read(HERE / '十二条件の主判定と全場平均の小射影.json')
    fixed, _ = read(HERE / 'engine/金融事前固定.json')
    plan, _ = read(HERE / 'engine/試行計画.json')
    account, _ = read(PUBLIC / '逆票返済OFFの全場会計.json')
    result_path = HERE / 'engine/finance/結果.json'
    assert summary['全合格'] and account['全合格']
    assert summary['counts'] == {'既input一読': 33, '価格票準備口座': 66, '新account金融': 792}
    assert hashlib.sha256(result_path.read_bytes()).hexdigest() == summary['結果SHA256']
    assert len(fixed['configs']) == len(summary['cases']) == 12
    assert fixed['configs'] == plan['spec']['entry']['conditions']
    assert summary['source_SHA256'] == fixed['source_SHA256'] == plan['spec']['implementation']
    assert len(fixed['source_SHA256']) == 16
    assert account['金融source_SHA256'] == summary['source_SHA256']
    table, previous = read(DATA / 'trials.json')
    found = [r for r in table['trials'] if r['id'] == plan['id']]
    assert len(found) == 1 and found[0]['spec'] == plan['spec']
    row = found[0]
    evidence = dict(path=result_path.relative_to(ROOT).as_posix(),
                    label='既知33場の反票OFF正式12条件・792口座。ON12は保存再利用。',
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
        '反対価格票退出のみOFFで12条件を33場一回運転。全12は両商品合計赤字、目標達成0。'
        f'事前順位の参考TOPIX全場平均netは{top["mean_session_net"]}円、'
        f'平均10万円を含む主条件は{top["primary_pass"]}。日経の三基準は{nk["pass_all"]}、円額床は未指定。'
        'ON保存集計との差・全場・上位3除外・途中逆行・昼夜・方向を別記。')
    row['completion_limitations'] = (
        '同じ既知33場での探索。ON個別親の対応と経路は未収録。全差額を共通親の退出だけの効果としない。'
        'ラージ気配のmini/micro代理・価格時計模型。真受信順/部分FAK/実キュー/市場影響は未測。'
        '新しい未知セッションでの成功証明ではない。現在API・実注文・ライブApp変更0。')

    # ----------------------------------------
    # 台帳の変更前を指紋で保存し、一時ファイルから置換する。
    table['updated_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    before = hashlib.sha256(previous).hexdigest()
    history = DATA / 'history' / ('trials_' + before + '.json')
    if not history.exists():
        history.write_bytes(previous)
    temporary = DATA / 'trials_109_completion.tmp'
    temporary.write_text(json.dumps(table, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                         encoding='utf-8', newline='\n')
    temporary.replace(DATA / 'trials.json')
    proof = dict(全合格=True, 完了ID=plan['id'], 元台帳SHA256=before,
                  更新台帳SHA256=hashlib.sha256((DATA / 'trials.json').read_bytes()).hexdigest(),
                  完成結果=evidence, 新金融=0, 原入力=0, API=0)
    (HERE / '試行完了の登録.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n',
                                             encoding='utf-8', newline='\n')
    print('反票OFF正式12条件を完了登録。利益目標は未達。新金融0。')


if __name__ == '__main__':
    main()
