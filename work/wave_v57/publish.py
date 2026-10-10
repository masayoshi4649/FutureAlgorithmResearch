"""損益を改変せず、調査の入口と短い日本語の資料案内を作る。"""

from __future__ import annotations

import json
import csv
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FOLDER = '00054_補充監視3手法の実装とセッション損益'
REPORT = ROOT / 'アルゴリズム調査' / FOLDER


def yen(value: float) -> str:
    """機能: 金額を符号付き日本語向け表記へ整える。

    引数: value(float)。返り値: 金額表記(str)。
    """
    return f'{value:+,.0f}' if value else '0'


def main() -> None:
    """機能: 全主条件の各場収支を公開し、最新作業へのリンクを更新する。

    引数: なし。返り値: なし(None)。既存作業の本文と計算結果は変更しない。
    """
    results = json.loads((HERE / '売買結果.json').read_text(encoding='utf8'))
    evaluation = json.loads((HERE / '報告評価.json').read_text(encoding='utf8'))
    primary = [m for m in results['methods'] if m['primary']]
    lines = ['# 補充監視3手法の検証結果', '', evaluation['headline'], '']
    lines.extend('- ' + value for value in evaluation['findings'])
    lines += ['', '## 条件', '', '主条件は補充2回・始値0.05%幅。TOPIXminiは5枚、NK225microは10枚で入り、追加なし。片方向上限10枚・20枚以内。費用0、全て場内返済。ATR・機械学習は使用していない。', '',
              '常に10枚・20枚で実行する場合は、注文による価格変化がない仮定のもとで金額と返済枚数が2倍になる。勝率・損益比は変わらない。', '',
              '全期間表は判断の次の有効原本行の最終価格・中値・売買気配を比較。各セッション表は中値評価。HTMLでは各場の評価価格も切り替えられる。', '', '## 全期間', '',
              '|手法|銘柄|利益円|損失円|収支円|中値収支円|売買気配収支円|', '|---|---|---:|---:|---:|---:|---:|']
    for method in primary:
        for symbol in ('TOPIX', 'NK225'):
            summary = method['summary'][symbol]
            lines.append(f"|{method['id']}|{symbol}|{summary['profit']:,.0f}|{summary['loss']:,.0f}|{yen(summary['net'])}|{yen(summary['sensitivity']['中値']['net'])}|{yen(summary['sensitivity']['売買気配']['net'])}|")
    lines += ['', '## 各セッションの中値評価収支（円）', '',
              '|セッション|R1 TOPIX|R1 NK|R2 TOPIX|R2 NK|R3 TOPIX|R3 NK|',
              '|---|---:|---:|---:|---:|---:|---:|']
    for session in results['sessions']:
        cells = [session]
        for method in primary:
            for symbol in ('TOPIX', 'NK225'):
                account = next(a for a in method['accounts'] if a['session'] == session and a['symbol'] == symbol)
                cells.append(yen(account['sensitivity']['中値']['net']))
        lines.append('|' + '|'.join(cells) + '|')
    lines += ['', '各場の利益・損失・返済枚数、週計、12条件の比較は[HTML](補充監視3手法の説明と損益.html)を参照。', '',
              '23場は既に研究に使用した保存期間であり、真の未見期間テストではない。今回の売買仕様は損益を見る前に固定し、原本順と途中切断で未来参照を点検している。']
    (REPORT / '検証結果.md').write_text('\n'.join(lines) + '\n', encoding='utf8')
    rows = []
    for method in results['methods']:
        for account in method['accounts']:
            for mode in ('中値', '売買気配'):
                item = account['sensitivity'][mode]
                rows.append(dict(手法=method['id'], セッション=account['session'], 銘柄=account['symbol'], 評価価格=mode,
                                 利益円=item['profit'], 損失円=item['loss'], 収支円=item['net'], 利益返済枚数=item['win_qty'],
                                 損失返済枚数=item['loss_qty'], 同値返済枚数=item['flat_qty'], 枚数差=item['win_qty']-item['loss_qty'],
                                 往復数=item['cycles']))
    with (REPORT / '中値と売買気配のセッション別損益.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (REPORT / 'README.md').write_text('''# 補充監視3手法の実装とセッション損益

最初に見るファイルは [補充監視3手法の説明と損益.html](補充監視3手法の説明と損益.html) です。

## 読む順序

1. HTML：三つの手法の短い説明、各23場の利益・損失・収支、枚数、週計、価格評価の感度。
2. [検証結果.md](検証結果.md)：主条件の全期間と全セッションの収支を簡潔に確認。
3. [中値と売買気配のセッション別損益.csv](中値と売買気配のセッション別損益.csv)：12条件の各場・各価格評価の利益・損失・収支と枚数。
   [セッション別損益.csv](セッション別損益.csv)・[週別損益.csv](週別損益.csv)は従来の最終約定価格による評価。
4. [売買仕様固定.json](../../work/wave_v57/売買仕様固定.json)：結果を見る前の規則とコード・入力のハッシュ。
5. [独立監査](../../work/wave_v57/review/)・[特徴監査.json](../../work/wave_v57/特徴監査.json)：原本一致、補充状態、未来参照、台帳照合。

## 再現

プロジェクトルートから以下を実行します。Python、NumPy、Numbaを使用します。

```text
python work/wave_v57/features.py
python work/wave_v57/backtest.py
python work/wave_v57/report/build_report.py
python work/wave_v57/publish.py
```

原本を変更せず、現在APIにも接続しません。コードを変更すると固定ハッシュ照合で停止します。新しい条件の調査は別作業にします。
原本入力一覧は特徴監査、全注文は `work/wave_v57/台帳/{手法ID}/{セッション}_{銘柄}.csv` にあります。
旧アプリケーションE01の売買条件は変更していません。
''', encoding='utf8')
    # ----------------------------------------
    # 作業一覧の旧リンクは残し、最新の表示と新規案内だけ置き換える。
    index_path = ROOT / 'アルゴリズム調査/index.html'
    text = index_path.read_text(encoding='utf8')
    if '<!--00054開始-->' not in text:
        text = text.replace('class="task latest"', 'class="task"').replace(' <span class="badge">最新</span>', '')
        begin = text.index('    <p class="lead">')
        end = text.index('</p>', begin) + 4
        text = text[:begin] + '    <p class="lead">最新00054：補充監視の3手法を12条件で実装。全23セッションの利益・損失・収支と、約定価格を変えた感度を掲載。</p>' + text[end:]
        article = f'''<!--00054開始--><article class="task latest"><div class="number">作業00054 <span class="badge">最新</span></div><h2>補充監視3手法の実装と損益</h2><p>同価格の数量回復を追い、反転・補充切れ突破・補充位置追従の三つを売買まで実装。補充回数と追跡幅を変えた12条件を、保存済み全23場で検証。</p><a class="button" href="{FOLDER}/補充監視3手法の説明と損益.html">3手法の説明と各セッション損益 →</a><p><a href="{FOLDER}/検証結果.md">短い検証結果</a> ／ <a href="{FOLDER}/README.md">読む順序と再現</a></p></article><!--00054終了-->\n'''
        text = text.replace('<!--00053開始-->', article + '<!--00053開始-->')
        index_path.write_text(text, encoding='utf8')
    readme_path = ROOT / 'アルゴリズム調査/README.md'
    text = readme_path.read_text(encoding='utf8')
    if '<!--00054案内開始-->' not in text:
        text = text.replace('**最新は00053', '**00053')
        heading = '# アルゴリズム調査の作業一覧\n'
        article = f'''\n<!--00054案内開始-->
**最新は00054の[補充監視3手法の説明と損益]({FOLDER}/補充監視3手法の説明と損益.html)。補充の後の反転・突破・補充位置追従を実装。12条件・全23場の利益・損失・収支と、最終価格/中値/売買気配での価格評価を掲載。**

[読む順序と再現]({FOLDER}/README.md) · [短い検証結果]({FOLDER}/検証結果.md)。
<!--00054案内終了-->\n'''
        readme_path.write_text(text.replace(heading, heading + article, 1), encoding='utf8')


if __name__ == '__main__':
    main()
