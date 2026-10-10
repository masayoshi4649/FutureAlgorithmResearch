"""今回の資料案内と既存の調査一覧を更新する。過去の作業フォルダは編集しない。"""

from pathlib import Path
import re

from build_report import FOLDER, OUT, ROOT, TITLE


def main() -> None:
    """機能: 読む順序・再現方法を保存し、00057を最新の入口へ追加する。

    引数: なし。返り値: なし(None)。既存の作業本文・結果を変更しない。
    """
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'README.md').write_text(f'''# 中期売買と週内グリッドの手数料込み検証

最初に見るファイルは [{TITLE}]({TITLE}.html) です。

読む順序：

1. 上記HTMLの冒頭と比較表。代表10条件の考え方・結果・各セッションの利益、損失、手数料、含み増減、枚数を確認します。
2. [全160条件](全160条件.html)。代表以外の30/45/60分、平均の期間、管理幅、段数、場内/週内持越しを比較します。
3. [全セッションCSV](全160条件のセッション損益.csv) と [週・全体CSV](全160条件の週と全体損益.csv)。約定モデルごとに全条件を省略せず載せています。
4. [固定仕様](../../work/wave_v60/調査仕様.json)、[独立監査](../../work/wave_v60/review/README.md)、[現在確認の取得記録](../../work/wave_v60/live/取得記録.json)。

## 範囲と結論の読み方

保存済み25場（2026/9/21昼〜10/7昼）は全て既知データです。中期120条件とグリッド40条件を固定して再生しました。日経とTOPIXの円収支を足し合わせて順位を作っていません。

手数料は提示された立会手数料を使用します。TOPIX miniは片道1枚41.8円、NK225 microは11円。注文枚数を掛けて1円未満切捨て、新規と返済の両方へ課します。J-NETは仮定しません。中期は初回5枚/10枚、グリッドは方向別上限10枚/20枚です。証拠金・価格への自分の注文の影響は算定していません。

主評価はラージ板の買ask・売bidで、小型商品実気配の代用です。中値参考と待機指値仮定も独立再生しています。待機指値は通過を要求しますが、実際の待ち順や全数量の約定を証明するものではありません。

グリッドの残玉と含み損は消していません。各場の純収支＝実現利益−実現損失−その場の注文手数料＋含み増減。週末は金曜ナイト内で全返済し、週末を越えません。10/7昼は週途中の資料終端なので「調査終了清算」と分けました。現在ナイト確認では、その清算を入れずに週初から連結し、未決済は時価評価します。

## 実装と再現

売買コードは `work/wave_v60/medium` と `work/wave_v60/grid`、一回取得と部分再生は `work/wave_v60/live` にあります。手法の機械的な詳細は固定仕様と各コードを参照してください。原本 `book`、`candle_1min`、`candle_5min` は変更していません。

プロジェクトルートから、既存の固定入力と同じPython環境（NumPy・Numba）で実行します。

```text
python work/wave_v60/medium/run.py --run
python work/wave_v60/grid/backtest.py --run
python work/wave_v60/analyze.py
python work/wave_v60/build_report.py
python work/wave_v60/publish.py
```

コードと入力のSHA照合が失敗した場合、固定記録を上書きして通してはいけません。初回の時間切れ停止と訂正理由は `medium/v1` と `調査仕様_初版.json` に保存しています。利益を見た後の条件変更ではありません。

現在データの取得は1回だけです。取得プログラムは開始記録があれば再取得を拒否します。再現時は保存済み原本を使い、APIの再取得は行いません。現在結果は固定した赤字参考条件の確認であり、採用推奨ではありません。

## 主な根拠

在庫保有と注文位置の関係は [Avellaneda–Stoikov](https://people.orie.cornell.edu/sfs33/LimitOrderBook.pdf) と [Guéantほか](https://arxiv.org/abs/1105.3115) を参照しました。論文のマーケットメイクをそのまま再現した検証ではありません。

商品の単位と取引終了時刻は [JPX ミニTOPIX](https://www.jpx.co.jp/derivatives/products/domestic/mini-topix-futures/index.html)、[日経225マイクロ](https://www.jpx.co.jp/derivatives/products/domestic/225micro-futures/01.html)、[取引時間](https://www.jpx.co.jp/derivatives/rules/trading-hours/) を参照。1pt当たり1,000円/10円、実商品呼値0.25pt/5ptを区別しました。
''',encoding='utf-8')
    # ----------------------------------------
    # 過去の案内を保ち、今回の入口だけ先頭に追加する。
    readme=ROOT/'アルゴリズム調査'/'README.md'
    text=readme.read_text(encoding='utf-8')
    text=re.sub(r'<!--00057案内開始-->.*?<!--00057案内終了-->\s*','',text,flags=re.S)
    text=text.replace('**最新は00056の','**00056の')
    notice=f'''<!--00057案内開始-->
**最新は00057の[{TITLE}]({FOLDER}/{TITLE}.html)。中期120条件・週内グリッド40条件を、手数料と残玉を含めて検証。各場・各週の金額と枚数、両建ての効果、現在ナイトの一回確認を掲載。**

[全160条件]({FOLDER}/全160条件.html) · [資料案内]({FOLDER}/README.md)。
<!--00057案内終了-->

'''
    heading='# アルゴリズム調査の作業一覧\n\n'
    assert text.startswith(heading)
    readme.write_text(heading+notice+text[len(heading):],encoding='utf-8')
    index=ROOT/'アルゴリズム調査'/'index.html'
    text=index.read_text(encoding='utf-8')
    text=re.sub(r'<!--00057開始-->.*?<!--00057終了-->','',text,flags=re.S)
    text=text.replace('class="task latest"','class="task"').replace('<span class="badge">最新</span>','')
    text=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00057：30〜60分の中期売買と、週末を越えないグリッド・両建てを手数料込みで検証。</p>',text,count=1,flags=re.S)
    article=f'''<!--00057開始--><article class="task latest"><div class="number">作業00057 <span class="badge">最新</span></div><h2>中期売買と週内グリッドの手数料込み検証</h2><p>中期120条件とグリッド40条件。残玉の含み損、方向別上限、手数料、指値の約定仮定を含め、全25場と現在ナイトを確認。</p><a class="button" href="{FOLDER}/{TITLE}.html">説明とセッション損益 →</a><p><a href="{FOLDER}/全160条件.html">全160条件</a> ／ <a href="{FOLDER}/README.md">資料案内</a></p></article><!--00057終了-->'''
    assert '<!--00056開始-->' in text
    text=text.replace('<!--00056開始-->',article+'\n<!--00056開始-->',1)
    index.write_text(text,encoding='utf-8')
    print('00057の資料案内と調査一覧を更新しました。')


if __name__=='__main__':
    main()
