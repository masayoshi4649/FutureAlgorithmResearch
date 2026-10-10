"""新作業の資料と最新リンクを公表し、相対リンクを確認する。"""

import hashlib
import json
import re
import shutil
from urllib.parse import unquote,urlsplit
from bs4 import BeautifulSoup
from build_report import ROOT,HERE,OUT,TITLE


def main():
    """機能: 監査済み資料をコピーし、00044を索引の先頭に追加する。

    引数: なし。返り値: なし(None)。過去作業の成果は変更しない。
    """
    for name in ('独立確認.json','表示確認.json'):
        proof=json.loads((HERE/name).read_text(encoding='utf8'))
        assert proof['全合格']
        shutil.copy2(HERE/name,OUT/'検証資料'/name)
    folder=OUT.name;index=ROOT/'アルゴリズム調査/index.html'
    text=index.read_text(encoding='utf8')
    lead='最新00044：新候補E01・E08と元の候補1を、入口・途中・出口の説明と16セッション・週別の金額／枚数で比較。'
    text=re.sub(r'<p class="lead">.*?</p>',lambda _:'<p class="lead">'+lead+'</p>',text,count=1,flags=re.S)
    text=re.sub(r'<!--00044開始-->.*?<!--00044終了-->','',text,flags=re.S)
    def former(match):
        """機能: 直前の作業から最新表示だけを外す。

        引数: match(re.Match)。返り値: 旧記事(str)。
        """
        return match.group().replace('class="task latest"','class="task"').replace('最新・検算完了','比較調査')
    text=re.sub(r'<!--00043開始-->.*?<!--00043終了-->',former,text,flags=re.S)
    card=f'<!--00044開始--><article class="task latest"><div class="number">作業00044 <span class="badge">最新・検算完了</span></div><h2>新候補2手法と基準の説明・セッション損益</h2><p>E01・E08と元の候補1を00042と同じ形式で整理。入口・途中・出口の説明、16セッション・週・全期間の利益／損失／収支と決済枚数。</p><a class="button" href="{folder}/{TITLE}">新候補の説明と各セッション損益 →</a><p><a href="{folder}/README.md">読む順序・数量前提・検算資料</a></p></article><!--00044終了-->'
    text=text.replace('</header>','</header>'+card,1);index.write_text(text,encoding='utf8')
    readme=ROOT/'アルゴリズム調査/README.md';text=readme.read_text(encoding='utf8')
    latest=f'**最新は00044の[新候補2手法の説明と損益]({folder}/{TITLE})。E01・E08と元の候補1の入口・途中・出口、16セッション・週別の金額と決済枚数を00042形式で表示。**'
    text=re.sub(r'\*\*最新は.*?\*\*',lambda _:latest,text,count=1)
    text=re.sub(r'^\| `00044_.*?\n','',text,flags=re.M)
    text=text.replace('`00043_赤字原因とエントリー見送り`（最新）','`00043_赤字原因とエントリー見送り`')
    row=f'| `{folder}`（最新） | 新候補E01・E08と元基準の説明・16場損益 | [説明と損益]({folder}/{TITLE}) | [資料案内]({folder}/README.md) |\n'
    text=text.replace('| --- | --- | --- | --- |\n','| --- | --- | --- | --- |\n'+row,1);readme.write_text(text,encoding='utf8')
    links=[]
    for path in list(OUT.glob('*.html'))+list(OUT.glob('*.md')):
        source=path.read_text(encoding='utf8')
        items=[tag.get('href') for tag in BeautifulSoup(source,'html.parser').select('[href]')] if path.suffix=='.html' else re.findall(r'\]\(([^)]+)\)',source)
        for item in items:
            parsed=urlsplit(item)
            if parsed.scheme or not parsed.path:continue
            target=(path.parent/unquote(parsed.path)).resolve();assert target.exists(),(path,item)
            links.append(str(target.relative_to(ROOT)))
    data=json.loads((HERE/'報告データ.json').read_text(encoding='utf8'))
    for path,sha in data['過去HTML指紋'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha
    proof=dict(全合格=True,相対リンク数=len(links),過去HTML不変=True,対象=links)
    (HERE/'公表確認.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print('00044の索引・相対リンク・過去HTML不変を確認',flush=True)


if __name__=='__main__':main()
