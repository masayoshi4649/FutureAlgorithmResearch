"""修正版全974条件の証跡と既存損益の表示検算を結び、作業00036を案内する。"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
import report

HERE, ROOT, OUT = report.HERE, report.ROOT, report.OUT


def verify() -> dict:
    """機能: 全条件修正・金額枚数・暗色描画・リンクを現物指紋へ結合する。

    引数: なし。返り値: 公表証拠 (dict)。収益の採否は変更しない。
    """
    references = {}
    def bind(path: Path, expected: str | None = None) -> None:
        """機能: 一つの資料の改変がないことを確認する。

        引数: path (Path)、expected (str|None)。返り値: なし (None)。
        """
        actual = report.digest(path)
        assert expected is None or expected == actual, str(path)
        references[path.relative_to(ROOT).as_posix()] = actual
    state_path = HERE / '状態修正の全再生.json'
    state = report.read(state_path)
    for flag in ('全合格','修正後実装状態契約合格','経済全配列完全一致','全保存統計一致','原版監査を無変更で使用','既知12行だけ修正'):
        assert state[flag] is True, flag
    assert (state['全条件数'], state['主条件数'], state['補助条件数'], state['全入力数']) == (974,206,768,25324)
    assert state['状態変更行数'] == 12 and state['状態変更条件数'] == 1
    assert state['全原本行会計数'] == 2855617030
    assert state['API取得数'] == 0 and not state['現在保存物使用'] and not state['旧成果変更'] and not state['採否変更']
    fixed_path = HERE / '状態修正の固定.json'
    bind(fixed_path, state['固定SHA256'])
    fixed = report.read(fixed_path)
    expected = {row['id'] for row in fixed['条件']}
    assert len(expected) == len(state['結果']) == 974
    assert {row['id'] for row in state['結果']} == expected
    assert sum(row['全入力数'] for row in state['結果']) == 25324
    assert sum(row['状態変更行数'] for row in state['結果']) == 12
    for row in state['結果']:
        assert row['全合格'] and row['全入力数'] == 26
        assert row['状態変更行数'] == (12 if row['id'] == 'H019__B00_T120_F25_N3__R1__L015' else 0)
        bind(ROOT / row['実体'], row['実体SHA256'])
    for relative, sha in state['参照資料SHA256'].items():
        bind(ROOT / relative, sha)
    # ----------------------------------------
    # 金額の表示検査と、実ブラウザの開閉・画像検査を別々に要求する。
    own = report.read(HERE / 'report_data_audit.json')
    independent = report.read(HERE / 'report_display_audit.json')
    assert independent['数値説明照合合格'] and independent['全リンク存在']
    assert (independent['全候補数'], independent['全銘柄セッション数'], independent['全返済件数']) == (10,260,2929)
    assert independent['全比較行数'] == 20 and independent['全金額枚数行数'] == 320
    assert independent['表示変造拒否数'] == 3 and not independent['金額ゼロの負符号表示']
    bind(state_path, own['状態修正再生SHA256'])
    for relative, sha in independent['参照SHA256'].items():
        bind(ROOT / relative, sha)
    html = OUT / (report.TITLE + '.html')
    bind(html, own['HTML_SHA256'])
    bind(HERE / 'report.py', own['報告実装SHA256'])
    visual = report.read(HERE / 'report_visual_check.json')
    assert visual['全合格'] and visual['HTML_SHA256'] == report.digest(html)
    assert len(visual['結果']) == 2
    for row in visual['結果']:
        assert row['成功'] and row['全市場開閉数'] == 20 and row['全損益行数'] == 320 and row['暗色']
        bind(HERE / row['画像'], row['画像SHA256'])
    for name in ('report_data_audit.json','report_display_audit.json','report_visual_check.json','publish.py'):
        bind(HERE / name)
    links = 0
    for path in (html, OUT / 'README.md'):
        source = path.read_text(encoding='utf-8')
        urls = [a['href'] for a in BeautifulSoup(source,'html.parser').select('[href]')] if path.suffix == '.html' else re.findall(r'\]\(([^)]+)\)',source)
        for url in urls:
            parsed = urlsplit(url)
            if parsed.scheme or not parsed.path:
                continue
            assert (path.parent / unquote(parsed.path)).resolve().exists(), url
            links += 1
        bind(path)
    return dict(公表可能=True,再生条件数=974,再生口座数=25324,状態修正行数=12,
                金額表示候補数=10,全金額枚数行数=320,内部リンク数=links,
                新発見974条件ではない=True,採否変更=False,全体目標達成=False,現在API追加取得数=0,
                参照SHA256=references)


def index() -> None:
    """機能: 過去の作業リンクを残し、最新作業を00036へ更新する。

    引数: なし。返り値: なし (None)。
    """
    path = OUT.parent / 'index.html'
    body = path.read_text(encoding='utf-8')
    body = re.sub(r'<!--00036開始-->.*?<!--00036終了-->','',body,flags=re.S)
    body = body.replace('task latest','task')
    body = re.sub(r' <span class="badge">最新[^<]*</span>','',body)
    body = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新00036：黒字候補を再評価し、状態修正版974条件を再検算。基本形と数量調整候補を残し、原本の細かな板更新を使う検査へ進みます。</p>',body,count=1)
    block = f'''<!--00036開始--><article class="task latest"><div class="number">作業00036 <span class="badge">最新・検算完了</span></div><h2>{report.TITLE}</h2><p>既知12行の状態不具合を修正。974条件の注文・損益は不変。黒字10候補の金額と決済枚数を整理しました。</p><a class="button" href="{OUT.name}/{report.TITLE}.html">候補の比較と各週・各セッション損益 →</a><p><a href="{OUT.name}/README.md">資料案内</a></p></article><!--00036終了-->'''
    path.write_text(body.replace('</header>','</header>'+block,1),encoding='utf-8')
    path = OUT.parent / 'README.md'
    body = path.read_text(encoding='utf-8')
    body = re.sub(r'\*\*最新は.*?\*\*',f'**最新は00036の[{report.TITLE}]({OUT.name}/{report.TITLE}.html)。既存974条件の状態修正を検算し、黒字10候補の損益を整理しました。**',body,count=1)
    body = re.sub(r'^\| `00036_.*\n','',body,flags=re.M).replace('`（最新）','`')
    row = f'\n| `{OUT.name}`（最新） | 黒字候補を保持、状態修正版974条件が経済同値 | [比較と各損益]({OUT.name}/{report.TITLE}.html) | [資料案内]({OUT.name}/README.md)・[状態再生](../work/wave_v41/状態修正の全再生.json) |'
    body = body.replace('| --- | --- | --- | --- |','| --- | --- | --- | --- |'+row,1)
    path.write_text(body,encoding='utf-8')


if __name__ == '__main__':
    proof = verify()
    index()
    import json
    (HERE / '公表確認.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    print('00036を正式案内へ追加。旧成果を保持し、状態修正と収益採否を分離。',flush=True)
