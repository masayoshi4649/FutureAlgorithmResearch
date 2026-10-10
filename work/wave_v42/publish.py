"""正式な計算・数表・図・実Chrome・目視を結び、作業一覧を00037へ更新する。"""

from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import unquote,urlsplit

from bs4 import BeautifulSoup

import report


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=report.OUT
TITLE='原本全行の板観測と対照比較'
PRIOR=OUT.parent/'00036_黒字候補の再評価と状態修正'
read=report.read
digest=report.digest


def save(path: Path, value: dict) -> None:
    """機能: 公表証跡を今回の作業領域へ原子的に保存する。

    引数: path(Path)、value(dict)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def links(path: Path) -> int:
    """機能: HTMLとMarkdownの内部参照・アンカーが存在するか検査する。

    引数: path(Path)。返り値: 内部リンク数(int)。自分の公表証跡だけ生成前を許す。
    """
    body=path.read_text(encoding='utf-8')
    urls=[a['href'] for a in BeautifulSoup(body,'html.parser').select('[href]')] if path.suffix=='.html' else re.findall(r'\]\(([^)]+)\)',body)
    count=0
    for href in urls:
        value=urlsplit(href)
        if value.scheme or value.netloc:continue
        target=(path.parent/unquote(value.path)).resolve() if value.path else path.resolve()
        if target==HERE/'公表確認.json':continue
        assert target.is_file(),(path,href)
        if value.fragment and target.suffix=='.html':
            ids={element.get('id') for element in BeautifulSoup(target.read_text(encoding='utf-8'),'html.parser').select('[id]')}
            assert unquote(value.fragment) in ids,(path,href)
        count+=1
    return count


def audit() -> dict:
    """機能: 全計算・全数表・全図・実Chromeと画像を同じ保存実体へ結ぶ。

    引数: なし。返り値: 公表可否と参照指紋(dict)。どれか未完備なら停止する。
    """
    refs={}
    def bind(path: Path, expected: str | None=None) -> None:
        """機能: 同じ資料を異なる指紋で結合することを拒否する。

        引数: path(Path)、expected(str|None)。返り値: なし(None)。
        """
        assert path.resolve().is_relative_to(ROOT)
        actual=digest(path);relative=path.relative_to(ROOT).as_posix()
        assert expected is None or actual==expected,(relative,expected,actual)
        assert relative not in refs or refs[relative]==actual,relative
        refs[relative]=actual
    complete=read(HERE/'完備監査.json')
    assert complete['検証完了'] and complete['全13評価確認'] and complete['全原本場内返済']
    assert (complete['全条件数'],complete['全会計入力数'],complete['因果入力数'])==(260,6760,1040)
    assert complete['全体目標達成'] is False and complete['現在API取得数']==0 and complete['保存ライブ使用'] is False
    for relative,value in complete['参照資料SHA256'].items():bind(ROOT/relative,value)
    bind(HERE/'complete.py',complete['ガードSHA256'])
    fixed=read(HERE/'探索条件の固定.json');specs=fixed['主条件']+fixed['補助条件']
    ids=[spec['id'] for spec in specs]
    assert len(ids)==len(set(ids))==260
    financial=read(HERE/'report_audit.json')
    assert financial['全合格'] and financial['全数表暫定版'] is False
    assert (financial['全条件数'],financial['全台帳数'],financial['損益表示行数'],
        financial['比較表示行数'],financial['差分表示行数'],financial['段階表示行数'])==(260,6760,8320,40,12,6)
    for name in ('全返済からの金額枚数R一致','全期間週各場一致','全260選択対象一致',
        '主副の判定分離一致','全リンク一致','全13既知','学習除外なし'):assert financial[name]
    for group in ('参照資料SHA256','出力SHA256'):
        for relative,value in financial[group].items():bind(ROOT/relative,value)
    bind(HERE/'report.py',financial['報告実装SHA256'])
    bind(HERE/'report_audit.py',financial['監査実装SHA256'])
    manifest=read(HERE/'report_manifest.json')
    assert not manifest['暫定版'] and manifest['固定比較']==list(report.COMPARISONS)
    assert manifest['全条件数']==260 and manifest['損益行数']==8320
    for group in ('参照資料SHA256','出力SHA256'):
        for relative,value in manifest[group].items():bind(ROOT/relative,value)
    chart=read(HERE/'chart_audit.json');chart_fixed=read(HERE/'chart_fixed.json')
    assert chart['全合格'] and chart['全図示数']==104 and chart['暫定'] is False
    for name in ('全注文一致','全返済一致','全数量一致','全損益一致','全保存曲線指紋一致',
        '帯公開時点一致','新旧数量比率出典一致','全13学習除外なし'):assert chart[name]
    assert set(chart_fixed['方式'])=={'F00','F01','F02','F05'} and chart_fixed['学習専用セッション数']==0
    assert len(chart['結果'])==104
    chart_set={(row['id'],row['session'],row['symbol']) for row in chart['結果']}
    assert len(chart_set)==104 and all(row['全合格'] for row in chart['結果'])
    for relative,value in chart['参照SHA256'].items():bind(ROOT/relative,value)
    for relative,value in chart_fixed['SHA256'].items():bind(ROOT/relative,value)
    bind(HERE/'chart_fixed.json',chart['固定SHA256'])
    bind(HERE/'探索条件の固定.json',chart['探索固定SHA256'])
    bind(OUT/'５分足と売買.html',chart['HTML_SHA256'])
    browser=read(HERE/'chart_browser_audit.json')
    assert browser['全合格'] and browser['正式HTML不変'] and browser['全画面数']==104
    assert len(browser['結果'])==104 and {(row['id'],row['session'],row['symbol']) for row in browser['結果']}==chart_set
    assert all(row['全合格'] for row in browser['結果'])
    bind(OUT/'５分足と売買.html',browser['HTML_SHA256'])
    bind(HERE/'chart_browser_audit.py',browser['実装SHA256'])
    bind(HERE/'chart_audit.json',browser['表示監査SHA256'])
    # ----------------------------------------
    # 表の全選択と、画像を実際に読み取った記録を計算の成功とは別に確認する。
    visual=read(HERE/'report_visual_check.json')
    for name in ('全合格','全260選択合格','各方式32行一致','暗色2画面','正式HTML不変','目視確認済'):assert visual[name]
    assert len(visual['結果'])==2 and {row['画面'] for row in visual['結果']}=={report.MAIN,report.ALL}
    for row in visual['結果']:
        assert row['成功'] and row['目視確認済'] and row['背景']=='rgb(11, 18, 27)'
        assert row['全選択数']==(260 if row['画面']==report.ALL else 0)
        if row['画面']==report.ALL:
            assert len(row['全操作'])==260 and [item['id'] for item in row['全操作']]==ids
            assert all(item['成功'] and item['行数']==32 for item in row['全操作'])
        bind(OUT/row['画面'],row['HTML_SHA256']);bind(HERE/row['画像'],row['画像SHA256'])
    bind(HERE/'report_visual_check.py',visual['監査実装SHA256'])
    chart_visual=read(HERE/'chart_visual_check.json')
    assert chart_visual['全合格'] and chart_visual['正式HTML不変'] and chart_visual['目視確認済']
    assert len(chart_visual['画像'])==2
    bind(OUT/'５分足と売買.html',chart_visual['HTML_SHA256'])
    for row in chart_visual['画像']:
        assert row['成功'] and row['目視確認済'] and row['新旧u区別']
        bind(HERE/row['画像'],row['画像SHA256'])
    bind(HERE/'report_chart_visual.py',chart_visual['監査実装SHA256'])
    link_count=0
    for path in (OUT/report.MAIN,OUT/report.ALL,OUT/'５分足と売買.html',OUT/'README.md'):
        link_count+=links(path);bind(path)
    for name in ('完備監査.json','assess_results.json','report_manifest.json','report_audit.json',
        'report_selftest.json','report_visual_check.json','chart_audit.json','chart_fixed.json',
        'chart_browser_audit.json','chart_visual_check.json','今回の到達点.md','publish.py'):
        bind(HERE/name)
    for relative,value in refs.items():assert digest(ROOT/relative)==value,relative
    return dict(公表可能=True,全条件数=260,全入力数=6760,全図示数=104,数表行数=8320,
        全260方式32行の実Chrome操作=True,目視確認画面数=4,内部リンク数=link_count,
        全体目標達成=False,未知での有効性確認=False,現在API追加取得数=0,保存ライブ使用=False,
        参照SHA256=refs)


def update_index() -> dict:
    """機能: 旧作業の本文とリンクを残して、共通一覧の最新を00037へ移す。

    引数: なし。返り値: 更新後の案内指紋と内部リンク数(dict)。旧作業フォルダは変更しない。
    """
    path=OUT.parent/'index.html';body=path.read_text(encoding='utf-8')
    previous=BeautifulSoup(body,'html.parser')
    old_count=len(previous.select('article.task'))
    existed='<!--00037開始-->' in body
    body=re.sub(r'<!--00037開始-->.*?<!--00037終了-->','',body,flags=re.S)
    body=body.replace('task latest','task');body=re.sub(r' <span class="badge">最新[^<]*</span>','',body)
    body=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00037：原本全行の板観測260条件を検算。今回の主案・副案は両市場赤字で不採用。00036の既存黒字候補は保持しています。</p>',body,count=1)
    block=f'''<!--00037開始--><article class="task latest"><div class="number">作業00037 <span class="badge">最新・検算完了</span></div><h2>{TITLE}</h2><p>公開端点から原本全行へ数量観測を拡張。旧品質維持とP局所品質を別に評価し、全260条件を記録しました。主案・副案とも両市場赤字・活動基準未達。</p><a class="button" href="{OUT.name}/{report.MAIN}">短い比較と結論 →</a><a class="button" href="{OUT.name}/{report.ALL}">各週・各セッションの損益 →</a><p><a href="{OUT.name}/５分足と売買.html">5分足と売買</a> ／ <a href="{OUT.name}/README.md">資料案内</a></p></article><!--00037終了-->'''
    assert body.count('</header>')==1
    body=body.replace('</header>','</header>'+block,1)
    parsed=BeautifulSoup(body,'html.parser')
    assert len(parsed.select('article.task'))==old_count+(0 if existed else 1)
    assert len(parsed.select('article.latest'))==1 and '00037' in parsed.select_one('article.latest').text
    assert '00036_黒字候補の再評価と状態修正/黒字候補の再評価と状態修正.html' in body
    path.write_text(body,encoding='utf-8')
    md=OUT.parent/'README.md';body=md.read_text(encoding='utf-8')
    body=re.sub(r'\*\*最新は.*?\*\*',f'**最新は00037の[{TITLE}]({OUT.name}/{report.MAIN})。全260条件を検算し、今回の主案・副案は両市場赤字で不採用。00036の既存黒字候補は保持しています。**',body,count=1)
    body=re.sub(r'^\| `00037_.*\n','',body,flags=re.M).replace('`（最新）','`')
    line=f'\n| `{OUT.name}`（最新） | 原本全行の板観測260条件、主案・副案は両市場赤字 | [比較と結論]({OUT.name}/{report.MAIN}) | [全損益]({OUT.name}/{report.ALL})・[売買図]({OUT.name}/５分足と売買.html)・[資料案内]({OUT.name}/README.md) |'
    assert body.count('| --- | --- | --- | --- |')==1
    body=body.replace('| --- | --- | --- | --- |','| --- | --- | --- | --- |'+line,1)
    assert body.count('`（最新）')==1 and '| `00036_黒字候補の再評価と状態修正` |' in body
    md.write_text(body,encoding='utf-8')
    return dict(案内SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in (path,md)},
        案内内部リンク数=links(path)+links(md),最新作業='00037')


def main() -> None:
    """機能: 全証拠確認後にだけ一覧を更新し、旧00036の不変性を保存する。

    引数: なし。返り値: なし(None)。売買・採否・凍結コードは変更しない。
    """
    before={path.relative_to(ROOT).as_posix():digest(path) for path in PRIOR.rglob('*') if path.is_file()}
    assert before
    proof=audit()
    result=update_index()
    for relative,value in before.items():assert digest(ROOT/relative)==value,relative
    proof.update(result,旧00036不変=True,旧00036SHA256=before)
    proof['参照SHA256'].update(result['案内SHA256'])
    for relative,value in proof['参照SHA256'].items():assert digest(ROOT/relative)==value,relative
    save(HERE/'公表確認.json',proof)
    print(json.dumps({k:v for k,v in proof.items() if k not in ('参照SHA256','旧00036SHA256','案内SHA256')},ensure_ascii=False))


if __name__=='__main__':main()
