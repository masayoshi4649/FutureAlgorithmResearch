"""正式損益を開かず、報告の36条件説明と公開導線を実装へ静的照合する。"""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
REPORT = WORK / 'report'
sys.dont_write_bytecode = True


def digest(path: Path) -> str:
    """
    機能: 読取対象と検査証跡の内容指紋を求める。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source(path: Path) -> str:
    """
    機能: 条件コード又は報告テンプレートだけをUTF-8で読む。
    引数: path(Path)。
    返り値: str。正式新97損益・台帳・結論補足は読まない。
    """
    return path.read_text(encoding='utf-8')


def load_catalog() -> list[dict]:
    """
    機能: 損益を参照しない36条件の定数を独立に読む。
    引数: なし。
    返り値: list[dict]は根が固定した入口と出口の設定。
    """
    spec = importlib.util.spec_from_file_location('報告の静的条件照合97', WORK / 'catalog.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result.catalog()


def generated_rules(main: str, configs: list[dict]) -> list[dict]:
    """
    機能: ruleだけを隔離実行し、架空の損益を作らず36説明文を取得する。
    引数: main(str)はmain.js、configs(list[dict])は条件定数。
    返り値: list[dict]はIDと入口・途中・出口の表示文。DOM・ネットワーク・会計なし。
    """
    escape = next(line for line in main.splitlines() if line.startswith('function escapeHtml('))
    start = main.index('function rule(config)')
    end = main.index('/**', start)
    javascript = escape + '\n' + main[start:end] + "\nconst values=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(values.map(c=>({id:c.id,text:rule(c).replace(/<[^>]+>/g,'' )}))));"
    result = subprocess.run(['node', '-e', javascript], input=json.dumps(configs, ensure_ascii=False),
        capture_output=True, text=True, encoding='utf-8', check=True)
    return json.loads(result.stdout)


def main() -> None:
    """
    機能: 9入口×4出口と最新00093導線を照合し、解消済み指摘も含む証跡を保存する。
    引数: なし。
    返り値: None。報告・README・固定依存・正式損益は変更しない。
    """
    paths = sorted(REPORT.glob('*.py')) + sorted(REPORT.glob('*.js')) + [
        REPORT / 'template.html', REPORT / 'style.css', WORK / 'catalog.py', WORK / 'engine.py',
        WORK / 'strategy.py', WORK / '結果前の設計案.json', ROOT / 'README.md',
        ROOT / 'アルゴリズム調査/README.md', ROOT / 'アルゴリズム調査/index.html',
        ROOT / 'work/wave_v83/data.py', ROOT / 'work/wave_v77/inputs/prepare.py',
        ROOT / 'work/wave_v91/inputs/metadata.json', Path(__file__)]
    before = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    for path in REPORT.glob('*.py'):
        ast.parse(source(path))
    for name in ('main.js', 'probe.js'):
        subprocess.run(['node', '--check', str(REPORT / name)], capture_output=True, check=True)
    configs = load_catalog()
    assert len(configs) == 36 and {c['id'] for c in configs} == {f'A{a}_X{x}' for a in range(9) for x in range(4)}
    for c in configs:
        a, x = int(c['id'][1]), int(c['id'][-1])
        assert c['entry_wait_kind'] == a and c['entry_width_bp'] == 10. and c['entry_wait_seconds'] == 300.
        assert c['entry_bbo_confirm'] == (a in (1, 3, 4, 5, 6, 7, 8))
        assert (c['trend_initial_stop_bp'], c['trend_protection_mode'], c['trend_hold_seconds']) == (
            (40., 0, 1800.), (10., 0, 1800.), (20., 2, 1800.), (10., 1, 0.))[x]
        assert c['trend_budget'] == 8 and c['range_budget'] == 0 and c['loss_reentry_kind'] == 'none'
    main_text, template, probe = (source(REPORT / name) for name in ('main.js', 'template.html', 'probe.js'))
    rules = generated_rules(main_text, configs)
    entry_patterns = ('候補から直ちに新規', '両市場の買い・売り気配が各1呼値',
        '1W順行し現在正常な相手気配', '1W順行し、両気配再進行', '2W順行し、両気配再進行',
        '不利極値から半W回復', '局所有利極値から半W押し', '局所有利極値から1W押し',
        '局所有利極値から1W押し')
    for config, rule in zip(configs, rules):
        assert rule['id'] == config['id']
        a = config['entry_wait_kind']
        text = rule['text']
        assert all(part in text for part in ('入口：', '途中：', '出口：', 'TOPIX8枚、日経16枚',
            entry_patterns[a], '追尾は始値の0.4%幅', '停止線は不利へ戻さない',
            '停止条件成立後の次正常気配', '返済後30秒', '希望停止価格での約定は保証されない'))
        assert f"初期損切りは始値の{config['trend_initial_stop_bp']/100:.1f}%" in text
        assert ('通常の保有期限なし' if config['trend_hold_seconds'] == 0 else '実新規から30分で返済判断') in text
        if a == 0:
            assert '追加のJ2・両気配再確認なし' in text and '発注時に旧J2' not in text
        else:
            assert '出口幅と独立' in text and '発注時に旧J2同方向許可を再確認' in text
        if a == 2:
            assert '相手の最初正常行も可' in text and '気配再進行比較なし' in text
        if a in (5, 6, 7):
            assert '半W回復' in text
        if a == 8:
            assert '1W回復' in text
    assert all(text in template for text in ('00093', '全36で元の旧J8候補を固定',
        '有効中立60秒と発火間隔600秒', '待機・保有・市場予約中の候補は消費して復活させない',
        'Wは出口の初期幅Sとは独立', '副幅も呼値へ切上げ', '候補以後の局所有利極値',
        '初回押し成立行で回復用の不利極値を新しく設定', '候補価格より有利な新規は保証しない',
        'A0は候補から即時で追加の再確認なし', 'A2は相手が最初に正常になった行も発注可',
        'A1とA3〜8', '厳密な時計更新', '最初の正常ペアは基準作成だけ', 'その行には発注しない',
        '保存上の運用区切り60秒前', '運用区切りは実立会終了とは別',
        'https://www.jpx.co.jp/derivatives/rules/trading-hours/', '追加5秒悪化なし'))
    assert '場末60秒前' not in template and '30分でも返済' not in main_text
    assert '運用区切り60秒前' in probe and '入口9種説明' in probe and '即時対照の資格' in probe
    assert '価格のみの正常復帰' in probe and '待機幅と停止幅の分離' in probe
    assert 'range_budget>0' not in probe
    build, publish = source(REPORT / 'build.py'), source(REPORT / 'publish.py')
    assert "'A7_X3'" in build and 'len(catalog) == 36' in build and '口座数=2232' in build
    assert "default_method=analysis['primary']" in build
    assert "'00093_押し回復と両市場再確認の待機入口'" in publish and 'max(numbers) == 92' in publish
    assert "'<!--00092案内開始-->'" in publish and "'<!--00092開始-->'" in publish
    assert '00093案内開始' in publish and '00093開始' in publish and '最新の調査は' in publish
    assert '<!--00092案内開始-->' in source(ROOT / 'アルゴリズム調査/README.md')
    assert '<!--00092開始-->' in source(ROOT / 'アルゴリズム調査/index.html')
    assert '最新の調査は' in source(ROOT / 'README.md')
    assert not (ROOT / 'アルゴリズム調査/00093_押し回復と両市場再確認の待機入口').exists()
    after = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    assert before == after, '検査中に読取対象が変わったため再検査が必要です'
    corrected = [
        dict(指摘='30分までの実返済保証と読める旧表現', 元箇所='report/main.js:68',
             現在='実新規から30分で返済判断、次正常気配で返済', 解消=True),
        dict(指摘='場末60秒前と実連続立会末の混同', 元箇所='report/template.html:37',
             現在='保存運用区切りと実立会末を区別しJPX公式リンク', 解消=True),
        dict(指摘='A0の余分資格とA2の初正常同行例外が不明瞭', 元箇所='report/main.js:63〜64,template.html:34',
             現在='A0追加再確認なし、A2初正常同行可、BBO群初回は基準のみ', 解消=True),
        dict(指摘='W/S独立と副幅呼値化の説明不足', 元箇所='report/template.html:33', 解消=True),
        dict(指摘='入口9種類の表示検査がなかった', 元箇所='report/probe.js:33〜55',
             現在='9入口/A0/A2/回復幅検査追加、非活動旧range枝削除', 解消=True),
        dict(指摘='過渡版probeだけ旧場末60秒前語句が残った', 元箇所='report/probe.js:12',
             現在='運用区切り60秒前へ更新済み。読取時差の指摘と最終版を区別', 解消=True)]
    proof = dict(全合格=True, 種類='正式損益未読の静的報告照合', 条件説明隔離実行=36,
        入口種類=9, 出口種類=4, 元候補固定及び待機幅と出口幅独立=True,
        A0旧資格のみ=True, A2現在正常peerと初正常同行可=True,
        A6から8局所有利peakと初arm不利極値=True, 同候補から悪い取得もあり得る=True,
        通常期限と保存運用区切り及び実立会末を区別=True, 公開予定番号=93,
        根README及び研究READMEとindexの更新アンカー一致=True,
        過渡版の指摘と現時点解消確認=corrected,
        非表示の旧コピー識別名=['verify.py:149 表示名独立95', 'verify.py:161 表示正規化95の旧価格読取',
            'verify.py:175 隔離描画95。固有module名だけで読み込む実パスは新97。経済条件や表示へ影響なし'],
        任意改善=['未活動の反発・回復源行は0表示だが現在36条件の戦略ではないため、非使用枠と表示してもよい。',
            'A5は直接順行でも成立する点を短文へ補足してもよい。実装差は発見していない。'],
        未検査=['正式金額・全31表示・QA画像・新97実約定の立会内確認は根の全31完了通知後の正式検査対象。'],
        正式97損益閲覧=0, 正式97損益実行=0, report変更=0, 固定依存変更=0,
        API取得=0, 実注文=0, SHA256=after)
    destination = HERE / '報告36条件説明と00093最新導線の損益前静的整合.json'
    destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in proof.items() if key not in (
        'SHA256', '過渡版の指摘と現時点解消確認', '非表示の旧コピー識別名', '任意改善', '未検査')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
