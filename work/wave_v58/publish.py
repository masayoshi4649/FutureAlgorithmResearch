"""原因分析の資料案内と最新作業へのリンクを更新する。"""

from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FOLDER = '00055_補充監視が赤字になった原因'
REPORT = ROOT / 'アルゴリズム調査' / FOLDER


def main() -> None:
    """機能: 原因分析の成果を案内し、既存作業を保持したまま一覧へ加える。

    引数: なし。返り値: なし(None)。売買コードや過去の成績は変更しない。
    """
    assert (REPORT / '赤字の原因と理論の検証.html').exists()
    (REPORT / 'README.md').write_text('''# 補充監視が赤字になった原因

最初に見るファイルは [赤字の原因と理論の検証.html](赤字の原因と理論の検証.html) です。

## 読む順序

1. HTML：何が確認でき、何をまだ断定できないか。入口の方向性・表示回復の意味・出口12対照。
2. [入口の固定時点診断](../../work/wave_v58/entry/入口固定時点の診断.json)：元の入口後1・5・15・30分の中値変化と欠測率。
3. [出口12条件の結果](../../work/wave_v58/exit/出口対照結果.json)：元の入口候補を固定して、壁・追跡・追跡開始を変えた運用全体の差。
4. [理論の独立反証](../../work/wave_v58/review/理論の独立反証.md)：観測できる量と、未来の利益まで推論できる範囲を分離。
5. [独立監査](../../work/wave_v58/review/)：原本行、未来の診断ラベル、損益と元手法の再現を確認。

## 今回の範囲

00054の主条件3つを対象にした原因分析です。新しい入口条件の探索ではありません。
売買の評価価格は中値、費用0、TOPIXmini5枚・NK225micro10枚、追加なし、全て場内返済です。
出口の変更により保有時間が変わると、実際に採用される入口も変わります。元候補固定の比較を同一取引の純粋な出口効果とは解釈しません。
将来価格は入口の事後診断にのみ使用します。元の売買を未来情報で選び直しません。
23場は既に研究に使用した保存期間です。今回の条件を事前固定しても、真の未見検証にはなりません。
00054の結果、入力原本、E01実行プログラムは変更していません。現在APIは取得していません。
''', encoding='utf8')
    # ----------------------------------------
    # 最新案内だけを追加し、旧成果へのリンクを保持する。
    path = ROOT / 'アルゴリズム調査/index.html'
    content = path.read_text(encoding='utf8')
    if '<!--00055開始-->' not in content:
        content = content.replace('class="task latest"', 'class="task"').replace(' <span class="badge">最新</span>', '')
        start = content.index('    <p class="lead">')
        end = content.index('</p>', start) + 4
        content = content[:start] + '    <p class="lead">最新00055：補充監視が赤字だった理由を、入口後の値動き・表示回復の意味・出口12対照から分析。</p>' + content[end:]
        article = f'''<!--00055開始--><article class="task latest"><div class="number">作業00055 <span class="badge">最新</span></div><h2>補充監視が赤字になった原因</h2><p>市場原理から未来の収益性へ何を仮定したのか。元の入口後の値動き、約定を伴わない表示回復、壁とトレーリングの部品対照を検証。</p><a class="button" href="{FOLDER}/赤字の原因と理論の検証.html">赤字の原因と理論の検証 →</a><p><a href="{FOLDER}/README.md">読む順序と分析範囲</a></p></article><!--00055終了-->\n'''
        content = content.replace('<!--00054開始-->', article + '<!--00054開始-->')
        path.write_text(content, encoding='utf8')
    path = ROOT / 'アルゴリズム調査/README.md'
    content = path.read_text(encoding='utf8')
    if '<!--00055案内開始-->' not in content:
        content = content.replace('**最新は00054', '**00054')
        article = f'''\n<!--00055案内開始-->
**最新は00055の[赤字の原因と理論の検証]({FOLDER}/赤字の原因と理論の検証.html)。元の入口後の方向性、補充という代理指標の意味、壁とトレーリングの出口12対照を調べ、原理と収益仮説の違いを整理。**

[読む順序と分析範囲]({FOLDER}/README.md)。
<!--00055案内終了-->\n'''
        path.write_text(content.replace('# アルゴリズム調査の作業一覧\n', '# アルゴリズム調査の作業一覧\n' + article, 1), encoding='utf8')


if __name__ == '__main__':
    main()
