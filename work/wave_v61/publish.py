"""00058の読む順序と再現資料を保存し、調査一覧へ新しい入口を追加する。"""

import re

from build_report import FOLDER, OUT, ROOT, TITLE


def main() -> None:
    """機能: 今回の資料案内を作成し、既存一覧の最新表示を更新する。

    引数: なし。返り値: なし(None)。過去の作業フォルダは編集しない。
    """
    OUT.mkdir(parents=True,exist_ok=True)
    text=f'''# 場内完結の時間軸と積極度の再検証

最初に [{TITLE}]({TITLE}.html) を開いてください。

読む順序：

1. 上記HTMLの結論と上位参考条件。
2. 同じHTMLの戦略別の章。「6時間軸×3積極度」「週合計」「25セッション」の表を開けます。
3. [全450条件](全450条件.html)、[各セッションCSV](全450条件のセッション損益.csv)、[各週・全体CSV](全450条件の週と全体損益.csv)。幅も変えた全条件を省略していません。
4. [前回から変更する根拠](../../work/wave_v61/review/前回から変更する根拠.md)、[共通固定仕様](../../work/wave_v61/調査仕様.json)、[比較と選定](../../work/wave_v61/比較と選定.json)、[独立監査](../../work/wave_v61/review/README.md)。

## 比較の意味

対象は保存済み25場（2026/9/21昼〜10/7昼）。全て既知資料です。方向性270条件＝入口5×保有上限6×幅3×積極度3、在庫管理180条件＝方式5×保有上限6×幅2×積極度3。主条件10個を損益計算前に固定し、結果から選んだ参考条件とは分けています。

全て場内返済です。保有の予定上限は5/15/30/60/120/240分。途中の損切りは早く働き、原本の時計に空白があれば期限観測も約定も遅れます。次の実観測行で判断・約定し、期限ぴったりの架空価格は生成しません。保存時計は受信時刻ではない点も含め、予定と実保有を区別します。

TOPIX miniは片方向同時10枚、NK225 microは20枚が上限です。慎重・通常設定では実稼働上限をさらに小さくしています。延べ決済枚数が多いことと、保有上限は別です。

手数料はTOPIX mini41.8円/枚、NK micro11円/枚、税込片道の立会手数料。注文合計で1円未満切り捨て、新規と返済の両方へ計上。全玉返済のまとめ方による端数差も保存します。

主評価はラージの売買気配を小型商品の代理に使用。中値は独立再生した参考。在庫管理では待機指値をラージ1呼値以上気配が通過した場合だけ、その指値で全約定すると仮定した比較もあります。小型商品の実板、待ち順・実約定量、証拠金、市場インパクトは再現していません。

各場の利益・損失は費用前、純収支はその差から全注文手数料を控除。決済枚数の勝敗は往復手数料を配分して判定します。最大資産下落は途中の全含み損益と発生手数料を含みます。両建ての利益玉だけを集計することはありません。

## 実装と再生成

実装は `work/wave_v61/directional` と `work/wave_v61/inventory`。軽量な結果は各 `集計結果.json`、注文と返済原簿は各 `ledgers` 又は `ledger` のpklへ保存し、集計JSONに対応先とSHAがあります。

元入力は前回の `work/wave_v60/inputs.pkl` と `quotes.pkl`。原本 `book`、`candle_1min`、`candle_5min` と前回の結果は変更していません。新しいデータを追加するときは新しい作業番号へ条件と入力を固定し、旧結果を残してください。

保存済み結果から表示を再生成する場合、プロジェクトルートで次を実行します。APIアクセスは発生しません。

```text
python -X utf8 work/wave_v61/analyze.py
python -X utf8 work/wave_v61/current_report.py
python -X utf8 work/wave_v61/build_report.py
python -X utf8 work/wave_v61/publish.py
```

新しい売買の計算は各枝の `run.py` 又は `backtest.py` にあります。固定SHAと開始記録で上書きを防ぎます。再計算するために固定記録を消したり、成績に合わせて書き換えてはいけません。

## 現在確認

[取得前の候補固定](../../work/wave_v61/live/候補固定.json)、[一回取得記録](../../work/wave_v61/live/取得記録.json)、[既知前半と追加区間](../../work/wave_v61/live/既知前半と追加区間.json) を分けて保存します。

同じナイトの前半は前回既に参照済みです。そこを未知成績と呼ばず、今回初めて取得する追加行の資産変化を別表示します。原本前半が一致しなければ連続検証を停止し、再取得しません。現在の未決済玉は強制清算せず、買玉bid・売玉askで時価評価します。実注文は行いません。

今回の取得は10/8 01:17:58 JSTまでの10/7ナイトです。現在確認は[途中会計CSV](現在確認の途中会計.csv)へ保存しました。場が終わっていないため、最終セッション収支とは区別しています。

## 理論資料

[Fodra–Labadieの在庫制約と方向判断](https://arxiv.org/abs/1206.4810) を、在庫を偏らせない注文と期限末の整理の参考にしました。論文の完全再現でも、日本先物の利益を保証する資料でもありません。
'''
    (OUT/'README.md').write_text(text,encoding='utf-8')
    # ----------------------------------------
    # 過去のリンクを残し、今回の入口だけを先頭へ加える。
    path=ROOT/'アルゴリズム調査'/'README.md'
    text=path.read_text(encoding='utf-8')
    text=re.sub(r'<!--00058案内開始-->.*?<!--00058案内終了-->\s*','',text,flags=re.S)
    text=text.replace('**最新は00057の','**00057の')
    prefix='# アルゴリズム調査の作業一覧\n\n'
    assert text.startswith(prefix)
    notice=f'''<!--00058案内開始-->
**最新は00058の[{TITLE}]({FOLDER}/{TITLE}.html)。持越し損失の知見を場内完結へ反映。5〜240分・3段階の積極度・10戦略450条件を手数料込みで比較し、各場の金額・枚数を掲載。**

[全450条件]({FOLDER}/全450条件.html) · [資料案内]({FOLDER}/README.md)。
<!--00058案内終了-->

'''
    path.write_text(prefix+notice+text[len(prefix):],encoding='utf-8')
    path=ROOT/'アルゴリズム調査'/'index.html'
    text=path.read_text(encoding='utf-8')
    text=re.sub(r'<!--00058開始-->.*?<!--00058終了-->','',text,flags=re.S)
    text=text.replace('class="task latest"','class="task"').replace('<span class="badge">最新</span>','')
    text=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00058：場内完結450条件。保有5〜240分・積極度3段階・10戦略を手数料込みで比較。</p>',text,count=1,flags=re.S)
    notice=f'''<!--00058開始--><article class="task latest"><div class="number">作業00058 <span class="badge">最新</span></div><h2>場内完結の時間軸と積極度の再検証</h2><p>期限を延ばさない在庫管理、追加停止・逆玉整理・利益方向追加・カバーと、方向性の5入口。450条件の時間軸・積極度・金額・枚数を比較。</p><a class="button" href="{FOLDER}/{TITLE}.html">説明と各セッション損益 →</a><p><a href="{FOLDER}/全450条件.html">全450条件</a> ／ <a href="{FOLDER}/README.md">資料案内</a></p></article><!--00058終了-->'''
    assert '<!--00057開始-->' in text
    path.write_text(text.replace('<!--00057開始-->',notice+'\n<!--00057開始-->',1),encoding='utf-8')
    print('00058の資料案内と調査一覧を更新しました。')


if __name__=='__main__':
    main()
