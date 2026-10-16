"""売買反転の全表示を、元の会計ファイルと隔離したブラウザで検査する。"""
from pathlib import Path
import hashlib
import importlib.util
import json
from urllib.parse import unquote
from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
PRIOR = BASE.parent / 'wave_v81'
OUT = ROOT / 'アルゴリズム調査/00078_安定赤字手法の売買反転検証'
MAIN = OUT / '安定して負ける手法の反転と全セッション損益.html'
ALL = OUT / '全188条件の前半反転比較.html'


def read(path):
    """
    機能: 保存済みJSONを読む。
    引数: path (Path)。
    返り値: dict 又は list の保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def embedded(path):
    """
    機能: HTMLとその埋め込みJSONを読む。
    引数: path (Path)。
    返り値: tuple[str, dict] のHTMLと会計。
    """
    source = path.read_text(encoding='utf-8')
    return source, json.loads(BeautifulSoup(source, 'html.parser').select_one('#report-data').string)


def verify_group(data):
    """
    機能: 事後相場分類を元の場別会計から独立に再加算する。
    引数: data (dict) は公開表示資料。
    返り値: int の照合した組・商品・分類・元逆の数。
    """
    classification = read(BASE / 'diagnosis/相場分類.json')
    count = 0
    for pair in data['pairs']:
        for row in data['regimes'][pair['label']]:
            selected = {r['session'] for r in classification['rows'] if r['symbol'] == row['symbol'] and r['regime'] == row['regime']}
            assert row['sessions'] == len(selected)
            for variant in ('original', 'reverse'):
                rows = [r for r in data['final']['5'][pair[variant]['id']]['rows'] if r['symbol'] == row['symbol'] and r['session'] in selected]
                a = row[variant]
                for field in ('profit', 'loss', 'net', 'fees', 'trades'):
                    assert a[field] == sum(r[field] for r in rows)
                assert a['winning_sessions'] == sum(r['net'] > 0 for r in rows)
                assert a['losing_sessions'] == sum(r['net'] < 0 for r in rows)
                assert a['no_trade_sessions'] == sum(r['trades'] == 0 for r in rows)
                assert a['sessions'] == len(rows)
                denominator = a['profit'] + a['loss']
                assert a['profit_share'] == (a['profit'] / denominator if denominator else None)
                count += 1
    return count


# ----------------------------------------
def main():
    """
    機能: 保存値・操作・全損益・相場診断・狭幅・赤字色を検査して証拠を保存する。
    引数: なし。
    返り値: None。公開HTMLと損益資料を変更しない。
    """
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (MAIN, ALL)}
    source, data = embedded(MAIN)
    other, all_data = embedded(ALL)
    files = 0
    for delay, methods in data['final'].items():
        for identifier, result in methods.items():
            assert result == read(BASE / f'final/delay{delay}/results/{identifier}.json')
            files += 1
    for identifier, metrics in data['strict'].items():
        saved = read(BASE / f'quality3/results/{identifier}.json')
        assert metrics == saved['periods']['対象']
        files += 1
    for row in all_data['rows']:
        candidates = [PRIOR / stage / 'results' / (row['parent_id'] + '.json') for stage in ('first', 'improved')]
        originals = [p for p in candidates if p.exists()]
        assert len(originals) == 1
        original = read(originals[0])
        reverse = read(BASE / 'first/results' / ('R__' + row['parent_id'] + '.json'))
        assert row['config'] == original['config']
        assert row['original'] == original['periods']['対象']
        assert row['reverse'] == reverse['periods']['対象']
        files += 2
    assert data['front_diagnosis'] == read(BASE / 'diagnosis/前半の毎場赤字66条件を実際に反転した集計.json')
    groups = verify_group(data)
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
    spec = importlib.util.spec_from_file_location('旧隔離描画82', ROOT / 'work/wave_v52/review/verify_report.py')
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
             (main_source, '費用分解と相場分類', 1500, 1900, '<script>const main=document.querySelector("main"),cost=document.getElementById("cost-results").closest("details"),regime=document.getElementById("regimes");cost.open=true;main.replaceChildren(cost,regime);window.scrollTo(0,0);</script>'),
             (all_source, '全188広幅', 1500, 1450, ''),
             (all_source, '全188狭幅', 520, 1450, '')]
    results = [renderer.render(*view) for view in views]
    assert hashes == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (MAIN, ALL)}, '描画中の公開資料変更'
    output = dict(全合格=True, 目視確認=False, 公開HTML変更=False,
                  独立照合元結果数=files, 相場分類再集計数=groups, 静的ローカルリンク数=links,
                  通信遮断='複製CSP connect-src none と到達不能proxyで遮断',
                  結果=results, HTML_SHA256=hashes)
    (HERE / 'HTML表示の独立検査.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
