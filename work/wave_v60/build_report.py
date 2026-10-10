"""中期売買と週内グリッドを、費用・含み損を省略しない短いHTMLへまとめる。"""

import csv
import hashlib
import html
import json
from pathlib import Path

from analyze import load, aggregate, method_accounts, SYMBOLS, WEEKS


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FOLDER = '00057_中期売買と週内グリッドの手数料込み検証'
OUT = ROOT / 'アルゴリズム調査' / FOLDER
TITLE = '30〜60分売買と週内グリッドの説明と損益'
NAMES = {'TOPIX':'TOPIX mini', 'NK225':'NK225 micro'}
MODES = {'quote':'条件成立後の売買気配', 'mid':'中値約定の参考', 'passive':'待機指値・通過確認の仮定'}
DESCRIPTIONS = {
    'MT1': ('GC・DC', '5分足の短い平均が長い平均を上抜いたら買い、下抜いたら売り。'),
    'MT2': ('高安の突破', '直近の確定足の高値・安値を抜け、移動平均の向きも一致したら入る。'),
    'MT3': ('押し目・戻りから再開', '長い平均の向きに合わせ、短い平均まで戻った価格が再び進み始めたら入る。'),
    'MR1': ('平均への回帰', '一方向の動きが弱いときに、平均から離れた価格がボリンジャーバンド内へ戻ったら逆張りする。'),
    'MA1': ('追従と回帰の切替', '方向性が強ければ押し目・戻り、弱ければ平均への回帰を選ぶ。中間は見送る。'),
    'G0': ('上限だけの往復グリッド', '中心より下に買い、上に売りを並べ、1間隔戻れば利確。同じ段を再配置する。損失保護のない比較基準。'),
    'G1': ('全建玉の損失予算', '往復グリッドに、含み損と手数料を含む資産下落で全返済する規則を加える。30分休止して再開し、週の損失予算に達したらその週は終了。'),
    'G2': ('方向を認めて逆玉整理', 'G1に加え、上昇が続けば売り玉を整理して買い新規だけにする。下降時は逆。損失を抱えた方向への追加を止める。'),
    'G3': ('逆行時のカバー両建て', 'G1に加え、方向が保有と逆なら反対玉を建てて正味の枚数を抑える。カバー中は格子を休止し、方向の失速や追跡線でカバーを返済する。'),
    'G4': ('順張りの逆指値グリッド', '上には買い逆指値、下には売り逆指値。進む方向へ建て、2間隔利確・1間隔損切り・順行後の追跡で返済する。G1の全体損失予算も使う。'),
}
CSS = '''body{margin:0;background:#101720;color:#e0e7ef;font:16px/1.7 system-ui,sans-serif}main{max-width:1280px;margin:auto;padding:26px 24px 64px}h1{font-size:1.75rem;line-height:1.4}h2{font-size:1.23rem;margin:25px 0 12px}h3{font-size:1rem}a{color:#8ac1ff}p{margin:10px 0}section,.notice{border:1px solid #34475b;border-radius:9px;background:#182432;padding:17px;margin:18px 0}.notice{border-left:4px solid #83b1fb}.muted{font-size:.87rem;color:#afc2d4}.table-wrap{overflow-x:auto;margin:12px 0;border:1px solid #354659;border-radius:6px}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:.87rem}th,td{text-align:right;padding:9px 11px;border-bottom:1px solid #304258}th{background:#23354a}th:first-child,td:first-child{text-align:left}tbody tr:nth-child(even){background:#14202d}.positive{color:#8ce1b6}.negative{color:#ffa59e}.flat{color:#d0dbe5}summary{cursor:pointer;color:#a9cdff;padding:7px 0}details{margin:10px 0}nav{display:flex;gap:14px;flex-wrap:wrap}code{color:#b5d6ff;font-size:.85rem}strong{color:#f0f5ff}@media(max-width:600px){main{padding:15px 12px 40px}h1{font-size:1.4rem}section{padding:12px}th,td{padding:8px}}'''


def esc(value: object) -> str:
    """機能: 表示値をHTMLへエスケープする。

    引数: value(object)。返り値: 安全な文字列(str)。
    """
    return html.escape(str(value), quote=True)


def number(value: float | None, digits: int = 0) -> str:
    """機能: 数値と欠測値を書式化する。

    引数: value(float|None)、digits(int)。返り値: 表示文字列(str)。
    """
    if value is None:
        return '—'
    if abs(value) < 1e-7:
        value = 0
    return f'{value:,.{digits}f}'.replace('-', '−')


def money(value: float) -> str:
    """機能: 円収支の正負を色と符号で示す。

    引数: value(float)。返り値: HTML断片(str)。
    """
    cls = 'positive' if value > 1e-7 else 'negative' if value < -1e-7 else 'flat'
    return f'<span class="{cls}">{"+" if value > 1e-7 else ""}{number(value)}</span>'


def table(headers: list[str], rows: list[list[str]]) -> str:
    """機能: 狭幅画面では内部を横スクロールできる表を作る。

    引数: headers(list[str])、rows(list[list[str]])。返り値: HTML表(str)。
    """
    head = ''.join(f'<th scope="col">{esc(h)}</th>' for h in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{v}</td>' for v in row) + '</tr>' for row in rows)
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def page(title: str, content: str) -> str:
    """機能: 暗色の単独HTML文書を組み立てる。

    引数: title(str)、content(str)。返り値: HTML(str)。
    """
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><style>{CSS}</style></head><body>
<!--
[コンポーネント概要]
main は中期・グリッドの比較報告です。残玉込み会計と注文モデルを分けます。
.table-wrap は会計表を横スクロールする領域です。
details は各セッションと検証条件の詳細を開閉します。
.positive / .negative / .flat は収支の正負・同値を暗色背景で示します。
--><main>{content}</main></body></html>'''


def save_csv(name: str, rows: list[dict]) -> None:
    """機能: UTF-8 BOM付きCSVを保存し、全セルを再読込で照合する。

    引数: name(str)、rows(list[dict])。返り値: なし(None)。
    """
    with (OUT / name).open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (OUT / name).open(encoding='utf-8-sig', newline='') as file:
        actual = list(csv.DictReader(file))
    assert actual == [{k:'' if v is None else str(v) for k,v in r.items()} for r in rows]


def detail_table(method: dict, mode: str) -> str:
    """機能: 両銘柄のセッション別粗利益・粗損失・費用・含み増減を並べる。

    引数: method(dict)、mode(str)。返り値: 会計HTML表(str)。
    """
    rows = []
    for a in sorted((a for a in method['accounts'] if a['price_mode'] == mode), key=lambda a:(a['session'], a['symbol'])):
        delta = a['unrealized_end'] - a['unrealized_start']
        assert abs(a['gross_profit'] - a['gross_loss'] - a['fees'] + delta - a['net']) < 1e-3
        rows.append([esc(a['session'].replace('_Day',' 昼').replace('_Night',' 夜')), esc(NAMES[a['symbol']]),
                     number(a['gross_profit']),number(a['gross_loss']),number(a['fees']),money(delta),money(a['net']),
                     f'{a["win_qty"]}/{a["loss_qty"]}/{a["flat_qty"]}',
                     f'{a.get("end_long_qty",0)}/{a.get("end_short_qty",0)}'])
    return table(['セッション','商品','実現利益・円','実現損失・円','当場手数料・円','含み増減・円','純収支・円','勝/負/同値枚','期末買/売枚'],rows)


def weekly_table(method: dict) -> str:
    """機能: 週合計と全体の損益を主価格モデルで示す。

    引数: method(dict)。返り値: HTML表(str)。
    """
    rows = []
    for week in (*WEEKS, '全25場'):
        for symbol in SYMBOLS:
            a = aggregate(method_accounts(method,symbol,WEEKS if week=='全25場' else [week]))
            delta = sum(v['unrealized_end']-v['unrealized_start'] for v in method_accounts(method,symbol,WEEKS if week=='全25場' else [week]))
            rows.append([esc(week + ('〈週途中・調査端清算〉' if week==WEEKS[-1] else '')),esc(NAMES[symbol]),
                         number(a['gross_profit']),number(a['gross_loss']),number(a['fees']),money(delta),money(a['net']),
                         f'{a["win_qty"]}/{a["loss_qty"]}/{a["flat_qty"]}'])
    return table(['期間','商品','実現利益・円','実現損失・円','手数料・円','含み増減・円','純収支・円','勝/負/同値枚'],rows)


def comparison(methods: list[dict], medium: bool) -> str:
    """機能: 主条件や参考候補を、銘柄ごとの収支とリスクで比較する。

    引数: methods(list[dict])、medium(bool)。返り値: HTML表(str)。
    """
    rows = []
    for method in methods:
        for symbol in SYMBOLS:
            v = method['summary'][symbol]
            row=[f'<a href="#{esc(method["id"])}">{esc(method["id"])}</a>',esc(NAMES[symbol]),money(v['net']),
                 number(v['fees']),number(v['drawdown']),number(v['win_rate']*100 if v['win_rate'] is not None else None,1)+'%',
                 number(v['payoff'],2)]
            if medium:
                row += [number(v['hold_median_minutes'],1),money(method['mid_summary'][symbol]['net'])]
            else:
                row += [str(v['max_long_qty'])+'/'+str(v['max_short_qty']),money(method['passive_summary'][symbol]['net'])]
            rows.append(row)
    return table(['手法ID','商品','費用後純収支・円','手数料・円','最大資産下落・円','取引勝率','平均勝/負',
                  '保有中央値・分' if medium else '最大買/売枚','中値参考・円' if medium else '待機指値仮定・円'],rows)


def stress_section() -> str:
    """機能: 固定した人工相場での損失構造を、実データ成績と分けて表示する。

    引数: なし。返り値: 検査説明と表のHTML(str)。
    """
    data=json.loads((HERE/'review'/'主グリッドの人工相場検査.json').read_text(encoding='utf-8'))
    rows=[]
    for family in ('G0','G1','G2','G3','G4'):
        row=[esc(DESCRIPTIONS[family][0])]
        for symbol in SYMBOLS:
            v=next(v for v in data['結果'] if v['方式']==family and v['銘柄']==symbol and v['経路']=='上昇')
            row += [money(v['収支']),str(v['返済玉数'])]
        rows.append(row)
    return '<details><summary>一方向へ進み続ける人工相場で、何が起きたか</summary><p>実データで少なかった極端な経路も、条件を変えずに検査しました。以下は上昇が続く人工の1週間です。発生確率や実際の期待利益を示す表ではありません。</p>'+table(
        ['主方式','TOPIX純収支円','返済玉数','NK純収支円','返済玉数'],rows)+ '<p>無保護のG0は大きく損失を抱え、G1・G3は損失を抑えて停止しました。G2は取引なし、G4は順方向で利益となりました。保護は破綻的な逆行を減らす仕組みであり、利益の保証ではありません。下降・往復・V字・場間ギャップも含む50検査は<a href="../../work/wave_v60/review/主グリッドの人工相場検査.json">人工相場の全結果</a>に保存しています。</p></details>'


def current_section() -> str:
    """機能: 一度取得した場の途中会計を、履歴の清算済み会計と分けて示す。

    引数: なし。返り値: 主評価と参考表のHTML(str)。同時に8口座のCSVを保存する。
    """
    rows={'quote':[],'mid':[]}
    csv_rows=[]
    weeks=[]
    for name in ('中期','グリッド'):
        data=json.loads((HERE/'live'/f'現在{name}の途中損益.json').read_text(encoding='utf-8'))
        for a in sorted(data['accounts'],key=lambda v:(v['price_mode'],v['symbol'])):
            trade_rows=[dict(zip(data['返済列'],t)) for t in a['trades']]
            gross=[t.get('gross',t.get('gross_pnl')) for t in trade_rows]
            profit=sum(v for v in gross if v>0)
            loss=-sum(v for v in gross if v<0)
            won=sum(t['qty'] for t in trade_rows if t.get('net',t.get('net_pnl'))>0)
            lost=sum(t['qty'] for t in trade_rows if t.get('net',t.get('net_pnl'))<0)
            flat=sum(t['qty'] for t in trade_rows if t.get('net',t.get('net_pnl'))==0)
            start=a.get('unrealized_start',0.)
            end=a['unrealized_end']
            fees=a['fees_incurred']
            net=a['economic_net']
            assert abs(profit-loss-fees+end-start-net)<1e-3
            long=a.get('long_qty',max(a.get('position',0),0))
            short=a.get('short_qty',max(-a.get('position',0),0))
            rows[a['price_mode']].append([esc(name),esc(NAMES[a['symbol']]),number(profit),number(loss),number(fees),
                money(end-start),money(net),f'{int(won)}/{int(lost)}/{int(flat)}',f'{long}/{short}',money(end)])
            csv_rows.append(dict(分類=name,手法ID=data['選定候補']['id'],セッション=a['session'],銘柄=a['symbol'],
                約定モデル=MODES[a['price_mode']],実現利益円=profit,実現損失円=loss,当場手数料円=fees,
                前場末含み円=start,現在含み円=end,含み増減円=end-start,当場純収支円=net,
                勝ち枚数=int(won),負け枚数=int(lost),同値枚数=int(flat),現在買枚数=long,現在売枚数=short))
            if name=='グリッド' and a['price_mode']=='quote':
                weeks.append([esc(NAMES[a['symbol']]),money(a['week_before_current_net']),money(net),money(a['week_economic_net'])])
    save_csv('現在ナイトの途中損益.csv',csv_rows)
    heads=['系統','商品','実現利益円','実現損失円','当場手数料円','含み増減円','当場純収支円','勝/負/同値枚','現在買/売枚','現在含み円']
    return table(heads,rows['quote'])+'<details><summary>中値参考と、継続した週の会計</summary>'+table(heads,rows['mid'])+table(
        ['グリッド商品','10/7昼末の週累計円','当場純収支円','現在までの週累計円'],weeks)+'</details><p class="muted"><a href="現在ナイトの途中損益.csv">現在ナイトCSV</a> ／ <a href="../../work/wave_v60/live/確認候補固定.json">取得前の候補固定</a> ／ <a href="../../work/wave_v60/live/取得記録.json">一回取得の記録</a>。共通toは受信時刻の上限、売買再生の経過時間は原本のCurrentPriceTimeと行順です。</p>'


def main() -> None:
    """機能: 全160条件と主10条件、週順診断、現在確認を報告にまとめる。

    引数: なし。返り値: なし(None)。売買規則・候補を変更しない。
    """
    datasets = {b:load(b) for b in ('medium','grid')}
    narrative=json.loads((HERE/'報告判断.json').read_text(encoding='utf-8'))
    selected=json.loads((HERE/'事前基準と週順選定.json').read_text(encoding='utf-8'))
    OUT.mkdir(parents=True,exist_ok=True)
    csv_rows,period_rows=[],[]
    for branch,data in datasets.items():
        for method in data['methods']:
            for a in method['accounts']:
                delta=a['unrealized_end']-a['unrealized_start']
                assert abs(a['gross_pnl']-a['fees']+delta-a['net'])<1e-3
                csv_rows.append(dict(分類='中期' if branch=='medium' else 'グリッド',手法ID=method['id'],主条件=method['primary'],
                    約定モデル=MODES[a['price_mode']],セッション=a['session'],銘柄=a['symbol'],
                    実現利益円=a['gross_profit'],実現損失円=a['gross_loss'],実現粗収支円=a['gross_pnl'],
                    当場注文手数料円=a['fees'],開始含み円=a['unrealized_start'],終了含み円=a['unrealized_end'],
                    含み増減円=delta,期間純収支円=a['net'],勝ち枚数=a['win_qty'],負け枚数=a['loss_qty'],同値枚数=a['flat_qty'],
                    期末買枚数=a.get('end_long_qty',0),期末売枚数=a.get('end_short_qty',0),
                    最大買枚数=a['max_long_qty'],最大売枚数=a['max_short_qty'],最大資産下落円=a['drawdown']))
            for mode in ('quote','mid')+(() if branch=='medium' else ('passive',)):
                for symbol in SYMBOLS:
                    for week in (*WEEKS,'全25場'):
                        v=aggregate(method_accounts(method,symbol,WEEKS if week=='全25場' else [week],mode))
                        period_rows.append(dict(分類=branch,手法ID=method['id'],約定モデル=MODES[mode],銘柄=symbol,期間=week,
                            実現利益円=v['gross_profit'],実現損失円=v['gross_loss'],手数料円=v['fees'],純収支円=v['net'],
                            勝ち枚数=v['win_qty'],負け枚数=v['loss_qty'],同値枚数=v['flat_qty'],総利益損失比=v['pf'],平均勝ち負け比=v['payoff']))
    save_csv('全160条件のセッション損益.csv',csv_rows)
    save_csv('全160条件の週と全体損益.csv',period_rows)
    content=f'<nav><a href="../index.html">調査一覧</a><a href="全160条件.html">全条件</a><a href="README.md">資料案内</a></nav><h1>{TITLE}</h1><p class="muted">00057／2026年9月21日〜10月7日の既知25セッション。中期120条件・グリッド40条件。</p>'
    content+='<div class="notice">'+''.join(f'<p>{esc(p)}</p>' for p in narrative['冒頭'])+'</div>'
    content+='<p>主評価はラージ板の<strong>買いask・売りbid</strong>を使い、TOPIX miniは片道1枚41.8円、NK225 microは11円の手数料を新規・返済とも計上。注文ごとに1円未満を切り捨てます。指標は中値から作り、最終約定値は使いません。</p>'
    content+='<p class="muted">小型商品の実際の気配は保存されていないため、ラージ気配による代理評価です。中値参考と待機指値仮定も別に示します。証拠金必要額と自身の注文による価格影響は計算していません。</p>'
    content+='<h2>30〜60分を目安に返済する方法</h2>'+''.join(f'<p>{esc(p)}</p>' for p in narrative['中期'])
    middle=[m for m in datasets['medium']['methods'] if m['primary']]
    content+=comparison(middle,True)
    content+='<p class="muted">主5条件は5分足3本/9本平均・幅0.1%・1幅順行後の1幅追跡・45分期限。ほかに6本/12本平均、幅0.2%、固定利確、30/60分期限を比較。早い損切りを認めるため、45分設定は45分保有の保証ではありません。実際の中央値を表に示しました。</p>'
    content+='<h2>週内グリッドと両建て</h2>'+''.join(f'<p>{esc(p)}</p>' for p in narrative['グリッド'])
    grids=[m for m in datasets['grid']['methods'] if m['primary']]
    content+=comparison(grids,False)
    content+='<p class="muted">主5条件は週初価格の0.125%間隔・片側5段・週内持越し。TOPIXは1段2枚で片方向上限10枚、NKは4枚で上限20枚。両建てでも上限は方向別に守ります。0.075%間隔・10段・各場で返済する型も比較しました。</p>'
    content+='<h2>指値と持ち越しで何が変わったか</h2>'+''.join(f'<p>{esc(p)}</p>' for p in narrative['解釈'])
    content+=stress_section()
    if narrative.get('注目条件'):
        content+='<h2>結果を見て取り上げた参考条件</h2><p class="muted">以下は事後の比較対象です。上の主10条件や規則を差し替えたものではありません。</p>'
    featured=[]
    for branch,key in narrative.get('注目条件',[]):
        method=next(m for m in datasets[branch]['methods'] if m['id']==key)
        featured.append((branch,method))
        content+=comparison([method],branch=='medium')
    # ----------------------------------------
    # 実現益だけでは評価せず、週合計と全場の含み変化を手法ごとに示す。
    for branch,method in [('medium',m) for m in middle]+[('grid',m) for m in grids]+featured:
        family=method['family']; name,description=DESCRIPTIONS[family]
        content+=f'<section id="{esc(method["id"])}"><h2>{esc(name)}</h2><p><code>{esc(method["id"])}</code></p><p>{esc(description)}</p>'
        if branch=='medium':
            content+='<p>途中は返済可能な気配で損切り・利確・追跡を監視。期限に達したら次の観測価格で返済し、各セッション内で全玉を返します。</p>'
        else:
            content+='<p>主評価では、価格が飛んでも通過した格子の仮想価格で順に約定したことにはしません。週末は全返済し、最後の10月7日昼は週途中の「調査終了清算」として区別します。</p>'
        content+='<details><summary>週と全体の利益・損失・手数料・純収支</summary>'+weekly_table(method)+'</details>'
        content+='<details><summary>25セッションの損益と決済枚数・残建玉（主評価）</summary>'+detail_table(method,'quote')+'</details>'
        if branch=='grid':
            content+='<details><summary>待機指値の約定を仮定した各場損益</summary>'+detail_table(method,'passive')+'</details>'
        content+='</section>'
    content+='<p class="muted">実現利益・実現損失は費用前の決済損益です。純収支＝実現利益−実現損失−当場手数料＋含み増減。勝/負/同値枚数は往復手数料を配分した決済玉の延べ枚数で、残建玉とは別です。平均勝/負は費用後の1枚当たり平均利益÷1枚当たり平均損失、取引勝率は返済した玉の組数によります。最大資産下落は含み・発生費用込み。損失予算は撤退の判断線で、ギャップ時の損失上限を保証しません。</p>'
    content+='<h2>前週だけで選ぶとどうなったか</h2>'+''.join(f'<p>{esc(p)}</p>' for p in narrative['選択'])
    for branch,values in selected['結果'].items():
        rows=[]
        for seq in values['週順選定']:
            row=['中期' if branch=='medium' else 'グリッド',esc(seq['適用週']),esc(seq['選定']['id'] if seq['選定'] else '該当なし（取引0）')]
            row += [money(seq['翌週成績'][s]['net']) if seq['翌週成績'] else '0' for s in SYMBOLS]
            rows.append(row)
        content+=table(['分類','適用週','前週までで選んだ条件','TOPIX純収支円','NK純収支円'],rows)
    content+='<h2>現在セッションの一回確認</h2>'+''.join(f'<p>{esc(p)}</p>' for p in narrative['現在確認'])
    content+=current_section()
    content+='<details><summary>検証範囲・注文モデル・資料</summary><p>既知25場を再利用しています。120＋40条件と主条件は成績を見る前に固定。週順の選定も真の未知検証とは呼びません。主気配評価と中値参考は独立再生で、価格が変わると出口や後続入口も変わります。</p><p>グリッドの主評価はcontroller型の「条件到達後に発注」です。待機指値仮定は、前行以前から置いた指値を参照ラージ1呼値以上気配が通過した場合のみ指値で約定し、触値では約定しません。注文の順番・全数量の実約定は、この保存板だけでは証明できません。</p><p>保存時計には夜間の空白があり、最初の試行は早い運用期限05:50の条件で安全停止しました。入口や返済判断予定を変えず、同じ場のザラバ終了前までに次の観測価格で返済する形へ訂正し、初版と理由を保存しています。受信時刻がないため、30〜60分や返済時刻は保存された約定時計での評価です。</p><p>保有在庫によって追加や整理を変える設計は、<a href="https://people.orie.cornell.edu/sfs33/LimitOrderBook.pdf">Avellaneda–Stoikov</a>、<a href="https://arxiv.org/abs/1105.3115">Guéantほか</a>の在庫リスクの考えを参考にしました。これらのマーケットメイクをそのまま再現したものではなく、日本先物の利益を保証する根拠にはしていません。</p>'
    content+='<nav><a href="全160条件のセッション損益.csv">全場会計CSV</a><a href="全160条件の週と全体損益.csv">週・全体CSV</a><a href="../../work/wave_v60/調査仕様.json">固定仕様</a><a href="../../work/wave_v60/事前基準と週順選定.json">選定記録</a><a href="../../work/wave_v60/review/README.md">独立監査</a></nav></details>'
    (OUT/(TITLE+'.html')).write_text(page(TITLE,content),encoding='utf-8')
    # ----------------------------------------
    # 全ての条件を、結果の良否で省略せず別画面に並べる。
    full=f'<nav><a href="{TITLE}.html">短い報告へ</a></nav><h1>全160条件の比較</h1><p>数値は手数料後、円。各銘柄の収支を足し合わせて順位を作りません。中値・待機指値は主評価とは独立した仮定です。</p>'
    for branch,data in datasets.items():
        for family in dict.fromkeys(m['family'] for m in data['methods']):
            rows=[]
            for method in data['methods']:
                if method['family']!=family:
                    continue
                row=[esc(method['id'])+(' ★主' if method['primary'] else '')]
                for symbol in SYMBOLS:
                    v=method['summary'][symbol]
                    row += [money(v['net']),money(method['mid_summary'][symbol]['net'])]
                    if branch=='grid':
                        row += [money(method['passive_summary'][symbol]['net'])]
                    row += [number(v['drawdown']),number(v['cycles'])]
                rows.append(row)
            heads=['手法ID']
            for symbol in SYMBOLS:
                heads += [symbol+'気配',symbol+'中値']+([symbol+'指値仮定'] if branch=='grid' else [])+[symbol+'最大下落',symbol+'決済組']
            full+=f'<h2>{esc(family)} {esc(DESCRIPTIONS[family][0])}</h2>'+table(heads,rows)
    full+='<p>W10/W20は幅0.1%/0.2%、T30/T45/T60は最長保有分。グリッドD075/D125は間隔0.075%/0.125%、L05/L10は片側段数、Sは場内返済、Wは週内持越し。全セッションの金額・枚数は<a href="全160条件のセッション損益.csv">会計CSV</a>で確認できます。</p>'
    (OUT/'全160条件.html').write_text(page('全160条件の比較',full),encoding='utf-8')
    evidence=dict(会計CSV行数=len(csv_rows),期間CSV行数=len(period_rows),会計一致=True,
        結果SHA256={b:hashlib.sha256((HERE/b/'売買結果.json').read_bytes()).hexdigest() for b in datasets},
        現在結果SHA256={n:hashlib.sha256((HERE/'live'/f'現在{n}の途中損益.json').read_bytes()).hexdigest() for n in ('中期','グリッド')},
        HTML_SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.html')})
    (HERE/'報告出力照合.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False))


if __name__=='__main__':
    main()
