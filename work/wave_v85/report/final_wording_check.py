"""最終の結論文だけの訂正を同一数値・同一描画コードと照合し、主画像を更新する。"""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
from bs4 import BeautifulSoup

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('wave85_browser_final', HERE / 'verify_browser.py')
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)


def main():
    """
    機能: 先に全数検査した複製と最終HTMLの数値・構造を比較し、追記を検査記録へ保存する。
    引数: なし。
    返り値: None。公開HTMLは変更しない。
    """
    proof = qa.read(HERE / 'HTML表示の独立検査.json')
    checks = []
    for actual, previous in ((qa.MAIN, HERE / 'visual/主全体広幅.html'), (qa.ALL, HERE / 'visual/全25比較広幅.html')):
        old = BeautifulSoup(previous.read_text(encoding='utf-8'), 'html.parser')
        text, data = qa.embedded(actual)
        new = BeautifulSoup(text, 'html.parser')
        old_data = json.loads(old.select_one('#report-data').string)
        keys = sorted(k for k in data if data[k] != old_data[k])
        assert keys == ['conclusion']
        assert data['results'] == old_data['results'] and data['fixed'] == old_data['fixed']
        assert [s.string for s in new.find_all('style')] == [s.string for s in old.find_all('style')]
        old_scripts = [s.string for s in old.find_all('script') if s.string and 'const DATA =' in s.string]
        new_scripts = [s.string for s in new.find_all('script') if s.string and 'const DATA =' in s.string]
        assert old_scripts == new_scripts
        for soup in (old, new):
            for script in list(soup.find_all('script')):
                script.decompose()
        assert str(old.body) == str(new.body)
        checks.append(dict(ファイル=actual.name, 数値不変=True, 戦略仕様不変=True, 描画コード不変=True,
                           本文構造不変=True, データ変更キー=keys, 結論=data['conclusion']))
    # ----------------------------------------
    renderer_spec = importlib.util.spec_from_file_location('隔離最終描画85', qa.ROOT / 'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(renderer_spec)
    renderer_spec.loader.exec_module(renderer)
    renderer.OUT, renderer.VISUAL = qa.OUT, HERE / 'visual'
    renderer.PROBE = '<script>' + (HERE / 'browser_probe.js').read_text(encoding='utf-8') + '</script>'
    source = qa.MAIN.read_text(encoding='utf-8')
    source = source.replace('<head>', '<head><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:"><script>window.browserErrors=[];window.addEventListener("error",e=>window.browserErrors.push(e.message));window.addEventListener("unhandledrejection",e=>window.browserErrors.push(String(e.reason)));</script>')
    views = [(source, '主全体広幅', 1500, 1650, ''), (source, '主全体狭幅', 520, 1650, ''),
        (source, '全30場の決済枚数', 1500, 2550, '<script>document.getElementById("account-select").value="leg";window.reportTest.render();document.querySelector("main").replaceChildren(document.getElementById("sessions"));window.scrollTo({top:0,behavior:"instant"});setTimeout(()=>window.scrollTo({top:0,behavior:"instant"}),500);</script>')]
    for view in views:
        result = renderer.render(*view)
        proof['結果'] = [result if row['画面'] == result['画面'] else row for row in proof['結果']]
    proof['最終文言修正検査'] = checks
    proof['HTML_SHA256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (qa.MAIN, qa.ALL)}
    proof['目視確認'] = False
    (HERE / 'HTML表示の独立検査.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('最終文言の数値・構造不変と主画像更新に合格')


if __name__ == '__main__':
    main()
