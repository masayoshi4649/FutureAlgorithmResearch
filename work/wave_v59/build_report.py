"""固定72条件の旧場・追加場を区別した、日本語の短い報告を生成する。"""

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'アルゴリズム調査/00056_小幅回収と移動平均の比較'
TITLE = '小幅回収と移動平均の説明と損益'
SYMBOLS = ('TOPIX', 'NK225')
NAMES = {'TOPIX': 'TOPIX mini・5枚', 'NK225': 'NK225 micro・10枚'}
DESCRIPTIONS = {
    'S1': ('範囲の端の反発', '直近の狭い価格帯の下端で反発したら買い、上端で反落したら売る。', '入口時の価格帯を保持し、外へ抜けたら撤退する。追いかけて建て増さない。'),
    'S2': ('ボリンジャーバンド内への復帰', '値幅が狭いときだけ、平均から1.5標準偏差以上離れた価格が帯内へ戻ったら逆張りする。', '平均を通り越してからは入らず、入口時の価格帯を外れたら撤退する。'),
    'S3': ('短い行き過ぎからの戻り', '値幅が狭いときだけ、直前5分で1幅以上下げた後の反発を買う。上げた後の反落は売る。', 'まだ平均の手前にある戻りを狙い、入口時の価格帯を外れたら撤退する。'),
    'M1': ('移動平均のGC・DC', '確定1分足の5本平均が20本平均を上抜いたら買い、下抜いたら売る。', '逆方向へ動いたら追跡線で撤退する。同じ方向に線が並んでいるだけでは繰り返し入らない。'),
    'M2': ('移動平均の収束後の動き出し', '5本平均と20本平均が直前2本で接近し、差が半幅を超えて開いた方向に入る。短期平均の傾きと終値も同方向を求める。', '収束だけで反転を決めつけず、実際に動き出してから入り、追跡線で撤退する。'),
    'A1': ('小幅回収と追従の自動切替', '狭い往復の条件ならS1。往復条件ではなく、方向性が強いときはGC・DCを使う。中間は見送る。', '入口時に方式を決める。往復を狙った建玉は後で追従へ変えず、範囲外で撤退する。'),
}
CSS = '''body{margin:0;background:#101720;color:#e0e7ef;font:16px/1.7 system-ui,sans-serif}main{max-width:1240px;margin:auto;padding:28px 24px 70px}h1{font-size:1.75rem;line-height:1.45}h2{font-size:1.28rem;margin:32px 0 12px}h3{font-size:1.05rem}p{margin:10px 0}a{color:#86bdff}section,.notice{background:#182331;border:1px solid #304459;border-radius:10px;padding:18px;margin:18px 0}.notice{border-left:4px solid #7cacff}.muted{color:#aebfd0;font-size:.88rem}.positive{color:#8ce1b6}.negative{color:#ffa59e}.flat{color:#cad5e1}.table-wrap{overflow-x:auto;border:1px solid #354659;border-radius:6px;margin:12px 0}table{border-collapse:collapse;width:100%;font-size:.88rem;white-space:nowrap}th,td{text-align:right;padding:9px 12px;border-bottom:1px solid #2d4054}th{background:#233449;color:#cedff2}th:first-child,td:first-child{text-align:left}tbody tr:nth-child(even){background:#14202d}details{margin:14px 0}summary{cursor:pointer;color:#a9ceff;padding:8px 0}code{color:#c6dfff;font-size:.87rem}nav{display:flex;gap:14px;flex-wrap:wrap}dl{display:grid;grid-template-columns:4em 1fr;gap:8px 12px}dt{font-weight:bold;color:#bbd7f5}dd{margin:0}@media(max-width:600px){main{padding:15px 12px 40px}h1{font-size:1.4rem}section{padding:12px}th,td{padding:8px}dl{grid-template-columns:3em 1fr}}'''


def read(name: str) -> dict:
    """機能: 作業内の保存結果だけを読む。

    引数: name(str) は相対パス。返り値: JSON内容(dict)。原本は読まない。
    """
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def esc(value: object) -> str:
    """機能: 表示値をHTML用に変換する。

    引数: value(object)。返り値: エスケープ文字列(str)。
    """
    return html.escape(str(value), quote=True)


def number(value: float | None, digits: int = 0) -> str:
    """機能: 数値を桁区切りで表示する。

    引数: value(float|None)、digits(int)。返り値: 表示文字列(str)。
    """
    return '—' if value is None else f'{value:,.{digits}f}'.replace('-', '−')


def money(value: float) -> str:
    """機能: 収支の符号と色を付ける。

    引数: value(float)。返り値: HTML断片(str)。
    """
    css = 'positive' if value > 0 else 'negative' if value < 0 else 'flat'
    text = f'{value:+,.0f}'.replace('-', '−')
    return f'<span class="{css}">{text}</span>'


def table(headers: list[str], rows: list[list[str]]) -> str:
    """機能: 横スクロールできる表を生成する。

    引数: headers(list[str])、rows(list[list[str]])。返り値: HTML表(str)。
    """
    head = ''.join(f'<th scope="col">{esc(h)}</th>' for h in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{v}</td>' for v in row) + '</tr>' for row in rows)
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def aggregate(accounts: list[dict], quote: bool = False) -> dict:
    """機能: 保存台帳の金額・枚数を加算する。含み曲線の再計算は行わない。

    引数: accounts(list[dict])、quote(bool)。返り値: 加算可能指標と比率(dict)。
    """
    views = [a['sensitivity']['売買気配'] if quote else a for a in accounts]
    out = {k: sum(a[k] for a in views) for k in
           ('profit', 'loss', 'net', 'win_qty', 'loss_qty', 'flat_qty', 'wins', 'losses', 'cycles')}
    out['positive_sessions'] = sum(a['net'] > 0 for a in views)
    out['active_sessions'] = sum(a['cycles'] > 0 for a in views)
    out['without_best'] = out['net'] - max((a['net'] for a in views), default=0)
    out['win_rate'] = out['wins'] / out['cycles'] if out['cycles'] else None
    out['pf'] = out['profit'] / out['loss'] if out['loss'] else None
    win = out['profit'] / out['win_qty'] if out['win_qty'] else None
    loss = out['loss'] / out['loss_qty'] if out['loss_qty'] else None
    out['payoff'] = win / loss if win is not None and loss else None
    return out


def save_csv(name: str, rows: list[dict]) -> None:
    """機能: 会計表をUTF-8 BOM付きCSVに保存し、全セルを再読込照合する。

    引数: name(str)、rows(list[dict])。返り値: なし(None)。
    """
    with (OUT / name).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (OUT / name).open(encoding='utf-8-sig', newline='') as stream:
        actual = list(csv.DictReader(stream))
    expected = [{key: '' if value is None else str(value) for key, value in row.items()} for row in rows]
    assert actual == expected


def session_rows(accounts: list[dict], sessions: list[str], quote: bool = False) -> list[list[str]]:
    """機能: 場別の利益・損失・収支と決済枚数を二銘柄横並びにする。

    引数: accounts(list[dict])、sessions(list[str])、quote(bool)。返り値: 表の行(list[list[str]])。
    """
    lookup = {(a['session'], a['symbol']): a for a in accounts}
    rows = []
    for session in sessions + ['合計']:
        label = session.replace('_Day', ' 昼').replace('_Night', ' 夜')
        if session in ('2026-10-06_Night', '2026-10-07_Day'):
            label += '〈追加〉'
        row = [esc(label)]
        for symbol in SYMBOLS:
            a = (aggregate([v for v in accounts if v['symbol'] == symbol], quote) if session == '合計'
                 else lookup[(session, symbol)]['sensitivity']['売買気配'] if quote else lookup[(session, symbol)])
            row += [number(a['profit']), number(a['loss']), money(a['net']),
                    f'{a["win_qty"]}/{a["loss_qty"]}/{a["flat_qty"]}']
        rows.append(row)
    return rows


def page(title: str, content: str) -> str:
    """機能: 暗色の単独HTMLへ内容を組み込む。

    引数: title(str)、content(str)。返り値: 完全なHTML(str)。
    """
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><style>{CSS}</style></head><body>
<!--
[コンポーネント概要]
main は検証結果のルートです。主条件と追加確認の区分を保持します。
.table-wrap は狭い画面で会計表を横へスクロールする領域です。
details は詳しい場別会計と定義を利用者が展開できる折り畳みです。
.positive / .negative / .flat は収支の正負と同値を暗色背景で示します。
--><main>{content}</main></body></html>'''


def main() -> None:
    """機能: 二段階の結果を整合確認し、主6条件と全72条件の報告を作る。

    引数: なし。返り値: なし(None)。売買規則・採用候補は変更しない。
    """
    dev, hold = read('dev/売買結果.json'), read('holdout/売買結果.json')
    selection, narrative = read('追加場適用前固定.json'), read('報告判断.json')
    assert len(dev['sessions']) == 23 and len(hold['sessions']) == 2
    assert selection['開発結果SHA256'] == hashlib.sha256((HERE / 'dev/売買結果.json').read_bytes()).hexdigest()
    sessions = dev['sessions'] + hold['sessions']
    dm, hm = ({m['id']: m for m in data['methods']} for data in (dev, hold))
    assert list(dm) == list(hm) and len(dm) == 72
    OUT.mkdir(parents=True, exist_ok=True)
    full_accounts = {key: dm[key]['accounts'] + hm[key]['accounts'] for key in dm}
    csv_rows, totals = [], []
    for key, m in dm.items():
        for a in full_accounts[key]:
            for quote in (False, True):
                v = a['sensitivity']['売買気配'] if quote else a
                csv_rows.append(dict(手法ID=key, 主条件=m['primary'], 区分='追加2場' if a['session'] in hold['sessions'] else '旧23場',
                                     セッション=a['session'], 銘柄=a['symbol'], 評価='売買気配' if quote else '中値',
                                     利益円=v['profit'], 損失円=v['loss'], 収支円=v['net'], 勝ち枚数=v['win_qty'],
                                     負け枚数=v['loss_qty'], 同値枚数=v['flat_qty'], 勝負枚数差=v['win_qty']-v['loss_qty'],
                                     決済組数=v['cycles'], 場内最大減少額円=v['drawdown']))
        weekly = {}
        for session in sessions:
            day = datetime.fromisoformat(session[:10])
            week = (day - timedelta(days=day.weekday())).date().isoformat()
            weekly.setdefault('週 ' + week, []).append(session)
        for label, chosen in [('旧23場', dev['sessions']), ('追加2場', hold['sessions']), ('全25場', sessions), *weekly.items()]:
            for symbol in SYMBOLS:
                accounts = [a for a in full_accounts[key] if a['symbol'] == symbol and a['session'] in chosen]
                for quote in (False, True):
                    v = aggregate(accounts, quote)
                    names = {'profit':'利益円','loss':'損失円','net':'収支円','win_qty':'勝ち枚数','loss_qty':'負け枚数',
                             'flat_qty':'同値枚数','wins':'勝ち組数','losses':'負け組数','cycles':'決済組数',
                             'positive_sessions':'黒字場数','active_sessions':'取引場数','without_best':'最大黒字場除外収支円',
                             'win_rate':'取引勝率','pf':'総利益損失比','payoff':'平均勝ち負け比'}
                    totals.append(dict(手法ID=key, 主条件=m['primary'], 期間=label, 銘柄=symbol,
                                       評価='売買気配' if quote else '中値', **{names[k]: value for k,value in v.items()}))
    save_csv('全72条件の各セッション損益.csv', csv_rows)
    save_csv('全72条件の期間合計.csv', totals)
    # ----------------------------------------
    # 主条件の注文は、判定と次行約定の時刻・行番号まで公開する。
    order_rows = []
    for key in dict.fromkeys(selection['主6条件'] + selection['採用候補']):
        for a in full_accounts[key]:
            for order, qprice in zip(a['orders'], a['quote_order_prices']):
                order_rows.append(dict(手法ID=key, セッション=a['session'], 銘柄=a['symbol'],
                    判断時刻=datetime.fromtimestamp(order[0], timezone(timedelta(hours=9))).isoformat(),
                    約定時刻=datetime.fromtimestamp(order[1], timezone(timedelta(hours=9))).isoformat(),
                    判断原本行=int(order[2])+1, 約定原本行=int(order[3])+1,
                    種別='新規' if order[4] == 1 else '返済', 売買='買い' if order[5] > 0 else '売り',
                    枚数=int(order[6]), 中値約定=order[7], 気配約定=qprice, 中値実現損益円=order[8], 理由番号=int(order[9]), 組ID=int(order[10]), 幅W=order[12]))
    save_csv('主6条件と候補の全注文.csv', order_rows)
    # ----------------------------------------
    # 最初の画面は比較と結論だけとし、詳しい会計は手法ごとに展開できる。
    content = f'<nav><a href="../index.html">調査一覧</a><a href="全72条件.html">全72条件</a><a href="README.md">資料案内</a></nav><h1>{TITLE}</h1>'
    content += '<p class="muted">00056／旧23セッション＋規則固定後の追加2セッション／2026年9月21日〜10月7日</p>'
    content += '<div class="notice">' + ''.join(f'<p>{esc(x)}</p>' for x in narrative['冒頭']) + '</div>'
    content += '<p>両銘柄に同じ条件を適用。TOPIX miniは新規5枚、NK225 microは新規10枚で、上限10枚・20枚以内。増玉なし、場を跨がず全返済します。下表の主評価は判断後の<strong>次の板更新の中値</strong>。費用は0です。</p>'
    headers = ['セッション', 'TOPIX利益円', 'TOPIX損失円', 'TOPIX収支円', 'TOPIX勝/負/同値枚', 'NK利益円', 'NK損失円', 'NK収支円', 'NK勝/負/同値枚']
    for key in selection['採用候補']:
        accounts = full_accounts[key]
        content += f'<section id="candidate"><h2>旧23場で残った候補｜{key}</h2><p>直近10本の1分足が狭い範囲で往復しているときに、価格がボリンジャーバンドの内側へ戻ったら逆張り。<strong>利確1幅・損切り1幅・最長10分</strong>。範囲外へ抜けたら先に撤退します。トレーリングは使いません。</p>'
        content += ''.join(f'<p>{esc(x)}</p>' for x in narrative['候補'])
        candidate_rows = []
        for symbol in SYMBOLS:
            a = [v for v in accounts if v['symbol'] == symbol]
            v, q = aggregate(a), aggregate(a, True)
            candidate_rows.append([esc(NAMES[symbol]), money(dm[key]['summary'][symbol]['net']),
                money(dm[key]['summary'][symbol]['without_best']), money(hm[key]['summary'][symbol]['net']),
                money(v['net']), money(q['net']), number(v['win_rate'] * 100, 1) + '%', number(v['payoff'], 2)])
        content += table(['商品', '旧23場・円', '旧最大黒字場除外・円', '追加2場・円', '全25場・円', '気配全25場・円', '全25場勝率', '平均勝ち/負け'], candidate_rows)
        content += table(headers, session_rows(accounts, []))
        content += '<details><summary>候補の25セッション損益（中値）</summary>' + table(headers, session_rows(accounts, sessions)) + '</details>'
        content += '<details><summary>候補の25セッション損益（売買気配）</summary>' + table(headers, session_rows(accounts, sessions, True)) + '</details></section>'
    content += '<h2>先に決めた主6条件の比較</h2><p class="muted">結果で選んだ上記候補とは区別します。小幅3手法の主条件は利益保護付きX2、移動平均2手法はトレーリングX3です。</p>'
    rows = []
    for key in selection['主6条件']:
        m = dm[key]
        for symbol in SYMBOLS:
            a = [a for a in full_accounts[key] if a['symbol'] == symbol]
            v, q = aggregate(a), aggregate(a, True)
            rows.append([f'<a href="#{m["family"]}">{m["family"]} {esc(DESCRIPTIONS[m["family"]][0])}</a>', esc(NAMES[symbol]),
                         money(m['summary'][symbol]['net']), money(hm[key]['summary'][symbol]['net']), money(v['net']),
                         money(q['net']), number(v['win_rate'] * 100 if v['win_rate'] is not None else None, 1) + '%', number(v['payoff'], 2)])
    content += table(['主手法', '商品・新規枚数', '旧23場・円', '追加2場・円', '全25場・円', '同注文を気配約定・円', '取引勝率', '平均勝ち/負け'], rows)
    content += '<p class="muted">気配約定は同じ注文を「買いask・売りbid」で評価した価格感度です。参照板はラージなので小型商品の実約定そのものではありません。手数料を加えた数字ではありません。勝率の分母には同値決済を含みます。平均勝ち/負けは各銘柄内の1枚当たり平均金額比です。</p>'
    content += '<h2>今回わかったこと</h2>' + ''.join(f'<p>{esc(x)}</p>' for x in narrative['考察'])
    for key in selection['主6条件']:
        m, accounts = dm[key], full_accounts[key]
        name, entry, middle = DESCRIPTIONS[m['family']]
        exit_text = ('最初から1幅のトレーリング。買いは最高中値から1幅下、売りは最安中値から1幅上で返済。' if m['family'].startswith('M') else
                     '初期損切り1幅、利確1.5幅。半幅順行したら半幅のトレーリングを有効にし、遅くとも10分で返済。')
        if m['family'] == 'A1':
            exit_text += ' GC・DC側だけは利確上限と10分制限を外し、1幅トレーリング。'
        content += f'<section id="{m["family"]}"><h2>{m["family"]}｜{esc(name)}</h2><p class="muted"><code>{key}</code></p><dl><dt>入口</dt><dd>{esc(entry)}</dd><dt>途中</dt><dd>{esc(middle)}</dd><dt>出口</dt><dd>{esc(exit_text)}</dd></dl>'
        content += '<p>' + esc(narrative['手法別'][m['family']]) + '</p>'
        content += table(headers, session_rows(accounts, [], False))
        content += '<details><summary>25セッションの利益・損失・収支と枚数（中値）</summary>' + table(headers, session_rows(accounts, sessions)) + '</details>'
        content += '<details><summary>同じ注文を売買気配で約定した場合</summary>' + table(headers, session_rows(accounts, sessions, True)) + '</details></section>'
    content += '<details><summary>幅・移動平均・売買条件の定義</summary><p>1幅Wは、その場で最初に観測した中値の0.025%を呼値へ切上げた値（最低2呼値）。ATRは使いません。半幅と1.5幅も呼値へ切上げます。主条件は確定1分足の5本/20本平均。ほかに1分足3/10・10/40、5分足3/10を比較しました。</p><p>狭い往復とは、現在足を除く直前20本の高安幅が2〜6W、効率比ERが0.35以下、20本平均と3本前の差がW以下で、現在終値が範囲内の場合です。将来の大波を知って避ける処理ではありません。固定した箱の高安から1呼値外側へ抜けたら返済します。</p><p>欠損足は過去終値で補完しますが、長期窓の実観測80%以上と直近実観測を必須にします。補完は収束を人工的に強める可能性が残ります。「次の板更新」は価格変更を伴わない更新も含む次の有効原本レコードです。時計は受信時刻ではなく最終約定時刻で、同時刻でも原本行順を守ります。実行時の通信遅延はこの試算に含みません。</p><p>入口が同じでも出口で保有時間が変わり、その後に入れる候補も変わります。出口だけの純粋な効果とは解釈しません。</p></details>'
    content += '<details><summary>検証の分離・資料</summary><p>旧23場は繰り返し使った既知データです。今回は72条件と主6条件、採用基準を損益計算前に固定。旧場の結果と採用候補を保存してから、未読の10月6日夜・7日昼へ一度だけ適用しました。追加2場の結果による主条件差し替えはしていません。</p>'
    content += f'<p>事前の研究候補採用基準を満たした条件数：{len(selection["採用候補"])}。基準は両銘柄それぞれで、中値黒字・最大黒字場を除いて黒字・平均勝ち/負け&gt;1・旧3期間すべて黒字・決済30回以上・取引8場以上。</p>'
    content += '<p>短い反転には売買気配の往復も混ざり得るため中値と気配を分けました。<a href="https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1984.tb03897.x">Roll (1984)</a>。最高成績だけを抜き出さないよう、試した全条件を残しました。選択偏りは残ります。今回、統計的な選択補正検定を実施したという意味ではありません。<a href="https://eprints.lse.ac.uk/119144/1/dp303.pdf">Sullivan・Timmermann・White</a>。</p>'
    content += '<nav><a href="全72条件の各セッション損益.csv">全場会計CSV</a><a href="全72条件の期間合計.csv">期間・週合計CSV</a><a href="主6条件と候補の全注文.csv">全注文CSV</a><a href="../../work/wave_v59/調査仕様.json">固定仕様</a><a href="../../work/wave_v59/追加場適用前固定.json">追加前の選定記録</a></nav></details>'
    (OUT / f'{TITLE}.html').write_text(page(TITLE, content), encoding='utf-8')
    # ----------------------------------------
    # 72条件の成績は主6条件とは別画面へ全て掲載し、最高成績だけを抜かない。
    full = f'<nav><a href="{TITLE}.html">短い説明と主6条件</a></nav><h1>全72条件の比較</h1><p>旧23場と追加2場を分けて表示。全て次の板更新で約定。円収支は銘柄別に読み、銘柄間で足し合わせた順位を作りません。</p>'
    for family in DESCRIPTIONS:
        rows = []
        for key, m in dm.items():
            if m['family'] != family:
                continue
            row = [esc(key) + (' ★主条件' if m['primary'] else '')]
            for symbol in SYMBOLS:
                accounts = [a for a in full_accounts[key] if a['symbol'] == symbol]
                v, q = aggregate(accounts), aggregate(accounts, True)
                row += [money(m['summary'][symbol]['net']), money(hm[key]['summary'][symbol]['net']), money(v['net']), money(q['net']), str(v['cycles'])]
            rows.append(row)
        full += f'<h2>{family} {esc(DESCRIPTIONS[family][0])}</h2>' + table(['手法ID', 'TOPIX旧23場', 'TOPIX追加2場', 'TOPIX全25場', 'TOPIX気配全25場', 'TOPIX決済組', 'NK旧23場', 'NK追加2場', 'NK全25場', 'NK気配全25場', 'NK決済組'], rows)
    full += '<p>全72条件の各場の利益・損失・収支・勝負枚数は<a href="全72条件の各セッション損益.csv">全場会計CSV</a>。X1=1幅利確・1幅損切り・10分、X2=1.5幅利確・順行半幅後に半幅追跡・10分、X3=即時1幅追跡。A1の追従側は常にX3です。</p>'
    (OUT / '全72条件.html').write_text(page('全72条件の比較', full), encoding='utf-8')
    evidence = dict(合格=True, 条件数=len(dm), 会計CSV行数=len(csv_rows), 期間CSV行数=len(totals), 注文CSV行数=len(order_rows),
                    入力SHA256={stage: hashlib.sha256((HERE / stage / '売買結果.json').read_bytes()).hexdigest() for stage in ('dev', 'holdout')},
                    HTML_SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.html')})
    (HERE / '報告出力照合.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == '__main__':
    main()
