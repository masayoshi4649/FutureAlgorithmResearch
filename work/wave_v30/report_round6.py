"""保有撤回の情報源を比べた84条件を、短い結論と全セッション損益で表示する。"""

from __future__ import annotations

from datetime import datetime
import gzip
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = '00025_相手不一致と保有撤回の分離'
OUT = ROOT / 'アルゴリズム調査' / NAME
TITLE = '相手不一致と保有撤回'
SYMBOLS = ('TOPIX', 'NK225')


def read(path: Path, default: object = None) -> object:
    """機能: 保存済み報告資料を読み、未完了なら既定値を返す。

    引数: path (Path)、default (object)。返り値: 内容 (object)。現在保存物は拒否する。
    """
    assert 'live' not in path.parts
    if not path.exists():
        return default
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def money(value: float) -> str:
    """機能: 円額を符号付きで表示する。

    引数: value (float)。返り値: 暗色背景で読める円額 (str)。
    """
    css = 'good' if value > 0 else 'bad' if value < 0 else 'muted'
    return f'<span class="{css}">{value:+,.0f}</span>'


def table(headers: list, rows: list) -> str:
    """機能: 表示済みセルの表を横スクロール枠で包む。

    引数: headers/rows (list)。返り値: HTML (str)。
    """
    return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{h}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{v}</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def sums(rows: list[dict]) -> dict:
    """機能: 決済金額と枚数だけを期間合算する。

    引数: rows (list[dict])。返り値: 加算可能な項目の合計 (dict)。最大下落は合算しない。
    """
    keys = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units', 'closed_units')
    return {key: sum(r[key] for r in rows) for key in keys}


def result_row(label: str, row: dict) -> list:
    """機能: 金額と決済枚数を同じ行に並べる。

    引数: label (str)、row (dict)。返り値: 表セル (list)。
    """
    return [escape(label), money(row['gross_profit_yen']), money(-row['gross_loss_yen']), money(row['net_yen']),
            f"{row['profit_units']:,}", f"{row['loss_units']:,}", f"{row['zero_units']:,}",
            f"{row['profit_units']-row['loss_units']:+,}"]


def comparisons(candidates: list[dict]) -> list[dict]:
    """機能: 収支順位で選ばず、12入口の対応差を全件で要約する。

    引数: candidates (list[dict])。返り値: 管理方式・銘柄ごとの対照結果 (list[dict])。
    """
    by_id = {c['id']: c for c in candidates}
    output = []
    for c_id, s_id, label in [('L001', 'L002', '反転'), ('L003', 'L004', '中立10分'), ('L005', 'L006', '併用')]:
        for symbol in SYMBOLS:
            for left, right, contrast in [(s_id, c_id, '自己−両市場'), (s_id, 'L000', '自己−価格のみ'), (c_id, 'L000', '両市場−価格のみ')]:
                pairs = [(by_id[f'H{i:03d}__{left}'], by_id[f'H{i:03d}__{right}']) for i in range(3, 92, 8)]
                net = [a['symbols'][symbol]['net_yen'] - b['symbols'][symbol]['net_yen'] for a, b in pairs]
                dd = [a['symbols'][symbol]['drawdown_yen'] - b['symbols'][symbol]['drawdown_yen'] for a, b in pairs]
                output.append({'mode': label, 'symbol': symbol, 'contrast': contrast, 'n': 12,
                               'net_median': float(np.median(net)), 'dd_median': float(np.median(dd)),
                               'net_better': sum(v > 0 for v in net), 'dd_better': sum(v < 0 for v in dd),
                               'net_equal': sum(v == 0 for v in net)})
    return output


def update_index(complete: bool) -> None:
    """機能: 作業一覧の最新リンクを新作業へ更新し、過去資料を残す。

    引数: complete (bool)。返り値: なし (None)。
    """
    base = ROOT / 'アルゴリズム調査'
    path = base / 'index.html'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<!--00025開始-->.*?<!--00025終了-->', '', text, flags=re.S)
    text = text.replace('task latest', 'task').replace(' <span class="badge">最新</span>', '')
    state = '全84条件の反証結果' if complete else '第6反復を検証中'
    text = re.sub(r'<p class="lead">.*?</p>', f'<p class="lead">最新は00025（{state}）。現在データの追加取得は行っていません。</p>', text, count=1)
    block = f'<!--00025開始--><article class="task latest"><div class="number">作業00025 <span class="badge">最新</span></div><h2>{TITLE}</h2><p>入口と枚数を固定し、保有撤回だけを両市場一致と自己方向に分ける84条件。</p><a class="button" href="{NAME}/{TITLE}.html">{state} →</a><p><a href="{NAME}/README.md">資料案内</a></p></article><!--00025終了-->'
    text = text.replace('</header>', '</header>' + block, 1)
    path.write_text(text, encoding='utf-8')
    path = base / 'README.md'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00025の[{TITLE}]({NAME}/{TITLE}.html)（{state}）。**', text, count=1)
    text = re.sub(r'^\| `00025_.*\n', '', text, flags=re.M).replace('`（最新）', '`')
    anchor = '| --- | --- | --- | --- |'
    text = text.replace(anchor, anchor + f'\n| `{NAME}`（最新） | 同じ入口の84条件を全件反証 | [第6反復]({NAME}/{TITLE}.html) | [資料案内]({NAME}/README.md) |', 1)
    path.write_text(text, encoding='utf-8')


def main() -> None:
    """機能: 完了した資料だけを集計し、短い本文と全84明細を生成する。

    引数: なし。返り値: なし (None)。未保存の検査は通過としない。
    """
    OUT.mkdir(exist_ok=True)
    fixed = read(HERE / '探索条件の固定.json')
    candidates = read(HERE / '全条件の期間集計.json.gz', [])
    first = read(HERE / '一次反証の結果.json', [])
    random = read(HERE / '無関係対照の要約.json', [])
    decision = read(HERE / '研究候補の固定.json')
    episode = read(HERE / 'episode_audit.json', {})
    guard = read(HERE / '選抜整合の監査.json')
    accounting = read(HERE / 'all_accounting_audit.json', {})
    mechanism = read(HERE / 'context_comparison.json', {})
    guard_ok = bool(guard and guard.get('完全性検査通過') is True
                    and all(guard.get(k) == v for k, v in
                            {'全探索候補数': 84, '一次反証候補数': 84, '乱数候補数': 84,
                             '乱数実体数': 10752, '波明細数': 704, '現在データ使用': False}.items())
                    and (HERE / '研究候補の固定.json').exists()
                    and guard.get('選抜JSON_SHA256') == sha256((HERE / '研究候補の固定.json').read_bytes()).hexdigest())
    complete = bool(len(candidates) == len(first) == len(random) == 84 and decision and guard_ok
                    and len({c['id'] for c in candidates}) == 84
                    and {r['candidate']['id'] for r in first} == {c['id'] for c in candidates}
                    and {r['candidate']['id'] for r in random} == {c['id'] for c in candidates}
                    and len(episode.get('結果', [])) == 704
                    and accounting.get('全監査合格') is True and accounting.get('全入力数') == 2184
                    and mechanism.get('全入力数') == 2184)
    body = [f'<p><a href="../index.html">作業一覧</a></p><h1>{TITLE}</h1>']
    if not complete:
        body.append(f'<p class="lead">検証中：本再生 {len(candidates)}/84、一次反証 {len(first)}/84、乱数対照 {len(random)}/84。最終資料を確認中です。</p>')
    elif decision['主候補'] is None:
        body.append('<p class="lead">既存の黒字候補は残りました。今回追加した出口には、改良を確認できませんでした。</p>')
        passed = [r for r in first if not r['first_stage_failures']]
        if all(r['candidate']['manager_id'] == 'L000' for r in passed):
            body.append(f'<p>追加撤回を使う72条件は一次反証を通過せず、通過した{len(passed)}条件は<strong>価格ストップと追跡返済だけを使う既存型</strong>でした。今回は固定検査を通る追加撤回がなく、両銘柄の収支75%維持・最大下落20%削減という改良目標も未達でした。</p>')
    else:
        body.append('<p class="lead">事前基準に合う研究候補が残りました。未知期間の成績は未確認です。</p>')
    body.append('<p>問いは単純です。<strong>他方の市場が追随しないだけで降りる必要があるか。</strong>同じ入口・枚数のまま、両市場の確認（C）、自己の方向だけ（S）、価格注文だけ（B0）を比較しました。</p>')
    body.append('<p class="muted">既知13セッション（9月21日〜29日デイ）。現在データは追加取得・再利用していません。金額はTOPIXミニ／NKマイクロ換算、費用0・指定価格約定。全玉をセッション内で返済します。</p>')
    if len(first) == 84:
        passed = [r['candidate'] for r in first if not r['first_stage_failures']]
        random_status = {}
        for item in random:
            modes = item['summary']
            random_status[item['candidate']['id']] = bool(len(modes) == 2 and all(
                m['試行数'] == 64 and m['両銘柄で候補以上の収支seed数'] <= 3
                and all(m['symbols'][symbol]['候補以上のPF_seed数'] <= 6 for symbol in SYMBOLS) for m in modes))
        body.append('<details><summary>残った既存候補の収支を見る（一次反証通過）</summary>' + table(
            ['手法', 'TOPIX収支 円', '利益÷損失', 'NK収支 円', '利益÷損失', '乱数対照'],
            [[c['id'], money(c['symbols']['TOPIX']['net_yen']), f"{c['symbols']['TOPIX']['money_ratio']:.2f}",
              money(c['symbols']['NK225']['net_yen']), f"{c['symbols']['NK225']['money_ratio']:.2f}",
              '未完了' if c['id'] not in random_status else '通過' if random_status[c['id']] else '未達'] for c in passed]) +
            '<p>ここでの通過は既知データ上の検査です。出口追加の75%収支／80%最大下落という目標とは別で、基準B0自身は同入口B0より20%下落を減らせないため「新しい改良」には入りません。</p></details>')
    if (OUT / '５分足と売買.html').exists():
        body.append('<p><a class="button" href="５分足と売買.html">５分足と売買位置を見る</a></p>')
    body.append('<details><summary>7管理の機械的な条件</summary><p>入口は12種類の中期方向＋両市場確認＋短期価格確認。新規は0.25ATRの反発・反落追跡で、TOPIX5枚／NK10枚。初期1ATR相当で損切り、2ATRで2枚／5枚を利確、1.5ATR後は3ATR幅で追跡。最長360分、返済後5分休止。ATRは公開済み5分足の12期間平滑、注文準備時に固定します。</p>')
    body.append(table(['ID', '保有中の追加返済条件'], [[m['id'], escape(m['name'])] for m in fixed['managers']]))
    body.append('<p>Cは両市場が一致した方向、不一致なら中立。Sは自市場だけの方向。反転は保有方向と逆になれば、次原本行以降に全返済。中立は方向0が10分続けば返済。価格による損切り・追跡・時間切れも常に監視します。即時ドテンはしません。</p></details>')
    compared = comparisons(candidates) if len(candidates) == 84 else []
    if compared:
        body.append('<h2>自己だけの撤回は改善したか</h2><p>各欄は全12入口の差の中央値。収支差はプラス、最大下落の差はマイナスが改善です。</p>')
        compact = []
        for r in compared:
            if r['contrast'] != '自己−両市場':
                continue
            base = next(x for x in compared if x['mode'] == r['mode'] and x['symbol'] == r['symbol'] and x['contrast'] == '自己−価格のみ')
            compact.append([r['mode'], r['symbol'], money(r['net_median']), f"{r['dd_median']:+,.0f}", money(base['net_median']), f"{base['dd_median']:+,.0f}"])
        body.append(table(['方式', '銘柄', '自己−両市場：収支', '同：最大下落', '自己−価格のみ：収支', '同：最大下落'], compact))
        body.append('<p class="muted">「自己」が「両市場」より良くても、「価格のみ」へ戻っただけなら新しい優位とは扱いません。収支差には早期返済後の再エントリーも含まれます。</p>')
        if mechanism:
            label_map = {'中立10分': '中立', '反転': '反転', '併用': '併用'}
            comparison_map = {'自己−両市場': 'S-C', '自己−価格のみ': 'S-B0', '両市場−価格のみ': 'C-B0'}
            for row in compared:
                independent = next(r for r in mechanism['全12入口の等重み集計'] if r['mode'] == label_map[row['mode']] and r['symbol'] == row['symbol'] and r['comparison'] == comparison_map[row['contrast']])
                assert row['net_median'] == independent['収支差中央値円'] and row['dd_median'] == independent['DD差中央値円']
            body.append('<details><summary>似たEMAをまとめた5思想でも比較する</summary><p>EMA二系統を一思想へまとめ、価格差・高安突破・VWAP・回帰と合わせた5群です。群内平均の後で群間中央値を取り、近いEMA条件の多さに引っ張られないか確認します。単位は円。</p>' + table(
                ['撤回', '比較', '銘柄', '収支差', '最大下落の差'],
                [[r['mode'], r['comparison'], r['symbol'], money(r['思想内平均収支差の中央値円']), f"{r['思想内平均DD差の中央値円']:+,.0f}"] for r in mechanism['EMAを統合した5思想の等重み']]) + '</details>')
            body.append('<details><summary>なぜ同じ価格でも返済が変わったか</summary><p>例えば9月21日TOPIXのH043。10:06:32の時点では、両市場Cの中立時計は606秒でした。その内訳は自己中立383秒→相手未一致71秒→自己中立152秒。途中の71秒では自己の売り方向が復活していたため、自己Sの中立時計はリセットされ、152秒でした。Cだけが中立返済する分岐を確認しました。</p><p>逆に自己の方向が反転すると、相手が追随する前にSだけが早く返済する分岐もあります。自己だけを見ることは、単に長く握ることではありません。分岐後の再新規まで含めて収支を比較しています。</p><p><a href="../../work/wave_v30/context_cause_summary.md">全件の原因集計</a></p></details>')
    if candidates:
        body.append('<h2>手法別の利益・損失・収支</h2><p>入口と管理を選ぶと、両銘柄の週別・全セッションが開きます。勝ち／負け枚数は決済した枚数で、差は保有残ではありません。</p>')
        body.append('<div class="controls"><label>入口 <select id="signal-filter"><option value="">全入口</option>' + ''.join(f'<option value="{s["id"]}"' + (' selected' if s['id'] == 'H019' else '') + f'>{s["id"]} {escape(s["name"])}</option>' for s in fixed['signals']) + '</select></label><label>管理 <select id="manager-filter"><option value="">全管理</option>' + ''.join(f'<option value="{m["id"]}">{m["id"]} {escape(m["name"])}</option>' for m in fixed['managers']) + '</select></label></div><p id="visible-count"></p>')
        failures = {x['candidate']['id']: x['first_stage_failures'] for x in first}
        wave = {x['method']: x for x in episode.get('方法別要約', [])}
        body.append('<details><summary>全84条件の一覧を開く（銘柄間の円額は合算しません）</summary>' + table(['手法', 'TOPIX収支 円', '最大下落 円', 'NK収支 円', '最大下落 円', '一次反証'],
                          [[f'<a href="#{c["id"]}">{c["id"]}</a>', money(c['symbols']['TOPIX']['net_yen']), f"{c['symbols']['TOPIX']['drawdown_yen']:,.0f}", money(c['symbols']['NK225']['net_yen']), f"{c['symbols']['NK225']['drawdown_yen']:,.0f}", '未完了' if c['id'] not in failures else '通過' if not failures[c['id']] else '未達'] for c in candidates]) + '</details>')
        headers = ['期間', '利益 円', '損失 円', '収支 円', '勝ち枚', '負け枚', '同値枚', '枚数差']
        verified = []
        for spec in fixed['signals']:
            saved = {x['id']: x['rows'] for x in read(HERE / 'sessions' / (spec['id'] + '.json.gz'), [])}
            for manager in fixed['managers']:
                identifier = spec['id'] + '__' + manager['id']
                candidate = next((c for c in candidates if c['id'] == identifier), None)
                if not candidate:
                    continue
                body.append(f'<details class="method" id="{identifier}" data-signal="{spec["id"]}" data-manager="{manager["id"]}"><summary>{identifier}：{escape(spec["name"])}／{escape(manager["name"])}</summary>')
                body.append(f'<p>{escape(spec["description"])} {escape(manager["description"])}</p>')
                for symbol in SYMBOLS:
                    rows = sorted([r for r in saved[identifier] if r['symbol'] == symbol], key=lambda r: r['session'])
                    assert len(rows) == 13
                    total = sums(rows)
                    for key, value in total.items():
                        assert abs(value - candidate['symbols'][symbol][key]) < .01
                    groups = [('全13セッション', total), ('9/21〜25（10セッション）', sums([r for r in rows if r['session'][:10] < '2026-09-28'])),
                              ('9/28〜29（3セッション）', sums([r for r in rows if r['session'][:10] >= '2026-09-28']))]
                    body.append(f'<h3>{symbol}：' + ('ミニ' if symbol == 'TOPIX' else 'マイクロ') + '</h3>')
                    values = [result_row(label, row) for label, row in groups]
                    values += [result_row(r['session'].replace('_Day', ' 昼').replace('_Night', ' 夜'), r) for r in rows]
                    body.append(table(headers, values))
                    s = candidate['symbols'][symbol]
                    body.append(f'<p>利益÷損失 {s["money_ratio"]:.2f}、1枚平均の勝ち÷負け {s["average_unit_payoff"]:.2f}、含み損込み最大下落 {s["drawdown_yen"]:,.0f}円。最大2勝ちセッションを除いた収支 {s["two_sessions_removed_net"]:+,.0f}円。</p>')
                    verified.append({'id': identifier, 'symbol': symbol, '13セッション合算一致': True, **total})
                if identifier in failures:
                    body.append('<p>一次反証：' + ('通過' if not failures[identifier] else escape('、'.join(failures[identifier]))) + '</p>')
                if identifier in wave:
                    waves = sorted([r for r in episode['結果'] if r['method'] == identifier], key=lambda r: (r['wave'], r['symbol']))
                    assert len(waves) == 8
                    body.append(f'<details class="waves"><summary>指定波：正方向20分の目安 {wave[identifier]["目安達成区間数"]}/8。保有時間と区間損益を見る</summary><p>区間損益は始点と終点の実現＋含みの差。区間に入る前の建玉も含み、当該時間に新規した玉の最終損益ではありません。20分は目的適合の目安です。</p>' +
                                table(['波', '銘柄', '正方向 分', '逆方向 分', '区間損益 円'],
                                      [[escape(r['波名']), r['symbol'], f"{r['正方向ネット保有分']:.1f}", f"{r['逆方向ネット保有分']:.1f}", money(r['時価損益差円'])] for r in waves]) + '</details>')
                body.append('</details>')
        (OUT / '表示数値の検査.json').write_text(json.dumps(verified, ensure_ascii=False, indent=2), encoding='utf-8')
    body.append('<details><summary>検証の範囲・再現資料</summary><p>84条件は同じ13セッションからの発見です。上位だけを選ばず全件へ遅延・近傍・条件除去・64乱数×2方式・指定8波を適用。研究候補には、旧H019D273と同入口B0の両方に対して「両銘柄で収支75%維持、最大下落20%削減」も要求します。これは事前の改善目標であり、未達が直ちに全手法の赤字や無価値を意味するものではありません。</p><p>全2,184入力を注文から独立に再計算し、全玉の損益・在庫・最大下落が一致。未来切断・将来値改変・上下反射、枚数上限と場内返済も確認しました。これらは会計と因果性の検査で、未知相場の利益保証ではありません。</p><p><a href="README.md">資料案内と再現手順</a> · <a href="../../work/wave_v30/次段階の敵対整理.md">既存候補の評価と次に確かめること</a></p></details>')
    css = ':root{color-scheme:dark;background:#0b121e;color:#e4edf8;font-family:"Yu Gothic UI",Meiryo,sans-serif}body{max-width:1280px;margin:auto;padding:28px 20px;line-height:1.75}h1{font-size:30px}h2{font-size:23px;margin-top:32px}h3{font-size:18px}.lead{font-size:21px;color:#b9d8ff}a{color:#8ec9ff}.good{color:#76e0b6}.bad{color:#ff9ca9}.muted{color:#a8bacf}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:14px}th,td{padding:7px 10px;border-bottom:1px solid #2d4059;text-align:right}th{background:#192a40;color:#bfd3eb}th:first-child,td:first-child{text-align:left}details{background:#111d2e;border:1px solid #30445e;border-radius:9px;margin:16px 0;padding:14px}summary{cursor:pointer;font-weight:bold}select{font:inherit;background:#15263d;color:#e4edf8;padding:5px;max-width:100%}.controls{display:flex;gap:20px;flex-wrap:wrap}.controls label{max-width:100%}.method[hidden]{display:none}.button{display:inline-block;padding:9px 15px;background:#205a91;border-radius:7px}'
    script = '''/**
 * 保存済み手法の表示だけを選択する。
 * @param {Event|undefined} event - 選択操作。省略可能。
 * @returns {undefined} 返り値なし。売買や通信は行わない。
 */
function filterMethods(event){const s=document.getElementById('signal-filter'),m=document.getElementById('manager-filter');if(!s)return;let count=0;document.querySelectorAll('.method').forEach(e=>{e.hidden=!!((s.value&&e.dataset.signal!==s.value)||(m.value&&e.dataset.manager!==m.value));if(!e.hidden)count++;});document.getElementById('visible-count').textContent=count+'手法を表示';}
document.querySelectorAll('select').forEach(e=>e.addEventListener('change',filterMethods));filterMethods();
document.querySelectorAll('a[href^="#H"]').forEach(a=>a.addEventListener('click',()=>{document.querySelectorAll('select').forEach(s=>s.value='');filterMethods();document.getElementById(a.getAttribute('href').slice(1)).open=true;}));'''
    html = '<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + TITLE + '</title><style>' + css + '</style><body><!--\n[コンポーネント概要]\n.controls は入口・管理による表示選択、.method は全玉の期間別損益です。\n表の値は保存済み結果を照合して表示し、通信や注文は行いません。\n-->' + ''.join(body) + '<script>' + script + '</script></body></html>'
    destination = OUT / (TITLE + '.html')
    destination.write_text(html, encoding='utf-8')
    for target in re.findall(r'href="([^"]+)"', html):
        if target.startswith('#'):
            assert f'id="{target[1:]}"' in html
        elif not urlsplit(target).scheme:
            resolved = (OUT / unquote(target)).resolve()
            assert resolved.exists() or target == 'README.md'
    (OUT / 'README.md').write_text(f'''# 作業00025：{TITLE}

最初に見るファイルは [{TITLE}]({TITLE}.html) です。

読む順序：
1. 主報告の短い結論と全入口の対応比較。
2. 手法を選び、TOPIXミニ／NKマイクロの全玉・週別・13セッション損益。
3. ５分足図（生成後）で新規・返済と入口／保有方向の違い。
4. [結果前の設計](../../work/wave_v30/管理設計の固定.json)、[反証規則](../../work/wave_v30/反証規則の固定.json)、work/wave_v30内の構造・比較・会計監査。

詳しい根拠：[構造と先読み検査](../../work/wave_v30/context_structure_audit.md)、[全件の対応比較](../../work/wave_v30/context_comparison.md)、[最初の返済分岐](../../work/wave_v30/context_cause_summary.md)、[全84の独立会計](../../work/wave_v30/all_accounting_audit.md)、[選抜の整合性](../../work/wave_v30/選抜整合の監査.json)、[改良なしと解なしの区別](../../work/wave_v30/次段階の敵対整理.md)。

初回TOPIX5枚／NK10枚、片方向同時上限10／20枚。費用0、指定価格約定。大きい契約の原本を小型契約倍率へ換算している。損失玉を含め全玉を場内返済する。

全84は既知13セッションの限定診断。現在APIと保存済み9月29日ナイト21時のデータは使わない。候補採用と診断の完了を区別する。

再現：プロジェクトルートで `python -X utf8 work/wave_v30/verify_replay.py --run --workers 12`。固定元と既存結果の指紋・集計を照合してから再実行する。反証・指定波・独立監査を完了してから `python -X utf8 work/wave_v30/select_verified.py`、`python -X utf8 work/wave_v30/report_round6.py`。凍結コードに差があれば停止する。
''', encoding='utf-8')
    data = {'最終資料完備': complete, '全条件': len(candidates), '一次反証': len(first), '乱数対照': len(random),
            '主候補': None if decision is None else decision['主候補'], '対応比較': compared,
            '現在データ使用': False, '表数': html.count('<table>')}
    (OUT / '表示データ.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    update_index(complete)
    print(json.dumps(data, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
