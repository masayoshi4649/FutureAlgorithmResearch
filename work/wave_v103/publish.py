"""根担当の目視後、今回の新作業だけを公開して三つの案内を更新する。"""

import argparse
import json
from pathlib import Path
import re
import runpy
import shutil


HERE = Path(__file__).resolve().parent
RESEARCH = runpy.run_path(str(HERE/'research.py'))
ROOT = RESEARCH['ROOT']
FOLDER = '00099_板の定着と進行失敗の入口検証'
TITLE = '板の定着と進行失敗の説明と全セッション損益.html'


def main() -> None:
    """
    機能: 根担当が見た資料を未使用00099へ保存し、最新の入口を明確にする。
    引数: CLI --root-viewed(bool)は独立監査後の実画像目視が済んだこと。
    返り値: None。過去の作業フォルダや原データを変更しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--root-viewed', action='store_true', required=True)
    parser.parse_args()
    read, digest, save = (RESEARCH[name] for name in ('read', 'digest', 'save'))
    generated = read(HERE/'report/生成結果_最終.json')
    viewed = read(HERE/'report/根担当の目視確認.json')
    assert generated['全合格'] and viewed['全合格'] and viewed['HTML_SHA256'] == generated['HTML_SHA256']
    for name, wanted in viewed['画像SHA256'].items():
        assert digest(ROOT/name) == wanted
    assert digest(ROOT/generated['HTML']) == generated['HTML_SHA256']
    target = ROOT/'アルゴリズム調査'/FOLDER
    assert not target.exists()
    target.mkdir()
    for name in (TITLE, '公開会計.json'):
        shutil.copyfile(HERE/'report/preview_final'/name, target/name)
    (target/'README.md').write_text(
        '# 板の定着と進行失敗の入口検証\n\n'
        f'最初に[説明と全32セッション損益]({TITLE})を見てください。最大収益より、赤字の頻度と損失規模を優先した19条件の比較です。\n\n'
        '読む順序は、HTMLの結論と比較表 → 各手法を開いた全セッション損益 → [公開会計](公開会計.json)です。\n\n'
        '保存済み32セッションは既知です。無取引は勝ちに含めず、両商品を個別に評価します。単一条件は各商品1枚、配分はTOPIX10枚・日経20枚です。\n\n'
        '[検証コード](../../work/wave_v103/research.py)、[金融事前固定](../../work/wave_v103/金融事前固定.json)、[安定性評価](../../work/wave_v103/金融結果前の安定性評価.json)を保存しています。\n', encoding='utf-8')
    guide = ROOT/'アルゴリズム調査/README.md'
    before = {str(path.relative_to(ROOT)): digest(path) for path in
        (guide, ROOT/'アルゴリズム調査/index.html', ROOT/'README.md')}
    current = guide.read_text(encoding='utf-8')
    current = current.replace('**最新は00098の', '**00098の', 1)
    entry = f'<!--00099案内開始-->\n**最新は00099の[説明と全32セッション損益]({FOLDER}/{TITLE})。板の定着・進行失敗と部品対照・配分の19条件。赤字頻度と損失規模を優先して比較。**\n\n[読む順序]({FOLDER}/README.md) · [全会計]({FOLDER}/公開会計.json)。無取引は勝ちに含めず、既知32場として評価。\n<!--00099案内終了-->\n\n'
    assert '<!--00099案内開始-->' not in current
    first, rest = current.split('\n', 1)
    guide.write_text(first+'\n\n'+entry+rest.lstrip('\n'), encoding='utf-8')
    index = ROOT/'アルゴリズム調査/index.html'
    current = index.read_text(encoding='utf-8')
    current = current.replace('class="task latest"', 'class="task"').replace('<span class="badge">最新</span>', '')
    current = current.replace('作業00098 · 最新', '作業00098')
    current, count = re.subn(r'<p class="lead">.*?</p>', '<p class="lead">最新00099：板の定着と進行失敗。全32場の赤字頻度と損失規模を比較。</p>', current, count=1)
    assert count == 1 and '<!--00099開始-->' not in current
    entry = f'<!--00099開始--><article class="task latest"><div class="number">作業00099 <span class="badge">最新</span></div><h2>板の定着と進行失敗の入口検証</h2><p>19条件・全32場。利益額の最大化より、毎場の赤字頻度と損失規模を優先。全セッションの相殺前利益・損失・収支を掲載。</p><a class="button" href="{FOLDER}/{TITLE}">説明と全セッション損益</a> <a href="{FOLDER}/README.md">読む順序</a></article><!--00099終了-->\n'
    current = current.replace('<!--00098開始-->', entry+'<!--00098開始-->', 1)
    index.write_text(current, encoding='utf-8')
    root_guide = ROOT/'README.md'
    current = root_guide.read_text(encoding='utf-8')
    current, count = re.subn(r'最新の調査は .*?(?=\n\n)',
        f'最新の調査は **[00099：板の定着と進行失敗の入口検証](アルゴリズム調査/{FOLDER}/{TITLE})** です。19条件・全32場で赤字頻度と損失規模を比較。[読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。両銘柄の安定収益と金額利益80%への調査は継続中です。',
        current, count=1)
    assert count == 1
    root_guide.write_text(current, encoding='utf-8')
    save(HERE/'report/公開結果.json', dict(全合格=True, フォルダ=str(target.relative_to(ROOT)),
        公開HTML_SHA256=digest(target/TITLE), 公開会計_SHA256=digest(target/'公開会計.json'),
        目視確認SHA256=digest(HERE/'report/根担当の目視確認.json'),
        案内変更前=before, 案内変更後={name: digest(ROOT/name) for name in before},
        既存作業フォルダ変更=0, 原データ変更=0, API取得=0, 実注文=0))
    print('新00099と三つの入口を更新しました。', flush=True)


if __name__ == '__main__':
    main()
