"""反復中の調査結果を、過去の成果を保持して最新の入口へ載せる。"""

import json
import re
from pathlib import Path

import analyze
import build

HERE = Path(__file__).resolve().parent


def main():
    """
    機能: 数値と画面の検証を確認し、各索引と公開指紋を更新する。
    引数: なし。
    返り値: None。旧00082の本文と成果は保持する。
    """
    proof = analyze.read(HERE / '公開数値照合.json')
    display = analyze.read(HERE / '表示の独立検査.json')
    assert proof['全合格'] and display['全合格'] and display['目視確認']
    assert analyze.sha(build.PUBLIC / build.MAIN) == display['公開SHA256']
    old = build.ROOT / 'アルゴリズム調査/00082_E01の狭幅トレールと再エントリー'
    before = {str(p.relative_to(build.ROOT)): analyze.sha(p) for p in old.iterdir() if p.is_file()}
    root_readme = build.ROOT / 'README.md'
    content = root_readme.read_text(encoding='utf-8')
    line = f'最新の調査は **[00083：再参加の損失原因と改善の反復検証](アルゴリズム調査/{build.FOLDER}/{build.MAIN})** です。原因を保存原板で確認し、入口・損切り・部分利確を全30場で検証しています。調査は継続中です。[読む順序](アルゴリズム調査/{build.FOLDER}/README.md)も参照してください。'
    content, count = re.subn(r'^最新の調査は .*$', line, content, count=1, flags=re.MULTILINE)
    assert count == 1
    root_readme.write_text(content, encoding='utf-8')
    # ----------------------------------------
    # 最新の案内のみ更新し、過去作業の本文と数値を保つ。
    research_readme = build.ROOT / 'アルゴリズム調査/README.md'
    text = research_readme.read_text(encoding='utf-8')
    text = re.sub(r'<!--00083案内開始-->.*?<!--00083案内終了-->\s*', '', text, flags=re.DOTALL)
    text = text.replace('**最新は00082の', '**00082の')
    block = f'''<!--00083案内開始-->
**最新は00083の[{build.MAIN}]({build.FOLDER}/{build.MAIN})。具体的な損失原因と、原因に基づく改修の全30セッション結果。改善を反復中です。**

[読む順序]({build.FOLDER}/README.md) · [公開会計]({build.FOLDER}/公開会計.json)。
<!--00083案内終了-->

'''
    first, rest = text.split('\n', 1)
    research_readme.write_text(first+'\n\n'+block+rest.lstrip(), encoding='utf-8')
    index = build.ROOT / 'アルゴリズム調査/index.html'
    text = index.read_text(encoding='utf-8')
    text = re.sub(r'<!--00083開始-->.*?<!--00083終了-->\s*', '', text, flags=re.DOTALL)
    text = text.replace('class="task latest"', 'class="task"').replace('<span class="badge">最新</span>', '')
    text = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新00083：再参加の損失原因を原板で確認し、改善を全30場で反復検証しています。</p>', text, count=1, flags=re.DOTALL)
    article = f'''\n<!--00083開始--><article class="task latest"><div class="number">作業00083 <span class="badge">最新</span></div><h2>再参加の損失原因と改善の反復検証</h2><p>どの値動きで失敗したかを確認し、入口・初期停止・部分利確を検証。具体例の図と全セッションの損益を掲載しています。調査継続中。</p><a class="button" href="{build.FOLDER}/{build.MAIN}">原因と改善の結果</a> <a href="{build.FOLDER}/README.md">読む順序</a></article><!--00083終了-->\n'''
    assert '</header>' in text
    index.write_text(text.replace('</header>', '</header>'+article, 1), encoding='utf-8')
    for name, digest in before.items():
        assert analyze.sha(build.ROOT / name) == digest
    output = dict(全合格=True, 旧00082保持=before,
                  公開SHA256={p.name: analyze.sha(p) for p in build.PUBLIC.iterdir()
                              if p.is_file() and p.name != '公開指紋.json'})
    (build.PUBLIC / '公開指紋.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('00083の入口を更新。調査は継続中。旧00082全ファイル保持。')


if __name__ == '__main__':
    main()
