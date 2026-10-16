"""注文管理3HTMLの表示値・操作を保存会計と隔離した実ブラウザで検査する。"""
from pathlib import Path
import hashlib
import importlib.util
import json
import statistics
from urllib.parse import unquote
from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
OUT = ROOT / 'アルゴリズム調査/00079_方向予測を使わない注文手法の検証'
MAIN = OUT / '予測を使わない注文手法と全セッション損益.html'
FAMILY = OUT / '家族別12手法の説明と全セッション損益.html'
ALL = OUT / '全288条件の前半比較.html'


def read(path):
    """
    機能: 保存JSONを復元する。
    引数: path (Path)。
    返り値: dict 又は list の保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def embedded(path):
    """
    機能: 公開HTMLと埋込み会計を読み込む。
    引数: path (Path)。
    返り値: tuple[str, dict] のHTMLと会計。
    """
    source = path.read_text(encoding='utf-8')
    return source, json.loads(BeautifulSoup(source, 'html.parser').select_one('#report-data').string)


def inspect_data(data, checked):
    """
    機能: 表示資料を元の会計・代表選択・乱数感度と独立照合する。
    引数: data (dict)、checked (set[str]) は重複を除く照合元ファイル。
    返り値: None。不一致は例外とする。
    """
    fixed = read(BASE / 'results/事前固定.json')
    selection = read(BASE / '前半選定.json')
    assert data['sessions'] == fixed['全30']
    expected = selection['primary'] if len(data['methods']) == 2 else selection['families']
    assert [m['id'] for m in data['methods']] == list(dict.fromkeys(r['id'] for r in expected))
    for field, folder in [('final', 'final/delay0'), ('ideal', 'ideal'), ('ideal_fee', 'ideal_fee')]:
        if field not in data:
            continue
        content = data[field]['0'] if field == 'final' else data[field]
        for identifier, result in content.items():
            path = BASE / folder / 'results' / (identifier + '.json')
            assert result == read(path), (field, identifier)
            checked.add(str(path))
            for period, sessions in [('前16', fixed['前16']), ('後14', fixed['後14']), ('対象', fixed['全30'])]:
                for symbol in ('TOPIX', 'NK225'):
                    subset = [r for r in result['rows'] if r['session'] in sessions and r['symbol'] == symbol]
                    saved = result['periods'][period][symbol]
                    for key in ('profit', 'loss', 'net', 'cycle_profit', 'cycle_loss', 'cycle_net', 'fees', 'midpoint_gross', 'spread_drag'):
                        assert abs(saved[key] - sum(r[key] for r in subset)) < 1e-6
                    assert saved['winning_sessions'] == sum(r['net'] > 0 for r in subset)
                    assert saved['losing_sessions'] == sum(r['net'] < 0 for r in subset)
                    assert saved['no_trade_sessions'] == sum(r['trades'] == 0 for r in subset)
    source = read(BASE / 'diagnosis/12家族代表の損失構造.json')
    assert data['diagnosis'] == {r['config']['id']: r for r in source['families'] + source['primary_extra']}
    sensitivity = read(BASE / 'sensitivity/無作為20種の比較.json')
    assert data['sensitivity'] == sensitivity
    for row in sensitivity['rows']:
        path = BASE / f'sensitivity/seed{row["seed"]:02d}/results' / (sensitivity['config']['id'] + '.json')
        assert row['metrics'] == read(path)['periods']['対象']
        checked.add(str(path))
    assert [r['seed'] for r in sensitivity['rows']] == list(range(20))
    for symbol in ('TOPIX', 'NK225'):
        values = [r['metrics'][symbol]['net'] for r in sensitivity['rows']]
        saved = sensitivity['symbols'][symbol]
        assert abs(saved['mean_net'] - statistics.mean(values)) < 1e-6
        assert saved['median_net'] == statistics.median(values)
        assert saved['worst_net'] == min(values) and saved['best_net'] == max(values)
        assert saved['profitable_seeds'] == sum(x > 0 for x in values)
    assert sensitivity['both_profitable_seeds'] == sum(all(r['metrics'][s]['net'] > 0 for s in ('TOPIX', 'NK225')) for r in sensitivity['rows'])
    if 'persistent' in data:
        assert len(data['persistent']) == 3
        assert data['persistent_spec'] == read(BASE / 'persistent/固定条件.json')
        for row in data['persistent']:
            for field, folder in [('original', 'final/delay0'), ('result', 'persistent')]:
                path = BASE / folder / 'results' / (row['parent_id'] + '.json')
                assert row[field] == read(path)
                checked.add(str(path))


# ----------------------------------------
def main():
    """
    機能: 保存会計と全操作を照合し、広幅・狭幅・損益表・追加診断を描画する。
    引数: なし。
    返り値: None。公開HTMLや売買結果は変更しない。
    """
    paths = (MAIN, FAMILY, ALL)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    contents = [embedded(p) for p in paths]
    checked = set()
    for source, data in contents[:2]:
        inspect_data(data, checked)
    for row in contents[2][1]['rows']:
        path = BASE / 'train/results' / (row['config']['id'] + '.json')
        result = read(path)
        assert row['config'] == result['config'] and row['metrics'] == result['periods']['前16']
        checked.add(str(path))
    assert len(contents[2][1]['rows']) == 288
    links = 0
    for source, data in contents:
        soup = BeautifulSoup(source, 'html.parser')
        for tag in soup.select('a[href]'):
            href = tag['href']
            if href.startswith(('https:', 'http:')):
                continue
            if href.startswith('#'):
                assert soup.find(id=href[1:]) is not None, href
            else:
                assert (OUT / unquote(href.split('#')[0])).exists(), href
            links += 1
    spec = importlib.util.spec_from_file_location('旧隔離描画83', ROOT / 'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = OUT
    renderer.VISUAL = HERE / 'visual'
    renderer.PROBE = '<script>' + (HERE / 'browser_probe.js').read_text(encoding='utf-8') + '</script>'
    policy = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:">'
    errors = '<script>window.browserErrors=[];window.addEventListener("error",e=>window.browserErrors.push(e.message));window.addEventListener("unhandledrejection",e=>window.browserErrors.push(String(e.reason)));</script>'
    main_source, family_source, all_source = [source.replace('<head>', '<head>' + policy + errors) for source, _ in contents]
    views = [(main_source, '主全体広幅', 1500, 1500, ''),
             (main_source, '主全体狭幅', 520, 1600, ''),
             (family_source, '家族別広幅', 1500, 1500, ''),
             (family_source, '家族別狭幅', 520, 1600, ''),
             (main_source, '全セッション損益', 1500, 2350, '<script>document.querySelector("main").replaceChildren(document.getElementById("all-sessions"));window.scrollTo(0,0);</script>'),
             (main_source, '在庫と費用分解', 1500, 1900, '<script>const main=document.querySelector("main"),inventory=document.getElementById("inventory"),logical=document.getElementById("logical-results").closest("details");logical.open=true;main.replaceChildren(inventory,logical);window.scrollTo(0,0);</script>'),
             (all_source, '全288広幅', 1500, 1450, ''),
             (all_source, '全288狭幅', 520, 1450, '')]
    if 'persistent' in contents[0][1]:
        views.append((main_source, '指値保持と全場', 1500, 2450, '<script>const panel=document.getElementById("order-retention");panel.querySelector("details").open=true;document.querySelector("main").replaceChildren(panel);window.scrollTo(0,0);</script>'))
    results = []
    for view in views:
        result = renderer.render(*view)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}, '描画中の公開HTML変更'
    output = dict(全合格=True, 目視確認=False, 公開HTML変更=False, 独立照合元結果数=len(checked),
                  静的ローカルリンク数=links, 通信遮断='複製CSP connect-src none と到達不能proxyで遮断',
                  結果=results, HTML_SHA256=hashes)
    (HERE / 'HTML表示の独立検査.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(完了=True, 独立照合元結果数=len(checked), 画像数=len(results), HTML_SHA256=hashes), ensure_ascii=False))


if __name__ == '__main__':
    main()
