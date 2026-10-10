"""単独レポートの資料案内と新しい作業へのリンクを公開する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

import report


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def documents() -> None:
    """機能: 最初に見るHTMLと再現・監査の読む順序を今回フォルダに書く。

    引数: なし。返り値: なし(None)。
    """
    text = '''# 作業00069：T1L1_R01の全セッションと金額評価

**最初に見るファイル：[T1L1_R01の全セッション結果](T1L1_R01の全セッション結果.html)。**

読む順序：

1. 主HTML：手法の短い説明、TOPIXミニ10枚／NK225マイクロ20枚の合計、全29セッション、週、五分足と売買履歴。
2. [銘柄別の全セッション会計](銘柄別の全セッション会計.json)：同じHTMLに埋め込んだ金額・回数・枚数・売買図の固定データ。
3. [金額会計の独立監査](../../work/wave_v72/audit/R01金額評価監査の読む順.md)：旧28場、仕様を変えない追加デイ、台帳からの再計算。
4. [追加再生](../../work/wave_v72/replay/README.md)・[公開会計](../../work/wave_v72/公開会計.json)・[表示検査](../../work/wave_v72/review/HTML表示の独立検査.json)。

## 金額指標

- 総利益：手数料後に黒字だった取引の金額合計。
- 総損失：手数料後に赤字だった取引の損失絶対額合計。
- 金額損失割合：総損失÷（総利益＋総損失）。50%未満なら合計黒字。無取引は未定義。
- 利益／損失比：総利益÷総損失。1より大きければ合計黒字。
- 収支：総利益−総損失。手数料は既に含むため、再度引かない。

比率は銘柄別・期間合計の金額から計算します。異なる銘柄の金額合算、各場の率の単純平均はしません。前回の損失発生率は「赤字取引数÷全取引数」であり、枚数比率ではありませんでした。回数と枚数はHTMLの補助欄へ残しています。

## 範囲と方式

保存データは2026-09-21デイ〜2026-10-09デイの29場。従来の28場を再利用し、10月9日デイだけ仕様変更なしで追加再生しました。今回、別の入口・出口の探索や最適化は行っていません。

T1L1_R01のR01は段階利益固定の管理IDです。旧R01PのEMA入口とは別です。ATR、相手銘柄との一致、増し玉、両建ては使いません。各銘柄を独立に判定します。

判断はラージ板、中値8呼値進行→4呼値反転、両気配反転確認。予約価格基準の16呼値損切り、4呼値刻み利益保護、4呼値順行後の8呼値通常トレール、60分期限、場内全返済を維持します。初回約定から60分30秒の共通新規時計も維持します。

成立の次の有効原本行で、買いask／売りbidへ約定する仮定。TOPIX miniは1pt1000円、NK microは1円10円、片道手数料は各41.8円／11円。手数料は注文合計の1円未満を切り捨てます。小型商品の実際の板・約定待ちは再現していません。利益保護線の更新は次観測から判定し、線と同値でも返済条件が成立します。保護線は実約定価格ではなく親予約価格が基準で、約定時の利益は保証しません。

各場内で全返済し、損失玉を後日へ残しません。原本book/candleは読み取り専用。現在API取得0、実注文0。既知の多数条件から選んだ方式なので、未知期間の安定性とは区別してください。

## 再現

保存済み結果からレポートを再生成します。プロジェクトルートから実行し、既存の凍結結果と追加保存入力を参照します。

```text
python -X utf8 work/wave_v72/report.py
python -X utf8 work/wave_v72/review/verify_report.py
python -X utf8 work/wave_v72/publish.py
```

追加再生を行った[run.py](../../work/wave_v72/replay/run.py)と[display.py](../../work/wave_v72/replay/display.py)は、完了済みファイルを上書きしないため、保存済み状態では再実行を停止します。

実装：[入口](../../work/wave_v69/signals/core.py)・[共通新規時計](../../work/wave_v70/inputs/schedule.py)・[途中と出口](../../work/wave_v70/engine.py)・[従来設定](../../work/wave_v70/results/T1L1_R01.json)・[今回のHTML生成](../../work/wave_v72/report.py)。
'''
    (report.OUT/'README.md').write_text(text, encoding='utf8')


def links(paths: list[Path]) -> int:
    """機能: HTML・Markdownに記載したローカルリンクの存在を確認する。

    引数: paths(list[Path])。返り値: 照合リンク数(int)。
    """
    count = 0
    for path in paths:
        source = path.read_text(encoding='utf8')
        hrefs = ([t['href'] for t in BeautifulSoup(source, 'html.parser').select('a[href]')]
                 if path.suffix == '.html' else re.findall(r'\]\(([^)]+)\)', source))
        for href in hrefs:
            if href.startswith(('http:', 'https:', '#')):
                continue
            target = path.parent/unquote(href.split('#', 1)[0].split('?', 1)[0])
            assert target.exists(), (path, href)
            count += 1
    return count


def main() -> None:
    """機能: 独立監査と表示検査済みの今回成果を最新作業として登録する。

    引数: なし。返り値: なし(None)。過去作業フォルダは変更しない。
    """
    proof = json.loads((HERE/'review/HTML表示の独立検査.json').read_text(encoding='utf8'))
    audit = json.loads((HERE/'audit/R01全29場統合結果の金額独立照合.json').read_text(encoding='utf8'))
    preserved = json.loads((HERE/'replay/再生後の保全照合.json').read_text(encoding='utf8'))
    assert audit['合格'] and audit['独立会計口座数'] == 58 and preserved['全合格']
    assert proof['全合格'] and proof['目視確認']
    assert hashlib.sha256((report.OUT/report.MAIN).read_bytes()).hexdigest() == proof['HTML_SHA256']
    documents()
    folder = report.OUT.name
    index = ROOT/'アルゴリズム調査/index.html'
    readme = ROOT/'アルゴリズム調査/README.md'
    source = index.read_text(encoding='utf8').replace('class="task latest"', 'class="task"').replace(' <span class="badge">最新</span>', '')
    source = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新00069：T1L1_R01だけの全29セッション。銘柄別の利益・損失・収支と金額損失割合、五分足の売買図。</p>', source, count=1, flags=re.S)
    block = f'''<!--00069開始--><article class="task latest"><div class="number">作業00069 <span class="badge">最新</span></div><h2>T1L1_R01の全セッションと金額評価</h2><p>TOPIXミニ10枚／NK225マイクロ20枚を銘柄別に集計。固定した同手法で全29場、利益・損失・収支、金額損失割合、週集計、五分足と新規・返済履歴。</p><a class="button" href="{folder}/{report.MAIN}">全セッション結果を開く →</a><p><a href="{folder}/README.md">資料案内</a> · <a href="{folder}/銘柄別の全セッション会計.json">全会計データ</a></p></article><!--00069終了-->'''
    if '<!--00069開始-->' in source:
        source = re.sub(r'<!--00069開始-->.*?<!--00069終了-->', block, source, flags=re.S)
    else:
        assert '<!--00068開始-->' in source
        source = source.replace('<!--00068開始-->', block+'\n<!--00068開始-->', 1)
    # ----------------------------------------
    # 案内の最新表示を一つにし、既存作業のリンクは維持する。
    source_md = readme.read_text(encoding='utf8').replace('**最新は00068', '**00068')
    guide = f'''<!--00069案内開始-->
**最新は00069の[T1L1_R01の全セッション結果]({folder}/{report.MAIN})。TOPIXミニ10枚／NKマイクロ20枚、全29場、銘柄別の金額損失割合・利益／損失比・損益、週集計と五分足売買図。**

[資料案内]({folder}/README.md) · [全会計データ]({folder}/銘柄別の全セッション会計.json)。
<!--00069案内終了-->
'''
    if '<!--00069案内開始-->' in source_md:
        source_md = re.sub(r'<!--00069案内開始-->.*?<!--00069案内終了-->\n?', guide, source_md, flags=re.S)
    else:
        assert '<!--00068案内開始-->' in source_md
        source_md = source_md.replace('<!--00068案内開始-->', guide+'\n<!--00068案内開始-->', 1)
    index.write_text(source, encoding='utf8')
    readme.write_text(source_md, encoding='utf8')
    count = links([index, readme, report.OUT/report.MAIN, report.OUT/'README.md'])
    (HERE/'公開リンク照合.json').write_text(json.dumps(dict(合格=True, 照合数=count, 最新='00069'), ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(dict(合格=True, 照合リンク数=count), ensure_ascii=False))


if __name__ == '__main__':
    main()
