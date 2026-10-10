"""追加完備・全数表・図・実Chrome・画像を同じ実体へ結んで00038を公開する。"""

from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import unquote,urlsplit

from bs4 import BeautifulSoup

import report


HERE,ROOT,OUT=report.HERE,report.ROOT,report.OUT
TITLE='時間窓合議と入口の安定性'
PRIOR=OUT.parent/'00037_原本全行の板観測と対照比較'
read,digest=report.read,report.digest


def links(path: Path) -> int:
    """機能: HTML又はMarkdownの全内部リンクとHTMLアンカーを検査する。

    引数: path(Path)。返り値: 内部リンク数(int)。自分の公表証跡だけ生成前を許す。
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
    """機能: 32条件の追加完備と表示・実操作・画像の全証拠を厳密に結ぶ。

    引数: なし。返り値: 公表証跡(dict)。不完全な段階は停止する。
    """
    report.verify_guard();refs={}
    def bind(path: Path, expected: str|None=None) -> None:
        """機能: 内容指紋を確認し、同じ参照の異なる内容を拒否する。

        引数: path(Path)、expected(str|None)。返り値: なし(None)。
        """
        path=path.resolve();assert path.is_relative_to(ROOT)
        relative=path.relative_to(ROOT).as_posix();actual=digest(path)
        assert expected is None or expected==actual,(relative,expected,actual)
        assert relative not in refs or refs[relative]==actual,relative
        refs[relative]=actual
    for name,groups in (('完備監査.json',('参照資料SHA256','出力SHA256')),
                        ('追加完備監査.json',('参照資料SHA256','必須成果SHA256'))):
        proof=read(HERE/name);bind(HERE/name)
        for group in groups:
            for relative,sha in proof[group].items():bind(ROOT/relative,sha)
    fixed=read(HERE/'探索条件の固定.json');ids=[s['id'] for s in fixed['conditions']]
    assert len(ids)==len(set(ids))==32
    financial=read(HERE/'report_audit.json')
    assert financial['全合格'] and not financial['全数表暫定版']
    assert (financial['全条件数'],financial['全台帳数'],financial['損益表示行数'],financial['比較表示行数'],
        financial['集中診断表示行数'],financial['差分表示行数'])==(32,832,1024,48,48,8)
    for flag in ('全返済からの金額枚数一致','全元組の集中診断一致','全期間週各場一致','全32選択対象一致','二出口の判定分離一致','全リンク一致'):
        assert financial[flag] is True
    for group in ('参照資料SHA256','出力SHA256'):
        for relative,sha in financial[group].items():bind(ROOT/relative,sha)
    bind(HERE/'report.py',financial['報告実装SHA256']);bind(HERE/'report_audit.py',financial['監査実装SHA256'])
    manifest=read(HERE/'report_manifest.json')
    assert not manifest['暫定版'] and manifest['全条件数']==32 and manifest['損益行数']==1024
    bind(HERE/'report.py',manifest['生成実装SHA256'])
    for group in ('参照資料SHA256','出力SHA256'):
        for relative,sha in manifest[group].items():bind(ROOT/relative,sha)
    visual=read(HERE/'report_visual_check.json')
    for flag in ('全合格','全32選択合格','各方式32行一致','暗色2画面','正式HTML不変','目視確認済'):assert visual[flag] is True
    assert len(visual['結果'])==2 and {r['画面'] for r in visual['結果']}=={report.MAIN,report.ALL}
    for row in visual['結果']:
        assert row['成功'] and row['目視確認済'] and row['背景']=='rgb(11, 18, 27)'
        assert row['全選択数']==(32 if row['画面']==report.ALL else 0)
        if row['画面']==report.ALL:
            assert len(row['全操作'])==32 and [r['id'] for r in row['全操作']]==ids
            assert all(r['成功'] and r['行数']==32 for r in row['全操作'])
        bind(OUT/row['画面'],row['HTML_SHA256']);bind(HERE/row['画像'],row['画像SHA256'])
    bind(HERE/'report_visual_check.py',visual['監査実装SHA256'])
    wording=read(HERE/'report_revision.json')
    assert wording['全合格'] and not any(wording[k] for k in ('売買変更','採否変更','数値変更'))
    for field in ('旧証跡SHA256','新証跡SHA256'):
        for relative,sha in wording[field].items():bind(ROOT/relative,sha)
    independent=read(HERE/'採否結果の独立照合.json')
    assert independent['全合格'] and (independent['全条件数'],independent['全入力数'])==(32,832)
    assert independent['金額枚数元組比率活動除外一致'] and independent['固定採否と数値差一致']
    assert independent['追加売買再生'] is False and independent['旧採否関数呼出'] is False
    for relative,sha in independent['参照資料SHA256'].items():bind(ROOT/relative,sha)
    diagnostic=read(HERE/'入口経路の事後診断.json')
    assert diagnostic['全合格'] and diagnostic['事後診断'] and not diagnostic['採否変更'] and not diagnostic['売買再生']
    expected_diagnostic={(f'{window}__{manager}__V000',symbol)
        for window in ('M2_100','V2_100','U3_100') for manager in report.MANAGERS for symbol in report.SYMBOLS}
    assert len(diagnostic['結果'])==12 and {(r['id'],r['symbol']) for r in diagnostic['結果']}==expected_diagnostic
    assert all(r['同じ初回約定の収支差円']==0 for r in diagnostic['結果'])
    bind(HERE/'追加完備監査.json',diagnostic['元追加完備SHA256'])
    bind(HERE/'entry_path_diagnostic.py',diagnostic['実装SHA256'])
    # ----------------------------------------
    # 4固定方式×26の図集合を、実ブラウザの集合と同じHTMLへ接続する。
    chart=read(HERE/'chart_audit.json');chart_fixed=read(HERE/'chart_fixed.json')
    assert chart['全合格'] and chart['全図示数']==104
    for flag in ('全原本足一致','全注文返済一致','全原本曲線指紋一致','全金額枚数一致','全4方向帯一致'):
        assert chart[flag] is True
    selected={f'{signal}__{manager}__V000' for signal in ('S100','M2_100') for manager in report.MANAGERS}
    assert set(chart_fixed['方式'])==selected
    expected={(identifier,n,s) for identifier in selected for n in fixed['全セッション'] for s in report.SYMBOLS}
    assert len(chart['結果'])==104 and {(r['id'],r['session'],r['symbol']) for r in chart['結果']}==expected
    assert all(r['全合格'] for r in chart['結果'])
    for relative,sha in chart['参照SHA256'].items():bind(ROOT/relative,sha)
    for relative,sha in chart_fixed['SHA256'].items():bind(ROOT/relative,sha)
    bind(HERE/'chart_fixed.json',chart['固定SHA256']);bind(OUT/'５分足と売買.html',chart['HTML_SHA256'])
    browser=read(HERE/'chart_browser_audit.json')
    assert browser['全合格'] and browser['正式HTML不変'] and browser['全画面数']==104
    assert len(browser['結果'])==104 and {(r['id'],r['session'],r['symbol']) for r in browser['結果']}==expected
    assert all(r['全合格'] and r['方向帯数']==4 for r in browser['結果'])
    bind(OUT/'５分足と売買.html',browser['HTML_SHA256'])
    bind(HERE/'chart_browser_audit.py',browser['実装SHA256']);bind(HERE/'chart_audit.json',browser['表示監査SHA256'])
    seen=read(HERE/'chart_visual_check.json')
    for flag in ('全合格','正式HTML不変','目視確認済'):assert seen[flag] is True
    assert len(seen['画像'])==2
    bind(OUT/'５分足と売買.html',seen['HTML_SHA256'])
    for row in seen['画像']:
        assert row['成功'] and row['目視確認済']
        bind(HERE/row['画像'],row['画像SHA256'])
    bind(HERE/'chart_visual_check.py',seen['監査実装SHA256'])
    revision=read(HERE/'chart_revision.json')
    assert revision['全合格'] and not any(revision[k] for k in ('売買変更','採否変更','入力変更','新売買再生'))
    for item in revision['旧証跡']:
        for relative,sha in item['旧証跡SHA256'].items():bind(ROOT/relative,sha)
    for field in ('新証跡SHA256','成果SHA256'):
        for relative,sha in revision[field].items():bind(ROOT/relative,sha)
    total_links=0
    for path in (OUT/report.MAIN,OUT/report.ALL,OUT/'５分足と売買.html',OUT/'README.md'):
        total_links+=links(path);bind(path)
    for name in ('assess_results.json','report_manifest.json','report_audit.json','report_selftest.json','report_visual_check.json',
        'chart_generation.json','chart_audit.json','chart_fixed.json','chart_browser_audit.json','chart_visual_check.json','chart_revision.json',
        '採否結果の独立照合.json','入口経路の事後診断.json','report_revision.json','publish.py'):
        bind(HERE/name)
    for relative,sha in refs.items():assert digest(ROOT/relative)==sha,relative
    decision=read(HERE/'assess_results.json')
    assert decision['監査完了'] and not decision['主案の事後差替'] and not decision['全体目標達成']
    return dict(公表可能=True,全条件数=32,全入力数=832,全図示数=104,数表行数=1024,
        全32方式32行の実Chrome操作=True,目視確認画面数=4,内部リンク数=total_links,
        出口別の研究候補={m:decision['出口別'][m]['既知比較の研究候補'] for m in report.MANAGERS},
        合議固有の予測付加価値='未判定',全体目標達成=False,未知での有効性確認=False,
        現在API追加取得数=0,保存ライブ使用=False,参照SHA256=refs)


def update_index() -> dict:
    """機能: 過去の各作業本文を保持し、共通一覧の最新を00038へ更新する。

    引数: なし。返り値: 案内指紋とリンク数(dict)。
    """
    path=OUT.parent/'index.html';body=path.read_text(encoding='utf-8');old_count=len(BeautifulSoup(body,'html.parser').select('article.task'))
    existed='<!--00038開始-->' in body
    body=re.sub(r'<!--00038開始-->.*?<!--00038終了-->','',body,flags=re.S)
    body=body.replace('task latest','task');body=re.sub(r' <span class="badge">最新[^<]*</span>','',body)
    summary='H019の近接3窓を合議し、単一窓との収支・時計感度を二出口別に比較。全32条件を検算し、黒字基礎・追加改善・指定波を分けて表示。'
    body=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00038：'+summary+'</p>',body,count=1)
    block=f'''<!--00038開始--><article class="task latest"><div class="number">作業00038 <span class="badge">最新・検算完了</span></div><h2>{TITLE}</h2><p>{summary}</p><a class="button" href="{OUT.name}/{report.MAIN}">短い比較と結論 →</a><a class="button" href="{OUT.name}/{report.ALL}">各週・各セッションの損益 →</a><p><a href="{OUT.name}/５分足と売買.html">5分足と売買</a> ／ <a href="{OUT.name}/README.md">資料案内</a></p></article><!--00038終了-->'''
    assert body.count('</header>')==1;body=body.replace('</header>','</header>'+block,1)
    parsed=BeautifulSoup(body,'html.parser')
    assert len(parsed.select('article.task'))==old_count+(0 if existed else 1)
    assert len(parsed.select('article.latest'))==1 and '00038' in parsed.select_one('article.latest').text
    assert '00037_原本全行の板観測と対照比較/原本全行の板観測と対照比較.html' in body
    path.write_text(body,encoding='utf-8')
    md=OUT.parent/'README.md';body=md.read_text(encoding='utf-8')
    body=re.sub(r'\*\*最新は.*?\*\*',f'**最新は00038の[{TITLE}]({OUT.name}/{report.MAIN})。{summary}**',body,count=1)
    body=re.sub(r'^\| `00038_.*\n','',body,flags=re.M).replace('`（最新）','`')
    line=f'\n| `{OUT.name}`（最新） | 時間窓合議32条件、二出口の黒字基礎と時計耐性を別判定 | [比較と結論]({OUT.name}/{report.MAIN}) | [全損益]({OUT.name}/{report.ALL})・[売買図]({OUT.name}/５分足と売買.html)・[資料案内]({OUT.name}/README.md) |'
    assert body.count('| --- | --- | --- | --- |')==1;body=body.replace('| --- | --- | --- | --- |','| --- | --- | --- | --- |'+line,1)
    assert body.count('`（最新）')==1 and '| `00037_原本全行の板観測と対照比較` |' in body
    md.write_text(body,encoding='utf-8')
    return dict(案内SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in (path,md)},
        案内内部リンク数=links(path)+links(md),最新作業='00038')


def main() -> None:
    """機能: 全資料検証後に一覧を更新し、旧00037の完全不変を記録する。

    引数: なし。返り値: なし(None)。
    """
    before={p.relative_to(ROOT).as_posix():digest(p) for p in PRIOR.rglob('*') if p.is_file()};assert before
    result=audit();navigation=update_index()
    for relative,sha in before.items():assert digest(ROOT/relative)==sha,relative
    result.update(navigation,旧00037不変=True,旧00037SHA256=before)
    result['参照SHA256'].update(navigation['案内SHA256'])
    for relative,sha in result['参照SHA256'].items():assert digest(ROOT/relative)==sha,relative
    (HERE/'公表確認.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('参照SHA256','旧00037SHA256','案内SHA256')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
