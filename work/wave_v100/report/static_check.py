"""正式損益を読まず、報告の構文・34条件説明・公開前ガードだけを静的検査する。"""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]


def digest(path: Path) -> str:
    """
    機能: 検査したソースだけの指紋を取得する。
    引数: path(Path)はコード又は静的条件素材。
    返り値: strはSHA256。正式会計は読み込まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 出版を実行せず、全34純条件と新番号及び旧成果保持の静的整合を検査する。
    引数: なし。
    返り値: None。正式結果や公開前HTMLを生成しない検査証跡を保存する。
    """
    existing_html = {str(path.relative_to(HERE)): digest(path) for path in HERE.rglob('*.html')
                     if '公開前' in path.parts}
    for path in HERE.glob('*.py'):
        ast.parse(path.read_text(encoding='utf-8'))
    for name in ('main.js', 'probe.js', 'check_rule.js'):
        subprocess.run(['node', '--check', str(HERE / name)], check=True, capture_output=True)
    spec = importlib.util.spec_from_file_location('98静的表示条件の読取', WORK / 'catalog.py')
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)
    configs = catalog.catalog()
    static = dict(catalog=configs, primary=catalog.PRIMARY)
    material_path = HERE / '静的条件表示の素材.json'
    material_path.write_text(json.dumps(static, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    process = subprocess.run(['node', str(HERE / 'check_rule.js'), str(material_path)],
                             check=True, capture_output=True, text=True, encoding='utf-8')
    pure = json.loads(process.stdout)
    assert pure['全合格'] and pure['純条件説明検査'] == 34 and pure['会計読取'] == 0
    template = (HERE / 'template.html').read_text(encoding='utf-8')
    publish = (HERE / 'publish.py').read_text(encoding='utf-8')
    build = (HERE / 'build.py').read_text(encoding='utf-8')
    verify = (HERE / 'verify.py').read_text(encoding='utf-8')
    assert '00096 ·' in template and '正式34条件' in template
    assert 'https://kabucom.github.io/kabusapi/ptal/push.html' in template
    assert 'https://www.jpx.co.jp/derivatives/rules/trading-hours/' in template
    assert '運用区切りと実立会終了は別' in template
    assert '元候補から不利方向' in template and '実約定価格の保証ではない' in template
    assert "NAME = '00096_元候補からの入口価格上限と安定性'" in publish
    assert 'assert max(numbers) == 95' in publish and '(89, 90, 91, 92, 93, 94, 95)' in publish
    assert 'assert not target.exists()' in publish and 'folder.rglob' in publish
    assert "visual['表示検査SHA256']" in publish and "visual['生成結果SHA256']" in publish
    assert all('追いかける価格を制限した手法と全セッション損益.html' in source for source in (build, verify, publish))
    assert '口座数=2108' in build and '保存会計口座数=2108' in verify
    assert '条件数=34' in build and '保存結果一致数=34' in verify
    assert existing_html == {str(path.relative_to(HERE)): digest(path) for path in HERE.rglob('*.html')
                             if '公開前' in path.parts}, '静的検査では既存の公開前HTMLを変更しません'
    paths = [HERE / name for name in ('build.py', 'template.html', 'style.css', 'main.js', 'probe.js',
             'verify.py', 'publish.py', 'static_check.py', 'check_rule.js', '静的条件表示の素材.json')]
    paths += [WORK / 'catalog.py', WORK / '公式仕様の時計項目と保存原本の区別.json']
    proof = dict(全合格=True, 純説明=pure, Python構文検査=True, JavaScript構文検査=True,
                 新番号='00096', 旧89から95保持の公開ガード=True, 根目視と生成表示指紋ガード=True,
                 正式損益読取=0, HTML生成=0, 描画検査実行=0, 公開実行=0, API取得=0, 実注文=0,
                 既存公開前HTML不変=True,
                 SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths})
    (HERE / '34純条件説明と新番号及び公開ガードの静的検査.json').write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in proof.items() if key != 'SHA256'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
