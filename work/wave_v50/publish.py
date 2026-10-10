"""新作業の資料と最新リンクを公表し、相対リンクを確認する。"""

import hashlib
import json
import re
import shutil
from urllib.parse import unquote,urlsplit
from bs4 import BeautifulSoup
from build_report import ROOT,HERE,OUT,TITLE


def main():
    """機能: 監査済み00044の更新を索引へ反映し、後続の作業案内も維持する。

    引数: なし。返り値: なし(None)。過去作業の成果は変更しない。
    """
    data=json.loads((HERE/'報告データ.json').read_text(encoding='utf8'))
    count=data['対象セッション数']
    html_sha=hashlib.sha256((OUT/TITLE).read_bytes()).hexdigest()
    for name in ('独立確認.json','表示確認.json'):
        proof=json.loads((HERE/name).read_text(encoding='utf8'))
        assert proof['全合格']
        stored_sha=proof.get('HTML_SHA256',proof.get('HTML指紋'))
        if stored_sha is not None:assert stored_sha==html_sha
        shutil.copy2(HERE/name,OUT/'検証資料'/name)
    folder=OUT.name;index=ROOT/'アルゴリズム調査/index.html'
    text=index.read_text(encoding='utf8')
    later = any(int(p.name[:5]) > 44 for p in index.parent.iterdir()
                if p.is_dir() and re.match(r'^\d{5}_', p.name))
    latest_session=max(r['session'] for r in data['候補'][0]['sessions']).replace('_Day',' デイ').replace('_Night',' ナイト').replace('-','/')
    lead=f'最新00044：{latest_session}まで全{count}セッション。新候補E01・E08と元の候補1の説明、各場・週別の金額／枚数を比較。'
    if not later:
        text=re.sub(r'<p class="lead">.*?</p>',lambda _:'<p class="lead">'+lead+'</p>',text,count=1,flags=re.S)
    else:
        text=re.sub(r'<p data-update="00044">.*?</p>','',text,flags=re.S)
        text=text.replace('</header>',f'<p data-update="00044">損益レポート00044を更新：{latest_session}まで全{count}セッション。</p></header>',1)
    def former(match):
        """機能: 直前の作業から最新表示だけを外す。

        引数: match(re.Match)。返り値: 旧記事(str)。
        """
        return match.group().replace('class="task latest"','class="task"').replace('最新・検算完了','比較調査')
    text=re.sub(r'<!--00043開始-->.*?<!--00043終了-->',former,text,flags=re.S)
    card=f'<!--00044開始--><article class="task latest"><div class="number">作業00044 <span class="badge">最新・検算完了</span></div><h2>新候補2手法と基準の説明・セッション損益</h2><p>E01・E08と元の候補1を00042と同じ形式で整理。{latest_session}まで全{count}セッション。入口・途中・出口の説明、各場・週・全期間の利益／損失／収支と決済枚数。</p><a class="button" href="{folder}/{TITLE}">新候補の説明と各セッション損益 →</a><p><a href="{folder}/README.md">読む順序・数量前提・検算資料</a></p></article><!--00044終了-->'
    if later:
        card=card.replace('class="task latest"','class="task"').replace('最新・検算完了','更新・検算完了')
    if '<!--00044開始-->' in text:
        text=re.sub(r'<!--00044開始-->.*?<!--00044終了-->',lambda _:card,text,flags=re.S)
    else:
        text=text.replace('</header>','</header>'+card,1)
    index.write_text(text,encoding='utf8')
    readme=ROOT/'アルゴリズム調査/README.md';text=readme.read_text(encoding='utf8')
    latest=f'**最新は00044の[新候補2手法の説明と損益]({folder}/{TITLE})。{latest_session}まで全{count}セッション。E01・E08と元の候補1の入口・途中・出口、各場・週別の金額と決済枚数を00042形式で表示。**'
    if not later:
        text=re.sub(r'\*\*最新は.*?\*\*',lambda _:latest,text,count=1)
    else:
        text=re.sub(r'\n<!--00044更新開始-->.*?<!--00044更新終了-->\n','\n',text,flags=re.S)
        note=f'\n<!--00044更新開始-->\n**00044更新：[{latest_session}まで全{count}セッションの損益]({folder}/{TITLE})。**\n<!--00044更新終了-->\n'
        text=text.replace('\n\n','\n'+note+'\n',1)
    text=text.replace('`00043_赤字原因とエントリー見送り`（最新）','`00043_赤字原因とエントリー見送り`')
    row=f'| `{folder}`（最新） | 新候補E01・E08と元基準の説明・{count}場損益 | [説明と損益]({folder}/{TITLE}) | [資料案内]({folder}/README.md) |\n'
    if later:
        row=row.replace('（最新）','（更新）')
    if re.search(r'^\| `00044_',text,re.M):
        text=re.sub(r'^\| `00044_.*?\n',lambda _:row,text,flags=re.M)
    else:
        text=text.replace('| --- | --- | --- | --- |\n','| --- | --- | --- | --- |\n'+row,1)
    readme.write_text(text,encoding='utf8')
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
