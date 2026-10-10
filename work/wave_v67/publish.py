"""00064の案内を作業一覧へ追加し、成果へのリンクを検査する。"""

import json
from pathlib import Path
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

import report

HERE = Path(__file__).resolve().parent
INDEX = report.ROOT / 'アルゴリズム調査/index.html'
README = INDEX.parent / 'README.md'
FOLDER = report.OUT.name


def main() -> None:
    """機能: 新作業を最新として登録し、旧案内・成果へのリンクを維持する。

    引数: なし。返り値: なし(None)。
    """
    for name in ('事前固定.json', '接続器の因果検査.json', '報告選定と安定性.json'):
        assert (HERE / name).exists()
    proof = json.loads((HERE / 'audit/E01と改修全32条件の独立FIFO会計.json').read_text(encoding='utf8'))
    assert proof['口座照合数'] == 1792 and len(proof['条件別']) == 32
    assert all(r['FIFOと料金と全期間一致'] for r in proof['条件別'])
    source = INDEX.read_text(encoding='utf8')
    source = source.replace('class="task latest"', 'class="task"').replace(' <span class="badge">最新</span>', '')
    source = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新00064：元E01と15改修を、保存28場・手数料込みで比較。</p>', source, count=1)
    block = f'''<!--00064開始--><article class="task latest"><div class="number">作業00064 <span class="badge">最新</span></div><h2>E01への回帰と知見を用いた改修</h2><p>元E01の完全再現、EMA再確認・途中撤退・利益保護・再参加の16条件。全28場の金額・枚数、2約定モデル、売買気配感度、5分足売買図。</p><a class="button" href="{FOLDER}/E01と改修の説明と全セッション損益.html">E01と改修の説明・損益を開く →</a><p><a href="{FOLDER}/全16改修条件.html">全16改修条件</a> · <a href="{FOLDER}/検証結果.md">短い検証結果</a> · <a href="{FOLDER}/README.md">資料案内</a></p></article><!--00064終了-->'''
    if '<!--00064開始-->' in source:
        source = re.sub(r'<!--00064開始-->.*?<!--00064終了-->', block, source, flags=re.S)
    else:
        source = source.replace('<!--00063開始-->', block + '\n<!--00063開始-->', 1)
    INDEX.write_text(source, encoding='utf8')
    text = README.read_text(encoding='utf8').replace('**最新は00063', '**00063')
    guide = f'''<!--00064案内開始-->
**最新は00064の[E01と改修の説明と全セッション損益]({FOLDER}/E01と改修の説明と全セッション損益.html)。元E01と15改修を保存28場・手数料込みで比較。前16選択／後12確認、金額と枚数、指定値／観測値、気配感度、5分足売買図。**

[全16改修条件]({FOLDER}/全16改修条件.html) · [短い検証結果]({FOLDER}/検証結果.md) · [資料案内]({FOLDER}/README.md)。
<!--00064案内終了-->
'''
    if '<!--00064案内開始-->' in text:
        text = re.sub(r'<!--00064案内開始-->.*?<!--00064案内終了-->\n?', guide, text, flags=re.S)
    else:
        text = text.replace('<!--00063案内開始-->', guide + '\n<!--00063案内開始-->', 1)
    README.write_text(text, encoding='utf8')
    links = []
    for path in (INDEX, report.OUT / 'E01と改修の説明と全セッション損益.html', report.OUT / '全16改修条件.html'):
        for tag in BeautifulSoup(path.read_text(encoding='utf8'), 'html.parser').select('a[href]'):
            href = tag['href']
            if href.startswith(('http', '#')):
                continue
            target = (path.parent / unquote(href.split('?', 1)[0].split('#', 1)[0])).resolve()
            assert target.exists(), target
            links.append(str(target))
    (HERE / '公開リンク照合.json').write_text(json.dumps(dict(全合格=True, 確認リンク数=len(links),
        公開先=str(report.OUT), 最新作業='00064'), ensure_ascii=False, indent=2), encoding='utf8')
    print('00064を一覧へ登録し、成果と全既存リンクを照合しました')


if __name__ == '__main__':
    main()
