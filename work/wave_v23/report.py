"""市場原理・売買結果・反証を短い入口と手法別の資料にまとめる。"""

from __future__ import annotations

from datetime import datetime, timedelta
import html
import json
from pathlib import Path
import pickle
import shutil

import numpy as np
import pandas as pd

import engine
import research

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
DEST = ROOT / 'アルゴリズム調査/00018_市場原理からの再探索'
NAMES = {'TOPIX': 'TOPIXミニ', 'NK225': 'NK225マイクロ'}
STYLE = '''
:root{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#0a111b;color:#e6edf6}*{box-sizing:border-box}body{margin:0;line-height:1.75}main{max-width:1200px;margin:auto;padding:36px 22px 70px}a{color:#88c6ff}h1{font-size:30px;margin:6px 0 16px}h2{font-size:22px;margin-top:34px}h3{font-size:18px}p{margin:10px 0}.muted,small{color:#a7b8ca}.tag{font-size:12px;color:#9cbada;letter-spacing:.08em}.panel,details{background:#121e2d;border:1px solid #2b4056;border-radius:10px;padding:18px;margin:18px 0}.warning{border-left:4px solid #e6b566;background:#24221d;padding:16px}.good{color:#66d9b1}.bad{color:#ff929e}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;white-space:nowrap}th,td{padding:9px 11px;border-bottom:1px solid #2a394b;text-align:right}th:first-child,td:first-child{text-align:left}th{color:#bcd0e6;background:#172637}summary{cursor:pointer;font-weight:bold}select,input,button{font:inherit;background:#142438;color:#e6edf6;border:1px solid #577390;border-radius:5px;padding:7px;margin:4px}button{cursor:pointer}canvas{width:100%;height:440px;background:#0c1522;border:1px solid #2a4057;border-radius:8px}.controls{display:flex;flex-wrap:wrap;align-items:center;gap:8px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}.grid .panel{margin:0}.step{padding:13px;background:#182c3d;border-radius:6px}code{color:#b2d9ff}li{margin:6px 0}a:focus-visible,summary:focus-visible{outline:3px solid #edbd66}pre{white-space:pre-wrap;word-break:break-word;font-size:12px}@media(max-width:600px){main{padding:22px 12px}h1{font-size:24px}th,td{padding:7px}canvas{height:350px}}
'''


def read(name: str) -> object:
    """機能: 今回作業の保存済みJSONを読む。

    引数: name (str)。返り値: 保存値 (object)。
    """
    return json.loads((OUT / name).read_text(encoding='utf-8'))


def esc(value: object) -> str:
    """機能: HTML本文へ安全に埋め込む。

    引数: value (object)。返り値: エスケープ済み文字列 (str)。
    """
    return html.escape(str(value))


def yen(value: float, sign: bool = False) -> str:
    """機能: 円額を小数なしで表示する。

    引数: value (float)、sign (bool)。返り値: 表示文字列 (str)。
    """
    return f'{value:+,.0f}' if sign else f'{value:,.0f}'


def number(value: float | None) -> str:
    """機能: 比率の欠損を区別して表示する。

    引数: value (float|None)。返り値: 表示文字列 (str)。
    """
    return '—' if value is None else f'{value:.2f}'


def balance(value: float) -> str:
    """機能: 収支を符号と色で表示する。

    引数: value (float)。返り値: HTML断片 (str)。
    """
    return f'<span class="{"good" if value > 0 else "bad" if value < 0 else "muted"}">{yen(value, True)}</span>'


def table(headers: list[str], rows: list[list[str]]) -> str:
    """機能: 横スクロール可能な表を作る。

    引数: headers (list[str])、rows (list[list[str]])。返り値: HTML (str)。
    """
    return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{h}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{v}</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def page(title: str, content: str, script: str = '') -> str:
    """機能: ダークテーマの単独HTMLを作る。

    引数: title/content/script (str)。返り値: HTML全文 (str)。
    """
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><style>{STYLE}</style></head><body>
<!--
[コンポーネント概要]
main は保存済み検証の表示領域です。全ページをダークテーマで統一します。
.panel は結論や手法、details は詳細条件とセッション損益です。
.scroll は表の横スクロール領域、.good/.bad は正負の収支を色分けします。
この資料は外部通信も実注文も行いません。引数と返り値はありません。
-->
<main><div class="tag">調査 00018 ／ 保存13セッション ／ 費用0・指定価格約定</div><nav><a href="結果.html">結論</a> · <a href="手法別の損益.html">手法別損益</a> · <a href="５分足と売買.html">５分足と売買</a> · <a href="README.md">資料案内</a></nav><h1>{esc(title)}</h1>{content}</main>{script}</body></html>'''


def period_table(rows: list[dict]) -> str:
    """機能: 全期間・週・各セッションの金額と決済枚数を表示する。

    引数: rows (list[dict])。返り値: HTML表 (str)。
    """
    sums = []
    weeks = sorted({(datetime.fromisoformat(r['session'][:10]) - timedelta(days=datetime.fromisoformat(r['session'][:10]).weekday())).date().isoformat() for r in rows})
    groups = [('全13セッション合計', rows)]
    for week in weeks:
        groups.append((week + 'の週', [r for r in rows if week <= r['session'][:10] < (datetime.fromisoformat(week) + timedelta(days=7)).date().isoformat()]))
    groups.extend((r['session'].replace('_Day', ' 昼').replace('_Night', ' 夜'), [r]) for r in sorted(rows, key=lambda r: r['session']))
    for label, selected in groups:
        a = research.aggregate(selected)
        sums.append([esc(label), yen(a['gross_profit_yen']), yen(a['gross_loss_yen']), balance(a['net_yen']), str(a['profit_units']), str(a['loss_units']), f"{a['profit_units']-a['loss_units']:+d}", str(a['zero_units'])])
    return table(['期間', '利益 円', '損失 円', '収支 円', '利益枚数', '損失枚数', '枚数差', '同値枚数'], sums)


def chart_payload(finalists: list[str], catalog: dict, inputs: dict) -> dict:
    """機能: 確定５分足と監査済み全返済の時刻・価格をチャート用にまとめる。

    引数: finalists (list[str])、catalog/inputs (dict)。返り値: 埋込みデータ (dict)。
    """
    candles, trades, choices, past_choices = {}, {}, {}, {}
    if (OUT/'手法選択の履歴.json').exists():
        events = read('手法選択の履歴.json')
        for event in events['相場状態から選択']:
            key = (event['selector_id'], event['session'], event['symbol'])
            choices.setdefault(key, []).append((event['seq'], event['selected_signal_id']))
        for event in events['過去確定成績から選択']:
            past_choices[(event['selector_id'],event['適用セッション'],event['symbol'])] = '+'.join(event['selected_ids'])
    for (session, symbol), ready in inputs.items():
        frame = pd.read_csv(ROOT / 'candle_5min' / symbol / f'{session}.csv')
        stamps = pd.to_datetime(frame.time).map(lambda t: t.timestamp()).to_numpy()
        valid = (stamps >= ready['start']) & (stamps <= ready['limit'])
        candles[session + '|' + symbol] = [[float(t), *[float(v) for v in row]] for t, row in zip(stamps[valid], frame.loc[valid, ['open', 'high', 'low', 'close']].to_numpy())]
    for identifier in finalists:
        stored = np.load(OUT / 'trades' / f'{identifier}.npz')
        for (session, symbol), ready in inputs.items():
            value = []
            for trade in stored[f'{session}_{symbol}_trades']:
                start, end = int(trade[6]), int(trade[7])
                key = (identifier.split('_')[0], session, symbol)
                monitored = past_choices.get(key, key[0])
                if key in choices:
                    history = choices[key]
                    index = np.searchsorted([item[0] for item in history], ready['seq'][start], side='right')-1
                    monitored = history[index][1] if index >= 0 else '未選択'
                value.append([float(ready['time_s'][start]), float(ready['time_s'][end]), int(trade[2]), int(trade[3]), float(trade[4]), float(trade[5]), float(trade[10] * research.MULT[symbol]), engine.REASONS[int(trade[9])], monitored])
            trades[identifier + '|' + session + '|' + symbol] = value
    return dict(methods={i: catalog[i]['name'] for i in finalists}, sessions=sorted({k[0] for k in inputs}), candles=candles, trades=trades)


def main() -> None:
    """機能: 全結果を新規番号の成果フォルダにまとめ、入口を更新する。

    引数: なし。返り値: なし (None)。原本と以前の作業フォルダは変更しない。
    """
    DEST.mkdir(exist_ok=True)
    ranking, rows, selection = read('全条件の期間集計.json'), read('全条件セッション集計.json'), read('選択結果.json')
    catalog = {x['id']: x for x in ranking}
    finalists = selection['finalists']
    walks = read('逐次選択の結果.json')
    controls = read('control_results.json')['ランダム方向集計'] + read('control_results_additional.json')['ランダム方向集計']
    evidence = read('philosophical_evidence.json')['期間集計']
    inputs = pickle.loads((OUT / 'inputs.pkl').read_bytes())
    byid = {x['id']: [] for x in ranking}
    for r in rows:
        byid[r['id']].append(r)

    # ----------------------------------------
    # 結論は事後最良と逐次選択を分け、予測と注文の効果を混同しない。
    overview = '''<p><strong>板を使う有望候補は残った。ただし「事前に安定して選べる」段階には達していない。</strong></p>
<p>58種類の方向判断 × 20種類の注文管理＝1,160条件を検証。全期間を見た共通候補の首位は <code>F32_G08</code>。最良気配の数量バランスと直近の価格方向を合わせて入る方法です。</p>
<div class="warning">過去だけで毎回候補を選び、次のセッションで評価した７区間は、TOPIX −79,500円／NK −13,700円。全13区間は既読なので、この逐次再現も真の未見試験とは区別します。</div>
<h2>共通候補５つ：同じ銘柄の利益と損失を比べる</h2><p class="muted">１位から３位は初回１枚、４位・５位はTOPIX５枚／NK10枚。円額の大小では順位を付けていません。</p>'''
    overview += table(['手法ID', '銘柄', '利益 円', '損失 円', '収支 円', '金額PF', '平均勝ち/負け・1枚', '黒字区間', '時価最大下落 円'],
        [[f'<a href="手法別の損益.html#{i}">{i}</a>', NAMES[s], yen(a['gross_profit_yen']), yen(a['gross_loss_yen']), balance(a['net_yen']), number(a['money_ratio']), number(a['average_unit_payoff']), f"{a['win_sessions']}/13", yen(a['drawdown_yen'])] for i in finalists for s,a in catalog[i]['symbols'].items()])
    overview += '''<p>損小利大は「１枚当たりの平均利益÷平均損失」と、損益全体の「総利益÷総損失（PF）」を分けて確認します。部分利確・両建ては、全玉を閉じた一組全体でも検算しています。</p>
<details><summary>首位 F32_G08 の機械的条件</summary><ol>
<li>有効な最良買い数量をB、売り数量をAとして、加重気配偏差 <code>(B−A)÷[2(B＋A)]</code> を計算。同一時刻ブロックの平均を、直近120秒の解放済みブロックで平均する（最低５ブロック）。</li>
<li>偏差が +0.06超、かつ120秒前から仲値が１呼値を超えて上昇なら買い。−0.06未満かつ下落なら売り。上昇・下落は対称。</li>
<li>開始20分後から、現在価格より0.25ATR順行した位置に１枚の逆指値。有効２分、方向が変われば取消。注文は次の原本行から有効。</li>
<li>１ATRで損切り。１ATR順行後は最高値／最安値から２ATRの追跡。新規注文時ATRを保有中固定し、呼値に丸める。</li>
<li>同方向２連敗で停止。反対信号か直近の損切り成立行の観測価格から１ATR順行で再開。初回注文の予定損失の−３倍以下にセッション時価損益が達したら停止・返済。これは目標水準でありギャップ時の損失保証ではない。</li>
<li>返済後５分休止。保有360分以内、日中15:35／夜間05:50で返済を指示し次観測で執行。新規はその５分前まで。</li></ol>
<p>ATRは確定５分足のTRをα=1/12で平滑化し、足終了から１分待って使用。最低３本が必要。LSTMは不要です。G00とG08は今回の全取引が同一で、好成績を連敗防御の効果とは認定できません。</p></details>
<h2>哲学から、検証できる問いへ</h2>
<p>売買は、評価・期限・在庫・リスクの違う参加者の交換です。買う人と売る人が同数約定するので、測るべきは<strong>「今すぐ約定したい圧力に、待っている注文が耐えるか」</strong>です。</p>
<div class="grid"><div class="step">売りが続く＋買い板が後退<br>→ 下落継続という仮説</div><div class="step">売りが続く＋補充され下がらない<br>→ 吸収・反発という仮説</div><div class="step">NKとTOPIXで同時に進む<br>→ 共通要因という仮説</div></div>
<p>ただし、流れの継続は価格の継続を保証しません。待つ側も注文を補充・取消して反応します。板から観測できない参加者の意図は仮説として扱います。<a href="https://arxiv.org/abs/1011.6402">注文イベントと価格応答の研究</a>、<a href="https://arxiv.org/abs/1808.09677">潜在流動性の研究</a>を参照しました。</p>
<details><summary>今回のデータで、この問いはどこまで支持されたか</summary>'''
    evidence_ids = ['F29','F32','F39','F40','F44','F47','F52','F53']
    overview += table(['仮説', '銘柄', '5分後の平均差 ATR', '5分予測件数', '15分後の平均差 ATR', '15分予測件数'], [[f"{sid} {next(e['手法名'] for e in evidence if e['手法ID']==sid)}", NAMES[s], f"{e5['平均方向付きATR差']:+.3f}" if e5['平均方向付きATR差'] is not None else '—', str(e5['予測件数']), f"{e15['平均方向付きATR差']:+.3f}" if e15['平均方向付きATR差'] is not None else '—', str(e15['予測件数'])] for sid in evidence_ids for s in NAMES for e5 in [next(e for e in evidence if e['手法ID']==sid and e['銘柄']==s and e['予測分数']==5 and e['売買']=='合計')] for e15 in [next(e for e in evidence if e['手法ID']==sid and e['銘柄']==s and e['予測分数']==15 and e['売買']=='合計')]])
    overview += '''<p>正なら予測方向へ進行、負なら逆行。毎分標本・保有前の方向判断そのものを測っています。窓が重なり独立標本ではないため、有意差とは呼びません。途中の順行で追跡利確できるので、固定時間後の方向差と売買損益は一致しません。</p><p>単純OFIや両市場一致は、両銘柄・両時間で一様な正の応答にはなりませんでした。同価格補充はNKの件数が少なく、強い一般化はできません。今回の代理条件の限界であり、板読み全体の否定ではありません。</p></details>
<h2>注文手法だけで稼げるのか</h2><p>同じ価格経路で方向だけを30分ごとのコイントスにした16乱数種も比較しました。NKは無予測方向でも黒字が多く、黒字というだけでは予測の価値を示せません。</p>'''
    overview += table(['管理', '銘柄', '黒字の乱数種', '収支中央値 円', 'PF中央値', '収支の最小〜最大 円'], [[c['manager_id'], NAMES[c['symbol']], f"{c['seed黒字数']}/16", balance(c['収支円']['中央値']), number(c['金額PF']['中央値']), f"{yen(c['収支円']['最小'])}〜{yen(c['収支円']['最大'])}"] for c in controls if c['manager_id'] in ['G00','G08','G18','G12']])
    overview += '''<p class="muted">G08のNKでは乱数中央値＋21,700円に対し首位候補＋17,100円。ただし首位のPFは2.38、乱数中央値1.56。収支と損失効率で結論が違います。乱数種は独立した16期間ではなく同じ相場上の比較。G08/G12は選択後に追加した同管理の診断です。逆指値の価格確認も残るため、全価格条件がランダムという意味ではありません。</p>
<h2>長期下落への回答</h2><p>売り・買い対称の判断、方向撤回、連敗停止、リスク一定化を入れました。ただし、滑らかな下落では「0.25ATR順行を２分だけ待つ入口」が失効を繰り返す弱点が残ります。次観測成行G18はこの入口問題を解消しますが、実データの60分順張りF08_G18はTOPIX −79,000円／NK ＋37,100円でした。</p>
<p><strong>入りやすさを増やすと、往復相場での損失も増えます。今回、全状況で優れる一つの完成形は見つかっていません。</strong>人工的な連続下落など6,400再生は注文管理単体の検査であり、実板を含む戦略の将来利益の証明ではありません。</p>
<details><summary>以前のM3逆360分版との比較</summary><p>以前の固定１枚は全13区間でTOPIX ＋209,000円・時価最大下落39,500円、NK ＋30,700円・同10,000円。新首位は収支では下回り、時価最大下落はTOPIX34,500円、NK4,900円へ小さくなっています。新手法が全面的に上位とは言えません。</p><p>M3逆方向を主役にせず、継続売りも仮説へ含めた点が今回の変更です。後から良い候補を選んだ13区間の成績は、旧手法の将来耐性を否定する証拠にもなりません。</p></details>
<details><summary>逐次選択の内訳と検証条件</summary>'''
    overview += table(['評価セッション','事前選択ID','過去側の資格','TOPIX収支 円','NK収支 円'], [[f['評価セッション'], f['選択ID'], '合格' if f['過去側資格合格'] else '未達から選択', balance(next(r['net_yen'] for r in f['結果'] if r['symbol']=='TOPIX')), balance(next(r['net_yen'] for r in f['結果'] if r['symbol']=='NK225'))] for f in walks['folds']])
    overview += '''<p>最初６区間だけで選び、次の１区間を評価。以後過去を１区間ずつ追加。共通資格は両銘柄で黒字、組PF1.10以上、取引組数≥区間数、60%以上の区間で取引、50%以上で黒字、最大勝ち区間／最大勝ち組をそれぞれ除いても黒字。41条件が全期間で合格。順位は弱い銘柄側の最大勝ち区間除外PFを優先。損失ゼロでPF未定義の候補は保守的に資格外。</p>
<p>未来切断648件・未来改変216件、学習４条件の過去のみ学習、選出５候補の130詳細再生を監査。全玉の含み損を含む現金・在庫・時価を再構成し、約定の次行性と場内返済を確認。全期間既読のため、探索による過適合はこの監査では除けません。</p>
<p>TOPIXミニ最大10枚／NKマイクロ最大20枚は片方向の同時保有上限。使用原本は既存先物で、小型商品の実板約定を再現したものではありません。費用０・指定価格約定という依頼条件で統一しています。</p></details>'''
    if (OUT/'neighbor_results.json').exists():
        overview += '<details><summary>注文幅の±20%感度分析</summary><p>入口・損切り・追跡幅を一つずつ変更した事後診断。再選択はしていません。</p><p><a href="neighbor_results.json">全結果を開く</a></p></details>'
    if (OUT/'live/current_result.json').exists():
        live = read('live/current_result.json')
        overview += '<h2>固定５候補：現在セッションの一回照合</h2><div class="panel"><p>9/29ナイト、17:25締切。各データURL一回取得。まだ開始25分で、確定損益は全候補０。未完成の成績を13完了区間へ足しません。</p>'
        overview += table(['手法','銘柄','実現収支 円','含み損益 円','合算 円','買い保有','売り保有'], [[r['手法ID'],NAMES[r['銘柄']],balance(r['実現収支円']),balance(r['含み損益円']),balance(r['合算損益円']),str(r['保有買い枚数']),str(r['保有売り枚数'])] for r in live['結果']])
        overview += '<p><a href="current_result.json">取得・会計の詳細</a>。実発注ではなく、固定後の保存スナップショット再生です。</p></div>'
    overview += '<p><a href="市場原理と反証.md">市場原理と反証の全文</a> · <a href="research_notes.md">研究資料と採用した観点</a> · <a href="検証結果.md">数値の短い報告</a></p>'
    (DEST/'結果.html').write_text(page('市場原理からの再検証', overview), encoding='utf-8')

    # ----------------------------------------
    # 手法別の章は短い説明と金額・枚数に絞り、詳細を折り畳む。
    body = '<p>各系統で共通基準の最上位を掲載。上位５系統を先に並べ、残りを折り畳みます。全1,160条件は<a href="全条件の期間集計.json">期間集計</a>・<a href="全条件セッション集計.json">セッション明細</a>に保存しています。</p><p class="muted">利益・損失枚数は決済枚数。枚数差＝利益枚数−損失枚数であり、保有残高でも金銭収支でもありません。全13区間は9/21の週10区間と9/28の週３区間です。</p>'
    representatives, families = list(finalists), {catalog[i]['family'] for i in finalists}
    for item in ranking:
        if item['family'] not in families:
            representatives.append(item['id'])
            families.add(item['family'])
    for n, identifier in enumerate(representatives, 1):
        item = catalog[identifier]
        title = f'{n}. {identifier} ／ {item["signal"]["name"]}'
        if identifier not in finalists:
            body += f'<details id="{identifier}"><summary>{esc(title)}</summary>'
        else:
            body += f'<section class="panel" id="{identifier}"><h2>{esc(title)}</h2>'
        body += f'<p>{esc(item["signal"]["description"])}</p><p>注文管理：{esc(item["manager"]["name"])}。{esc(item["manager"]["description"])}</p><p class="muted">共通資格：{"合格" if item["qualified"] else "未達"}。値幅は銘柄別ATRで正規化。各セッション内で返済。</p>'
        for symbol in NAMES:
            a = item['symbols'][symbol]
            body += f'<h3>{NAMES[symbol]}版</h3><p>全期間 {balance(a["net_yen"])} 円 ／ 金額PF {number(a["money_ratio"])} ／ １枚平均勝ち/負け {number(a["average_unit_payoff"])} ／ 組PF {number(a["cycle_ratio"])}。最大勝ち区間除外 {balance(a["best_removed_net"])} 円、最大勝ち組除外 {balance(a["best_trade_removed_net"])} 円。</p>'
            body += f'<p class="muted">黒字 {a["win_sessions"]}/13区間、取引 {a["cycles"]}組、最大同時買い{a["max_long"]}枚／売り{a["max_short"]}枚。時価最大下落 {yen(a["drawdown_yen"])}円。</p><details><summary>週合計・セッション別の利益／損失／収支（金額・枚数）</summary>' + period_table([r for r in byid[identifier] if r['symbol']==symbol]) + '</details>'
        body += '<details><summary>機械的な数値条件</summary><pre>' + esc(json.dumps(dict(signal=item['signal'], manager=item['manager']),ensure_ascii=False,indent=2)) + '</pre><p>共通基準の全項目は<a href="managers.py">管理コード</a>を参照。返済までの一組に複数玉を含む場合、部分利確玉の勝率だけで判定しません。</p></details>'
        body += '</details>' if identifier not in finalists else '</section>'
    (DEST/'手法別の損益.html').write_text(page('手法別の説明と損益', body), encoding='utf-8')

    payload = chart_payload(finalists, catalog, inputs)
    chart = '<p>上位５候補の確定５分足と売買。線は新規→返済、緑の▲は買い新規、赤の▼は売り新規、黄色の×は返済です。線の色はその決済の利益／損失。部分利確は元の新規点を共有します。</p><p class="muted">明細の監視手法は新規約定時点に選ばれていた系統。逆指値を設置した時点の系統とは異なる場合があります。</p><div class="controls"><label>手法 <select id="method"></select></label><label>銘柄 <select id="symbol"><option value="TOPIX">TOPIXミニ</option><option value="NK225">NK225マイクロ</option></select></label><label>セッション <select id="session"></select></label></div><p id="chart-summary"></p><canvas id="chart" aria-label="５分足と新規返済のチャート"></canvas><div id="trade-table"></div>'
    js = (OUT/'chart.js').read_text(encoding='utf-8')
    scripts = '<script id="chart-data" type="application/json">' + json.dumps(payload, ensure_ascii=False, separators=(',',':'), allow_nan=False).replace('</','<\\/') + '</script><script>' + js + '</script>'
    (DEST/'５分足と売買.html').write_text(page('５分足と売買ポイント', chart, scripts), encoding='utf-8')

    # ----------------------------------------
    # 全条件と再現情報を同じ成果フォルダへ保存する。
    files = ['全条件一覧.json','全条件の期間集計.json','全条件セッション集計.json','探索前の固定記録.json','選択結果.json','逐次選択の結果.json','市場原理と反証.md','research_notes.md','日本語短評.md','philosophical_evidence.json','control_results.json','control_results_additional.json','control_README.md','control_README_additional.md','合成ストレス.json','追加板特徴監査.json','独立信号と会計監査.json','selected_audit.json','learned_flow_audit.json','validation_summary.md','current_result.json','neighbor_results.json','signals.py','engine.py','managers.py','learned_flow.py','research.py','prepare.py','depth_features.py','control_experiment.py','neighbor_diagnostic.py','current_check.py','report.py','chart.js']
    for name in files:
        if (OUT/name).exists():
            shutil.copy2(OUT/name, DEST/name)
    if (OUT/'live/current_result.json').exists():
        shutil.copy2(OUT/'live/current_result.json', DEST/'current_result.json')
        shutil.copy2(OUT/'live/取得記録.json', DEST/'現在データの取得記録.json')
        shutil.copy2(OUT/'live/現在照合の凍結記録.json', DEST/'現在照合の凍結記録.json')
    notes = ['# 検証結果', '', '58方向判断×20注文管理＝1,160条件。保存13セッションを使用。', '', '**共通の事後首位は F32_G08。全期間で良い候補はあるが、過去だけで候補を選び直す７区間の逐次評価は赤字。安定利益が実証されたとは扱わない。**', '', '| ID | 銘柄 | 利益円 | 損失円 | 収支円 | 金額PF | 平均１枚勝/負 | 最大勝ち区間除外円 |', '|---|---|---:|---:|---:|---:|---:|---:|']
    for i in finalists:
        for s,a in catalog[i]['symbols'].items():
            notes.append(f'| {i} | {NAMES[s]} | {yen(a["gross_profit_yen"])} | {yen(a["gross_loss_yen"])} | {yen(a["net_yen"],True)} | {number(a["money_ratio"])} | {number(a["average_unit_payoff"])} | {yen(a["best_removed_net"],True)} |')
    notes += ['', '逐次選択７区間：TOPIX −79,500円、NK −13,700円。損失ゼロPF未定義を保守的に資格外とするなどの基準は探索前に固定。', '', '同じ注文管理G08・ランダム方向16種の中央値はTOPIX +12,000円、NK +21,700円。首位のNK収支はこれを上回らない一方、PFは上回る。', '', 'F32_G00とF32_G08は今回同じ売買結果。連敗停止の貢献はこの期間では証明できない。', '', '連続下落の人工ストレスでは逆指値有効２分が失効し続ける入口の問題を確認。成行入口なら入りやすいが、実データのF08_G18はTOPIX赤字。全相場で優れる完成形は未確認。', '', '説明・各週・各セッションの金額と枚数は[手法別の損益](手法別の損益.html)、売買時刻は[５分足と売買](５分足と売買.html)。', '', '受信時刻・注文ID・約定主導方向・新規返済区分はない。補充・売買方向・他者の注文継続は代理観測であり意図を特定したとはしない。', '', '期間中の各売買は未来を使わず、13区間の手法選びは事後。両者を混同しない。']
    (DEST/'検証結果.md').write_text('\n'.join(notes)+'\n',encoding='utf-8')
    (DEST/'README.md').write_text('''# 00018 市場原理からの再探索

最初に見るファイルは **[結果.html](結果.html)** です。

読む順序：

1. [結論と反証](結果.html)：有望候補、逐次選択の失敗、板とランダム方向の検証。
2. [手法別の損益](手法別の損益.html)：各系統の説明、TOPIX版／NK版、セッション別・週別の金額と枚数。
3. [５分足と売買](５分足と売買.html)：上位５候補の売買位置と全決済。
4. [市場原理と反証](市場原理と反証.md)、[一次資料](research_notes.md)：売買の動機から観測可能な仮説へ。

全1,160条件の結果は `全条件の期間集計.json` と `全条件セッション集計.json`。原本や過去の調査フォルダ、M3固定台帳は変更していません。

再現元はプロジェクトルートの `work/wave_v23`。Python、NumPy、pandas、Numbaを使用し、RTX4090は不要でした。

保存データの再現順：`prepare.py` → `depth_features.py` → `research.py` → `control_experiment.py`／`philosophical_evidence.py`／監査・感度分析 → `report.py`。一回照合の `current_check.py` は再取得しない仕組みです。原本時刻の近似や指定価格約定など、入力条件は結論ページを参照してください。

全13区間は既読。未来参照がないことと、未見相場への優位性とは別です。固定後の現在途中セッションは独立した欄で表示し、過去の順位付けに戻しません。
''',encoding='utf-8')
    index = ROOT/'アルゴリズム調査/index.html'
    source = index.read_text(encoding='utf-8')
    if '<!--00018開始-->' not in source:
        source = source.replace('class="task latest"','class="task"').replace('<span class="badge">最新</span>','')
        source = source.replace('最新は9月28日夜・29日昼の固定条件検証。継続損益台帳も13セッションへ更新しました。','最新は00018。売買の原理から58信号・20注文管理を比較し、反証も掲載。')
        card = '<!--00018開始--><article class="task latest"><div class="number">作業00018 <span class="badge">最新</span></div><h2>市場原理からの再探索</h2><p>板の補充・撤退、注文の持続、両市場一致など1,160条件。候補の損益、逐次選択、コイントス対照と現在一回照合。</p><a class="button" href="00018_市場原理からの再探索/結果.html">結論と反証を開く →</a><p><a href="00018_市場原理からの再探索/手法別の損益.html">手法別の金額・枚数</a> · <a href="00018_市場原理からの再探索/５分足と売買.html">５分足</a> · <a href="00018_市場原理からの再探索/README.md">資料案内</a></p></article><!--00018終了-->'
        source = source.replace('<!--00017開始-->',card+'<!--00017開始-->')
        index.write_text(source,encoding='utf-8')
    path = ROOT/'アルゴリズム調査/README.md'
    source = path.read_text(encoding='utf-8')
    if '最新は00018' not in source:
        first = source.index('**最新は')
        last = source.index('**',first+2)+2
        source = source[:first]+'**最新は00018の[市場原理からの再検証](00018_市場原理からの再探索/結果.html)。[手法別損益](00018_市場原理からの再探索/手法別の損益.html)・[５分足](00018_市場原理からの再探索/５分足と売買.html)で詳細を確認できます。**'+source[last:]
        source = source.replace('`00017_9月28日夜と29日昼の固定候補検証`（最新）','`00017_9月28日夜と29日昼の固定候補検証`')
        source = source.replace('| `00017_', '| `00018_市場原理からの再探索`（最新） | 売買原理から1,160条件・対照・反証 | [結論](00018_市場原理からの再探索/結果.html) | [手法別損益](00018_市場原理からの再探索/手法別の損益.html)・[資料案内](00018_市場原理からの再探索/README.md) |\n| `00017_',1)
        source = source.replace('`00018_内容`','`00019_内容`')
        path.write_text(source,encoding='utf-8')
    print(f'保存しました: {DEST}',flush=True)


if __name__ == '__main__':
    main()
