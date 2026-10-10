"""第五反復の進行状況と、最初に読む資料を保存する。"""

from __future__ import annotations

from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
import shutil
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
REPORTS = HERE.parents[1] / 'アルゴリズム調査'
NAME = '00024_部分利確と最高利益の保護'
OUT = REPORTS / NAME
PREVIOUS = '00023_保有撤回と損失上限の再設計'


def main() -> None:
    """機能: 実行段階を短いダークHTMLと目次へ反映する。

    引数: なし。返り値: なし (None)。売買再生や現在データの参照は行わない。
    """
    progress = HERE / '進捗.json'
    done = json.loads(progress.read_text(encoding='utf-8'))['完了信号'] * 50 if progress.exists() else 0
    lead = f'4,800設定のうち{done:,}設定を計算済み。採用判定は未完了です。' if done else '設計を固定し、実装と合成経路を敵対検査しています。新しい損益計算は未実行です。'
    stamp = datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y/%m/%d %H:%M')
    html = f'''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>00024 部分利確と最高利益の保護</title><style>:root{{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#0b111c;color:#e4eaf3}}body{{max-width:1000px;margin:auto;padding:30px 20px;line-height:1.8}}a{{color:#8fc8ff}}h1{{font-size:27px}}details{{background:#142134;border:1px solid #34465e;padding:15px;border-radius:8px}}.muted{{color:#a9b9ce;font-size:14px}}</style>
<!--
[コンポーネント概要]
本文は既知データの研究進捗、detailsは結果前の比較範囲を表示します。
静的HTMLであり、通信や注文処理はありません。
-->
<p class="muted">作業00024・第５反復・更新 {stamp}</p><h1>部分利確と、最高利益の返上を調べる</h1>
<p><strong>{escape(lead)}</strong></p><p>入口と枚数を揃え、利益の一定割合を守る条件と、十分伸びた後に追跡幅を縮める条件を比較します。</p>
<p>残玉の初回損失幅を維持する案は、元のトレーリングが既に同じ水準を守るため、重複する探索軸から外しました。この包含関係も合成経路で確かめます。</p>
<details><summary>何を固定し、何を変えるか</summary><p>既知13セッション、同じ96入口×50管理。TOPIXミニ5枚／NKマイクロ10枚、初期1ATR、2ATRで部分利確、1.5ATRから3ATR追跡、最長360分、場内返済。</p>
<p>変えるのは、利益1・2・3Rから最高利益の25・50・75％を保護する設定と、順行2・3ATRから追跡を1.5・0.75ATRへ縮める設定です。それぞれ変更なしも含めます。利益保護は部分利確前にも動きます。</p>
<p>同じ入口の変更なし基準と旧主案の両方に対し、両銘柄で収支75％維持・最大下落20％削減を要求します。未来参照、変数感度、乱数方向、指定波も別に検査します。</p></details>
<p class="muted">費用０・指定価格約定。同じ既知データの再探索であり、未知性能の証明ではありません。現在APIは再取得せず、前回の現在保存データも再試験しません。</p>
<p><a href="../{PREVIOUS}/保有撤回と損失上限.html">完了した第４反復の結果</a> ／ <a href="管理設計の固定.json">固定管理仕様</a> ／ <a href="研究候補選抜の事前規則.json">採否の固定規則</a></p>
<p><a href="README.md">読む順序</a> ／ <a href="../index.html">調査一覧</a></p></html>'''
    OUT.mkdir(exist_ok=True)
    for filename in ('管理設計の固定.json', '研究候補選抜の事前規則.json'):
        shutil.copy2(HERE / filename, OUT / filename)
    (OUT / '部分利確と利益保護.html').write_text(html, encoding='utf-8')
    (OUT / 'README.md').write_text('# 作業00024：部分利確と最高利益の保護\n\n最初に [進捗と設計](部分利確と利益保護.html) を開いてください。\n\n' + lead + '\n\n読む順序：\n\n1. [進捗と設計](部分利確と利益保護.html)。\n2. [固定管理仕様](管理設計の固定.json) と [採否の規則](研究候補選抜の事前規則.json)。\n3. [完了した前回の結果](../' + PREVIOUS + '/保有撤回と損失上限.html)。\n\n計算・反証・全玉会計の監査が完了後に、セッション別・週別損益と５分足図解を追加します。現在データを再取得・再試験しません。\n', encoding='utf-8')
    # ----------------------------------------
    # 過去の作業カードを残し、新しい作業の案内だけを更新する。
    index_path = REPORTS / 'index.html'
    index = index_path.read_text(encoding='utf-8')
    index = re.sub(r'<!--00024開始-->.*?<!--00024終了-->', '', index, flags=re.S)
    index = index.replace('task latest', 'task').replace('<span class="badge">最新</span>', '')
    index = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新は00024（第５反復・進行中）。完了した検証は00023、前回の一回照合は00022です。</p>', index, count=1)
    card = f'<!--00024開始--><article class="task latest"><div class="number">作業00024 <span class="badge">最新</span></div><h2>部分利確と最高利益の保護</h2><p>{escape(lead)}</p><a class="button" href="{NAME}/部分利確と利益保護.html">進捗と設計を開く</a><p><a href="{PREVIOUS}/保有撤回と損失上限.html">完了した第４反復の結果</a></p></article><!--00024終了-->'
    assert '</header>' in index
    index = index.replace('</header>', '</header>' + card, 1)
    index_path.write_text(index, encoding='utf-8')
    readme_path = REPORTS / 'README.md'
    text = readme_path.read_text(encoding='utf-8')
    text = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00024の[部分利確と最高利益の保護]({NAME}/部分利確と利益保護.html)（進行中）。完了した結果は[00023]({PREVIOUS}/保有撤回と損失上限.html)です。**', text, count=1)
    text = re.sub(r'^\| `00024_.*?\r?\n', '', text, flags=re.M).replace('（最新）', '')
    anchor = '| --- | --- | --- | --- |'
    assert anchor in text
    row = f'| `{NAME}`（最新） | 同じ入口と枚数で利益保護4,800設定を検証中 | [進捗と設計]({NAME}/部分利確と利益保護.html) | [資料案内]({NAME}/README.md) |'
    text = text.replace(anchor, anchor + '\n' + row, 1)
    readme_path.write_text(text, encoding='utf-8')
    print(lead, flush=True)


if __name__ == '__main__':
    main()
