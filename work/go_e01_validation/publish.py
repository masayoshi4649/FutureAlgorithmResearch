"""Go版E01の案内と検証資料へのリンクを調査一覧へ追加する。"""

from pathlib import Path
import re

root = Path(__file__).resolve().parents[2]
research = root / "アルゴリズム調査"
folder = "00047_E01のGo注文プログラム"

# ----------------------------------------
# 過去作業の本文を保ったまま、最新案内だけを更新する。
index = research / "index.html"
text = index.read_text(encoding="utf-8")
text = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新00047：E01をGoへ移植。1銘柄・片方向上限をTOML設定し、実注文／dryrunとセッション別CSVに対応。</p>', text, count=1)
text = text.replace('<article class="task latest">', '<article class="task">')
text = text.replace('<span class="badge">最新</span>', '<span class="badge">比較</span>')
block = f'''<!--00047開始--><article class="task latest"><div class="number">作業00047 <span class="badge">最新</span></div><h2>E01のGo注文プログラム</h2><p>App/E01に実装。5商品から1銘柄を選択、片方向上限を設定。controllerの実データによるdryrun・CSV保存を確認。既定は実注文なし。</p><a class="button" href="../App/E01/README.md">起動方法と設定 →</a><p><a href="../App/E01/docs/仕様.md">仕様</a> · <a href="../App/E01/docs/検証結果.md">一致検証・実API試運転</a> · <a href="{folder}/README.md">資料案内</a></p></article><!--00047終了-->'''
text = re.sub(r'<!--00047開始-->.*?<!--00047終了-->', '', text, flags=re.S)
text = text.replace('<!--00046開始-->', block + '\n<!--00046開始-->', 1)
index.write_text(text, encoding="utf-8")

# ----------------------------------------
# Markdown一覧の冒頭と表に同じ作業を登録する。
readme = research / "README.md"
text = readme.read_text(encoding="utf-8")
text = text.replace('**最新は00046の', '**00046の')
text = text.replace('**実行用プログラムは00045の', '**従来のPython仮想実行は00045の')
note = f'''<!--00047案内開始-->
**最新は00047の[E01 Go注文プログラム](../App/E01/README.md)。`App/E01`に実装。設定はconf/*.toml、5商品・片方向上限、実注文／dryrun、セッション別CSVに対応。**

[仕様](../App/E01/docs/仕様.md) · [検証結果](../App/E01/docs/検証結果.md) · [資料案内]({folder}/README.md)。
<!--00047案内終了-->

'''
text = re.sub(r'<!--00047案内開始-->.*?<!--00047案内終了-->\s*', '', text, flags=re.S)
first = text.find('\n') + 1
text = text[:first] + '\n' + note + text[first:].lstrip('\n')
row = f'| `{folder}` | Go版E01・1銘柄上限・実注文／dryrun・CSV | [起動手順](../App/E01/README.md) | [仕様](../App/E01/docs/仕様.md)・[検証結果](../App/E01/docs/検証結果.md) |\n'
if not any(line.startswith(f'| `{folder}`') for line in text.splitlines()):
    text = text.replace('| `00046_', row + '| `00046_', 1)
readme.write_text(text, encoding="utf-8")
