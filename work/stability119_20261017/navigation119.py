"""正式公開後だけ、作業一覧と共通知見の入口を00119へ更新する。"""

from pathlib import Path
import re


BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
NAME = '00119_戦略の自動選択と場内黒字の再探索'
REPORT = '結論と全セッション損益.html'


def insert(path: Path, prefix: str) -> None:
    """
    機能: Markdownの最初の見出しに続いて最新の案内を挿入する。
    引数: path(Path)は既存資料、prefix(str)はリンク先まで含む日本語段落。
    返り値: None。同じ案内の二重追加を拒否する。
    """
    text = path.read_text(encoding='utf-8')
    assert '<!--00119案内-->' not in text
    head, rest = text.split('\n', 1)
    path.write_text(head + '\n\n<!--00119案内-->\n' + prefix + '\n<!--00119案内終了-->\n' + rest,
                    encoding='utf-8')


def main() -> None:
    """
    機能: 全場レポートと損失診断が存在した後、最新リンクを同期する。
    引数: なし。
    返り値: None。過去の成果・実装・金融会計を変更しない。
    """
    public = ROOT / 'アルゴリズム調査' / NAME
    assert (public / REPORT).is_file() and (public / '損失の原因と改善の結果.md').is_file()
    sentence = '暫定候補は少額E01の二口座並行運転。全40場の合算は26黒字・1赤字・13無取引で、毎場黒字は未達。自動選択、張り方、順逆、二脚相対価値の改善結果と具体的な損失原因も保存しています。'
    insert(ROOT / 'README.md', f'最新は[00119：場内安定黒字の再探索](アルゴリズム調査/{NAME}/{REPORT})。{sentence}')
    insert(ROOT / 'アルゴリズム調査/README.md', f'最新は[00119：場内安定黒字の再探索]({NAME}/{REPORT})。{sentence}')
    insert(ROOT / 'アルゴリズム調査/共通/知見台帳/README.md',
           f'最新は[00119：戦略の自動選択と場内黒字の再探索](../../{NAME}/README.md)。過去成績からの選択、復帰確認、平均建値、予定停止と実損失、同時曝露、少額E01、初期気配差の予算を法則単位で追記。場末合算は共同リスクや分散効果の証明と区別しています。')
    # ----------------------------------------
    # 過去の案内を消さず、「最新」だけは現在の作業へ揃える。
    for path in (ROOT / 'README.md', ROOT / 'アルゴリズム調査/README.md',
                 ROOT / 'アルゴリズム調査/共通/知見台帳/README.md'):
        text = path.read_text(encoding='utf-8')
        text = text.replace('最新は[00118', '前段は[00118').replace('最新：[00118', '前段：[00118')
        text = text.replace('最新の金融検証は[00116', '以前の金融検証は[00116').replace('最新の金融：[00116', '以前の金融：[00116')
        path.write_text(text, encoding='utf-8')
    path = ROOT / 'アルゴリズム調査/index.html'
    text = path.read_text(encoding='utf-8')
    assert '作業00119・' not in text
    article = f'''\n  <article class="task latest"><div class="number">作業00119・場内黒字の再探索</div><h2>利益源・執行・張り方・二脚取引を段階別に検証</h2><p>{sentence}</p><a class="button" href="{NAME}/{REPORT}">結論と全40場損益</a> <a href="{NAME}/損失の原因と改善の結果.md">どの時刻に何で負けたか</a> <a href="{NAME}/README.md">読む順序</a></article>'''
    text = text.replace('<article class="task latest"><div class="number">作業00118', '<article class="task"><div class="number">作業00118', 1)
    text = text.replace('<main id="work-list">', '<main id="work-list">' + article, 1)
    text = re.sub(r'<p class="lead">最新00118.*?</p>', '<p class="lead">最新00119では全40場を検証。単独型と二脚合計口座を分け、合計利益だけでなく各場の安定性と実損失を確認しています。</p>', text, count=1)
    text = re.sub(r'<footer>.*?</footer>', '<footer>最新00119は全40場。手数料・気配差・全残玉を含む保存検証で、実注文・現在API取得はありません。修正後の再検証は既知データ内の開発として扱います。</footer>', text, count=1, flags=re.S)
    path.write_text(text, encoding='utf-8')
    print('正式公開資料への四つの入口を更新。')


if __name__ == '__main__':
    main()
