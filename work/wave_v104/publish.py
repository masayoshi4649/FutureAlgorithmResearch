"""独立検算と根の目視後、新00100だけを公開して最新案内を更新する。"""

import argparse
import json
from pathlib import Path
import re
import shutil

import base


HERE = Path(__file__).resolve().parent
FOLDER = '00100_支持境界と利益追尾による毎場の損失抑制'
TITLE = '支持境界と利益追尾の説明と全セッション損益.html'


def main() -> None:
    """
    機能: 独立監査と目視が済んだ新資料を公開し、既存本文を保持して三案内を更新する。
    引数: CLI --root-viewed(bool)は実画像目視の完了確認。
    返り値: None。過去の作業フォルダや生データは変更しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--root-viewed', action='store_true', required=True)
    parser.parse_args()
    generated = base.read(HERE/'report/生成結果.json')
    reviewed = base.read(HERE/'report/独立HTML全場照合.json')
    viewed = base.read(HERE/'report/根担当の目視確認.json')
    assert generated['全合格'] and reviewed['全合格'] and viewed['全合格']
    assert generated['HTML_SHA256'] == reviewed['HTML_SHA256'] == viewed['HTML_SHA256']
    assert base.digest(HERE/'report/preview'/TITLE) == generated['HTML_SHA256']
    assert base.digest(HERE/'report/preview/公開会計.json') == generated['会計SHA256']
    for name, wanted in viewed['画像SHA256'].items():
        assert base.digest(base.ROOT/name) == wanted
    # ----------------------------------------
    # 案内の既存文章を先に照合し、変更対象以外を保存する。
    guide = base.ROOT/'アルゴリズム調査/README.md'
    index = base.ROOT/'アルゴリズム調査/index.html'
    root_guide = base.ROOT/'README.md'
    before = {str(path.relative_to(base.ROOT)): base.digest(path) for path in (guide, index, root_guide)}
    current = guide.read_text(encoding='utf-8')
    assert '<!--00100案内開始-->' not in current
    current = current.replace('**最新は00099の', '**00099の', 1)
    entry = f'<!--00100案内開始-->\n**最新は00100の[説明と全セッション損益]({FOLDER}/{TITLE})。支持境界と利益追尾、配分を121条件で比較。最大収益より毎場の損失を優先。**\n\n[読む順序]({FOLDER}/README.md) · [全会計]({FOLDER}/公開会計.json)。旧32と追加Dayは分けて掲載し、無取引は勝ちに含めません。\n<!--00100案内終了-->\n\n'
    first, rest = current.split('\n', 1)
    new_guide = first+'\n\n'+entry+rest.lstrip('\n')
    current = index.read_text(encoding='utf-8')
    assert '<!--00100開始-->' not in current and '<!--00099開始-->' in current
    current = current.replace('class="task latest"', 'class="task"').replace('<span class="badge">最新</span>', '')
    current = current.replace('作業00099 · 最新', '作業00099')
    current, count = re.subn(r'<p class="lead">.*?</p>', '<p class="lead">最新00100：支持境界と利益追尾。121条件の毎場の損失を比較。</p>', current, count=1)
    assert count == 1
    entry = f'<!--00100開始--><article class="task latest"><div class="number">作業00100 <span class="badge">最新</span></div><h2>支持境界と利益追尾による毎場の損失抑制</h2><p>121条件。赤字の頻度・損失規模・大勝ち依存を比較。配分はTOPIX10枚・日経20枚。全場の利益・損失・収支を掲載。</p><a class="button" href="{FOLDER}/{TITLE}">説明と全セッション損益</a> <a href="{FOLDER}/README.md">読む順序</a></article><!--00100終了-->\n'
    new_index = current.replace('<!--00099開始-->', entry+'<!--00099開始-->', 1)
    current = root_guide.read_text(encoding='utf-8')
    new_root, count = re.subn(r'最新の調査は .*?(?=\n\n)',
        f'最新の調査は **[00100：支持境界と利益追尾による毎場の損失抑制](アルゴリズム調査/{FOLDER}/{TITLE})** です。121条件の赤字頻度・損失規模・大勝ち依存を比較。[読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。両銘柄の安定収益と金額利益80%への調査は継続中です。', current, count=1)
    assert count == 1
    # ----------------------------------------
    # 未使用番号へ今回の結果を公開して、照合済み案内だけを書き換える。
    target = base.ROOT/'アルゴリズム調査'/FOLDER
    assert not target.exists()
    assert before == {name: base.digest(base.ROOT/name) for name in before}
    target.mkdir()
    for name in (TITLE, '公開会計.json'):
        shutil.copyfile(HERE/'report/preview'/name, target/name)
    (target/'README.md').write_text(
        '# 支持境界と利益追尾による毎場の損失抑制\n\n'
        f'最初に[短い説明と全セッション損益]({TITLE})を見てください。最大収益より、赤字頻度・損失規模・大勝ちへの依存を優先した121条件の比較です。\n\n'
        '読む順序は、HTMLの結論と比較表 → 各手法を開いた全セッション損益 → [公開会計](公開会計.json)です。\n\n'
        '単一手法は各商品1枚。二手法の配分はTOPIXミニ合計10枚、日経マイクロ合計20枚。利益・損失は手数料後、相殺前の取引別集計です。無取引を勝ちに含めません。\n\n'
        '[検証コード](../../work/wave_v104/research.py)、[金融前固定](../../work/wave_v104/金融事前固定.json)、[採用基準](../../work/wave_v104/安定性の採用基準補足.json)、[損失診断](../../work/wave_v104/支持幅と再参加及び利益保険の損失診断.json)を保存しています。\n', encoding='utf-8')
    for path, updated in ((guide, new_guide), (index, new_index), (root_guide, new_root)):
        path.write_text(updated, encoding='utf-8')
    proof = dict(全合格=True, フォルダ=str(target.relative_to(base.ROOT)),
        公開HTML_SHA256=base.digest(target/TITLE), 公開会計_SHA256=base.digest(target/'公開会計.json'),
        目視確認SHA256=base.digest(HERE/'report/根担当の目視確認.json'),
        独立HTML照合SHA256=base.digest(HERE/'report/独立HTML全場照合.json'),
        案内変更前=before, 案内変更後={name: base.digest(base.ROOT/name) for name in before},
        過去作業フォルダ変更=0, 原データ変更=0, 現在API=0, 実注文=0)
    (HERE/'report/公開結果.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('新00100と三つの案内を更新しました。', flush=True)


if __name__ == '__main__':
    main()
