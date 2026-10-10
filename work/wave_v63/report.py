"""決済勝率95%の探索結果と、比較用3候補の全セッション損益を公開する。"""

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
from pathlib import Path
import pickle
import re
import shutil

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / 'アルゴリズム調査/00060_決済勝率95パーセントの探索とPDCA'
JST = timezone(timedelta(hours=9))
SYMBOLS = ('TOPIX', 'NK225')
SELECTED = (
    ('microstructure/round3', 'M3_Q1_L1_T16_S8_H600_保有30分_校正10_60', '板圧力＋模擬取引の選別',
     'TOPIXで損小利大だった比較候補。勝率95%には未達。',
     ('買い側の表示圧力・最良数量・直近価格が同方向なら買い。売りは反対。直近10回の模擬決済が6回以上黒字の間だけ入る。',
      '実建玉とは別に模擬取引を続け、既に決済された成績だけで次の入口を選ぶ。追加玉は建てない。',
      '16呼値の利益、8呼値の損失、30分の保有期限、場内返済のうち最初に成立した条件で返す。')),
    ('microstructure/round3', 'M3_Q2_L0_T16_S8_H600_保有30分_校正5_60', '補充・表示圧力の確認＋模擬取引の選別',
     'NKで損小利大だった比較候補。TOPIXでは赤字。',
     ('売り執行の代理量が多い中で、買い板の数量回復と買い側の表示圧力を確認して買う。売りは反対。直近5回の模擬決済が3回以上黒字の間だけ入る。',
      '模擬取引の成績で新規の可否を更新する。補充を観測しただけでは入らず、入口方向の表示圧力が一定以上あることも要求する。',
      '16呼値の利益、8呼値の損失、30分の保有期限、場内返済のうち最初に成立した条件で返す。')),
    ('directional/round3', 'R3_DEPTH_C_quote', '価格の拒否＋板の確認から小幅を回収',
     'NKで勝率73.9%。平均利益は平均損失より小さく、損小利大には未達。',
     ('確定1分足が過去20分の安値を割って戻れば買い候補。高値を越えて戻れば売り候補。120秒以内に、その方向の板厚と1呼値の順行を確認して入る。',
      '板厚の強さは、その場の過去20分と比較する。確認が間に合わない場合や半幅逆行した場合は、新規を見送る。追加玉は建てない。',
      '始値の0.1%を基準幅とし、半幅で利確、1幅で損切り。60分の期限または場内返済でも返す。')),
)


def read(path: Path) -> dict:
    """機能: UTF-8の検証結果を読む。

    引数: path(Path)。返り値: JSON辞書(dict)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: object) -> None:
    """機能: 非有限数を許さず日本語JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def money(value: float, sign: bool = False) -> str:
    """機能: 円単位の表示を作る。

    引数: value(float)、sign(bool)。返り値: 表示文字列(str)。
    """
    value = 0. if value == 0 else value
    return f'{value:+,.0f}' if sign else f'{value:,.0f}'


def percentage(value: float | None) -> str:
    """機能: 未観測と勝率を区別して表示する。

    引数: value(float|None)。返り値: 表示文字列(str)。
    """
    return '未観測' if value is None else f'{value*100:.1f}%'


def ratio(value: float | None) -> str:
    """機能: 損失未観測を無限大にせず比率を表示する。

    引数: value(float|None)。返り値: 表示文字列(str)。
    """
    return '未観測' if value is None else f'{value:.3f}'


def normalize(account: dict) -> dict:
    """機能: 枝ごとの組会計を共通の費用後定義へ揃える。

    引数: account(dict)。返り値: 共通口座(dict)。
    """
    out = {k: account[k] for k in ('session', 'symbol', 'net', 'fees', 'gross_profit', 'gross_loss', 'win_qty', 'loss_qty', 'flat_qty', 'drawdown', 'equity_min', 'equity_max')}
    out.update(wins=account.get('group_wins', account['wins']), losses=account.get('group_losses', account['losses']),
        cycles=account.get('cycles', account.get('groups')), profit=account.get('group_profit', account['profit']), loss=account.get('group_loss', account['loss']))
    out['flats'] = out['cycles'] - out['wins'] - out['losses']
    assert abs(out['profit'] - out['loss'] - out['net']) < 1e-6
    assert abs(out['gross_profit'] - out['gross_loss'] - out['fees'] - out['net']) < 1e-6
    assert out['flats'] >= 0
    return out


def aggregate(accounts: list[dict]) -> dict:
    """機能: 同銘柄の全決済組を集計し、勝率と損益構造を計算する。

    引数: accounts(list[dict])。返り値: 合計(dict)。
    """
    fields = ('net', 'fees', 'gross_profit', 'gross_loss', 'wins', 'losses', 'flats', 'cycles', 'profit', 'loss', 'win_qty', 'loss_qty', 'flat_qty')
    out = {k: sum(a[k] for a in accounts) for k in fields}
    out['win_rate'] = out['wins']/out['cycles'] if out['cycles'] else None
    out['average_win'] = out['profit']/out['wins'] if out['wins'] else None
    out['average_loss'] = out['loss']/out['losses'] if out['losses'] else None
    out['payoff'] = out['average_win']/out['average_loss'] if out['average_win'] is not None and out['average_loss'] else None
    out['pf'] = out['profit']/out['loss'] if out['loss'] else None
    out['active_sessions'] = sum(a['cycles'] > 0 for a in accounts)
    out['positive_sessions'] = sum(a['net'] > 0 for a in accounts)
    out['without_best'] = out['net'] - max(0, max(a['net'] for a in accounts))
    level = peak = dd = 0.
    for a in sorted(accounts, key=lambda a:a['session']):
        dd = max(dd, a['drawdown'], peak-level-a['equity_min'])
        peak = max(peak, level+a['equity_max'])
        level += a['net']
    out['drawdown'] = dd
    out['raw95'] = out['cycles'] > 0 and out['win_rate'] >= .95
    out['profitable_small_loss_large_gain'] = out['net'] > 0 and out['payoff'] is not None and out['payoff'] > 1
    return out


def week(session: str) -> str:
    """機能: 保存場の日付を月曜始まりの週へまとめる。

    引数: session(str)。返り値: 週の月曜日(str)。
    """
    date = datetime.strptime(session[:10], '%Y-%m-%d').date()
    return str(date-timedelta(days=date.weekday()))


def table_row(label: str, a: dict, total: bool = False) -> str:
    """機能: 費用後金額と決済枚数の表行を生成する。

    引数: label(str)、a(dict)、total(bool)。返り値: HTML(str)。
    """
    color = 'pos' if a['net'] > 0 else 'neg' if a['net'] < 0 else 'quiet'
    return f'<tr class="{"total" if total else ""}"><th>{html.escape(label)}</th><td>{money(a["profit"])}</td><td>{money(a["loss"])}</td><td class="{color}">{money(a["net"],True)}</td><td>{a["win_qty"]}</td><td>{a["loss_qty"]}</td><td>{a["win_qty"]-a["loss_qty"]:+d}</td><td>{a["wins"]}/{a["cycles"]}</td><td>{money(a["fees"])}</td></tr>'


def session_table(accounts: list[dict]) -> str:
    """機能: 全25場、週別、全期間合計を欠落なく表示する。

    引数: accounts(list[dict])。返り値: HTML(str)。
    """
    assert len(accounts) == 25
    rows = [table_row(a['session'].replace('_Day',' 昼').replace('_Night',' 夜'), a) for a in sorted(accounts,key=lambda a:a['session'])]
    for w in sorted({week(a['session']) for a in accounts}):
        rows.append(table_row(f'{w} の週', aggregate([a for a in accounts if week(a['session']) == w]), True))
    rows.append(table_row('全期間', aggregate(accounts), True))
    return '<div class="scroll"><table><thead><tr><th>セッション</th><th>利益 円</th><th>損失 円</th><th>収支 円</th><th>勝ち枚数</th><th>負け枚数</th><th>枚数差</th><th>勝ち/決済</th><th>手数料 円</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'


def shell(title: str, body: str, script: str = '') -> str:
    """機能: 暗色の共通レイアウトを作る。

    引数: title/body/script(str)。返り値: 完成HTML(str)。
    """
    return '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+html.escape(title)+'''</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0d1420;color:#e7edf7;font:16px/1.65 system-ui,'Yu Gothic',sans-serif}main{max-width:1320px;margin:auto;padding:30px 24px 65px}h1{font-size:28px;line-height:1.4}h2{font-size:23px;margin-top:0}h3{font-size:19px}p{margin:12px 0}a{color:#8ec9ff}nav{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}nav a,.pill{background:#192839;border:1px solid #34465c;border-radius:8px;padding:7px 13px}.quiet,.sub{color:#a5b5ca}.sub{font-size:14px}.warning{padding:20px;background:#30271c;border:1px solid #826735;border-radius:12px}.card{padding:24px;margin:25px 0;background:#141f2e;border:1px solid #304157;border-radius:13px}.pos{color:#74e2bc}.neg{color:#ff9898}.scroll{overflow:auto;margin:15px 0}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:14px}th,td{border-bottom:1px solid #334257;padding:9px 12px;text-align:right}th:first-child{text-align:left}thead th{background:#213044;color:#bfd5f0}tbody th{font-weight:400}.total th,.total td{font-weight:700;background:#1c2b3d}.overview td:first-child{text-align:left}details{margin-top:16px}summary{cursor:pointer;color:#b8d6f4}code{font-size:12px;overflow-wrap:anywhere;white-space:normal;color:#bcd4fa}.rules{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.rules p{background:#1b293b;border-radius:8px;padding:13px;margin:0;font-size:15px}.rules b{display:block;color:#92c8ff;margin-bottom:5px}.tabs{display:flex;gap:7px;margin:15px 0}button,select,input{background:#20334a;color:#edf3ff;border:1px solid #59728e;border-radius:6px;padding:8px 13px;font:inherit}button.active{background:#315c78}.hidden{display:none}.charts{display:grid;grid-template-columns:1fr 1fr;gap:20px}svg{width:100%;height:auto;background:#111b28;border-radius:8px}.nowrap{white-space:nowrap}footer{color:#99acc4;font-size:14px;margin-top:30px}@media(max-width:800px){main{padding:18px 14px}h1{font-size:24px}.card{padding:16px}.rules,.charts{grid-template-columns:1fr}}@media print{.hidden{display:block}.tabs,nav{display:none}body{font-size:12px}.card{break-inside:auto}table{font-size:11px}}
</style><!--
[コンポーネント概要]
main は説明、条件表、全セッション損益をまとめる報告書です。
.card は手法または検証段階ごとの章です。
.tabs のボタンは同じ章の銘柄表示だけを切り替えます。
.symbol-panel は各銘柄の全25セッション・週別・全期間の表です。
.hidden は選ばれていない銘柄の表示を隠し、印刷時は両方を表示します。
.scroll は表の横スクロール領域です。各金額は費用後で、手数料を再度引きません。
#search は全条件表の文字検索、#count は表示件数です。
--><main><p class="sub">作業 00060 · 保存済み25セッション · 2026-09-21昼〜2026-10-07昼</p><h1>'''+html.escape(title)+'''</h1><nav><a href="95パーセント探索の説明と全セッション損益.html">3候補の説明と損益</a><a href="損失原因とPDCA.html">損失原因と改善結果</a><a href="全375条件.html">全375条件</a><a href="README.md">資料案内</a></nav>'''+body+'''<footer>実注文なし。全データは既に閲覧済みで、今回の候補選択は過去データへの適合です。未知データの検証合格を意味しません。</footer></main><script>'''+script+'''</script></html>'''


def chart(methods: list[dict], symbol: str) -> str:
    """機能: 同一銘柄の3候補の累積収支を暗色SVGで比較する。

    引数: methods(list[dict])、symbol(str)。返り値: SVGのHTML(str)。
    """
    curves = [[0.] for _ in methods]
    for k,m in enumerate(methods):
        for a in sorted([a for a in m['accounts'] if a['symbol']==symbol],key=lambda a:a['session']):
            curves[k].append(curves[k][-1]+a['net'])
    low = min(min(c) for c in curves); high = max(max(c) for c in curves)
    span = max(high-low,1.)
    low -= span*.1; high += span*.1
    def y(value: float) -> float:
        """機能: 円を図上の縦座標へ換算する。

        引数: value(float)。返り値: 縦座標(float)。
        """
        return 225-(value-low)/(high-low)*190
    parts = [f'<h3>{symbol} の累積収支（円）</h3><svg viewBox="0 0 560 290" role="img" aria-label="{symbol}の3候補の累積収支">']
    for value in (low,0.,high):
        yy = y(value)
        parts.append(f'<line x1="65" x2="535" y1="{yy}" y2="{yy}" stroke="#35465b"/><text x="8" y="{yy+4}" fill="#a7b9cf" font-size="12">{value/10000:.1f}万</text>')
    colors = ('#72d8bc','#8ab7ff','#edbc76')
    for k,curve in enumerate(curves):
        points = ' '.join(f'{65+i*470/25:.1f},{y(v):.1f}' for i,v in enumerate(curve))
        parts.append(f'<polyline points="{points}" fill="none" stroke="{colors[k]}" stroke-width="2.5"/><text x="{65+k*155}" y="270" fill="{colors[k]}" font-size="13">候補{k+1}</text>')
    parts.append('<text x="65" y="245" fill="#a7b9cf" font-size="12">9/21 昼</text><text x="470" y="245" fill="#a7b9cf" font-size="12">10/7 昼</text></svg>')
    return ''.join(parts)


def export_trades(method: dict, source: Path, number: int) -> None:
    """機能: 比較候補の全決済記録を原簿とCSVで保存する。

    引数: method(dict)、source(Path)、number(int)。返り値: なし(None)。
    """
    raw_path = Path(method['ledger'])
    raw_path = raw_path if raw_path.is_absolute() else source.parent/raw_path
    ledger = pickle.loads(raw_path.read_bytes())
    shutil.copyfile(raw_path,OUT/'台帳'/f'候補{number}_原簿.pkl')
    inputs = pickle.loads((HERE.parent/'wave_v60/inputs.pkl').read_bytes())
    for symbol in SYMBOLS:
        path = OUT/'台帳'/f'候補{number}_{symbol}_全決済.csv'
        with path.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream)
            writer.writerow(('セッション','方向','枚数','新規判断時刻','新規約定時刻','返済判断時刻','返済約定時刻','新規価格','返済価格','手数料前損益','手数料','費用後損益','新規原本行','返済原本行'))
            for key,data in sorted(ledger.items()):
                if key[1]!=symbol:
                    continue
                ready=inputs[key[:2]]
                for t in data['trades']:
                    if len(t)==13:
                        ed,ei,xd,xi,side,qty,ep,xp,ef,xf,gross,net,_=t
                        stamps=[ready['time_s'][int(i)] for i in (ed,ei,xd,xi)]
                        fees=ef+xf
                        seqs=[ready['seq'][int(ei)],ready['seq'][int(xi)]]
                    else:
                        assert len(t)==27
                        side,qty,ep,xp,gross,fees,net=t[2:9]
                        stamps=[ready['time_s'][int(np.searchsorted(ready['seq'],int(t[18])))],t[0],t[11],t[1]]
                        seqs=[t[12],t[13]]
                    writer.writerow((key[0],'買い' if side==1 else '売り',int(qty),*[datetime.fromtimestamp(float(v),JST).isoformat() for v in stamps],ep,xp,gross,fees,net,*[int(v) for v in seqs]))


def main() -> None:
    """機能: 凍結済み375条件を統合してHTML・全場CSV・台帳・索引を更新する。

    引数: なし。返り値: なし(None)。原本や過去作業フォルダを変更しない。
    """
    OUT.mkdir(exist_ok=True)
    (OUT/'台帳').mkdir(exist_ok=True)
    shutil.copyfile(HERE/'review/独立監査まとめ.md',OUT/'監査まとめ.md')
    shutil.copyfile(HERE/'inventory/候補3つの銘柄差.md',OUT/'3候補の銘柄差.md')
    shutil.copyfile(HERE/'inventory/候補3つの銘柄差.json',OUT/'3候補の銘柄差.json')
    sources = [(f'directional/round{i}', HERE/f'directional/round{i}/集計結果.json') for i in (1,2,3)]
    sources += [('inventory',HERE/'inventory/集計結果.json')]
    sources += [(f'microstructure/round{i}',HERE/f'microstructure/round{i}/集計結果.json') for i in (1,2,3)]
    sources += [('fresh_flow/round4',HERE/'fresh_flow/round4/集計結果.json')]
    methods, original, paths = [], {}, {}
    for branch,path in sources:
        for m in read(path)['methods']:
            accounts=[normalize(a) for a in m['accounts']]
            mode=m.get('price_mode','quote')
            if m.get('reference_only') and m.get('passive_entry'):
                mode='新規指値仮定'
            elif m.get('passive_entry'):
                mode='新規指値仮定'
            elif m.get('reference_only'):
                mode='二銘柄時計の参考'
            if mode in ('E','P'):
                mode={'E':'新規指値仮定','P':'新規と利確の指値仮定'}[mode]
            elif mode=='M':
                mode='中値参考'
            elif mode=='Q':
                mode='quote'
            item=dict(branch=branch,id=m['id'],mode=mode,config=m.get('config',{k:v for k,v in m.items() if k not in ('accounts','summary','ledger','weeks')}),
                source=str(path.relative_to(ROOT)).replace('\\','/'),accounts=accounts,summary={s:aggregate([a for a in accounts if a['symbol']==s]) for s in SYMBOLS})
            methods.append(item); original[(branch,m['id'])]=m; paths[(branch,m['id'])]=path
    assert len(methods)==375
    selected=[]
    for branch,id,name,note,rules in SELECTED:
        item=next(m for m in methods if m['branch']==branch and m['id']==id)
        selected.append(dict(**item,name=name,note=note,rules=rules))
    observed=[dict(branch=m['branch'],id=m['id'],symbol=s,**m['summary'][s]) for m in methods for s in SYMBOLS if m['summary'][s]['raw95']]
    assert all(v['cycles']==1 for v in observed)
    meta=dict(条件数=375,口座数=18750,期間='2026-09-21_Day〜2026-10-07_Day',セッション数=25,
        主勝率='新規から全玉0へ戻るまでを1決済組。全新規・返済費用後>0が勝ち。0以下も分母。無取引は分母外。',
        初回枚数={'TOPIXmini':5,'NK225micro':10},片方向上限={'TOPIXmini':10,'NK225micro':20},追加玉=False,
        手数料={'TOPIXmini':41.8,'NK225micro':11.0},費用計算='注文ごとにfloor(枚数×税込片道手数料)。mini5枚=209円、micro10枚=110円。',
        執行='主評価は判断の次の有効原本行で買いask/売りbid。実在mini/microの板・待ち順は未検証。',
        勝率目標の実測達成=observed,全場既知=True,現在取得回数=0,実注文=False,ATR使用=False,
        限界=['受信時計が無くCurrentPriceTimeは最終約定時計。主候補は単一銘柄raw順。','候補選択は既知25場への事後適合。将来の95%を保証しない。','50組/12活動場は説明用の十分さ目安で、ユーザーの追加要件ではない。'],
        結果SHA={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for _,p in sources})
    save(OUT/'調査仕様と集計.json',dict(meta=meta,selected=selected,methods=methods))
    save(OUT/'比較3候補.json',dict(meta=meta,methods=selected))
    with (OUT/'全375条件の一覧.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(('枝','手法ID','評価価格','銘柄','利益円','損失円','収支円','手数料円','勝ち組','負け組','決済組','勝率','平均勝ち負け比','PF','活動場','勝ち枚数','負け枚数','最大黒字場除外円','資産最大下落円'))
        for m in methods:
            for s in SYMBOLS:
                a=m['summary'][s]
                writer.writerow((m['branch'],m['id'],m['mode'],s,*[a[k] for k in ('profit','loss','net','fees','wins','losses','cycles','win_rate','payoff','pf','active_sessions','win_qty','loss_qty','without_best','drawdown')]))
    with (OUT/'比較3候補の全セッション.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(('候補','手法ID','銘柄','セッション','利益円','損失円','収支円','手数料円','勝ち枚数','負け枚数','枚数差','勝ち組','負け組','決済組'))
        for i,m in enumerate(selected,1):
            for a in m['accounts']:
                writer.writerow((i,m['id'],a['symbol'],a['session'],a['profit'],a['loss'],a['net'],a['fees'],a['win_qty'],a['loss_qty'],a['win_qty']-a['loss_qty'],a['wins'],a['losses'],a['cycles']))
            export_trades(original[(m['branch'],m['id'])],paths[(m['branch'],m['id'])],i)
    # ----------------------------------------
    # 3候補の説明は短くし、全損益と数値の規則は折りたたみへ分ける。
    intro='''<div class="warning"><b>取引を重ねて「95%勝ち」と「損小利大」を両立する3候補は、見つかりませんでした。</b><p>95%以上だったのは、TOPIXで1勝/1取引だった同じ入口の5条件だけです。下の3つは改善の比較対象で、95%達成手法としての推奨ではありません。</p></div><p>375条件を、入口・途中判断・出口へ分けて改良しました（対照・参考・再掲を含む）。全25場を省略せず表示します。</p><p class="sub">上限TOPIXミニ10枚／NKマイクロ20枚。今回の新規は5枚／10枚、追加なし。利益・損失は全取引費用後。手数料欄は既に収支へ含まれ、再度引きません。勝ち/決済は枚数で水増ししない取引数です。</p>'''
    overview='<div class="scroll"><table class="overview"><thead><tr><th>比較候補</th><th>銘柄</th><th>費用後収支 円</th><th>勝ち/決済</th><th>勝率</th><th>平均利益/損失</th><th>活動場/25</th><th>最大黒字場を除外 円</th></tr></thead><tbody>'
    for i,m in enumerate(selected,1):
        for s in SYMBOLS:
            a=m['summary'][s]
            overview+=f'<tr><td><a href="#candidate{i}">候補{i} {m["name"]}</a></td><td>{s}</td><td class="{"pos" if a["net"]>0 else "neg"}">{money(a["net"],True)}</td><td>{a["wins"]}/{a["cycles"]}</td><td>{percentage(a["win_rate"])}</td><td>{ratio(a["payoff"])}</td><td>{a["active_sessions"]}</td><td>{money(a["without_best"],True)}</td></tr>'
    overview+='</tbody></table></div>'
    graphs='<div class="charts">'+''.join('<div>'+chart(selected,s)+'</div>' for s in SYMBOLS)+'</div>'
    chapters=[]
    for i,m in enumerate(selected,1):
        blocks=''.join(f'<p><b>{label}</b>{text}</p>' for label,text in zip(('入口','途中判断','出口'),m['rules']))
        section=f'<section class="card" id="candidate{i}"><h2>候補{i}　{m["name"]}</h2><p>{m["note"]}</p><p class="sub"><code>{m["id"]}</code></p><div class="rules">{blocks}</div>'
        section+='<div class="tabs">'+''.join(f'<button type="button" class="{"active" if s=="TOPIX" else ""}" data-target="c{i}-{s}">{s}版</button>' for s in SYMBOLS)+'</div>'
        for s in SYMBOLS:
            a=m['summary'][s];q=5 if s=='TOPIX' else 10
            section+=f'<div id="c{i}-{s}" class="symbol-panel {"hidden" if s!="TOPIX" else ""}"><h3>{s}版 · 新規{q}枚</h3><p>勝率 <b>{percentage(a["win_rate"])}</b>（{a["wins"]}/{a["cycles"]}取引） · 平均利益 {money(a["average_win"] or 0)}円 / 平均損失 {money(a["average_loss"] or 0)}円 · PF {ratio(a["pf"])} · 最大資産下落 {money(a["drawdown"])}円</p>'+session_table([a for a in m['accounts'] if a['symbol']==s])+f'<a href="台帳/候補{i}_{s}_全決済.csv">全決済のCSV</a></div>'
        difference = {
            1: '銘柄差：16呼値の目標到達はTOPIX18/57取引、NK7/46取引。NKは手数料前+2,000円が費用10,120円で赤字になりました。今回選ばれたNKの入口では、継続が費用を上回るほど伸びませんでした。',
            2: '銘柄差：損切りはTOPIX43/77取引、NK27/59取引。TOPIXは同じ注文を中値へ置き換えても赤字で、費用だけが原因ではありません。過去5回の好調による選別は、今回のTOPIXでは十分に働きませんでした。',
            3: '銘柄差：平均利益/損失は両方とも約0.525。この実測額で収支均衡に必要な勝率は約65.5%です。TOPIXの57.9%は届かず、NKの73.9%は上回りました。銘柄の金額倍率だけが原因ではありません。',
        }
        section += '<p class="sub">'+difference[i]+' 今回の標本での説明であり、銘柄固有の性質を証明するものではありません。</p>'
        if i<3:
            c=m['config']
            section+=f'<details><summary>機械的な数値条件</summary><p>16原本更新ごとに候補判定。256更新連続で板が正常、開始5分以降、過去256更新の約定時計幅120秒以内、気配幅1呼値以下。TOPIXの目標8pt/損切り4pt、NKの目標160円/損切り80円。実際の返済は次行の気配なので、この幅を越す損失も含みます。利確トレーリングではなく固定目標の比較です。IDにH600が残りますが、実設定の保有期限は{c["hold"]//60}分です。</p><p>'
            if i==1:
                section+='直近64更新OFI÷平均最良量が±4以上、256更新のOFIも同符号、最良数量偏りが±0.6以上、64更新で1呼値以上の同方向変位。既知執行代理は同方向、分類不明の比率40%以下。'
            else:
                section+='減少表示量の80%以上が回復し、回復量が減少時最良量の25%以上になった補充完了を使います。完了から64更新以内、補充強度0.5以上、現在最良価格が補充価格の2呼値以内、反対執行代理が最良平均量以上、64更新の中値変位は±2呼値以内、直近16更新の方向付きOFI÷平均最良量が2以上。'
            section+='影取引は入口・出口・費用・休止条件を揃え、当該場で既に全返済した結果だけを利用します。運用の監視基準は昼15:35/夜05:50。新規は15:30/05:45未満、強制返済判断は15:34/05:49以降。次の有効原本行で返済し、保存通常区間の終端15:40/05:55未満に全返済します。実返済後10秒休止。</p></details>'
        else:
            section+='<details><summary>機械的な数値条件</summary><p>確定1分足の安値が過去20分安値を1呼値超下回り、終値がその安値より1呼値以上上で陽線なら買い候補。売りは対称。120秒/5,000原本行以内に方向付き近接量偏りが、その場の現在を除く20分の絶対偏り75%点以上、表示純変化が同符号、発火中値から1呼値順行を要求。板時計の鮮度5秒以内、60秒に最低3公開ブロック、気配幅0.15基準幅以内。基準幅は観測始値×0.1%を呼値へ切上げ、最低2呼値。半幅で利確、1幅で損切り、60分期限、実返済後10分休止。場の含み損と費用を含む資産が−3基準幅×上限枚数×価格倍率以下なら全返済し新規終了。新規は15:30/05:45未満、強制返済判断は15:34/05:49以降、次の有効原本行で返済して15:40/05:55未満に全返済。分足未確定値や未来の板確認を元の候補時刻へ戻しません。</p></details>'
        chapters.append(section+'</section>')
    small='<section class="card"><h2>1取引だけで100%だった条件</h2><p>板が支えた後の反発を待つB2のTOPIX版。5条件すべて1勝/1取引で、同じ入口を異なる返済/新規約定仮定で評価したものです。負けが一度もないため、平均損失と損小利大の比率は未観測です。</p><div class="scroll"><table><thead><tr><th>ID</th><th>価格</th><th>費用後収支 円</th><th>勝ち/決済</th></tr></thead><tbody>'
    for a in observed:
        m=next(m for m in methods if m['branch']==a['branch'] and m['id']==a['id'])
        small+=f'<tr><th>{a["id"]}</th><td>{m["mode"]}</td><td class="pos">{money(a["net"],True)}</td><td>1/1</td></tr>'
    small+='</tbody></table></div><p>これは観測上の95%達成ですが、「取引を続けても95%」の証拠にはしていません。NKは該当条件で無取引でした。</p></section>'
    common=next(m for m in methods if m['id']=='M3_Q2_L0_T16_S8_H600_保有30分_校正10_60')
    supplemental=f'<details class="card"><summary>両銘柄で黒字だった別配分の入口選別</summary><p>候補2の模擬取引窓を5回中3勝から10回中6勝へ変更すると、TOPIX+{money(common["summary"]["TOPIX"]["net"])}円・8/16取引、NK+{money(common["summary"]["NK225"]["net"])}円・9/17取引。両方黒字ですが、取引数がさらに減り、95%には届きません。全場の内訳は全375条件のJSONに保存しました。</p></details>'
    script='''/**
 * 銘柄タブを切り替えて、その候補の全セッション表を表示する。
 * 引数: event(MouseEvent)。返り値: なし(undefined)。
 */
function switchSymbol(event){const button=event.target.closest('button[data-target]');if(!button)return;const card=button.closest('.card');card.querySelectorAll('.symbol-panel').forEach(p=>p.classList.toggle('hidden',p.id!==button.dataset.target));card.querySelectorAll('button').forEach(b=>b.classList.toggle('active',b===button));}
document.addEventListener('click',switchSymbol);'''
    (OUT/'95パーセント探索の説明と全セッション損益.html').write_text(shell('決済勝率95%の探索と、比較3候補の全損益',intro+overview+graphs+''.join(chapters)+small+supplemental,script),encoding='utf-8')
    # ----------------------------------------
    # 全条件は検索表へ分離し、参考約定を主評価と混同しない。
    rows=[]
    for m in methods:
        cells=''.join(f'<td class="{"pos" if m["summary"][s]["net"]>0 else "neg"}">{money(m["summary"][s]["net"],True)}</td><td>{percentage(m["summary"][s]["win_rate"])} ({m["summary"][s]["wins"]}/{m["summary"][s]["cycles"]})</td><td>{ratio(m["summary"][s]["payoff"])}</td>' for s in SYMBOLS)
        rows.append(f'<tr><th>{m["branch"]}<br><code>{m["id"]}</code></th><td>{m["mode"]}</td>{cells}</tr>')
    allbody='<p>375条件には対照の再掲を含みます。750銘柄別評価を独立の発見数とは扱いません。「中値参考」「指値仮定」「二銘柄時計の参考」は主評価と区別します。</p><label>絞り込み <input id="search" placeholder="例：Q2、R3、quote"></label><p id="count" class="sub"></p><div class="scroll"><table id="all"><thead><tr><th>枝・手法ID</th><th>評価価格</th><th>TOPIX収支 円</th><th>TOPIX勝率 (勝/決済)</th><th>平均益/損</th><th>NK収支 円</th><th>NK勝率 (勝/決済)</th><th>平均益/損</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div><p><a href="全375条件の一覧.csv">一覧CSV</a> · <a href="調査仕様と集計.json">全25場の損益を含むJSON</a></p>'
    allscript='''/**
 * 条件表を文字列で絞り込み、表示件数を更新する。
 * 引数: なし。返り値: なし(undefined)。
 */
function filterRows(){const query=document.querySelector('#search').value.toLowerCase();let n=0;document.querySelectorAll('#all tbody tr').forEach(row=>{const show=row.textContent.toLowerCase().includes(query);row.hidden=!show;if(show)n++;});document.querySelector('#count').textContent=n+' / 375条件';}
document.querySelector('#search').addEventListener('input',filterRows);filterRows();'''
    (OUT/'全375条件.html').write_text(shell('全375条件の結果',allbody,allscript),encoding='utf-8')
    pdca='''<p>95%という目標へ近づいたかを、勝率だけでなく利益・損失・取引数で判定しました。各ラウンドは当該ラウンドの損益計算前に条件とコードを固定しています。ただし全25場は既知で、改良自体は事後研究です。</p>
<p class="sub">独立監査：18,750口座・426,137決済組の会計が一致。これは対照・参考・再掲を含む検算件数です。利益や95%勝率の保証ではありません。</p>
<section class="card"><h2>1　小さい利益が気配差に消える</h2><p><b>原因：</b>旧在庫I1は、同じ注文を中値へ付け替えるとTOPIX+183,974円/NK+28,116円ですが、気配では−279,026円/−290,484円。気配差の負担は463,000円/318,600円でした。一方、旧方向手法は中値でも赤字で、全部を費用のせいにはできません。</p><p><b>改善：</b>追加玉を止め、次行気配・新規指値・新規と利確の指値を分けて比較。</p><p><b>結果：</b>指値だけでは解決しませんでした。通過したら約定する仮定では、逆行した注文が選ばれ、狭い幅では約定時に損切り幅を使い切ります。これは指値技術全般の否定ではなく、今回の約定仮定と幅設計の衝突です。</p></section>
<section class="card"><h2>2　見えた圧力が、次の利益を予測するとは限らない</h2><p><b>原因：</b>OFIはすでに動いた価格や表示量の変化も含みます。買い優勢を観測できても、その後に買って気配差と費用を回収できるとは限りません。</p><p><b>改善：</b>補充・OFI・価格の反応を確認し、逆方向・利益保護・30分保有・休止時間を一つずつ変更。</p><p><b>結果：</b>短期板の第1ラウンド36条件はTOPIX全赤字、NK黒字1条件は7取引のみ。第2ラウンド72条件もTOPIX全赤字。第3ラウンドで現在場の完了模擬取引を入口選別に使うとTOPIX7/NK4条件が黒字になりましたが、95%は0条件でした。</p><p><b>追加反証：</b>新時計の最終値・出来高増分の平均約定代理と現在気配の不一致、16/64更新の単純待機も90条件で試し、全条件が両銘柄赤字でした。これは途中の価格保持・板品質を確認した待機ではありません。平均約定は個別売買の代用品でもありません。</p></section>
<section class="card"><h2>3　板の絶対閾値を固定すると機会が消える</h2><p><b>原因：</b>1分足の価格拒否へ強い板を同時要求した条件は、両銘柄とも無取引になりました。鮮度だけでなく数量の固定閾値がデータの通常範囲に合っていませんでした。</p><p><b>改善：</b>120秒以内に確認を待ち、その場の過去20分に対して強い板かどうかを判定。</p><p><b>結果：</b>NKの小幅返済は17勝/23取引=73.9%、+20,940円。ただし平均益/損は0.524で損小利大ではありません。同じ入口をトレール出口へ変えると45.5%、+4,160円、比1.269になり、勝率と平均利益が交換関係になりました。</p></section>
<section class="card"><h2>4　利益保護で勝率が上がっても、収支は上がらない</h2><p><b>原因：</b>当たった取引の利益を戻す事例があったため、順行後の費用込み建値保護と半幅トレールを追加。</p><p><b>結果：</b>在庫の主条件はTOPIX勝率41.9→48.4%、NK23.1→30.8%。収支はTOPIX+4,542→−12,958円、NK−149,160→−143,160円です。別条件ではTOPIXの4負けを勝ちへ変えても、13勝ち組の利益を約17万円削り、全体では約7.5万円悪化しました。</p><p><b>次に残る課題：</b>早い返済をどの取引に適用するかを、入口時点の情報で区別できるか。勝ち玉だけを数える方式や、場末に残った損失を無視する方式は採用していません。</p></section>
<section class="card"><h2>今回確認できた範囲</h2><p>機械的に実行できる入口・判断・出口です。未来の値は判断に入れず、途中切断・未来改変・注文価格・費用・全決済組・全行含み損を独立検算しました。ATRやLSTMは使用していません。</p><p>補充は表示数量の回復で、同じ参加者の補充や焦りを識別したものではありません。受信時刻・注文順番・mini/microの実板がないため、二銘柄の厳密な同時先行判定と実約定の保証は未検証です。最終約定時計が同じまま板は動くので、1原本行遅延を0秒約定とも扱いません。</p><p>「取引勝率95%」と「平均利益が平均損失以上」を同時に満たすなら、同じ決済組の金額でPFは少なくとも19以上になります。目標を下げず、今回は未達を明示します。</p><p>OFIと価格変化の研究は、主に同時の価格応答を説明するものです。<a href="https://arxiv.org/abs/1011.6402">Cont・Kukanov・Stoikov</a>。板数量偏りの次の中値予測も、今回の銘柄の費用後95%利益を保証しません。<a href="https://arxiv.org/abs/1512.03492">Gould・Bonart</a>。</p><p><a href="監査まとめ.md">独立監査</a> · <a href="3候補の銘柄差.md">3候補の銘柄差</a> · <a href="../../work/wave_v63/directional/PDCA説明.json">方向枝の固定条件と検証済み列</a> · <a href="../../work/wave_v63/inventory/原因と改善結果.md">在庫枝の原因</a></p></section>'''
    (OUT/'損失原因とPDCA.html').write_text(shell('赤字の原因から行った改良と結果',pdca),encoding='utf-8')
    # ----------------------------------------
    # 案内・検算結果・共通索引を更新する。
    save(OUT/'報告書の数値照合.json',dict(合格=True,条件数=len(methods),口座数=sum(len(m['accounts']) for m in methods),
        金額恒等式='全口座 profit-loss=net および gross_profit-gross_loss-fees=net 一致',
        全場網羅='各候補・銘柄25場、週別/全期間は同じ口座から再集計',
        実測95='1組のみの5条件。無取引は成功に含めない。',候補数=3,次の未使用作業番号='00061'))
    (OUT/'README.md').write_text('''# 決済勝率95%の探索とPDCA

最初に [95パーセント探索の説明と全セッション損益.html](95パーセント探索の説明と全セッション損益.html) を見てください。

読む順序：

1. 3比較候補の短い説明・全25場・週別・全期間の損益。TOPIX/NKタブで銘柄を切替。
2. [損失原因とPDCA.html](損失原因とPDCA.html)：なぜ負けたか、何を変え、どうなったか。
3. [全375条件.html](全375条件.html)：参考価格・再掲対照を含む全条件。
4. [独立監査](監査まとめ.md)、[集計仕様と全口座](調査仕様と集計.json)。

95%以上はTOPIXの同じ入口の1勝/1取引だけでした。負けの大きさが未観測で、3つの継続運用成功候補とはしていません。3候補は未達の比較対象です。

金額は費用後の全決済組を正負へ分けた利益・損失です。枚数はその組の決済枚数。手数料を再度引かないでください。全場内返済、初回TOPIXmini5枚/NKmicro10枚、追加なし、片方向上限10枚/20枚以内です。

[全セッションCSV](比較3候補の全セッション.csv) · [条件一覧CSV](全375条件の一覧.csv) · [決済原簿](台帳/)。

再現元は `../../work/wave_v63/`。各枝の固定仕様・実装・入力SHA・集計結果・原簿・独立監査を保持しています。報告書を同じ結果から生成：`python -X utf8 work/wave_v63/report.py`。保存原本は読み取りのみ、現在セッション取得と実注文は行っていません。
''',encoding='utf-8')
    research=OUT.parent
    card=f'<!--00060開始--><article class="task latest"><div class="number">作業00060 <span class="badge">最新</span></div><h2>決済勝率95%の探索とPDCA</h2><p>375条件の改良と独立監査。3比較候補の入口・途中・出口、全25場の費用後金額・枚数。95%の小標本達成と継続候補の未達を区別。</p><a class="button" href="{OUT.name}/95パーセント探索の説明と全セッション損益.html">3候補の説明と全損益を開く →</a><p><a href="{OUT.name}/損失原因とPDCA.html">原因と改良</a> · <a href="{OUT.name}/全375条件.html">全375条件</a> · <a href="{OUT.name}/README.md">資料案内</a></p></article><!--00060終了-->'
    index=(research/'index.html').read_text(encoding='utf-8')
    index=index.replace('class="task latest"','class="task"').replace('<span class="badge">最新</span>','')
    index=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00060：決済勝率95%の探索とPDCA。比較3候補の説明と、全25セッションの費用後損益。</p>',index,count=1,flags=re.S)
    index=re.sub(r'<footer>最新作業は.*?</footer>','<footer>最新作業は00060です。次の作業は00061以降へ追加します。</footer>',index,count=1,flags=re.S)
    if '<!--00060開始-->' in index:
        start=index.index('<!--00060開始-->');end=index.index('<!--00060終了-->')+len('<!--00060終了-->')
        index=index[:start]+card+index[end:]
    else:
        index=index.replace('<!--00059開始-->',card+'<!--00059開始-->',1)
    assert index.count('<!--00060開始-->')==1
    (research/'index.html').write_text(index,encoding='utf-8')
    readme=(research/'README.md').read_text(encoding='utf-8')
    readme=readme.replace('最新は00059の','00059の').replace('`00049_価格形成の観測から新手法を構築`（最新）','`00049_価格形成の観測から新手法を構築`')
    notice=f'<!--00060案内開始-->\n**最新は00060の[決済勝率95%の探索と全セッション損益]({OUT.name}/95パーセント探索の説明と全セッション損益.html)。375条件のPDCA、3比較候補の費用後損益と、95%未達の根拠。**\n\n[損失原因とPDCA]({OUT.name}/損失原因とPDCA.html) · [全375条件]({OUT.name}/全375条件.html) · [資料案内]({OUT.name}/README.md)。\n<!--00060案内終了-->\n\n'
    if '<!--00060案内開始-->' in readme:
        start=readme.index('<!--00060案内開始-->');end=readme.index('<!--00060案内終了-->')+len('<!--00060案内終了-->')
        readme=readme[:start]+notice.rstrip()+readme[end:]
    else:
        head,rest=readme.split('\n',1);readme=head+'\n\n'+notice+rest.lstrip('\n')
    (research/'README.md').write_text(readme,encoding='utf-8')
    print(f'{OUT.name}: 375条件・18,750口座・比較3候補の全25場を公開',flush=True)


if __name__=='__main__':
    main()
