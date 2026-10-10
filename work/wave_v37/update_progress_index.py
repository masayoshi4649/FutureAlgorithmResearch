"""数量調整の確定比較と、全条件の損益への入口を示す。"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
FOLDER = '00032_悪化時の部分減量と回復後の数量復元'
PREVIOUS = '00031_出来高通過と気配維持からの方向判定'


def main() -> None:
    """機能: 既存の作業リンクを保ち、今回の確定結果を一覧へ加える。

    引数: なし。返り値: なし (None)。完了した範囲だけを表示する。
    """
    directory = ROOT / 'アルゴリズム調査'
    path = directory / 'index.html'
    source = path.read_text(encoding='utf-8')
    source = re.sub(r'<!--00032開始-->.*?<!--00032終了-->', '', source, flags=re.S)
    source = source.replace('task latest', 'task')
    source = re.sub(r' <span class="badge">最新[^<]*</span>', '', source)
    source = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新の確定結果は00032：部分減量と数量復元の427条件を検算完了。改善8条件を次の反証へ残しました。</p>', source, count=1)
    block = f'''<!--00032開始--><article class="task latest"><div class="number">作業00032 <span class="badge">最新・検算完了</span></div><h2>悪化時の部分減量と回復後の数量復元</h2><p>主案はTOPIX +546,500円／NK +264,900円。元の管理より収支は改善しましたが、回復判断の優位は銘柄で異なります。全体の解は未確定です。</p><a class="button" href="{FOLDER}/悪化時の部分減量と回復後の数量復元.html">結果の比較 →</a><a class="button" href="{FOLDER}/全条件損益.html">週・セッション損益 →</a><a class="button" href="{FOLDER}/５分足と売買.html">５分足と売買 →</a><p><a href="{FOLDER}/README.md">資料案内・再現手順</a></p></article><!--00032終了-->'''
    path.write_text(source.replace('</header>', '</header>' + block, 1), encoding='utf-8')
    path = directory / 'README.md'
    source = path.read_text(encoding='utf-8')
    source = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00032の[部分減量と数量復元]({FOLDER}/悪化時の部分減量と回復後の数量復元.html)（427条件の独立検算完了）。**', source, count=1)
    source = re.sub(r'^\| `00032_.*\n', '', source, flags=re.M).replace('`（最新）', '`')
    anchor = '| --- | --- | --- | --- |'
    row = f'\n| `{FOLDER}`（最新） | 部分減量・復元427条件、改善8条件を次の反証へ | [結果の比較]({FOLDER}/悪化時の部分減量と回復後の数量復元.html) | [全損益]({FOLDER}/全条件損益.html)・[５分足]({FOLDER}/５分足と売買.html)・[資料]({FOLDER}/README.md) |'
    path.write_text(source.replace(anchor, anchor + row, 1), encoding='utf-8')
    print('00032の確定比較・全損益・売買図を一覧へ反映。')


if __name__ == '__main__':
    main()
