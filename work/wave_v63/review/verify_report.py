"""公開3ページ・CSV・選定候補を元の固定結果へ照合し、暗色画面を撮影する。"""

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup
import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT/'アルゴリズム調査/00060_決済勝率95パーセントの探索とPDCA'
spec = importlib.util.spec_from_file_location('隔離画面描画', HERE.parent.parent/'wave_v52/review/verify_report.py')
browser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(browser)
browser.OUT = OUT
browser.VISUAL = HERE/'visual'
JST = timezone(timedelta(hours=9))
FILES = ('95パーセント探索の説明と全セッション損益.html', '損失原因とPDCA.html', '全375条件.html')


def read(path: Path) -> dict:
    """機能: UTF-8のJSONを読む。

    引数: path(Path)。返り値: JSON(dict)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def equal(actual: object, expected: object) -> None:
    """機能: 未定義を保ったまま数値を比較する。

    引数: actual/expected(object)。返り値: なし(None)。
    """
    if expected is None:
        assert actual is None
    else:
        assert np.isclose(float(actual), float(expected), atol=1e-6, rtol=1e-10), (actual, expected)


def combine(accounts: list[dict]) -> dict:
    """機能: 口座を独立合計し、全組で勝率と平均損益比を算出する。

    引数: accounts(list[dict])。返り値: 合計(dict)。
    """
    fields = ('profit', 'loss', 'net', 'fees', 'win_qty', 'loss_qty', 'flat_qty', 'wins', 'losses', 'cycles')
    a = {k: sum(x[k] for x in accounts) for k in fields}
    a['win_rate'] = a['wins']/a['cycles'] if a['cycles'] else None
    a['payoff'] = (a['profit']/a['wins'])/(a['loss']/a['losses']) if a['wins'] and a['losses'] else None
    a['active_sessions'] = sum(x['cycles'] > 0 for x in accounts)
    a['without_best'] = a['net']-max(0, max(x['net'] for x in accounts))
    return a


def label_week(session: str) -> str:
    """機能: 場名を月曜始まり週へまとめる。

    引数: session(str)。返り値: 週名(str)。
    """
    d = datetime.strptime(session[:10], '%Y-%m-%d').date()
    return str(d-timedelta(days=d.weekday()))+' の週'


def cells(row: object) -> list[str]:
    """機能: 表行の表示文字列を抜き出す。

    引数: row(BeautifulSoupタグ)。返り値: 各セル(list[str])。
    """
    return [c.get_text(' ', strip=True) for c in row.find_all(['th', 'td'], recursive=False)]


def main() -> None:
    """機能: 元JSONと全表示・CSVを照合し広狭の実Chrome画面を保存する。

    引数: なし。返り値: なし(None)。公開成果は変更しない。
    """
    published = read(OUT/'調査仕様と集計.json')
    selected = read(OUT/'比較3候補.json')['methods']
    assert len(published['methods']) == 375 and len(selected) == 3
    assert 'mini5枚=209円' in published['meta']['費用計算']
    sources = {}
    full = {}
    summaries = 0
    for m in published['methods']:
        path = ROOT/m['source']
        if str(path) not in sources:
            raw = read(path)
            sources[str(path)] = {x['id']: x for x in raw['methods']}
        old = sources[str(path)][m['id']]
        old_accounts = {(a['session'], a['symbol']): a for a in old['accounts']}
        assert len(m['accounts']) == 50
        for a in m['accounts']:
            original = old_accounts[(a['session'], a['symbol'])]
            for name in ('net', 'fees', 'gross_profit', 'gross_loss', 'win_qty', 'loss_qty', 'flat_qty', 'drawdown', 'equity_min', 'equity_max'):
                equal(a[name], original[name])
            for name, alternate in (('wins', 'group_wins'), ('losses', 'group_losses'), ('profit', 'group_profit'), ('loss', 'group_loss')):
                equal(a[name], original.get(alternate, original[name]))
            equal(a['cycles'], original.get('cycles', original.get('groups')))
            equal(a['profit']-a['loss'], a['net'])
        for symbol in ('TOPIX', 'NK225'):
            accounts = [a for a in m['accounts'] if a['symbol'] == symbol]
            assert len(accounts) == 25
            for name, value in combine(accounts).items():
                equal(m['summary'][symbol][name], value)
            summaries += 1
        full[(m['branch'], m['id'])] = m
    soup = BeautifulSoup((OUT/FILES[0]).read_text(encoding='utf-8'), 'html.parser')
    table_rows = 0
    trade_rows = 0
    session_rows = []
    ready = pickle.loads((HERE.parent.parent/'wave_v60/inputs.pkl').read_bytes())
    overview = soup.select('table.overview tbody tr')
    assert len(overview) == 6
    for k, m in enumerate(selected, 1):
        canonical = full[(m['branch'], m['id'])]
        assert m['accounts'] == canonical['accounts'] and m['summary'] == canonical['summary']
        for si, symbol in enumerate(('TOPIX', 'NK225')):
            aa = sorted([a for a in m['accounts'] if a['symbol'] == symbol], key=lambda a:a['session'])
            s = combine(aa)
            text = cells(overview[(k-1)*2+si])
            assert text[1] == symbol
            assert text[2] == f'{s["net"]:+,.0f}'
            assert text[3] == f'{s["wins"]}/{s["cycles"]}'
            assert text[4] == f'{s["win_rate"]*100:.1f}%'
            assert text[5] == f'{s["payoff"]:.3f}'
            assert text[6] == str(s['active_sessions'])
            assert text[7] == f'{s["without_best"]:+,.0f}'
            expected = [(a['session'].replace('_Day', ' 昼').replace('_Night', ' 夜'), a) for a in aa]
            for w in sorted({label_week(a['session']) for a in aa}):
                expected.append((w, combine([a for a in aa if label_week(a['session']) == w])))
            expected.append(('全期間', s))
            rows = soup.select(f'#c{k}-{symbol} tbody tr')
            assert len(rows) == len(expected) == 29
            for row, (label, a) in zip(rows, expected):
                actual = cells(row)
                correct = [label, f'{a["profit"]:,.0f}', f'{(a["loss"] or 0):,.0f}', f'{a["net"]:+,.0f}',
                    str(a['win_qty']), str(a['loss_qty']), f'{a["win_qty"]-a["loss_qty"]:+d}',
                    f'{a["wins"]}/{a["cycles"]}', f'{a["fees"]:,.0f}']
                assert actual == correct, (label, actual, correct)
                table_rows += 1
        raw = sources[str(ROOT/m['source'])][m['id']]
        path = Path(raw['ledger'])
        if not path.is_absolute():
            path = (ROOT/m['source']).parent/path
        payload = path.read_bytes()
        assert payload == (OUT/'台帳'/f'候補{k}_原簿.pkl').read_bytes()
        ledger = pickle.loads(payload)
        for symbol in ('TOPIX', 'NK225'):
            with (OUT/'台帳'/f'候補{k}_{symbol}_全決済.csv').open(encoding='utf-8-sig', newline='') as f:
                csvrows = list(csv.DictReader(f))
            expected = []
            for key, data in sorted(ledger.items()):
                if key[1] != symbol:
                    continue
                r = ready[key[:2]]
                for t in data['trades']:
                    if len(t) == 13:
                        ed, ei, xd, xi = t[:4].astype(int)
                        stamps = [r['time_s'][i] for i in (ed, ei, xd, xi)]
                        side, qty, ep, xp, ef, xf, gross, net = t[4:12]
                        fees = ef+xf
                        seqs = [r['seq'][ei], r['seq'][xi]]
                    else:
                        side, qty, ep, xp, gross, fees, net = t[2:9]
                        stamps = [r['time_s'][np.searchsorted(r['seq'], t[18])], t[0], t[11], t[1]]
                        seqs = [t[12], t[13]]
                    expected.append([key[0], '買い' if side > 0 else '売り', str(int(qty)),
                        *[datetime.fromtimestamp(float(v), JST).isoformat() for v in stamps],
                        str(ep), str(xp), str(gross), str(fees), str(net), *[str(int(v)) for v in seqs]])
            assert len(csvrows) == len(expected)
            for a, e in zip(csvrows, expected):
                assert list(a.values()) == e
            trade_rows += len(expected)
        for a in m['accounts']:
            session_rows.append([str(k), m['id'], a['symbol'], a['session'],
                *[str(a[f]) for f in ('profit', 'loss', 'net', 'fees', 'win_qty', 'loss_qty')],
                str(a['win_qty']-a['loss_qty']), *[str(a[f]) for f in ('wins', 'losses', 'cycles')]])
    with (OUT/'比較3候補の全セッション.csv').open(encoding='utf-8-sig', newline='') as f:
        csvsession = list(csv.reader(f))[1:]
    assert csvsession == session_rows and len(csvsession) == 150
    all_soup = BeautifulSoup((OUT/FILES[2]).read_text(encoding='utf-8'), 'html.parser')
    allrows = all_soup.select('#all tbody tr')
    assert len(allrows) == 375
    for row, m in zip(allrows, published['methods']):
        cell = cells(row)
        assert cell[:2] == [m['branch']+' '+m['id'], m['mode']]
        for offset, symbol in ((2, 'TOPIX'), (5, 'NK225')):
            a = m['summary'][symbol]
            rate = '未観測' if a['win_rate'] is None else f'{a["win_rate"]*100:.1f}%'
            payoff = '未観測' if a['payoff'] is None else f'{a["payoff"]:.3f}'
            assert cell[offset:offset+3] == [f'{a["net"]:+,.0f}', f'{rate} ({a["wins"]}/{a["cycles"]})', payoff]
    with (OUT/'全375条件の一覧.csv').open(encoding='utf-8-sig', newline='') as f:
        allcsv = list(csv.DictReader(f))
    assert len(allcsv) == 750
    for row in allcsv:
        m = full[(row['枝'], row['手法ID'])]
        a = m['summary'][row['銘柄']]
        assert row['評価価格'] == m['mode']
        for column, field in (('利益円','profit'), ('損失円','loss'), ('収支円','net'), ('手数料円','fees'),
            ('勝ち組','wins'), ('負け組','losses'), ('決済組','cycles'), ('勝率','win_rate'),
            ('平均勝ち負け比','payoff'), ('PF','pf'), ('活動場','active_sessions'), ('勝ち枚数','win_qty'),
            ('負け枚数','loss_qty'), ('最大黒字場除外円','without_best'), ('資産最大下落円','drawdown')):
            equal(row[column] if row[column] != '' else None, a[field])
    observed = [(m['id'], s, m['summary'][s]) for m in published['methods'] for s in ('TOPIX','NK225')
                if m['summary'][s]['win_rate'] is not None and m['summary'][s]['win_rate'] >= .95]
    assert len(observed) == 5 and all(s == 'TOPIX' and a['cycles'] == a['wins'] == 1 and a['payoff'] is None for _, s, a in observed)
    small = soup.find('h2', string='1取引だけで100%だった条件').parent
    small_rows = small.select('tbody tr')
    assert len(small_rows) == 5
    for row, (ident, symbol, a) in zip(small_rows, observed):
        shown = cells(row)
        assert shown[0] == ident and shown[2:] == [f'{a["net"]:+,.0f}', '1/1']
    text = soup.get_text(' ', strip=True)
    for phrase in ('95%達成手法としての推奨ではありません', '同じ入口', '負けが一度もないため', '未知データの検証合格を意味しません', '全取引費用後'):
        assert phrase in text
    links = 0
    for name in FILES:
        doc = BeautifulSoup((OUT/name).read_text(encoding='utf-8'), 'html.parser')
        for link in doc.select('a[href]'):
            href = link['href']
            if href.startswith(('http:', 'https:', '#')):
                continue
            assert (OUT/unquote(href.split('#')[0])).exists(), href
            links += 1
    for name in ('README.md', '監査まとめ.md', '3候補の銘柄差.md'):
        for href in re.findall(r'\]\(([^)]+)\)', (OUT/name).read_text(encoding='utf-8')):
            if href.startswith(('http:', 'https:', '#')):
                continue
            assert (OUT/unquote(href.split('#')[0])).exists(), href
            links += 1
    index = (OUT.parent/'index.html').read_text(encoding='utf-8')
    assert index.index('<!--00060開始-->') < index.index('<!--00059開始-->')
    assert (OUT.parent/'README.md').read_text(encoding='utf-8').count('<!--00060案内開始-->') == 1
    for link in BeautifulSoup(index[index.index('<!--00060開始-->'):index.index('<!--00060終了-->')], 'html.parser').select('a[href]'):
        assert (OUT.parent/unquote(link['href'])).exists()
        links += 1
    browser.PROBE = '''<script>
/** 機能: 公開タブと絞込と描画寸法を検査する。引数: なし。返り値: 検査結果(object)。 */
function verify(){let tabs=0;if(document.querySelector('.tabs')){for(const b of document.querySelectorAll('button[data-target]')){b.click();const card=b.closest('.card');if(card.querySelectorAll('.symbol-panel:not(.hidden)').length!==1||document.getElementById(b.dataset.target).classList.contains('hidden'))throw Error('銘柄タブ');tabs++;}for(const c of document.querySelectorAll('.card')){const b=c.querySelector('button');if(b)b.click();}}
if(document.querySelector('#search')){const input=document.querySelector('#search');for(const q of ['', '校正', '不存在語']){input.value=q;input.dispatchEvent(new Event('input'));let count=[...document.querySelectorAll('#all tbody tr')].filter(x=>!x.hidden).length;if(document.querySelector('#count').textContent!==`${count} / 375条件`)throw Error('件数');}input.value='';input.dispatchEvent(new Event('input'));}
if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');if(/NaN|Infinity|__DATA__/.test(document.body.innerText))throw Error('未定義表示');return {全合格:true,銘柄タブ数:tabs,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.body).backgroundColor};}
try{document.body.dataset.check=JSON.stringify(verify());}catch(e){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(e)});}</script>'''
    rendered = []
    for name, title in zip(FILES, ('主報告','改善報告','全条件')):
        source = (OUT/name).read_text(encoding='utf-8')+'</body>'
        rendered.append(browser.render(source, title+'_広幅', 1500, 1300))
        rendered.append(browser.render(source, title+'_狭幅', 520, 1300))
    rendered.append(browser.render((OUT/FILES[0]).read_text(encoding='utf-8')+'</body>', 'セッション表', 1500, 1350,
        '<script>document.querySelector("main").replaceChildren(document.querySelector("#candidate1"));window.scrollTo(0,0);</script>'))
    record = dict(合格=True, 目視確認=False, 元固定口座18750の公開JSON一致=True, 全750銘柄集計一致= summaries,
        選定候補の場週全期間表示行=table_rows, 候補全場CSV行=len(csvsession), 決済CSV行=trade_rows,
        全条件HTML行=len(allrows), 全条件CSV行=len(allcsv), 観測95の一組だけ5条件確認=True,
        静的リンク数=links, 描画=rendered, SHA256={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in FILES})
    (HERE/'報告書の独立検査.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
