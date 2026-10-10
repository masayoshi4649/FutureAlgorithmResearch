"""固定入力・成果・表示を確認して作業00041を索引へ追加する。"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote,urlsplit

from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
RESEARCH=ROOT/'アルゴリズム調査'
NAME='00041_入口途中出口の分解検証'
OUT=RESEARCH/NAME


def read(path: Path) -> object:
    """機能: 日本語JSONを読み出す。

    引数: path(Path)。返り値: 内容(object)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """機能: 読取専用でファイル全体の指紋を求める。

    引数: path(Path)。返り値: SHA256(str)。
    """
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):result.update(block)
    return result.hexdigest()


def check_reference(item: tuple[str,str]) -> tuple[str,str]:
    """機能: 固定時の参照指紋と現在を比較する。

    引数: item(tuple[str,str])。返り値: 一致したパスと指紋(tuple[str,str])。
    """
    name,expected=item;actual=digest(ROOT/name)
    assert actual==expected,('固定参照の変化',name,expected,actual)
    return name,actual


def links(path: Path, content: str) -> int:
    """機能: 公表するHTML又はMarkdownの相対リンクの存在を確認する。

    引数: path(Path)、content(str)。返り値: 検査したリンク数(int)。
    """
    candidates=([a['href'] for a in BeautifulSoup(content,'html.parser').select('a[href]')]
        if path.suffix=='.html' else re.findall(r'\]\(([^)]+)\)',content))
    count=0
    for value in candidates:
        parsed=urlsplit(value)
        if parsed.scheme or not parsed.path:continue
        destination=(path.parent/unquote(parsed.path)).resolve()
        assert destination.exists(),('リンク先なし',str(path),value)
        count+=1
    return count


def main() -> None:
    """機能: 表示・参照・リンクを確認し、旧作業を保持して最新索引を更新する。

    引数: なし。返り値: なし(None)。データや経済条件を変更しない。
    """
    display=read(HERE/'表示検査_5画面.json')
    assert display['全合格'] and display['目視確認済']
    for row in display['結果']:
        assert digest(OUT/row['ファイル'])==row['HTML_SHA256']
        assert digest(HERE/row['画像'])==display['目視画像SHA256'][row['画像']]
    proofs=['entry_assessment.json','warm_assessment.json','mid_result.json','exit_results.json',
        'exit_integration_complete.json','integration_followup/clock/complete.json',
        'integration_followup/new/complete.json','統合追加ナイトの入力前提完了.json',
        'integrated_assessment.json','combined_baselines_audit.json']
    assert all(read(HERE/name)['全合格'] for name in proofs)
    references={}
    for name,key in [('追加ナイト照合の固定.json','原本SHA256'),('統合追試の固定.json','参照SHA256'),
        ('exit_integration_fixed.json','参照資料SHA256'),('統合追加ナイトの初期化修正.json','参照SHA256')]:
        for path,value in read(HERE/name)[key].items():
            assert path not in references or references[path]==value
            references[path]=value
    with ThreadPoolExecutor(max_workers=4) as pool:verified=dict(pool.map(check_reference,references.items()))
    raw_count=sum(path.startswith(('book/','candle_1min/','candle_5min/')) for path in verified)
    assert raw_count==84
    # ----------------------------------------
    # 公表物同士の金額・図・集合を確認する。
    html=(OUT/'全条件の損益.html').read_text(encoding='utf-8')
    methods=json.loads(BeautifulSoup(html,'html.parser').find(id='financial-data').string)
    assert len(methods)==168 and len({m['id'] for m in methods})==168
    assert sum(len(m['rows']) for m in methods)==5410
    normalized=[{'id':m['id'],'rows':m['rows']} for m in methods]
    display_digest=hashlib.sha256(json.dumps(normalized,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
    assert display_digest=='ab04e5738ee2c1a19a602d2a1219259be2fd89336a3f3516424c37e56bdc9779'
    lookup={m['id']:m for m in methods};plot_count=0
    for name,expected_count in [('追加ナイトの５分足と売買.html',10),('統合版の５分足と売買.html',24)]:
        soup=BeautifulSoup((OUT/name).read_text(encoding='utf-8'),'html.parser')
        plots=json.loads(soup.find(id='chart-data').string);assert len(plots)==expected_count
        for plot in plots:
            row=next(v for v in lookup[plot['id']]['rows'] if v['symbol']==plot['symbol'] and v['label']=='2026-09-29 ナイト')
            for field in ('gross_profit_yen','gross_loss_yen','net_yen','profit_units','loss_units','zero_units'):
                assert abs(plot['totals'][field]-row[field])<1e-8
            assert plot['tracking'][-1][1]==row['net_yen']
            assert all(0<=v[2]<=plot['cap'] and 0<=v[3]<=plot['cap'] for v in plot['tracking'])
            assert plot['tracking'][-1][2:]==[0.0,0.0]
            plot_count+=1
    output_links=sum(links(path,path.read_text(encoding='utf-8')) for path in OUT.iterdir() if path.suffix in ('.html','.md'))
    assert (HERE/'全方式表示と統合所見の最終独立レビュー.md').exists()
    # ----------------------------------------
    # 過去の作業フォルダを変えず、共通索引だけ更新する。
    previous=RESEARCH/'00040_50パーセント減量版の反証'
    previous_hash={str(path.relative_to(ROOT)):digest(path) for path in previous.rglob('*') if path.is_file()}
    index=RESEARCH/'index.html';readme=RESEARCH/'README.md'
    index_text=index.read_text(encoding='utf-8');readme_text=readme.read_text(encoding='utf-8')
    description='入口114比較・途中13比較・出口13診断を分解し、統合36方式と追加9月29日ナイトを検証。出口短縮の改善と、残る大勝ち依存を区別。'
    if '<!--00041開始-->' not in index_text:
        index_text=re.sub(r'<p class="lead">最新00040：.*?</p>',f'<p class="lead">最新00041：{description}</p>',index_text,count=1)
        index_text=index_text.replace('class="task latest"','class="task"',1).replace('<span class="badge">最新・検算完了</span>','',1)
        card=f'''<!--00041開始--><article class="task latest"><div class="number">作業00041 <span class="badge">最新・検算完了</span></div><h2>入口・途中判断・出口の分解検証</h2><p>{description}</p><a class="button" href="{NAME}/分解と結論.html">部品別の短い結論 →</a><a class="button" href="{NAME}/全条件の損益.html?method=F50__E10">各週・各セッションの損益 →</a><p><a href="{NAME}/統合版の５分足と売買.html">統合版の5分足と売買</a> ／ <a href="{NAME}/追加ナイトの５分足と売買.html">従来方式の追加ナイト</a> ／ <a href="{NAME}/出口単独の比較.html">出口だけの比較</a> ／ <a href="{NAME}/README.md">資料案内</a></p></article><!--00041終了-->'''
        assert '<!--00040開始-->' in index_text
        index_text=index_text.replace('<!--00040開始-->',card+'<!--00040開始-->',1)
    if f'`{NAME}`（最新）' not in readme_text:
        readme_text=re.sub(r'^\*\*最新は00040.*?\*\*$',f'**最新は00041の[入口・途中判断・出口の分解検証]({NAME}/分解と結論.html)。{description}**',readme_text,count=1,flags=re.M)
        readme_text=readme_text.replace('`00040_50パーセント減量版の反証`（最新）','`00040_50パーセント減量版の反証`')
        entry=f'| `{NAME}`（最新） | 入口114・途中13・出口13、統合36と追加ナイト | [部品別の結論]({NAME}/分解と結論.html) | [全損益]({NAME}/全条件の損益.html)・[統合売買図]({NAME}/統合版の５分足と売買.html)・[出口比較]({NAME}/出口単独の比較.html)・[資料案内]({NAME}/README.md) |'
        marker='| --- | --- | --- | --- |';assert marker in readme_text
        readme_text=readme_text.replace(marker,marker+'\n'+entry,1).replace('`00021_内容`','`00042_内容`')
    index_links=links(index,index_text)+links(readme,readme_text)
    assert index_text.count('class="task latest"')==1 and '最新00041' in index_text
    index.write_text(index_text,encoding='utf-8');readme.write_text(readme_text,encoding='utf-8')
    assert all(digest(ROOT/path)==value for path,value in previous_hash.items())
    report=dict(全合格=True,原本84不変=True,固定参照一致数=len(verified),原本追加取得数=0,
        表示検査数=5,目視確認済=True,損益方式数=168,表示損益行数=5410,出口診断数=13,
        独立数値検算の正規化SHA256=display_digest,
        追加売買図数=plot_count,出力リンク数=output_links,索引リンク数=index_links,
        旧00040不変=True,経済コード変更=False,
        出力SHA256={str(path.relative_to(ROOT)):digest(path) for path in [*sorted(OUT.iterdir()),index,readme] if path.is_file()},
        根拠SHA256={str((HERE/name).relative_to(ROOT)):digest(HERE/name) for name in proofs+['統合所見.json','表示検査_5画面.json','全方式表示と統合所見の最終独立レビュー.md']})
    (HERE/'公表前最終監査.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if not isinstance(v,dict)},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
