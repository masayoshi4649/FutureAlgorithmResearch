"""研究151の資料案内を既存の研究入口へ追加する。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDER = "00151_損切りなし両建てと利益玉トレーリング"
DESCRIPTION = "損切りなし18条件を25夜で比較。P05は早い利益回収で改善、N03は22勝でも大きな残玉損失。再参加回転と両建ての効果を分離。"


def main():
    """研究README・共通知見・HTML入口へ既存内容を保持して追記する。

    引数: なし。返り値: None。同じ研究案内があるファイルは変更しない。
    """
    targets = [(ROOT / "README.md", "アルゴリズム調査/"),
               (ROOT / "アルゴリズム調査/README.md", ""),
               (ROOT / "アルゴリズム調査/共通/知見台帳/README.md", "../../")]
    for path, prefix in targets:
        content = path.read_text(encoding="utf-8")
        if FOLDER not in content:
            content = f"最新：[{FOLDER}]({prefix}{FOLDER}/README.md)。{DESCRIPTION}\n\n" + content
            path.write_text(content, encoding="utf-8")
    # ----------------------------------------
    path = ROOT / "アルゴリズム調査/index.html"
    content = path.read_text(encoding="utf-8")
    if "<!--00151開始-->" not in content:
        block = f'''<!--00151開始-->
<!--
00151の研究入口です。比較・損益は手法別の正式Excelテーブル、説明と診断はMarkdownに分離します。
-->
<article class="task latest"><div class="number">作業00151・損切りなし18条件と2対照</div><h2>損切りなし両建てと利益玉トレーリング</h2><p>{DESCRIPTION}</p><a class="button" href="{FOLDER}/損切りなし両建ての全夜間損益.xlsx">手法別の全25夜損益</a> <a href="{FOLDER}/README.md">結論と具体的な残玉</a></article>
<!--00151終了-->

'''
        assert "<!--00150開始-->" in content
        content = content.replace("<!--00150開始-->", block + "<!--00150開始-->", 1)
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
