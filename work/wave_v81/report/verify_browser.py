"""固定代表の全場表示と全188条件の比較表を、通信しない実ブラウザで確かめる。"""
from pathlib import Path
import hashlib
import importlib.util
import json
from urllib.parse import unquote
from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
OUT = ROOT / 'アルゴリズム調査/00077_保有時間を決めない二市場方向追従'
MAIN = OUT / '時間で区切らない方向追従と全セッション損益.html'
ALL = OUT / '全条件の前半比較.html'


def embedded(path):
    """
    機能: 元HTMLと埋め込まれた保存数値を読む。
    引数: path (Path)。
    返り値: tuple[str, dict] のHTMLとJSON。
    """
    source = path.read_text(encoding='utf-8')
    return source, json.loads(BeautifulSoup(source, 'html.parser').select_one('#report-data').string)


# ----------------------------------------
def main():
    """
    機能: 独立会計照合、全切替、狭幅、色、表示を確認してPNGと証拠を保存する。
    引数: なし。
    返り値: None。公開HTMLと試験結果を変更しない。
    """
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (MAIN, ALL)}
    source, data = embedded(MAIN)
    other, all_data = embedded(ALL)
    files = 0
    for delay, methods in data['final'].items():
        for identifier, result in methods.items():
            path = BASE / f'final/delay{delay}/results/{identifier}.json'
            assert result == json.loads(path.read_text(encoding='utf-8'))
            files += 1
    for identifier, metrics in data['strict'].items():
        saved = json.loads((BASE / f'quality3/results/{identifier}.json').read_text(encoding='utf-8'))
        assert metrics == saved['periods']['対象']
        files += 1
    for row in all_data['rows']:
        stage = 'first' if row['stage'] == '初回' else 'improved'
        path = BASE / stage / 'results' / (row['config']['id'] + '.json')
        saved = json.loads(path.read_text(encoding='utf-8'))
        assert row['config'] == saved['config'] and row['metrics'] == saved['periods']['前16']
        files += 1
    links = 0
    for html in (source, other):
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup.select('a[href]'):
            href = tag['href']
            if href.startswith(('https:', 'http:')):
                continue
            if href.startswith('#'):
                assert soup.find(id=href[1:]) is not None
            else:
                assert (OUT / unquote(href.split('#')[0])).exists(), href
            links += 1
    spec = importlib.util.spec_from_file_location('旧隔離描画81', ROOT / 'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = OUT
    renderer.VISUAL = HERE / 'visual'
    renderer.PROBE = '<script>' + (HERE / 'browser_probe.js').read_text(encoding='utf-8') + '</script>'
    policy = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:">'
    errors = '<script>window.browserErrors=[];window.addEventListener("error",e=>window.browserErrors.push(e.message));window.addEventListener("unhandledrejection",e=>window.browserErrors.push(String(e.reason)));</script>'
    main_source = source.replace('<head>', '<head>' + policy + errors)
    all_source = other.replace('<head>', '<head>' + policy + errors)
    views = [(main_source, '主全体広幅', 1500, 1500, ''),
             (main_source, '主全体狭幅', 520, 1600, ''),
             (main_source, '全セッション損益', 1500, 2350, '<script>document.querySelector("main").replaceChildren(document.getElementById("all-sessions"));window.scrollTo(0,0);</script>'),
             (main_source, '実保有と損失原因', 1500, 2200, '<script>const main=document.querySelector("main"),hold=document.getElementById("holding"),change=document.getElementById("change-results").closest("section"),detail=[...document.querySelectorAll("details")].find(d=>d.querySelector("summary").textContent.includes("赤字が"));if(!detail)throw Error("損失理由の説明がありません");detail.open=true;main.replaceChildren(hold,change,detail);window.scrollTo(0,0);</script>'),
             (all_source, '全188広幅', 1500, 1450, ''),
             (all_source, '全188狭幅', 520, 1450, '')]
    results = [renderer.render(*view) for view in views]
    assert hashes == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (MAIN, ALL)}, '描画中の公開資料変更'
    output = dict(全合格=True, 目視確認=False, 公開HTML変更=False,
                  独立照合元結果数=files, 静的ローカルリンク数=links,
                  通信遮断='複製CSP connect-src none と到達不能proxyで遮断',
                  結果=results, HTML_SHA256=hashes)
    (HERE / 'HTML表示の独立検査.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
