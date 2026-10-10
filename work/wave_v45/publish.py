"""完備・独立検算・暗色図を同じ成果に結合し、00040を案内する。"""

from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import unquote,urlsplit

from bs4 import BeautifulSoup

import report

HERE,ROOT,OUT=report.HERE,report.ROOT,report.OUT
TITLE='50パーセント減量版の反証'
PRIOR=OUT.parent/'00039_減量開始時点と利益保護'
read,digest=report.read,report.digest


def links(path: Path) -> int:
    """機能: 各資料の内部リンクとページ内参照を確認する。

    引数: path(Path)。返り値: 有効リンク件数(int)。
    """
    body=path.read_text(encoding='utf-8')
    urls=[e['href'] for e in BeautifulSoup(body,'html.parser').select('[href]')] if path.suffix=='.html' else re.findall(r'\]\(([^)]+)\)',body)
    count=0
    for href in urls:
        url=urlsplit(href)
        if url.scheme or url.netloc:continue
        target=(path.parent/unquote(url.path)).resolve() if url.path else path.resolve()
        if target==HERE/'公表確認.json':continue
        assert target.is_file(),(path,href)
        if url.fragment and target.suffix=='.html':
            ids={e.get('id') for e in BeautifulSoup(target.read_text(encoding='utf-8'),'html.parser').select('[id]')}
            assert unquote(url.fragment) in ids,(path,href)
        count+=1
    return count


def audit() -> dict:
    """機能: 数表・売買図・独立計算・実ブラウザ・目視を結合する。

    引数: なし。返り値: 公表証跡(dict)。不完全な段階では公表を停止する。
    """
    report.verify_guard();refs={}

    def bind(path: Path, expected: str|None=None) -> None:
        """機能: 実体指紋の不一致と参照の競合を拒否する。

        引数: path(Path)、expected(str|None)。返り値: なし(None)。
        """
        path=path.resolve();assert path.is_relative_to(ROOT)
        relative,actual=path.relative_to(ROOT).as_posix(),digest(path)
        assert expected is None or actual==expected,relative
        assert relative not in refs or refs[relative]==actual,relative
        refs[relative]=actual

    for name,groups in (
        ('完備監査.json',('参照資料SHA256','出力SHA256')),
        ('post_audit.json',('参照資料SHA256',)),
        ('report_manifest.json',('参照資料SHA256','出力SHA256')),
        ('report_audit.json',('参照資料SHA256','出力SHA256')),
        ('chart_fixed.json',('SHA256',)),
        ('chart_generation.json',('参照SHA256',)),
        ('chart_audit.json',('参照SHA256',))):
        proof=read(HERE/name);bind(HERE/name)
        if name not in ('chart_fixed.json','report_manifest.json'):assert proof['全合格'] is True
        for group in groups:
            for relative,sha in proof[group].items():bind(ROOT/relative,sha)
    full=read(HERE/'完備監査.json')
    assert (full['全条件数'],full['全入力数'],full['因果入力数'],full['旧単一窓一致入力数'])==(153,3978,612,156)
    assert (full['既知引継条件数'],full['新規再生条件数'])==(11,142)
    repair=read(HERE/'metadata_repair.json');bind(HERE/'metadata_repair.json')
    assert repair['全合格'] and repair['変更はreuse_sourceのnull補完のみ'] and repair['全七成果不変']
    assert repair['既知11完了記録不変'] and (repair['新規条件数'],repair['修復資料数'])==(142,144)
    assert repair['探索固定SHA256']==digest(HERE/'探索条件の固定.json')
    bind(HERE/'metadata_repair.py',repair['実装SHA256'])
    for group in ('入力資料SHA256','出力資料SHA256','全経済成果SHA256','既知11SHA256'):
        for relative,sha in repair[group].items():bind(ROOT/relative,sha)
    post=read(HERE/'post_audit.json')
    assert post['完備元SHA256']==digest(HERE/'完備監査.json')
    assert post['全条件数']==153 and post['固定採否と数値差一致'] is True
    financial=read(HERE/'report_audit.json')
    assert (financial['全条件数'],financial['全台帳数'],financial['損益表示行数'])==(153,3978,4896)
    assert financial['全数表暫定版'] is False and financial['黒字と改善の判定分離一致'] is True
    bind(HERE/'report.py',financial['報告実装SHA256']);bind(HERE/'report_audit.py',financial['監査実装SHA256'])
    manifest=read(HERE/'report_manifest.json');assert manifest['暫定版'] is False
    bind(HERE/'report.py',manifest['生成実装SHA256'])
    visual=read(HERE/'report_visual_check.json')
    for flag in ('全合格','全153選択合格','各方式32行一致','暗色2画面','正式HTML不変','目視確認済'):
        assert visual[flag] is True
    assert len(visual['結果'])==2
    for row in visual['結果']:
        assert row['成功'] and row['目視確認済']
        bind(OUT/row['画面'],row['HTML_SHA256']);bind(HERE/row['画像'],row['画像SHA256'])
    bind(HERE/'report_visual_check.py',visual['監査実装SHA256'])
    for name in ('chart_generation.json','chart_audit.json'):
        value=read(HERE/name);assert value['全図示数']==104
        bind(OUT/'５分足と売買.html',value['HTML_SHA256'])
    browser=read(HERE/'chart_browser_audit.json')
    assert browser['全合格'] and browser['全画面数']==104 and browser['正式HTML不変']
    bind(OUT/'５分足と売買.html',browser['HTML_SHA256'])
    bind(HERE/'chart_browser_audit.py',browser['実装SHA256'])
    assert browser['表示監査SHA256']==digest(HERE/'chart_audit.json')
    pictures=read(HERE/'chart_visual_check.json')
    assert pictures['全合格'] and pictures['目視確認済'] and len(pictures['画像'])==2
    bind(OUT/'５分足と売買.html',pictures['HTML_SHA256'])
    bind(HERE/'chart_visual_check.py',pictures['監査実装SHA256'])
    for row in pictures['画像']:
        assert row['全合格'] and row['目視確認済']
        bind(HERE/row['画像'],row['画像SHA256'])
    revision=read(HERE/'chart_revision.json');bind(HERE/'chart_revision.json')
    assert revision['完了'] and revision['図HTML修正前後同一'] and revision['全104生成値修正前後同一']
    assert not any(revision[k] for k in ('他ソース変更','売買変更','採否変更','条件変更','新売買再生'))
    for name,sha in revision['旧資料SHA256'].items():bind(HERE/'表示監査の方式数修正前'/name,sha)
    for name,sha in revision['最終表示監査SHA256'].items():bind(HERE/name,sha)
    for name in ('report_visual_check.json','chart_browser_audit.json','chart_visual_check.json',
        '独立検算の所見.md','assess_results.json','publish.py'):
        bind(HERE/name)
    count=0
    for path in (OUT/report.MAIN,OUT/report.ALL,OUT/'５分足と売買.html',OUT/'README.md'):
        count+=links(path);bind(path)
    for relative,sha in refs.items():assert digest(ROOT/relative)==sha,relative
    decision=read(HERE/'assess_results.json')
    assert decision['監査完了'] and not decision['主案の事後差替']
    return dict(公表可能=True,主条件数=25,補助条件数=128,全条件数=153,全入力数=3978,
        既知引継条件数=11,新規再生条件数=142,既知引継入力数=286,新規再生入力数=3692,
        全図示数=104,損益数表行数=4896,全153選択実Chrome一致=True,目視確認画面数=4,
        内部リンク数=count,主案の既知研究候補=decision['既知比較の研究候補'],
        耐性付き研究候補=decision['耐性付き研究候補'],全体目標達成=False,
        現在API追加取得数=0,保存ライブ使用=False,参照SHA256=refs)


def update_index() -> dict:
    """機能: 過去の作業を保持して共通一覧の最新を00040へ進める。

    引数: なし。返り値: 案内指紋と内部リンク件数(dict)。
    """
    path=OUT.parent/'index.html';body=path.read_text(encoding='utf-8')
    previous=len(BeautifulSoup(body,'html.parser').select('article.task'))
    existed='<!--00040開始-->' in body
    body=re.sub(r'<!--00040開始-->.*?<!--00040終了-->','',body,flags=re.S)
    body=body.replace('task latest','task');body=re.sub(r' <span class="badge">最新[^<]*</span>','',body)
    summary='50%減量版の利益保護を、判断幅・時間窓・遅延・無作為対照で反証。既知11条件と新142条件を分け、各場・各週の損益を表示。'
    body=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00040：'+summary+'</p>',body,count=1)
    block=f'''<!--00040開始--><article class="task latest"><div class="number">作業00040 <span class="badge">最新・検算完了</span></div><h2>{TITLE}</h2><p>{summary}</p><a class="button" href="{OUT.name}/{report.MAIN}">短い比較と結論 →</a><a class="button" href="{OUT.name}/{report.ALL}">各週・各セッションの損益 →</a><p><a href="{OUT.name}/５分足と売買.html">5分足と売買</a> ／ <a href="{OUT.name}/README.md">資料案内</a></p></article><!--00040終了-->'''
    assert body.count('</header>')==1;body=body.replace('</header>','</header>'+block,1)
    parsed=BeautifulSoup(body,'html.parser')
    assert len(parsed.select('article.task'))==previous+(0 if existed else 1)
    assert len(parsed.select('article.latest'))==1 and '00040' in parsed.select_one('article.latest').text
    path.write_text(body,encoding='utf-8')
    md=OUT.parent/'README.md';body=md.read_text(encoding='utf-8')
    body=re.sub(r'\*\*最新は.*?\*\*',f'**最新は00040の[{TITLE}]({OUT.name}/{report.MAIN})。{summary}**',body,count=1)
    body=re.sub(r'^\| `00040_.*\n','',body,flags=re.M).replace('`（最新）','`')
    line=f'\n| `{OUT.name}`（最新） | 50%減量版の固定主案と25比較・128無作為対照 | [比較と結論]({OUT.name}/{report.MAIN}) | [全損益]({OUT.name}/{report.ALL})・[売買図]({OUT.name}/５分足と売買.html)・[資料案内]({OUT.name}/README.md) |'
    assert body.count('| --- | --- | --- | --- |')==1
    body=body.replace('| --- | --- | --- | --- |','| --- | --- | --- | --- |'+line,1)
    assert body.count('`（最新）')==1 and '| `00039_減量開始時点と利益保護` |' in body
    md.write_text(body,encoding='utf-8')
    return dict(最新作業='00040',案内内部リンク数=links(path)+links(md),
        案内SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in (path,md)})


def main() -> None:
    """機能: 全証拠の確認後に一覧を更新し、旧作業の不変も記録する。

    引数: なし。返り値: なし(None)。
    """
    before={p.relative_to(ROOT).as_posix():digest(p) for p in PRIOR.rglob('*') if p.is_file()};assert before
    result=audit();navigation=update_index()
    for relative,sha in before.items():assert digest(ROOT/relative)==sha
    result.update(navigation,旧00039不変=True,旧00039SHA256=before)
    result['参照SHA256'].update(navigation['案内SHA256'])
    (HERE/'公表確認.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print({k:v for k,v in result.items() if not isinstance(v,dict)},flush=True)


if __name__=='__main__':main()
