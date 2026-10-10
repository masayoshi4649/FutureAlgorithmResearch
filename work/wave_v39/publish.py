"""検算済みの板圧力研究を、成果一覧と短い資料案内へ公開する。"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit
from bs4 import BeautifulSoup
import runner

HERE, ROOT = runner.HERE, runner.ROOT
TITLE = '予想外の板圧力と独立価格対照'
OUT = ROOT / ('アルゴリズム調査/00034_' + TITLE)


def guide() -> None:
    """機能: 短い結論と読む順序、再現手順を保存する。

    引数: なし。返り値: なし (None)。売買条件や成績は変更しない。
    """
    text = f'''# {TITLE}

最初に[比較と結論]({TITLE}.html)を見てください。**板圧力の予想外の成分に、利益を増やす効果は確認できず、今回の主案は不採用です。**

読む順序：

1. [比較と結論]({TITLE}.html) — 固定8方式の比較、入口と返済の短い説明。
2. [全240条件の損益](全条件損益.html) — 手法ごとの各週・各セッションの利益／損失／収支、勝ち／負け／同値決済枚数。
3. [5分足と売買](５分足と売買.html) — 固定4方式×26市場セッション、全エントリーと返済。
4. [今回の到達点](../../work/wave_v39/今回の到達点.md) — 何が否定され、何を次に調べるか。

各市場1枚。TOPIXミニ・NK225マイクロの価格倍率へ換算、費用0・指定価格約定・場内全返済。初めの2セッションは学習のみで取引0。評価11セッションも既知です。新しい未知データや現在APIを取得していません。

検証は全240条件・6,240口座、代表960入力の因果確認まで完了。損益表は全32,009返済から別に集計して照合しています。多数の派生条件を独立した発見数とは扱いません。

## 再現と証跡

固定原本・実装が一致する環境で、ルートから次の順です。

```powershell
$env:PYTHONIOENCODING='utf-8'
python work/wave_v39/runner.py --workers 6
python work/wave_v39/complete.py
python work/wave_v39/chart_report.py
python work/wave_v39/chart_audit.py
python work/wave_v39/report.py
python work/wave_v39/report_audit.py
```

- [実装前の研究範囲](../../work/wave_v39/実装前の研究範囲.md)
- [全条件の固定](../../work/wave_v39/探索条件の固定.json)
- [完備監査](../../work/wave_v39/完備監査.json)
- [採否の内訳](../../work/wave_v39/assess_results.json)
- [全数表の独立監査](../../work/wave_v39/report_audit.json)
- [全売買図の独立監査](../../work/wave_v39/chart_audit.json)
- [公表確認](../../work/wave_v39/公表確認.json)
'''
    (OUT / 'README.md').write_text(text, encoding='utf-8')


def audit() -> dict:
    """機能: 完備会計・数表・図・描画とリンクの指紋を結合する。

    引数: なし。返り値: 公表可能な資料の記録 (dict)。経済的不採用を維持する。
    """
    refs = {}
    def bind(path: Path, sha: str | None = None) -> None:
        """機能: 現物の指紋を一致確認し記録する。

        引数: path (Path)、sha (str|None)。返り値: なし (None)。
        """
        actual = runner.digest(path)
        assert sha is None or actual == sha, str(path)
        refs[path.relative_to(ROOT).as_posix()] = actual

    complete = runner.read(HERE / '完備監査.json')
    assert complete['検証完了'] and complete['ガード版'] == 2
    assert (complete['全条件数'], complete['全会計入力数'], complete['因果入力数']) == (240, 6240, 960)
    for relative, sha in complete['参照資料SHA256'].items(): bind(ROOT / relative, sha)
    table = runner.read(HERE / 'report_audit.json')
    assert table['全合格'] and table['暫定版'] is False
    assert (table['損益表示行数'], table['比較表示行数'], table['未来反応表示行数']) == (7680, 16, 32)
    assert table['全返済数'] == 32009 and table['可視数値セル数'] == 54032
    for key in ('参照資料SHA256', '出力SHA256'):
        for relative, sha in table[key].items(): bind(ROOT / relative, sha)
    bind(HERE / 'report.py', table['報告実装SHA256'])
    bind(HERE / 'report_audit.py', table['監査実装SHA256'])
    chart = runner.read(HERE / 'chart_audit.json')
    assert chart['全合格'] and chart['全図示数'] == 104 and not chart['暫定']
    assert all(chart[k] for k in ('全注文一致', '全返済一致', '全数量一致', '全損益一致', '学習専用16画面の取引ゼロ'))
    bind(OUT / '５分足と売買.html', chart['HTML_SHA256'])
    for relative, sha in chart['参照SHA256'].items(): bind(ROOT / relative, sha)
    fixed = runner.read(HERE / 'chart_fixed.json')
    for relative, sha in fixed['SHA256'].items(): bind(ROOT / relative, sha)
    bind(HERE / 'chart_fixed.json', chart['固定SHA256'])
    # ----------------------------------------
    # 実ブラウザでの全選択と、主担当が目視した暗色の3画像を結合する。
    visual = runner.read(HERE / 'report_visual_check.json')
    assert visual['全合格'] and visual['全240選択合格'] and visual['暗色2画面']
    for row in visual['結果']:
        bind(OUT / row['画面'], row['HTML_SHA256'])
        bind(HERE / row['画像'], row['画像SHA256'])
    visual_chart = runner.read(HERE / 'report_chart_visual.json')
    assert visual_chart['全合格'] and visual_chart['正式HTML不変']
    bind(OUT / '５分足と売買.html', visual_chart['HTML_SHA256'])
    for row in visual_chart['表示2例']: bind(HERE / row['画像'], row['画像SHA256'])
    links = 0
    for path in [OUT / name for name in (TITLE + '.html', '全条件損益.html', '５分足と売買.html', 'README.md')]:
        body = path.read_text(encoding='utf-8')
        urls = [a['href'] for a in BeautifulSoup(body, 'html.parser').select('[href]')] if path.suffix == '.html' else re.findall(r'\]\(([^)]+)\)', body)
        for url in urls:
            parts = urlsplit(url)
            if parts.scheme or not parts.path: continue
            target = (path.parent / unquote(parts.path)).resolve()
            if target == HERE / '公表確認.json': continue
            assert target.exists(), (path.name, url)
            links += 1
        bind(path)
    for name in ('完備監査.json', 'report_manifest.json', 'report_audit.json', 'chart_audit.json',
                 'report_visual_check.json', 'report_chart_visual.json', '今回の到達点.md', 'publish.py'):
        bind(HERE / name)
    return dict(公表可能=True,全条件数=240,全入力数=6240,全図示数=104,
        数表行数=7680,主担当目視画面数=3,内部リンク数=links,
        未知での有効性確認=False,全体目標達成=False,現在API追加取得数=0,参照SHA256=refs)


def index() -> None:
    """機能: 最新00034を一覧の先頭へ追加する。

    引数: なし。返り値: なし (None)。過去の研究成果は保持する。
    """
    assert runner.read(HERE / '公表確認.json')['公表可能']
    path = OUT.parent / 'index.html'; body = path.read_text(encoding='utf-8')
    body = re.sub(r'<!--00034開始-->.*?<!--00034終了-->', '', body, flags=re.S)
    body = body.replace('task latest', 'task')
    body = re.sub(r' <span class="badge">最新[^<]*</span>', '', body)
    lead = '最新00034：板圧力の独立入口240条件を検証。今回の主案は不採用。発見と反証を継続中。'
    body = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">' + lead + '</p>', body, count=1)
    block = f'''<!--00034開始--><article class="task latest"><div class="number">作業00034 <span class="badge">最新・検算完了</span></div><h2>{TITLE}</h2><p>予測可能な板圧力を除いた残差を、素の板・価格・両市場・乱数と比較。利益への追加効果は未確認。</p><a class="button" href="{OUT.name}/{TITLE}.html">短い比較と結論 →</a><a class="button" href="{OUT.name}/全条件損益.html">各週・各セッションの損益 →</a><p><a href="{OUT.name}/５分足と売買.html">5分足と売買</a> ／ <a href="{OUT.name}/README.md">資料案内</a></p></article><!--00034終了-->'''
    path.write_text(body.replace('</header>', '</header>' + block, 1), encoding='utf-8')
    path = OUT.parent / 'README.md'; body = path.read_text(encoding='utf-8')
    body = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00034の[{TITLE}]({OUT.name}/{TITLE}.html)。240条件を検算し、今回の主案は不採用。探索は継続中です。**', body, count=1)
    body = re.sub(r'^\| `00034_.*\n', '', body, flags=re.M).replace('`（最新）', '`')
    row = f'\n| `{OUT.name}`（最新） | 予想外の板圧力240条件、情報追加は未達 | [比較と結論]({OUT.name}/{TITLE}.html) | [全損益]({OUT.name}/全条件損益.html)・[売買図]({OUT.name}/５分足と売買.html)・[資料案内]({OUT.name}/README.md) |'
    path.write_text(body.replace('| --- | --- | --- | --- |', '| --- | --- | --- | --- |' + row, 1), encoding='utf-8')


def main() -> None:
    """機能: 公表証跡を作成し、指定時だけ共通一覧を更新する。

    引数: --index (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--index', action='store_true')
    args = parser.parse_args(); guide(); runner.save(HERE / '公表確認.json', audit())
    if args.index: index()
    print('00034の全数表・売買図・資料案内を公表成果として確認。', flush=True)


if __name__ == '__main__': main()
