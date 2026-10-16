"""公開表を元結果へ照合し、暗色HTMLを隔離ブラウザで描画する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
PUBLIC = ROOT / 'アルゴリズム調査/00082_E01の狭幅トレールと再エントリー'
MAIN = PUBLIC / '狭いトレールと再エントリーの結果.html'


def number(value):
    """
    機能: 表示された円単位整数を比較可能な数値に戻す。
    引数: value(str)。
    返り値: int。
    """
    return int(value.replace(',', '').replace('円', '').strip())


def main():
    """
    機能: 全場の利益損失と合計、全条件、リンク、画面幅を独立照合する。
    引数: なし。
    返り値: None。元HTMLは変更せず検査記録と画像を保存する。
    """
    source = MAIN.read_text(encoding='utf-8')
    digest = hashlib.sha256(MAIN.read_bytes()).hexdigest()
    soup = BeautifulSoup(source, 'html.parser')
    fixed = json.loads((WORK / '事前固定.json').read_text(encoding='utf-8'))
    extra_path = WORK / 'phase2/事前固定.json'
    extra = json.loads(extra_path.read_text(encoding='utf-8')) if extra_path.exists() else None
    configs = fixed['catalog'] + (extra['catalog'] if extra else [])
    locations = {c['id']: WORK for c in fixed['catalog']}
    if extra:
        locations.update({c['id']: WORK / 'phase2' for c in extra['catalog']})
    results = {model: {c['id']: json.loads((locations[c['id']] / model / 'results' / (c['id']+'.json')).read_text(encoding='utf-8'))
                      for c in configs} for model in fixed['models']}
    checked = 0
    for detail in soup.select('#sessions > details'):
        identifier = detail.summary.get_text().split('：')[0]
        value = results['observed'][identifier]
        by_key = {(r['session'], r['symbol']): r for r in value['rows']}
        rows = detail.select('tbody > tr')
        assert len(rows) == 31
        for name, row in zip(fixed['全30']+['合計'], rows):
            cells = row.find_all(['th', 'td'])
            for offset, symbol in ((1, 'TOPIX'), (4, 'NK225')):
                target = value['periods']['全30'][symbol] if name == '合計' else by_key[name, symbol]
                expected = (target['campaign_profit'], -target['campaign_loss'], target['net'])
                for index, v in enumerate(expected):
                    assert number(cells[offset+index].get_text()) == round(v)
                    checked += 1
    for model, tables in [('observed', soup.select('#all table')[:2]), ('specified', soup.select('#all table')[2:])]:
        for symbol, tab in zip(('TOPIX', 'NK225'), tables):
            rows = tab.select('tbody > tr')
            assert len(rows) == len(configs)
            for row in rows:
                cells = row.find_all(['th', 'td'])
                target = results[model][cells[0].get_text()]['periods']['全30'][symbol]
                assert number(cells[2].get_text()) == round(target['net'])
                assert number(cells[5].get_text()) == -round(target['max_drawdown'])
                assert int(cells[6].get_text()) == target['campaigns']
                checked += 3
    for row in soup.select('#frequency tbody > tr'):
        cells = row.find_all(['th', 'td'])
        identifier = cells[0].select_one('.note').get_text()
        for offset, symbol in ((1, 'TOPIX'), (2, 'NK225')):
            target = results['observed'][identifier]['periods']['全30'][symbol]
            assert number(cells[offset].contents[0].get_text()) == round(target['net'])
            assert int(cells[offset].select_one('.note').get_text().replace('回', '')) == target['campaigns']
            checked += 2
    for link in soup.select('a[href]'):
        assert (PUBLIC / link['href']).exists()
    spec = importlib.util.spec_from_file_location('隔離表示86', ROOT / 'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = PUBLIC
    renderer.VISUAL = HERE / 'visual'
    renderer.PROBE = '''<script>
/**
 * 機能: 静的レポートの画面幅と未置換文字を検査する。
 * 引数: なし。
 * 返り値: object の表示検査結果。
 */
function inspectReport(){
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面外への横溢れ');
 if(/undefined|NaN|__TITLE__|__SUMMARY__/.test(document.body.innerText))throw Error('未定義表示');
 return {全合格:true,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,背景:getComputedStyle(document.body).backgroundColor};
}
try{document.body.dataset.check=JSON.stringify(inspectReport());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''
    csp = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:">'
    source = source.replace('<head>', '<head>'+csp)
    views = [renderer.render(source, '結論と比較', 1450, 1500),
             renderer.render(source, '狭い画面', 520, 1500),
             renderer.render(source, '全セッション', 1450, 2450,
                 '<script>const d=document.querySelectorAll("#sessions details")[1];d.open=true;document.querySelector("main").replaceChildren(d);</script>')]
    assert hashlib.sha256(MAIN.read_bytes()).hexdigest() == digest
    output = dict(全合格=True, 表示数値照合数=checked, 画面=views, 公開SHA256=digest, 目視確認=False)
    (HERE / '表示の独立検査.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
