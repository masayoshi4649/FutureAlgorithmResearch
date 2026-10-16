"""順行・反転の公開2HTMLを、元会計と通信遮断ブラウザで独立検査する。"""
from pathlib import Path
import hashlib
import importlib.util
import json
from urllib.parse import unquote
from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
OUT = ROOT / 'アルゴリズム調査/00080_順行逆指値と反転売買の検証'
MAIN = OUT / '順行逆指値とドテンの説明と全セッション損益.html'
ALL = OUT / '全108条件の前半比較.html'


def read(path):
    """
    機能: 保存済みJSONを読む。
    引数: path (Path)。
    返り値: dict 又は list。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def embedded(path):
    """
    機能: 公開HTMLと埋込み資料を読み取る。
    引数: path (Path)。
    返り値: tuple[str,dict] のHTMLと資料。
    """
    text = path.read_text(encoding='utf-8')
    return text, json.loads(BeautifulSoup(text, 'html.parser').select_one('#report-data').string)


def check_account(result, fixed):
    """
    機能: 元会計とは別に場会計を合算し、表示する各期間を照合する。
    引数: result/fixed (dict)。
    返り値: None。不整合は例外とする。
    """
    for period, selected in [('前16', fixed['前16']), ('後14', fixed['後14']), ('対象', fixed['全30'])]:
        for symbol in ('TOPIX', 'NK225'):
            rows = [r for r in result['rows'] if r['symbol'] == symbol and r['session'] in selected]
            a = result['periods'][period][symbol]
            for key in ('profit', 'loss', 'net', 'fees', 'trades', 'midpoint_gross', 'spread_drag'):
                assert abs(a[key] - sum(r[key] for r in rows)) < 1e-6
            assert a['winning_sessions'] == sum(r['net'] > 0 for r in rows)
            assert a['losing_sessions'] == sum(r['net'] < 0 for r in rows)
            assert a['no_trade_sessions'] == sum(r['trades'] == 0 for r in rows)


# ----------------------------------------
def main():
    """
    機能: 全資料・操作・数値・描画を確認し、最終SHA付きの検査証拠を保存する。
    引数: なし。
    返り値: None。公開HTML・売買・代表選定には書き込まない。
    """
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (MAIN, ALL)}
    source, data = embedded(MAIN)
    other, all_data = embedded(ALL)
    fixed = read(WORK / 'results/事前固定.json')
    assert data['selection'] == read(WORK / '前半選定.json')
    assert data['sessions'] == fixed['全30']
    assert set(m['id'] for m in data['methods']) == set(data['selection']['selected'])
    files = 0
    for model, folder in [('main', 'final/delay0/results'), ('ideal', 'ideal_fee/results')]:
        for identifier, result in data['results'][model].items():
            assert result == read(WORK / folder / (identifier + '.json'))
            check_account(result, fixed)
            files += 1
    assert data['supplement']['fixed'] == read(WORK / 'supplement/追加固定.json')
    for model, folder in [('main', 'supplement/final/results'), ('ideal', 'supplement/ideal_fee/results')]:
        result = data['supplement']['results'][model]
        assert result == read(WORK / folder / (result['config']['id'] + '.json'))
        check_account(result, fixed)
        files += 1
    for row in all_data['rows']:
        result = read(WORK / 'train/results' / (row['config']['id'] + '.json'))
        assert result['config'] == row['config'] and result['periods']['前16'] == row['metrics']
        files += 1
    pairs = data['comparisons']['direction'] + data['comparisons']['turn']
    assert [(p['first'], p['second']) for p in pairs] == [(p['left_id'], p['right_id']) for p in data['selection']['pairs']]
    links = 0
    for text in (source, other):
        soup = BeautifulSoup(text, 'html.parser')
        for tag in soup.select('a[href]'):
            href = tag['href']
            if href.startswith(('https:', 'http:')):
                continue
            if href.startswith('#'):
                assert soup.find(id=href[1:]) is not None
            else:
                assert (OUT / unquote(href.split('#')[0])).exists()
            links += 1
    spec = importlib.util.spec_from_file_location('旧隔離描画84', ROOT / 'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = OUT
    renderer.VISUAL = HERE / 'visual'
    renderer.PROBE = '<script>' + (HERE / 'browser_probe.js').read_text(encoding='utf-8') + '</script>'
    policy = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:">'
    errors = '<script>window.browserErrors=[];window.addEventListener("error",e=>window.browserErrors.push(e.message));window.addEventListener("unhandledrejection",e=>window.browserErrors.push(String(e.reason)));</script>'
    source = source.replace('<head>', '<head>' + policy + errors)
    other = other.replace('<head>', '<head>' + policy + errors)
    views = [(source, '主全体広幅', 1500, 1550, ''), (source, '主全体狭幅', 520, 1650, ''),
             (source, '全セッション損益', 1500, 2350, '<script>document.querySelector("main").replaceChildren(document.getElementById("all-sessions"));window.scrollTo(0,0);</script>'),
             (source, '同幅比較と費用', 1500, 1650, '<script>const cost=document.getElementById("cost-results").closest("details");cost.open=true;document.querySelector("main").replaceChildren(document.getElementById("fair-comparison"),cost);window.scrollTo(0,0);</script>'),
             (source, '参考条件の主結果', 1500, 2300, '<script>const panel=document.getElementById("supplement-panel");panel.open=true;document.querySelector("main").replaceChildren(panel);window.scrollTo(0,0);</script>'),
             (source, '参考条件の理論対照', 1500, 2300, '<script>document.getElementById("supplement-model-select").value="ideal";window.reportTest.renderSupplement();const panel=document.getElementById("supplement-panel");panel.open=true;document.querySelector("main").replaceChildren(panel);window.scrollTo(0,0);</script>'),
             (other, '全108広幅', 1500, 1450, ''), (other, '全108狭幅', 520, 1450, '')]
    results = []
    for view in views:
        result = renderer.render(*view)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (MAIN, ALL)}
    proof = dict(全合格=True, 目視確認=False, 独立照合元結果数=files, 静的ローカルリンク数=links,
                 公開HTML変更=False, 通信遮断='複製CSP connect-src none と到達不能proxyで遮断',
                 結果=results, HTML_SHA256=hashes)
    (HERE / 'HTML表示の独立検査.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(完了=True, 保存元結果=files, 画像数=len(results), HTML_SHA256=hashes), ensure_ascii=False))


if __name__ == '__main__':
    main()
