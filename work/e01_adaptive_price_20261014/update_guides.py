"""完成した二段の比較を案内へ接続し、過去の調査への導線を保つ。"""

import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FOLDER = '00106_支持の強さで注文価格を切り替えるE01'
TITLE = '支持の強さで注文価格を切り替えるE01と全セッション損益'
OLD_FOLDER = '00105_公開価格を追わないE01の改善'
OLD_TITLE = '公開価格を追わないE01と銘柄別固定設定の全セッション損益'


def replace_section(text: str, begin: str, end: str, replacement: str) -> str:
    """
    機能: 案内の指定区間を差し替え、残りの既存作業を保存する。
    引数: text/begin/end/replacement(str) は本文・境界・新本文。
    返り値: str は案内。境界が無い場合は停止する。
    """
    start = text.index(begin)
    stop = text.index(end, start)
    return text[:start]+replacement+text[stop:]


def main() -> None:
    """
    機能: 根README・調査README・一覧へ00106と00105を接続する。
    引数: なし。公開完成資料と根が固定する案内計画だけを読む。
    返り値: None。金融・入力・APIは扱わず、未完成では更新しない。
    """
    plan_path = HERE/'公開案内計画.json'
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    assert plan['完成確認'] and plan['folder'] == FOLDER and plan['title'] == TITLE
    status = plan['status']
    public = ROOT/'アルゴリズム調査'/FOLDER
    assert (public/(TITLE+'.html')).is_file()
    assert (ROOT/'アルゴリズム調査'/OLD_FOLDER/(OLD_TITLE+'.html')).is_file()
    root_path = ROOT/'README.md'
    before = root_path.read_text(encoding='utf-8')
    root = replace_section(before, '現在の調査は', '## フォルダとデータ',
        f'現在の調査は **[00106：支持の強さで注文価格を切り替えるE01](アルゴリズム調査/{FOLDER}/README.md)** です。'
        f'{status}\n\n最初に [手法と全33場の損益](アルゴリズム調査/{FOLDER}/{TITLE}.html) を開いてください。'
        '[調査方針](アルゴリズム調査/調査方針.md)と'
        '[共通知見](アルゴリズム調査/共通/知見台帳/README.md)へ条件・原因・限界を記録しています。\n\n'
        f'前段の [00105：一律の公開価格制限](アルゴリズム調査/{OLD_FOLDER}/README.md) は保存。'
        '18対照の後、支持強度による切替8対照を別に固定・登録・一回再生し、保存済み結果と比較しました。\n\n')
    study_path = ROOT/'アルゴリズム調査/README.md'
    before_study = study_path.read_text(encoding='utf-8')
    study = replace_section(before_study, '**[00104：', '**[共通知見台帳]',
        f'**[00106：支持の強さで注文価格を切り替えるE01]({FOLDER}/README.md)**。{status}\n\n'
        f'[手法と全33場損益]({FOLDER}/{TITLE}.html) · [読む順序と根拠]({FOLDER}/README.md)。\n\n'
        f'前段 **[00105：公開価格を追わないE01の改善]({OLD_FOLDER}/README.md)**：'
        '一律価格制限18対照。見送った勝ちが後の負けへ置き換わる実例と5寄与を記録。'
        f'[全24比較と全場]({OLD_FOLDER}/{OLD_TITLE}.html)。\n\n'
        '比較元の [00104：E01の銘柄差の原因と修正検証]'
        '(00104_E01の銘柄差の原因と修正検証/README.md) は改変していません。\n\n')

    # ----------------------------------------
    # 新しい二作業のカードだけを追加し、旧カードを保持する。
    index_path = ROOT/'アルゴリズム調査/index.html'
    index = index_path.read_text(encoding='utf-8')
    assert '作業00105' not in index and '作業00106' not in index
    index = index.replace('<article class="task latest"><div class="number">作業00104',
        '<article class="task"><div class="number">作業00104', 1)
    cards = (f'\n  <article class="task latest"><div class="number">作業00106</div>'
        f'<h2>支持の強さで注文価格を切り替えるE01</h2><p>{html.escape(status)}</p>'
        f'<a class="button" href="{FOLDER}/{TITLE}.html">手法と全33場損益</a> '
        f'<a href="{FOLDER}/README.md">読む順序と根拠</a></article>'
        f'\n  <article class="task"><div class="number">作業00105</div>'
        '<h2>公開価格を追わないE01の改善</h2><p>一律の価格制限18対照を検証。'
        '勝ちを見送った後の再参加によって損失が増える経路を分解しました。</p>'
        f'<a class="button" href="{OLD_FOLDER}/{OLD_TITLE}.html">24比較と全場損益</a> '
        f'<a href="{OLD_FOLDER}/損失の原因と次の改善.md">具体的な損失と対策</a></article>')
    assert '<main id="work-list">' in index
    index = index.replace('<main id="work-list">', '<main id="work-list">'+cards, 1)
    index = index.replace('最新の調査00104：E01の銘柄差を調べ、入口と出口の16修正を比較。',
        '最新の調査00106：公開時の支持で注文価格を切り替え、両商品の全場を比較。', 1)
    for path, content in ((root_path, root), (study_path, study), (index_path, index)):
        path.write_text(content, encoding='utf-8', newline='\n')
    print('三つの案内を00106へ接続。00105と過去作業は保存。')


if __name__ == '__main__':
    main()
