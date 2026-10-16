"""今回の成果を、既存の案内から開けるようにする。金融源と過去作業を変えない。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FOLDER = '00104_E01の銘柄差の原因と修正検証'
REPORT = 'E01の銘柄差と修正後の全セッション損益.html'


def replace_section(text: str, begin: str, end: str, replacement: str) -> str:
    """
    機能: 指定した案内の区間だけを置換して、過去作業の一覧を保持する。
    引数: text/begin/end/replacement(str) は現本文・両境界・新しい案内。
    返り値: str は区間を更新した本文。境界不明なら停止する。
    """
    assert begin in text and end in text
    start = text.index(begin)
    stop = text.index(end, start)
    return text[:start]+replacement+text[stop:]


def main() -> None:
    """
    機能: 根README・作業README・一覧HTMLの最新案内を更新する。
    引数: なし。既存の三案内と今回の完成HTMLだけを扱う。
    返り値: None。金融再生・API・実注文は行わない。
    """
    public = ROOT/'アルゴリズム調査'/FOLDER
    assert (public/REPORT).exists()
    status = ('入口の方向票を厳しくしたB03はTOPIX＋7,342円・日経＋2,592円で数式三基準を達成。'
        'ただし活動7／8場・無取引26／25場、15取引中13件はナイト。毎場安定利益の確立ではありません。'
        '出口だけの10条件ではTOPIXの赤字を解消できませんでした。')
    root_path = ROOT/'README.md'
    root_before = root_path.read_text(encoding='utf-8')
    root_new = replace_section(root_before, '現在の調査は', '## フォルダとデータ',
        f'現在の調査は **[00104：E01の銘柄差の原因と修正検証](アルゴリズム調査/{FOLDER}/README.md)** です。'
        f'{status}\n\n最初に [説明と全33場の損益](アルゴリズム調査/{FOLDER}/{REPORT}) を開いてください。'
        f'[損失の具体時刻と判断](アルゴリズム調査/{FOLDER}/判断と損失の具体例.md)、'
        '[調査方針](アルゴリズム調査/調査方針.md)、'
        '[共通知見台帳](アルゴリズム調査/共通/知見台帳/README.md) に原因・限界を記録しています。\n\n'
        '前段の [00103](アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証/README.md) の保存結果は保持し、'
        '同一仕様は再利用しています。今回の16新条件は結果前に固定・登録し、全33場を一回再生しました。\n\n')

    # ----------------------------------------
    # 作業一覧の先頭だけを更新し、既存100作業以上の導線は残す。
    study_path = ROOT/'アルゴリズム調査/README.md'
    study_before = study_path.read_text(encoding='utf-8')
    study_new = replace_section(study_before, '**[00103：', '**[共通知見台帳]',
        f'**[00104：E01の銘柄差の原因と修正検証]({FOLDER}/README.md)**。{status}\n\n'
        f'[説明と全33場の損益]({FOLDER}/{REPORT}) · '
        f'[TOPIX赤字上位3場と判断]({FOLDER}/判断と損失の具体例.md) · [調査方針](調査方針.md)。\n\n'
        '前段の [00103：往復帯の回避と損失後再参加の統合検証]'
        '(00103_往復帯の回避と損失後再参加の統合検証/README.md) は保存済み。'
        '新しい入口と出口の部品結果は共通Markdownへ出典付きで追記しました。\n\n')
    index_path = ROOT/'アルゴリズム調査/index.html'
    index_before = index_path.read_text(encoding='utf-8')
    assert '作業00104' not in index_before
    index_new = index_before.replace('<article class="task latest"><div class="number">作業00103',
        '<article class="task"><div class="number">作業00103', 1)
    index_new = index_new.replace('両銘柄共通の三基準達成は未発見です。',
        'この00103調査時点では、両銘柄共通の三基準達成は未発見でした。', 1)
    index_new = index_new.replace('最新の調査00103：毎場の小〜中利益を目指し、具体的な失敗と改善を比較。',
        '最新の調査00104：E01の銘柄差を調べ、入口と出口の16修正を比較。', 1)
    card = (f'\n  <article class="task latest"><div class="number">作業00104 '
        '<span class="badge">銘柄差と修正検証</span></div><h2>E01の銘柄差の原因と修正検証</h2>'
        f'<p>{status}</p><a class="button" href="{FOLDER}/{REPORT}">説明と全33場の損益</a> '
        f'<a href="{FOLDER}/判断と損失の具体例.md">損失の具体時刻と判断</a> '
        f'<a href="{FOLDER}/README.md">読む順序と検証根拠</a></article>')
    assert index_new.count('<main id="work-list">') == 1
    index_new = index_new.replace('<main id="work-list">', '<main id="work-list">'+card, 1)
    changes = {}
    for path, before, after in ((root_path, root_before, root_new),
        (study_path, study_before, study_new), (index_path, index_before, index_new)):
        assert before != after
        path.write_text(after, encoding='utf-8', newline='\n')
        changes[path.relative_to(ROOT).as_posix()] = dict(
            変更前SHA256=hashlib.sha256(before.encode('utf-8')).hexdigest(),
            変更後SHA256=hashlib.sha256(path.read_bytes()).hexdigest())
    (HERE/'案内更新.json').write_text(json.dumps(dict(全合格=True,案内=changes,金融=0),
        ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('三つの案内を00104へ更新。過去の作業は保持。')


if __name__ == '__main__':
    main()
