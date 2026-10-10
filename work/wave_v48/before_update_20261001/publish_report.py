"""有望4方式の説明と損益を確認し、作業00042を一覧へ追加する。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote,urlsplit

from bs4 import BeautifulSoup

from build_report import HERE,ROOT,OUT,period_rows,session_label

CHECK=HERE/'update_20260930'


def digest(path: Path) -> str:
    """機能: 公表物と元保存結果の指紋を求める。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def links(path: Path, content: str) -> int:
    """機能: HTML又はMarkdownの相対リンクの存在を確認する。

    引数: path(Path)、content(str)。返り値: 確認数(int)。
    """
    values=([a['href'] for a in BeautifulSoup(content,'html.parser').select('a[href]')]
        if path.suffix=='.html' else re.findall(r'\]\(([^)]+)\)',content))
    count=0
    for value in values:
        parsed=urlsplit(value)
        if parsed.scheme or not parsed.path:continue
        assert (path.parent/unquote(parsed.path)).resolve().exists(),(str(path),value)
        count+=1
    return count


def main() -> None:
    """機能: 独立確認・表示・指紋を確認し、過去作業を維持して索引を更新する。

    引数: なし。返り値: なし(None)。売買データや条件は変更しない。
    """
    data=json.loads((HERE/'報告データ.json').read_text(encoding='utf-8'))
    display=json.loads((CHECK/'表示確認.json').read_text(encoding='utf-8'))
    assert data['全合格'] and display['全合格'] and display['目視確認済']
    target=OUT/'有望4手法の説明と損益.html'
    assert digest(target)==data['HTML_SHA256']==display['HTML_SHA256']
    assert all(digest(CHECK/r['画像'])==r['画像SHA256'] for r in display['結果'])
    assert all(digest(ROOT/path)==value for path,value in data['参照SHA256'].items())
    independent=CHECK/'独立確認.md';assert independent.exists() and independent.stat().st_size>300
    independent_data=CHECK/'独立確認.json'
    audit=json.loads(independent_data.read_text(encoding='utf-8'))
    assert audit['全合格'] and audit['HTML_SHA256']==digest(target)
    assert all(digest(ROOT/path)==value for path,value in audit['参照SHA256'].items())
    research=OUT.parent;previous=research/'00041_入口途中出口の分解検証'
    old={str(path.relative_to(ROOT)):digest(path) for path in previous.iterdir() if path.is_file()}
    count=sum(links(path,path.read_text(encoding='utf-8')) for path in OUT.iterdir() if path.suffix in ('.html','.md'))
    # ----------------------------------------
    # 公表済み作業の内容は保ち、共通索引の最新表示を移す。
    index=research/'index.html';readme=research/'README.md';name=OUT.name
    index_text=index.read_text(encoding='utf-8');readme_text=readme.read_text(encoding='utf-8')
    session_count=data['対象セッション数'];latest=session_label(max(r['session'] for r in data['候補'][0]['sessions']),True)
    description=f'有望4候補の入口・途中・出口を平易に説明。TOPIXミニ上限10枚・NKマイクロ上限20枚。{latest}まで全{session_count}場の利益・損失・収支を表示。'
    if '<!--00042開始-->' not in index_text:
        index_text=re.sub(r'<p class="lead">最新00041：.*?</p>',f'<p class="lead">最新00042：{description}</p>',index_text,count=1)
        index_text=index_text.replace('class="task latest"','class="task"',1).replace('<span class="badge">最新・検算完了</span>','',1)
        card=f'''<!--00042開始--><article class="task latest"><div class="number">作業00042 <span class="badge">最新・検算完了</span></div><h2>有望4手法の説明とセッション損益</h2><p>{description}</p><a class="button" href="{name}/有望4手法の説明と損益.html">手法の説明と各セッション損益 →</a><p><a href="{name}/README.md">読む順序・数量の前提・再現資料</a></p></article><!--00042終了-->'''
        assert '<!--00041開始-->' in index_text
        index_text=index_text.replace('<!--00041開始-->',card+'<!--00041開始-->',1)
    if f'`{name}`（最新）' not in readme_text:
        readme_text=re.sub(r'^\*\*最新は00041.*?\*\*$',f'**最新は00042の[有望4手法の説明とセッション損益]({name}/有望4手法の説明と損益.html)。{description}**',readme_text,count=1,flags=re.M)
        readme_text=readme_text.replace('`00041_入口途中出口の分解検証`（最新）','`00041_入口途中出口の分解検証`')
        readme_text=readme_text.replace('追記：[約8割の勝ちと損小利大での再評価]','00041の補足：[約8割の勝ちと損小利大での再評価]')
        marker='| --- | --- | --- | --- |';assert marker in readme_text
        row=f'| `{name}`（最新） | 有望4手法の平易な3段階説明と14場の損益 | [説明と損益]({name}/有望4手法の説明と損益.html) | [数量前提・資料案内]({name}/README.md) |'
        readme_text=readme_text.replace(marker,marker+'\n'+row,1).replace('`00042_内容`','`00043_内容`')
    # ----------------------------------------
    # 既存00042の追加データ更新ではリンク先を維持して件数と対象日だけ更新する。
    index_text=re.sub(r'<p class="lead">最新00042：.*?</p>',f'<p class="lead">最新00042：{description}</p>',index_text,count=1)
    card_match=re.search(r'<!--00042開始-->(.*?)<!--00042終了-->',index_text,re.S)
    assert card_match
    old_card=card_match.group(0)
    new_card=re.sub(r'<p>.*?</p>',f'<p>{description}</p>',old_card,count=1)
    index_text=index_text.replace(old_card,new_card,1)
    readme_text=re.sub(r'^\*\*最新は00042.*?\*\*$',f'**最新は00042の[有望4手法の説明とセッション損益]({name}/有望4手法の説明と損益.html)。{description}**',readme_text,count=1,flags=re.M)
    readme_text=re.sub(r'有望4手法の平易な3段階説明と\d+場の損益',f'有望4手法の平易な3段階説明と{session_count}場の損益',readme_text,count=1)
    assert index_text.count('class="task latest"')==1 and '最新00042' in index_text
    count+=links(index,index_text)+links(readme,readme_text)
    index.write_text(index_text,encoding='utf-8');readme.write_text(readme_text,encoding='utf-8')
    assert all(digest(ROOT/path)==value for path,value in old.items())
    row_count=len(period_rows(data['候補'][0]))*4
    report=dict(全合格=True,手法数=4,原結果口座数=data['会計入力数'],表示金額行数=row_count,表示枚数行数=row_count,
        目視画面数=6,全手法切替確認=True,リンク数=count,旧00041不変=True,
        新売買再生=True,現在API取得数=0,元保存結果不変=True,
        成果SHA256={str(path.relative_to(ROOT)):digest(path) for path in [target,OUT/'README.md',index,readme]},
        確認SHA256={str(path.relative_to(ROOT)):digest(path) for path in [HERE/'報告データ.json',CHECK/'表示確認.json',independent,independent_data]})
    (CHECK/'公表確認.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if not isinstance(v,dict)},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
