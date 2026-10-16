"""全範囲検算と表示確認後に00091を保存し、最新案内を更新する。"""

import hashlib
import json
from pathlib import Path
import re
import shutil


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
RESEARCH = ROOT / 'アルゴリズム調査'
FOLDER = '00091_両市場追従と損失後の反転確認'
OUT = RESEARCH / FOLDER
MAIN = OUT / '両市場追従と反転確認の説明と全セッション損益.html'


def read(path: Path) -> dict:
    """
    機能: 確定した日本語JSONを読む。
    引数: path(Path)。
    返り値: dictは資料内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    """
    機能: 内容を分割して公開成果の指紋を求める。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def hashes(values: dict) -> None:
    """
    機能: 相対位置と内容指紋の一致を検査する。
    引数: values(dict[str,str])。
    返り値: None。不一致を公開前に拒否する。
    """
    for relative, expected in values.items():
        assert sha(ROOT / relative) == expected, relative


def prior_files() -> dict:
    """
    機能: 直前三作業の全成果を指紋化する。
    引数: なし。
    返り値: dict[str,str]は旧公開ファイルの全指紋。
    """
    folders = ('00090_独立価格と現在確認によるセッション安定化',
               '00089_予定リスクと中心利確及び失敗後再参加',
               '00088_回復確認と中心帰還による再参加')
    assert all((RESEARCH / name).is_dir() for name in folders)
    return {str(path.relative_to(ROOT)): sha(path) for name in folders
            for path in sorted((RESEARCH / name).rglob('*')) if path.is_file()}


def evidence(manifest: dict, name: str) -> tuple[Path, dict]:
    """
    機能: 完了証跡のSHAと明示された合格値を確認する。
    引数: manifest(dict)、name(str)。
    返り値: tuple[Path,dict]は現在内容と一致した資料。
    """
    item = manifest['資料'][name]
    path = ROOT / item['path']
    assert sha(path) == item['SHA256'], name
    value = read(path)
    for key, expected in item['必須値'].items():
        assert value[key] == expected, (name, key)
    hashes(value.get('SHA256', {}))
    return path, value


def main() -> None:
    """
    機能: 全2356口座と608商品期間の独立照合・五画面確認後に公開する。
    引数: なし。
    返り値: Noneは新成果と最新リンクの保存。旧作業は変更しない。
    """
    manifest_path = HERE / '公開確定指紋.json'
    manifest = read(manifest_path)
    assert manifest['確定済み'] and manifest['全31既知']
    old_path = HERE / '旧00090_00089_00088公開成果の保持.json'
    old = read(old_path)['全旧成果SHA256']
    assert prior_files() == old
    _, fixed = evidence(manifest, '事前固定')
    assert fixed['正式新条件損益前固定'] and fixed['全31既知']
    assert len(fixed['条件']) == 38 and fixed['主'] == 'P3_R3_N'
    _, selection = evidence(manifest, '前16参考')
    assert selection['後15正式損益前選定'] and selection['固定SHA256'] == sha(WORK / '事前固定.json')
    hashes(selection['結果SHA256'])
    account_path, account = evidence(manifest, '正式会計')
    assert account['catalog'] == fixed['条件'] and account['sessions'] == fixed['全31']
    assert account['selected'] == selection['selected'] and account['primary'] == fixed['主']
    assert sum(len(value['rows']) for value in account['results'].values()) == 2356
    assert sum(len(value['periods']) * 2 for value in account['results'].values()) == 608
    assert sum(len(value['stability']) * 2 for value in account['results'].values()) == 608
    hashes(account['正式結果SHA256'])
    # ----------------------------------------
    # 全範囲・参考選定・原因の独立証跡は、確定資料で指定した件数まで検査する。
    for name in ('全範囲独立検算', '独立参考選定', '独立原因会計', '独立原因状態', '最悪場原板'):
        evidence(manifest, name)
    supplement_path, supplement = evidence(manifest, '説明補足')
    assert supplement['根集計SHA256'] == sha(account_path)
    assert supplement['正式全範囲独立検算完了'] and supplement['独立原因検査完了']
    assert supplement['売買及び会計の変更'] == 0
    hashes(supplement['根拠SHA256'])
    display = read(HERE / '表示の独立検査.json')
    generated = read(HERE / '生成結果.json')
    root_visual = read(HERE / '根担当の五画面目視.json')
    assert display['全合格'] and root_visual['全合格']
    assert display['保存結果一致数'] == generated['条件数'] == 38
    assert display['保存会計口座数'] == generated['口座数'] == 2356
    assert display['HTML_SHA256'] == generated['HTML_SHA256'] == root_visual['HTML_SHA256'] == sha(MAIN)
    assert len(display['画面']) == len(root_visual['確認画像SHA256']) == 5
    assert all(value['全合格'] and value['条件切替数'] == 38
               and value['セッション口座表示数'] == 2356 and value['JavaScriptエラー'] == 0
               for value in display['画面'])
    hashes(root_visual['確認画像SHA256'])
    hashes(generated['使用資料SHA256'])
    assert generated['使用資料SHA256'][str(supplement_path.relative_to(ROOT))] == sha(supplement_path)
    # ----------------------------------------
    # 検算済みの成果を保存し、旧リンクを残したまま最新案内を移す。
    shutil.copyfile(account_path, OUT / '公開会計.json')
    assert sha(OUT / '公開会計.json') == sha(account_path)
    guide = (HERE / 'README.template.md').read_text(encoding='utf-8').replace(
        '__SUMMARY__', '\n\n'.join(supplement['conclusion'][:3]))
    assert '__SUMMARY__' not in guide
    (OUT / 'README.md').write_text(guide, encoding='utf-8')
    root_readme = ROOT / 'README.md'
    text = root_readme.read_text(encoding='utf-8')
    line = (f'最新の調査は **[00091：両市場追従と損失後の反転確認]'
            f'(アルゴリズム調査/{FOLDER}/{MAIN.name})** です。38条件・全31既知場の赤字抑制と'
            f'全場損益を比較。[読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。'
            '両銘柄の安定収益と金額利益80%への調査は継続中です。')
    text, count = re.subn(r'^最新の調査は .*$', lambda match: line, text, count=1, flags=re.M)
    assert count == 1
    root_readme.write_text(text, encoding='utf-8')
    research_readme = RESEARCH / 'README.md'
    text = research_readme.read_text(encoding='utf-8')
    if '<!--00091案内開始-->' not in text:
        block = (f'<!--00091案内開始-->\n**最新は00091の[{MAIN.name}]({FOLDER}/{MAIN.name})。'
                 '38条件・全31場の赤字額と活動黒字数を比較。**\n\n'
                 f'[読む順序]({FOLDER}/README.md) · [公開会計]({FOLDER}/公開会計.json)。'
                 '全31は既知期間です。\n<!--00091案内終了-->\n\n')
        assert '<!--00090案内開始-->' in text
        text = text.replace('**最新は00090の', '**00090の', 1)
        text = text.replace('<!--00090案内開始-->', block + '<!--00090案内開始-->', 1)
    research_readme.write_text(text, encoding='utf-8')
    index = RESEARCH / 'index.html'
    text = index.read_text(encoding='utf-8')
    if '<!--00091開始-->' not in text:
        text = text.replace('class="task latest"', 'class="task"').replace(' <span class="badge">最新</span>', '')
        article = ('<!--00091開始--><article class="task latest"><div class="number">作業00091 '
                   '<span class="badge">最新</span></div><h2>両市場追従と損失後の反転確認</h2>'
                   '<p>38条件・全31既知場。最大利益より赤字場数・平均赤字・最大赤字を重視。</p>'
                   f'<a class="button" href="{FOLDER}/{MAIN.name}">説明と全場損益</a> '
                   f'<a href="{FOLDER}/README.md">読む順序</a></article><!--00091終了-->\n')
        assert '<!--00090開始-->' in text
        text = text.replace('<!--00090開始-->', article + '<!--00090開始-->', 1)
    text, count = re.subn(r'<p class="lead">最新00090：.*?</p>',
                         '<p class="lead">最新00091：両市場追従と反転確認。全31場の損失と安定性を比較。</p>',
                         text, count=1)
    assert count == 1
    index.write_text(text, encoding='utf-8')
    assert prior_files() == old
    outputs = [MAIN, OUT / 'README.md', OUT / '公開会計.json', root_readme, research_readme, index]
    proof = dict(全合格=True, 全口座=2356, 商品期間集計=608, 全31既知=True, 新未見確認場数=0,
                 旧成果不変=True, 根担当五画面目視確認=True, 条件及び参考の差替え=False,
                 公開指紋={str(path.relative_to(ROOT)): sha(path) for path in outputs},
                 公開確定指紋SHA256=sha(manifest_path), API取得=0, 実注文=0)
    (HERE / '公開結果.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
