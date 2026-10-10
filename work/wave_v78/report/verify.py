"""公開予定の二HTMLを保存結果と実ブラウザーの表示へ照合する。"""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path

from bs4 import BeautifulSoup

import generate

HERE = Path(__file__).resolve().parent


def browser(source: str, name: str, probe: str, width: int, height: int, extra: str = '') -> dict:
    """機能: 読取専用の既存Chrome描画器へ今回の検査を渡す。

    引数: source/name/probe/extra(str)、width/height(int)。返り値: 表示結果(dict)。
    """
    spec = importlib.util.spec_from_file_location('隔離描画78_' + name, generate.ROOT / 'work/wave_v52/review/verify_report.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUT = generate.OUT
    module.VISUAL = HERE / 'visual'
    module.PROBE = '<script>' + (HERE / probe).read_text(encoding='utf8') + '</script>'
    return module.render(source, name, width, height, extra)


def main() -> None:
    """機能: 元結果・全選択表示・広狭画面を一度照合する。

    引数: なし。返り値: なし(None)。
    """
    source = (generate.OUT / generate.MAIN).read_text(encoding='utf8')
    all_source = (generate.OUT / generate.ALL).read_text(encoding='utf8')
    all_data = json.loads(BeautifulSoup(all_source, 'html.parser').select_one('#report-data').string)
    data = json.loads(BeautifulSoup(source, 'html.parser').select_one('#report-data').string)
    accounts = 0
    for method in all_data['methods']:
        saved = generate.load(generate.WORK / 'results' / (method['id'] + '.json'))
        for field in ('rows', 'periods', 'config'):
            assert method[field] == generate.minimal(saved)[field]
        accounts += len(saved['rows'])
    for method in [data['benchmark'], *data['methods']]:
        saved = generate.load(generate.WORK / 'results' / (method['id'] + '.json'))
        assert method['rows'] == generate.minimal(saved)['rows']
        assert method['periods'] == generate.minimal(saved)['periods']
    baseline = generate.load(generate.WORK / 'results' / (data['benchmark']['id'] + '.json'))
    for part in data['partsOverview']:
        saved = generate.load(generate.WORK / 'results' / (part['id'] + '.json'))
        for symbol in generate.SYMBOLS:
            assert part['difference'][symbol] == saved['periods']['全30'][symbol]['net'] - baseline['periods']['全30'][symbol]['net']
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = [pool.submit(browser, source, '主報告_広幅', 'probe_main.js', 1480, 1300),
                 pool.submit(browser, source, '主報告_狭幅', 'probe_main.js', 520, 1250),
                 pool.submit(browser, all_source, '全条件_広幅', 'probe_all.js', 1480, 1250)]
        results = [task.result() for task in tasks]
    results.append(browser(source, '売買図', 'probe_main.js', 1480, 1050,
        '<script>document.querySelector("main").replaceChildren(document.querySelector("#chart").parentElement);window.scrollTo(0,0);</script>'))
    proof = dict(全合格=True, 元結果一致口座数=accounts, 実画面=results, 目視確認=False,
                 HTML_SHA256={name: generate.digest(generate.OUT / name) for name in (generate.MAIN, generate.ALL)})
    generate.save(HERE / '表示検査.json', proof)
    print(json.dumps(proof, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
