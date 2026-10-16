"""完成した新作業の入口だけを各索引へ追加する。"""

import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
FOLDER = '00082_E01の狭幅トレールと再エントリー'
MAIN = '狭いトレールと再エントリーの結果.html'
PUBLIC = ROOT / 'アルゴリズム調査' / FOLDER


def main():
    """
    機能: 完成した数値・監査を確認し、過去レポートを変更せず入口を更新する。
    引数: なし。
    返り値: None。公開指紋と三つの案内を保存する。
    """
    proof = json.loads((HERE / '表示照合.json').read_text(encoding='utf-8'))
    assert proof['全合格'] and (PUBLIC / MAIN).is_file()
    display = json.loads((HERE / '表示の独立検査.json').read_text(encoding='utf-8'))
    assert display['全合格'] and display['目視確認']
    assert hashlib.sha256((PUBLIC / MAIN).read_bytes()).hexdigest() == display['公開SHA256']
    assert (WORK / 'audit/独立監査の最終確認.json').is_file()
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (ROOT / 'アルゴリズム調査/00081_E01原版と知見統合改修の再検証').glob('*') if p.is_file()}
    fixed = json.loads((WORK / '事前固定.json').read_text(encoding='utf-8'))
    (PUBLIC / '検証条件.json').write_text(json.dumps(fixed, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    extra = WORK / 'phase2/事前固定.json'
    if extra.exists():
        (PUBLIC / '追加検証条件.json').write_bytes(extra.read_bytes())
    count_label = str(proof['条件数'])
    root_readme = ROOT / 'README.md'
    content = root_readme.read_text(encoding='utf-8')
    line = f'最新の調査は **[00082：E01の狭幅トレールと再エントリー](アルゴリズム調査/{FOLDER}/{MAIN})** です。狭い出口と再参加の{count_label}条件を全30場で比較しました。[読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。'
    content, count = re.subn(r'^最新の調査は .*$', line, content, count=1, flags=re.MULTILINE)
    assert count == 1
    root_readme.write_text(content, encoding='utf-8')
    # ----------------------------------------
    # 新作業は先頭へ追加し、過去作業の結果本文と数値を保持する。
    readme = ROOT / 'アルゴリズム調査/README.md'
    text = readme.read_text(encoding='utf-8')
    text = re.sub(r'<!--00082案内開始-->.*?<!--00082案内終了-->\s*', '', text, flags=re.DOTALL)
    text = text.replace('**最新は00081の', '**00081の')
    block = f'''<!--00082案内開始-->
**最新は00082の[{MAIN}]({FOLDER}/{MAIN})。狭い出口と再参加頻度の組合せ{count_label}条件を、手数料後の全30セッションで比較。**

[読む順序]({FOLDER}/README.md) · [公開会計]({FOLDER}/公開会計.json)。
<!--00082案内終了-->

'''
    first, rest = text.split('\n', 1)
    readme.write_text(first+'\n\n'+block+rest.lstrip(), encoding='utf-8')
    index = ROOT / 'アルゴリズム調査/index.html'
    text = index.read_text(encoding='utf-8')
    text = re.sub(r'<!--00082開始-->.*?<!--00082終了-->\s*', '', text, flags=re.DOTALL)
    text = text.replace('class="task latest"', 'class="task"').replace('<span class="badge">最新</span>', '')
    text = re.sub(r'<p class="lead">.*?</p>', f'<p class="lead">最新00082：E01のトレール幅と再参加頻度を{count_label}条件で比較。短い結論と全30セッション損益。</p>', text, count=1, flags=re.DOTALL)
    article = f'''\n<!--00082開始--><article class="task latest"><div class="number">作業00082 <span class="badge">最新</span></div><h2>E01の狭幅トレールと再エントリー</h2><p>細かく利確し、方向が続けば再参加する。狭幅・値動きによる短縮・利確後だけの再参加を、手数料後の全セッション損益で比較しました。</p><a class="button" href="{FOLDER}/{MAIN}">結論と全セッション損益</a> <a href="{FOLDER}/README.md">読む順序</a></article><!--00082終了-->\n'''
    assert '</header>' in text
    index.write_text(text.replace('</header>', '</header>'+article, 1), encoding='utf-8')
    for name, digest in before.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    output = dict(全合格=True, 過去00081保持=before,
        公開SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in PUBLIC.iterdir()
                    if p.is_file() and p.name != '公開指紋.json'})
    (PUBLIC / '公開指紋.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('00082の公開と入口を更新、00081全ファイル保持')


if __name__ == '__main__':
    main()
