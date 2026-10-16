"""原E01公開資料の元会計・全表示切替を通信遮断ブラウザで独立確認する。"""

from pathlib import Path
import hashlib
import importlib.util
import json
from urllib.parse import unquote
from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
OUT = ROOT / 'アルゴリズム調査/00081_E01原版と知見統合改修の再検証'
MAIN = OUT / 'E01原版と改修の説明と全セッション損益.html'
ALL = OUT / '全25条件の比較.html'


def read(path):
    """
    機能: 元結果又は固定仕様のJSONを読む。
    引数: path (Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def embedded(path):
    """
    機能: HTMLと埋め込まれた保存会計を取り出す。
    引数: path (Path)。
    返り値: tuple[str,dict]。
    """
    text = path.read_text(encoding='utf-8')
    return text, json.loads(BeautifulSoup(text, 'html.parser').select_one('#report-data').string)


def check_account(result, fixed):
    """
    機能: 保存場会計を別集計して期間・枚数・親組と脚の収支一致を確認する。
    引数: result/fixed (dict)。
    返り値: None。
    """
    for row in result['rows']:
        assert abs(row['profit'] - row['loss'] - row['net']) < 1e-6
        assert abs(row['cycle_profit'] - row['cycle_loss'] - row['net']) < 1e-6
        assert abs(row['gross'] - row['fees'] - row['net']) < 1e-6
        assert row['new_lots'] == row['exit_lots'] == row['settled_lots']
    for period in ('前16', '後14', '全30'):
        for symbol in ('TOPIX', 'NK225'):
            selected = [r for r in result['rows'] if r['session'] in fixed[period] and r['symbol'] == symbol]
            a = result['periods'][period][symbol]
            for field in ('profit', 'loss', 'net', 'fees', 'cycle_profit', 'cycle_loss', 'cycles', 'trades', 'new_lots', 'exit_lots', 'winning_lots', 'losing_lots'):
                assert abs(a[field] - sum(r[field] for r in selected)) < 1e-6
            assert a['no_trade_sessions'] == sum(r['cycles'] == 0 for r in selected)
            assert a['positive_sessions'] == sum(r['net'] > 0 for r in selected)


def main():
    """
    機能: 元50会計・全切替・広狭画面を検査し、読み取った公開SHAを記録する。
    引数: なし。
    返り値: None。公開HTMLは変更しない。
    """
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (MAIN, ALL)}
    source, data = embedded(MAIN)
    other, all_data = embedded(ALL)
    fixed = read(WORK / 'results/事前固定.json')
    assert data['fixed'] == all_data['fixed']
    assert all(value == fixed[key] for key, value in data['fixed'].items())
    assert data['results'] == all_data['results']
    files = 0
    for model in ('specified', 'observed'):
        for config in fixed['catalog']:
            result = data['results'][model][config['id']]
            assert result == read(WORK / model / 'results' / (config['id'] + '.json'))
            check_account(result, fixed)
            files += 1
    links = 0
    for text in (source, other):
        soup = BeautifulSoup(text, 'html.parser')
        for tag in soup.select('a[href]'):
            href = tag['href']
            if href.startswith(('http:', 'https:')):
                continue
            if href.startswith('#'):
                assert soup.find(id=href[1:]) is not None
            else:
                assert (OUT / unquote(href.split('#')[0])).exists()
            links += 1
    spec = importlib.util.spec_from_file_location('隔離描画85', ROOT / 'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = OUT
    renderer.VISUAL = HERE / 'visual'
    renderer.PROBE = '<script>' + (HERE / 'browser_probe.js').read_text(encoding='utf-8') + '</script>'
    csp = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:">'
    errors = '<script>window.browserErrors=[];window.addEventListener("error",e=>window.browserErrors.push(e.message));window.addEventListener("unhandledrejection",e=>window.browserErrors.push(String(e.reason)));</script>'
    source = source.replace('<head>', '<head>' + csp + errors)
    other = other.replace('<head>', '<head>' + csp + errors)
    views = [(source, '主全体広幅', 1500, 1650, ''), (source, '主全体狭幅', 520, 1650, ''),
        (source, '全30場の親組損益', 1500, 2550, '<script>document.querySelector("main").replaceChildren(document.getElementById("sessions"));window.scrollTo(0,0);</script>'),
        (source, '全30場の決済枚数', 1500, 2550, '<script>document.getElementById("account-select").value="leg";window.reportTest.render();document.querySelector("main").replaceChildren(document.getElementById("sessions"));window.scrollTo(0,0);</script>'),
        (source, '改修差と旧結果接続', 1500, 1600, '<script>const a=document.getElementById("change-results").closest("details"),b=document.getElementById("old-results").closest("details");a.open=b.open=true;document.querySelector("main").replaceChildren(a,b);window.scrollTo(0,0);</script>'),
        (source, '時間帯見送りの比較', 1500, 1650, '<script>const a=document.getElementById("time-results").closest("section");document.querySelector("main").replaceChildren(a);window.scrollTo(0,0);</script>'),
        (other, '全25比較広幅', 1500, 1600, ''), (other, '全25比較狭幅', 520, 1500, '')]
    results = []
    for view in views:
        result = renderer.render(*view)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (MAIN, ALL)}
    proof = dict(全合格=True, 目視確認=False, 独立照合元結果数=files, 静的リンク数=links,
                 通信遮断='CSP connect-src none と到達不能proxyを併用', 公開HTML変更=False,
                 結果=results, HTML_SHA256=hashes)
    (HERE / 'HTML表示の独立検査.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
