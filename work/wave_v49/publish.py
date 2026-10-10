"""新作業への索引を更新し、公開資料の相対リンクを確認する。"""

from pathlib import Path
import json
import re
from urllib.parse import unquote,urlsplit
from bs4 import BeautifulSoup
from build_report import ROOT,OUT,HERE


def main():
    """機能: 00043を最新作業として案内し、既存成果は保持する。

    引数: なし。返り値: なし(None)。
    """
    folder=OUT.name
    lead='最新00043：9月30日ナイトの赤字原因と、見送り・追従反復・時間短縮・支持抵抗・早期保護を16セッションで比較。'
    index=ROOT/'アルゴリズム調査/index.html';text=index.read_text(encoding='utf8')
    text=re.sub(r'<p class="lead">.*?</p>',lambda _: '<p class="lead">'+lead+'</p>',text,count=1,flags=re.S)
    text=re.sub(r'<!--00043開始-->.*?<!--00043終了-->','',text,flags=re.S)
    def former(match):
        """機能: 旧作業の最新表示だけを外す。

        引数: match(re.Match)。返り値: 旧記事(str)。
        """
        return match.group().replace('class="task latest"','class="task"').replace('最新・検算完了','固定4候補')
    text=re.sub(r'<!--00042開始-->.*?<!--00042終了-->',former,text,flags=re.S)
    card=f'<!--00043開始--><article class="task latest"><div class="number">作業00043 <span class="badge">最新・検算完了</span></div><h2>赤字原因と改善案の検証</h2><p>今回の損失を入口・途中・出口へ分解。見送り、板、追従と反復、時間短縮、支持抵抗、早期保護を比較し、全セッションの金額と決済枚数を表示。</p><a class="button" href="{folder}/赤字原因と改善案の検証.html">短い結論と全方式の損益 →</a><p><a href="{folder}/README.md">読む順序・再現方法</a></p></article><!--00043終了-->'
    text=text.replace('</header>','</header>'+card,1);index.write_text(text,encoding='utf8')
    readme=ROOT/'アルゴリズム調査/README.md';text=readme.read_text(encoding='utf8')
    newest=f'**最新は00043の[赤字原因と改善案の検証]({folder}/赤字原因と改善案の検証.html)。赤字原因、見送り・モード切替・時間短縮・支持抵抗・早期保護の16場比較。各方式の金額と決済枚数を表示。**'
    text=re.sub(r'\*\*最新は.*?\*\*',lambda _: newest,text,count=1)
    text=re.sub(r'^\| `00043_.*?\n','',text,flags=re.M)
    text=text.replace('`00042_有望4手法の説明とセッション損益`（最新）','`00042_有望4手法の説明とセッション損益`')
    newrow=f'| `{folder}`（最新） | 赤字原因と見送り・自動モード・早期出口 | [原因と比較]({folder}/赤字原因と改善案の検証.html) | [資料案内]({folder}/README.md) |\n'
    text=text.replace('| --- | --- | --- | --- |\n','| --- | --- | --- | --- |\n'+newrow,1);readme.write_text(text,encoding='utf8')
    # ----------------------------------------
    # HTMLと資料READMEの相対リンクを検算し、存在しない資料を公開しない。
    checked=[]
    for path in list(OUT.rglob('*.html'))+list(OUT.rglob('*.md')):
        source=path.read_text(encoding='utf8')
        if path.suffix=='.html':
            soup=BeautifulSoup(source,'html.parser');links=[tag.get('href') or tag.get('src') for tag in soup.select('[href],[src]')]
        else:links=re.findall(r'\]\(([^)]+)\)',source)
        for link in links:
            parsed=urlsplit(link)
            if parsed.scheme or not parsed.path:continue
            target=(path.parent/unquote(parsed.path)).resolve()
            assert target.exists(),(path,link)
            checked.append(str(target.relative_to(ROOT)))
    (HERE/'リンク確認.json').write_text(json.dumps(dict(合格=True,確認数=len(checked),対象=checked),ensure_ascii=False,indent=2),encoding='utf8')
    print('索引更新・相対リンク確認完了',flush=True)


if __name__=='__main__':main()
