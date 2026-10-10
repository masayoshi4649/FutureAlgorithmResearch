"""全数表と売買図を結び、00035の正式な資料案内を公開する。"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit
from bs4 import BeautifulSoup
import runner

HERE,ROOT=runner.HERE,runner.ROOT
TITLE='同じ価格帯の防御変化と突破'
OUT=ROOT/('アルゴリズム調査/00035_'+TITLE)


def guide() -> None:
    """機能: 最初に読む資料、短い結論、再現方法を保存する。

    引数: なし。返り値: なし (None)。
    """
    (OUT/'README.md').write_text(f'''# {TITLE}

最初に[比較と結論]({TITLE}.html)を見てください。**今回の主案は活動不足と赤字で不採用です。** 89比較・感度＋192方向乱数、全281条件を検算しました。

読む順序：

1. [比較と結論]({TITLE}.html) — 固定12方式、帯から実取引へ減る理由。
2. [全281条件の損益](全条件損益.html) — 各週・各セッションの利益／損失／収支、勝ち／負け／同値決済枚数。
3. [5分足と売買](５分足と売買.html) — 固定4方式×26入力、注文と返済、採用した価格帯と試行確定時刻。
4. [今回の到達点](../../work/wave_v40/今回の到達点.md) — 不採用の理由を短く説明。

各市場1枚、TOPIXミニ／NK225マイクロ倍率への換算、費用0・指定価格約定・場内全返済。全13セッションは既知で、全方式を同じ期間で評価しました。初期2セッションの学習除外はありません。現在API・保存ライブは使用していません。

## 再現と証跡

既存の固定入力が一致する環境で、ルートから実行します。

```powershell
$env:PYTHONIOENCODING='utf-8'
python work/wave_v40/runner.py --workers 6
python work/wave_v40/complete.py
python work/wave_v40/chart_report.py
python work/wave_v40/chart_audit.py
python work/wave_v40/report.py
python work/wave_v40/report_audit.py
```

- [収支前の比較計画](比較計画.html)・[機械規則](../../work/wave_v40/状態機械の草案.md)・[独立した批判](../../work/wave_v40/実装前の独立批判.md)
- [固定した281条件](../../work/wave_v40/探索条件の固定.json)・[採否の全内訳](../../work/wave_v40/assess_results.json)
- [公開10段の照合](../../work/wave_v40/released_depth_audit.json)・[帯状態の因果](../../work/wave_v40/check_band_causality.json)・[入口の因果](../../work/wave_v40/check_entry_signals.json)
- [全7,306口座の完備監査](../../work/wave_v40/完備監査.json)・[全数表の監査](../../work/wave_v40/report_audit.json)・[全104図の監査](../../work/wave_v40/chart_audit.json)
- [公表確認](../../work/wave_v40/公表確認.json)
''',encoding='utf-8')


def audit() -> dict:
    """機能: 正式結果・全数表・帯の売買図・描画を同じ指紋へ接続する。

    引数: なし。返り値: 公表可否と参照資料 (dict)。
    """
    refs={}
    def bind(path: Path,sha: str|None=None) -> None:
        """機能: 現物指紋を検査して公表資料へ結合する。

        引数: path (Path)、sha (str|None)。返り値: なし (None)。
        """
        actual=runner.digest(path);assert sha is None or actual==sha,str(path)
        refs[path.relative_to(ROOT).as_posix()]=actual
    complete=runner.read(HERE/'完備監査.json')
    assert complete['検証完了'] and complete['全13評価確認'] and complete['ガード版']==1
    assert (complete['全条件数'],complete['全会計入力数'],complete['因果入力数'])==(281,7306,1124)
    assert complete['全体目標達成'] is False
    for relative,sha in complete['参照資料SHA256'].items():bind(ROOT/relative,sha)
    report=runner.read(HERE/'report_audit.json')
    assert report['全合格'] and report['暫定版'] is False
    assert (report['全条件数'],report['全セッション台帳数'],report['損益表示行数'],
            report['比較表示行数'],report['未来反応表示行数'])==(281,7306,8992,24,48)
    assert report['全返済からの金額枚数R一致'] and report['全リンク一致']
    assert report['段階表示行数']==2 and report['全試行観測からの段階件数と候補一致']
    assert report['全13セッション評価'] and report['学習用除外なし']
    for key in ('参照資料SHA256','出力SHA256'):
        for relative,sha in report[key].items():bind(ROOT/relative,sha)
    bind(HERE/'report.py',report['報告実装SHA256']);bind(HERE/'report_audit.py',report['監査実装SHA256'])
    chart=runner.read(HERE/'chart_audit.json')
    assert chart['全合格'] and chart['全図示数']==104 and chart['暫定'] is False
    assert all(chart[k] for k in ('全注文一致','全返済一致','全数量一致','全損益一致',
        '全保存曲線指紋一致','帯公開時点一致','全13学習除外なし'))
    for relative,sha in chart['参照SHA256'].items():bind(ROOT/relative,sha)
    bind(OUT/'５分足と売買.html',chart['HTML_SHA256'])
    bind(HERE/'chart_fixed.json',chart['固定SHA256'])
    for relative,sha in runner.read(HERE/'chart_fixed.json')['SHA256'].items():bind(ROOT/relative,sha)
    browser=runner.read(HERE/'chart_browser_audit.json')
    assert browser['全合格'] and browser['全画面数']==104 and browser['正式HTML不変']
    bind(OUT/'５分足と売買.html',browser['HTML_SHA256'])
    # ----------------------------------------
    # 独立した数表検算とは別に、ブラウザの切替と暗色の実描画を確認する。
    visual=runner.read(HERE/'report_visual_check.json');assert visual['全合格']
    assert max(row['全選択数'] for row in visual['結果'])==281
    for row in visual['結果']:
        assert row['成功'];bind(OUT/row['画面'],row['HTML_SHA256']);bind(HERE/row['画像'],row['画像SHA256'])
    chart_visual=runner.read(HERE/'chart_visual_check.json');assert chart_visual['全合格']
    bind(OUT/'５分足と売買.html',chart_visual['HTML_SHA256'])
    for row in chart_visual['画像']:
        bind(HERE/row['画像'],row['画像SHA256'])
    assert len(chart_visual['画像'])>=2
    links=0
    for path in [OUT/name for name in (TITLE+'.html','全条件損益.html','５分足と売買.html','README.md')]:
        body=path.read_text(encoding='utf-8')
        urls=[a['href'] for a in BeautifulSoup(body,'html.parser').select('[href]')] if path.suffix=='.html' else re.findall(r'\]\(([^)]+)\)',body)
        for url in urls:
            parts=urlsplit(url)
            if parts.scheme or not parts.path:continue
            target=(path.parent/unquote(parts.path)).resolve()
            if target==HERE/'公表確認.json':continue
            assert target.exists(),(path.name,url);links+=1
        bind(path)
    for name in ('完備監査.json','report_manifest.json','report_audit.json','chart_audit.json',
        'report_visual_check.json','chart_visual_check.json','chart_browser_audit.json','今回の到達点.md','publish.py'):
        bind(HERE/name)
    return dict(公表可能=True,全条件数=281,全入力数=7306,全図示数=104,数表行数=8992,
        主担当目視画面数=4,内部リンク数=links,全体目標達成=False,現在API追加取得数=0,参照SHA256=refs)


def index() -> None:
    """機能: 準備中の入口を正式な結果へのリンクへ置き換える。

    引数: なし。返り値: なし (None)。過去資料への入口は保持する。
    """
    path=OUT.parent/'index.html';body=path.read_text(encoding='utf-8')
    body=re.sub(r'<!--00035開始-->.*?<!--00035終了-->','',body,flags=re.S)
    body=body.replace('task latest','task');body=re.sub(r' <span class="badge">最新[^<]*</span>','',body)
    body=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00035：同価格帯の防御変化281条件を検算。今回の主案は不採用。黒字の基礎候補を保持し、探索を継続しています。</p>',body,count=1)
    block=f'''<!--00035開始--><article class="task latest"><div class="number">作業00035 <span class="badge">最新・検算完了</span></div><h2>{TITLE}</h2><p>板の二試行比較は観測・活動が不足し、主案は両市場赤字。待たない突破も含む281条件を記録しました。</p><a class="button" href="{OUT.name}/{TITLE}.html">短い比較と結論 →</a><a class="button" href="{OUT.name}/全条件損益.html">各週・各セッションの損益 →</a><p><a href="{OUT.name}/５分足と売買.html">5分足と売買</a> ／ <a href="{OUT.name}/README.md">資料案内</a></p></article><!--00035終了-->'''
    path.write_text(body.replace('</header>','</header>'+block,1),encoding='utf-8')
    path=OUT.parent/'README.md';body=path.read_text(encoding='utf-8')
    body=re.sub(r'\*\*最新は.*?\*\*',f'**最新は00035の[{TITLE}]({OUT.name}/{TITLE}.html)。281条件を検算し、今回の主案は不採用。探索は継続中です。**',body,count=1)
    body=re.sub(r'^\| `00035_.*\n','',body,flags=re.M).replace('`（最新）','`')
    row=f'\n| `{OUT.name}`（最新） | 同価格帯の板履歴281条件、活動不足と赤字 | [比較と結論]({OUT.name}/{TITLE}.html) | [全損益]({OUT.name}/全条件損益.html)・[売買図]({OUT.name}/５分足と売買.html)・[資料案内]({OUT.name}/README.md) |'
    path.write_text(body.replace('| --- | --- | --- | --- |','| --- | --- | --- | --- |'+row,1),encoding='utf-8')


def main() -> None:
    """機能: 公表資料を検査し、成功した時だけ共通一覧を正式化する。

    引数: なし。返り値: なし (None)。
    """
    guide();runner.save(HERE/'公表確認.json',audit());index()
    print('00035の全281条件・8992損益行・104売買図を正式公開。',flush=True)


if __name__=='__main__':main()
