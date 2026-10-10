"""15秒最悪約定の資料を既存作業一覧へ追加する。"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT/'アルゴリズム調査'
FOLDER = '00046_E01の15秒最悪約定比較'
TITLE = 'E01の15秒最悪約定比較.html'


def main() -> None:
    """機能: 00046のレポート実在を確認し、HTMLとREADMEの先頭へ案内を置く。

    引数: なし。返り値: なし(None)。過去のレポート本文は変更しない。
    """
    assert (RESEARCH/FOLDER/TITLE).exists()
    assert (RESEARCH/FOLDER/'README.md').exists()
    assert (RESEARCH/FOLDER/'検証記録.json').exists()
    features = (RESEARCH/FOLDER/'悪化した約定の特徴.html').exists()
    feature_html = f'<a href="{FOLDER}/悪化した約定の特徴.html">悪化した約定の特徴</a> · ' if features else ''
    feature_markdown = f'\n補足：[悪化した約定の特徴]({FOLDER}/悪化した約定の特徴.html)。直前30秒の値動き・出口・時間帯・板との関係。\n' if features else ''
    index = RESEARCH/'index.html'
    text = index.read_text(encoding='utf-8')
    text = re.sub(r'<!--00046開始-->.*?<!--00046終了-->', '', text, flags=re.S)
    text = text.replace('class="task latest"', 'class="task"')
    text = text.replace('<span class="badge">最新・実装</span>', '<span class="badge">実装</span>')
    card = (f'<!--00046開始--><article class="task latest"><div class="number">作業00046 '
            f'<span class="badge">最新</span></div><h2>E01の15秒最悪約定比較</h2>'
            f'<p>全19セッション。発注判断後15秒の買い最高・売り最安を全新規・返済へ適用し、'
            f'理想約定との差を比較。判断と枚数を固定した価格感度です。</p>'
            f'<a class="button" href="{FOLDER}/{TITLE}">収支とセッション別比較を見る →</a>'
            f'<p>{feature_html}<a href="{FOLDER}/README.md">条件と読む順序</a> · '
            f'<a href="{FOLDER}/検証記録.json">独立検算</a></p></article><!--00046終了-->')
    assert '<!--00045開始-->' in text
    text = text.replace('<!--00045開始-->', card+'\n<!--00045開始-->', 1)
    index.write_text(text,encoding='utf-8')
    path = RESEARCH/'README.md'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<!--00046案内開始-->.*?<!--00046案内終了-->\s*', '', text, flags=re.S)
    text = text.replace('**最新は00045の', '**実行用プログラムは00045の')
    text = text.replace('`00045_E01リアルタイム仮想トレード`（最新）', '`00045_E01リアルタイム仮想トレード`')
    note = (f'<!--00046案内開始-->\n**最新は00046の[E01の15秒最悪約定比較]({FOLDER}/{TITLE})。'
            f'全19場で理想約定と15秒窓の最悪価格を比較。セッション別・週別の差を掲載。**\n'
            + feature_markdown + '<!--00046案内終了-->\n\n')
    heading = '# アルゴリズム調査の作業一覧\n'
    assert text.startswith(heading)
    text = text.replace(heading,heading+'\n'+note,1)
    text = re.sub(r'^\| `00046_E01の15秒最悪約定比較`.*\n', '', text, flags=re.M)
    marker = '| --- | --- | --- | --- |\n'
    row = (f'| `{FOLDER}`（最新） | E01全19場・判断後15秒の最悪約定 | '
           f'[比較レポート]({FOLDER}/{TITLE}) | [条件と読む順序]({FOLDER}/README.md)・'
           f'[検算]({FOLDER}/検証記録.json) |\n')
    assert marker in text
    path.write_text(text.replace(marker,marker+row,1),encoding='utf-8')
    print('00046の案内と既存00045の実行案内を更新しました。')


if __name__ == '__main__':
    main()
