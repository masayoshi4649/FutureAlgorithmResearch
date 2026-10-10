"""新しい調査の資料案内と一覧リンクを、過去の報告を残して更新する。"""

from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / 'アルゴリズム調査'
FOLDER = '00056_小幅回収と移動平均の比較'
TITLE = '小幅回収と移動平均の説明と損益'


def main() -> None:
    """機能: 読む順序・実行済みの範囲・最新の入口リンクを保存する。

    引数: なし。返り値: なし(None)。過去の作業フォルダは変更しない。
    """
    out = BASE / FOLDER
    readme = f'''# 小幅回収と移動平均の比較

最初に見るファイルは [小幅回収と移動平均の説明と損益]({TITLE}.html) です。

読む順序：

1. [短い説明と損益]({TITLE}.html)：残った候補、先に決めた主6条件、入口・途中・出口、各セッションの利益・損失・収支と勝ち/負け/同値の決済枚数。
2. [全72条件](全72条件.html)：全期間設定・出口の比較。旧23場と追加2場を分けて表示。
3. [各セッションの全会計CSV](全72条件の各セッション損益.csv)、[期間・週合計CSV](全72条件の期間合計.csv)、[主6条件と候補の全注文CSV](主6条件と候補の全注文.csv)：検算用資料。
4. [固定仕様](../../work/wave_v59/調査仕様.json)、[追加前の選定記録](../../work/wave_v59/追加場適用前固定.json)、[独立監査の案内](../../work/wave_v59/review/README.md)：検証の条件と証跡。

## 結果

小幅のボリンジャーバンド内復帰＋固定利確 `S2_M1_3_10_X1` が、旧23場の事前採用基準を唯一満たしました。中値収支はTOPIX +306,250円、NK +128,500円。条件を変えず追加2場で +1,250円、+6,500円でした。

同じ注文を買いask・売りbidで約定すると、全25場でTOPIX −1,880,000円、NK −486,000円。したがって、理想中値の研究候補です。実行可能な安定収益を確認した結果ではありません。

GC/DC・収束後の1幅トレーリングには、今回の設定で両銘柄を通じた安定黒字の根拠はありませんでした。自動切替の主条件は追従側が旧23場で各銘柄1回だけで、ほぼ小幅反発側の比較となりました。

## 数量と会計

- TOPIX miniは新規5枚、NK225 microは新規10枚。片方向上限10枚・20枚以内。追加・両建てなし。
- 基本約定は発注判断後の次の有効原本行の中値。別表で同じ注文行の買いask・売りbidを評価。最終約定値では取引しません。
- 参照板はラージ。気配評価もミニ・マイクロの実約定を保証しません。費用0で、価格仮定の比較です。
- 「利益」は黒字決済の合計、「損失」は赤字決済の絶対額合計、「収支」はその差。勝ち/負け/同値枚数は延べ決済枚数で、同時保有枚数ではありません。
- CSVの勝負枚数差は勝ち枚数−負け枚数であり、残建玉ではありません。全セッション残建玉0を照合済みです。
- 週はセッション開始日が属する月曜起点。全25場の合計を一週間と呼んでいません。
- CurrentPriceTimeは受信時刻ではなく最終約定時刻です。同時刻の板更新も原本行順を保持します。

## 実装と実行済み範囲

[features.py](../../work/wave_v59/features.py) で確定中値足、[signals.py](../../work/wave_v59/signals.py) で6入口×4期間×3出口の条件を生成し、[engine.py](../../work/wave_v59/engine.py) と [backtest.py](../../work/wave_v59/backtest.py) で原本順に再生しています。ATR・機械学習・現在セッションAPIは使用していません。

旧23場の前にコード・仕様・入力を固定し、`backtest.py --stage dev` を実行。事前基準の候補と旧結果SHAを保存した後にだけ、10月6日夜・7日昼を初めて読み、同じコードで `--stage holdout` を一度実行しました。追加結果による変更はありません。追加場の再読取・再実行はプログラムが拒否します。

保存結果からHTMLだけを再生成する場合は、プロジェクトルートで次を実行します。

```text
python -X utf8 work/wave_v59/build_report.py
```

原本 `book`・足ファイル、実注文アプリケーション、過去の研究フォルダは変更していません。現在API取得数・実注文数はいずれも0です。
'''
    (out / 'README.md').write_text(readme, encoding='utf-8')
    # ----------------------------------------
    # 一覧は新しい案内を先頭へ加え、以前の作業へのリンクを保持する。
    index = BASE / 'index.html'
    text = index.read_text(encoding='utf-8')
    marker = '<!--00056開始-->'
    block = f'{marker}<article class="task latest"><div class="number">作業00056</div><h2>小幅回収と移動平均の比較</h2><p>72条件を旧23場で比較し、固定後に追加2場で確認。短期BB復帰＋小幅利確に中値黒字候補。GC/DC・収束・自動切替も含め、価格感度と各場損益を掲載。</p><a class="button" href="{FOLDER}/{TITLE}.html">短い説明と損益 →</a><p><a href="{FOLDER}/全72条件.html">全72条件</a> ／ <a href="{FOLDER}/README.md">資料案内</a></p></article><!--00056終了-->'
    if marker not in text:
        text = text.replace('class="task latest"', 'class="task"')
        assert '<!--00055開始-->' in text
        text = text.replace('<!--00055開始-->', block + '<!--00055開始-->', 1)
        index.write_text(text, encoding='utf-8')
    readme_path = BASE / 'README.md'
    text = readme_path.read_text(encoding='utf-8')
    if '<!--00056案内開始-->' not in text:
        text = text.replace('**最新は00055の', '**00055の', 1)
        block = f'<!--00056案内開始-->\n**最新は00056の[{TITLE}]({FOLDER}/{TITLE}.html)。小幅回収・GC/DC・収束・自動切替の72条件を比較。旧23場と固定後の追加2場、理想中値と気配価格の違いを分け、各場の金額・枚数を掲載。**\n\n[全72条件]({FOLDER}/全72条件.html) · [資料案内]({FOLDER}/README.md)。\n<!--00056案内終了-->\n\n'
        first, rest = text.split('\n', 1)
        readme_path.write_text(first + '\n\n' + block + rest.lstrip('\n'), encoding='utf-8')


if __name__ == '__main__':
    main()
