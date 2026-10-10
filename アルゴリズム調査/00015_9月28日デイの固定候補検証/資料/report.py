"""追加日の固定候補検証を、短いダークHTMLと取引明細へまとめる。"""

from datetime import datetime
import html
import json
from pathlib import Path
import re
import shutil

import pandas as pd

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
FOLDER = '00015_9月28日デイの固定候補検証'
OUT = ROOT/'アルゴリズム調査'/FOLDER
PAGE = '9月28日デイの結果.html'
NAMES = {'TOPIX': 'TOPIXミニ', 'NK225': 'NK225マイクロ'}


def yen(value: float) -> str:
    """機能: 円額を符号付き整数へ整形する。

    引数: value (float)。返り値: 円表示 (str)。
    """
    value = 0. if abs(value)<1e-8 else value
    return ('+' if value>0 else '') + f'{value:,.0f}円'


def stamp(value: str) -> str:
    """機能: 日本時間の日時文字列から時分秒だけを表示する。

    引数: value (str)。返り値: 時刻表示 (str)。
    """
    return datetime.fromisoformat(value).strftime('%H:%M:%S')


def chart(symbol: str, trade: dict) -> str:
    """機能: 保存５分足と実際の再生約定点をSVGに描く。

    引数: symbol (str)、trade (dict)。返り値: 外部通信不要のSVG (str)。
    """
    frame = pd.read_csv(ROOT/'candle_5min'/symbol/'2026-09-28_Day.csv')
    times = pd.to_datetime(frame.time).dt.as_unit('ns').astype('int64').to_numpy()/1e9
    start, end = times[0], times[-1]+300
    low, high = float(frame.low.min()), float(frame.high.max())
    margin = max((high-low)*.15, 1.)
    low -= margin
    high += margin
    def x(t: float) -> float:
        """機能: 時刻を横座標に変換する。

        引数: t (float)。返り値: 座標 (float)。
        """
        return 72+(t-start)/(end-start)*800
    def y(p: float) -> float:
        """機能: 価格を縦座標に変換する。

        引数: p (float)。返り値: 座標 (float)。
        """
        return 28+(high-p)/(high-low)*245
    parts = [f'<svg viewBox="0 0 940 325" role="img" aria-label="{NAMES[symbol]}の５分足と売り新規・買い返済"><rect width="940" height="325" fill="#0c1521"/>']
    for index in range(5):
        price = low+(high-low)*index/4
        parts.append(f'<line x1="72" x2="880" y1="{y(price):.2f}" y2="{y(price):.2f}" stroke="#29394c"/><text x="65" y="{y(price)+4:.2f}" text-anchor="end" fill="#b8c8db" font-size="12">{price:,.1f}</text>')
    for index in range(0,len(frame),12):
        at = x(times[index])
        parts.append(f'<text x="{at:.2f}" y="302" text-anchor="middle" fill="#b8c8db" font-size="12">{stamp(frame.iloc[index].time)[:5]}</text>')
    for index, row in frame.iterrows():
        at = x(times[index]+150)
        color = '#56c99b' if row.close>=row.open else '#f17b96'
        top, bottom = y(max(row.open,row.close)), y(min(row.open,row.close))
        parts.append(f'<line x1="{at:.2f}" x2="{at:.2f}" y1="{y(row.high):.2f}" y2="{y(row.low):.2f}" stroke="{color}"/><rect x="{at-2.8:.2f}" y="{top:.2f}" width="5.6" height="{max(1,bottom-top):.2f}" fill="{color}"/>')
    entry_x, exit_x = x(datetime.fromisoformat(trade['entry_time']).timestamp()), x(datetime.fromisoformat(trade['exit_time']).timestamp())
    assert 72 <= entry_x <= exit_x <= 872
    parts.append(f'<line x1="{entry_x:.2f}" x2="{exit_x:.2f}" y1="{y(trade["entry_price"]):.2f}" y2="{y(trade["exit_price"]):.2f}" stroke="#edcc77" stroke-width="2" stroke-dasharray="5 4"/>')
    for at, price, label, color, anchor in [(entry_x,trade['entry_price'],'売り新規','#ffadcc','start'),(exit_x,trade['exit_price'],'買い返済','#8af0cb','end')]:
        parts.append(f'<circle cx="{at:.2f}" cy="{y(price):.2f}" r="5.5" fill="{color}" stroke="#07101b" stroke-width="2"/><text x="{at:.2f}" y="{max(17,y(price)-13):.2f}" text-anchor="{anchor}" fill="{color}" font-size="13" font-weight="bold">{label} {price:,.1f}</text>')
    return ''.join(parts)+'</svg>'


def main() -> None:
    """機能: 結果を保存し、共通索引に今回の結果へのリンクを追加する。

    引数: なし。返り値: なし (None)。損益や設定を変更しない。
    """
    rows = json.loads((WORK/'結果.json').read_text(encoding='utf-8'))
    trades = json.loads((WORK/'全取引.json').read_text(encoding='utf-8'))
    active = [r for r in rows if r['method_id']=='V0800']
    main_trades = [t for t in trades if t['method']=='V0800']
    body = ['<header><p class="eyebrow">作業00015 · 2026年９月28日デイ</p><h1>固定候補は両銘柄とも利益</h1><p>M3_逆_A00の360分版（V0800）を、９月27日に選んだ設定のまま適用。両銘柄とも朝に１回売り、360分後に返済しました。</p></header>',
            '<section><h2>本日の結果</h2><p class="note">TOPIXミニ・NK225マイクロ換算。費用０・指定価格約定。各銘柄・枚数を別々に実施した結果です。</p><div class="table"><table><thead><tr><th>銘柄</th><th>固定枚数</th><th>利益／利益枚数</th><th>損失／損失枚数</th><th>収支／枚数差</th></tr></thead><tbody>']
    for r in active:
        body.append(f'<tr><td>{NAMES[r["symbol"]]}</td><td>{r["quantity"]}枚</td><td>{yen(r["gross_profit_yen"])}／{r["profit_units"]}枚</td><td>{yen(-r["gross_loss_yen"])}／{r["loss_units"]}枚</td><td class="positive">{yen(r["net_yen"])}／+{r["unit_balance"]}枚</td></tr>')
    body.append('</tbody></table></div><p class="note">利益・損失枚数は返済した累計。今回は各銘柄１取引で全返済済みです。</p></section>')
    for t in main_trades:
        r = next(r for r in active if r['symbol']==t['symbol'] and r['quantity']==1)
        body.append(f'<section><h2>{NAMES[t["symbol"]]}：売りを６時間保有</h2><p><strong>{stamp(t["entry_time"])}　{t["entry_price"]:,.1f}で売り → {stamp(t["exit_time"])}　{t["exit_price"]:,.1f}で返済</strong></p><p>値幅 +{t["pnl_points"]:,.1f}。決済理由は保有時間の上限360分です。１枚の収支 <strong class="positive">{yen(t["pnl_yen"])}</strong>。</p>{chart(t["symbol"], t)}<p class="note">１枚当たり：含み損益込みの最大下落 {yen(r["drawdown_yen"])}、最も悪い途中損益 {yen(r["min_equity_yen"])}。確定損失０は、途中の含み損がなかったという意味ではありません。</p></section>')
    body.append('<section><h2>元の180分版との比較</h2><div class="table"><table><tr><th>固定１枚</th><th>180分版</th><th>360分版</th><th>改善額</th><th>取引回数</th></tr>')
    for symbol in NAMES:
        old = next(r for r in rows if r['symbol']==symbol and r['method_id']=='V0000' and r['quantity']==1)
        new = next(r for r in active if r['symbol']==symbol and r['quantity']==1)
        body.append(f'<tr><td>{NAMES[symbol]}</td><td>{yen(old["net_yen"])}</td><td>{yen(new["net_yen"])}</td><td>{yen(new["net_yen"]-old["net_yen"])}</td><td>{old["cycles"]}回 → {new["cycles"]}回</td></tr>')
    body.append('</table></div><p>今日は360分版で下落を長く保有でき、180分版の途中返済・再エントリー後の損失を減らせました。今日の結果から条件を選び直していません。</p></section>')
    body.append('<details><summary>全取引・データと検算</summary><p>方向判定は両銘柄の確定１分足、ATRは確定５分足、約定再生は生板の現在価格。従来と同じ公開遅延・原本順・呼値を使用。保存足と生板を時刻で再集計した足には少数の相違がありましたが、再集計足で補助再生しても今回の主候補の売買・収支は両銘柄とも一致しました。</p><p><a href="資料/全取引.json">全取引明細（180分版を含む）</a> · <a href="資料/結果.json">全集計</a> · <a href="資料/データ確認.json">原本と足の照合</a> · <a href="資料/実行前の固定記録.json">変更していない条件</a> · <a href="資料/audit_day28.json">独立監査</a> · <a href="資料/audit_bars.json">再集計足による補助確認</a></p></details>')
    body.append('<footer><a href="README.md">読む順序・再現方法</a> · <a href="検証結果.md">簡潔な報告書</a> · <a href="../index.html">調査一覧</a></footer>')
    css = 'body{margin:0;background:#0a111b;color:#e4edf7;font:16px/1.7 "Yu Gothic UI",Meiryo,sans-serif}main{max-width:1120px;margin:auto;padding:28px 22px}h1{font-size:30px}h2{font-size:22px;margin-top:0}.eyebrow,.note{color:#a6b9cf}.note{font-size:14px}section,details{background:#121e2c;border:1px solid #2a3c52;border-radius:12px;padding:22px;margin:20px 0}.table{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap}td,th{text-align:right;padding:10px;border-bottom:1px solid #2a3c52}td:first-child,th:first-child{text-align:left}a{color:#8ac8ff}.positive{color:#8af0cb}svg{width:100%;height:auto}summary{cursor:pointer}footer{margin:28px 0}strong{font-weight:700}a:focus-visible,summary:focus-visible{outline:2px solid #ffcb75}'
    page = '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>９月28日デイの固定候補結果</title><style>'+css+'</style></head><body><!--\n[コンポーネント概要]\nmain は固定候補の結果、取引点を重ねた保存５分足、180分版との比較をまとめます。\n.table は横スクロール可能な損益表、details は監査資料、SVG は暗色の売買図です。外部通信は行いません。\n--><main>'+''.join(body)+'</main></body></html>'
    OUT.mkdir(exist_ok=True)
    (OUT/PAGE).write_text(page, encoding='utf-8')
    lines = ['# ９月28日デイの固定候補結果', '', '対象はM3_逆_A00・360分版（V0800）。前回の設定を変更せず、新しい日中データへ適用しました。費用０・指定価格約定。現在API取得なし。', '',
             '| 銘柄 | 固定枚数 | 利益 | 損失 | 収支 | 利益枚数／損失枚数 |', '|---|---:|---:|---:|---:|---:|']
    lines += [f'| {NAMES[r["symbol"]]} | {r["quantity"]}枚 | {yen(r["gross_profit_yen"])} | {yen(-r["gross_loss_yen"])} | {yen(r["net_yen"])} | {r["profit_units"]}／{r["loss_units"]} |' for r in active]
    lines += ['', '両銘柄とも１回の売り取引。全返済済み。', '']
    lines += [f'- {NAMES[t["symbol"]]}：{stamp(t["entry_time"])}に{t["entry_price"]:,.1f}で売り、{stamp(t["exit_time"])}に{t["exit_price"]:,.1f}で返済。360分上限。' for t in main_trades]
    lines += ['', '元の180分版は固定１枚でTOPIX＋29,000円（５取引）、NK＋3,500円（７取引）。今回の360分版はそれぞれ＋9,000円、＋6,000円の改善でした。', '',
              '保存された足で指標を計算し、生板の現在価格で約定を再生する従来の処理を維持。保存足と生板から再集計した足に少数の差がありましたが、再集計足で補助再生しても主候補の売買・収支は両銘柄とも同じでした。', '']
    (OUT/'検証結果.md').write_text('\n'.join(lines), encoding='utf-8')
    (OUT/'README.md').write_text(f'# 00015 ９月28日デイの固定候補検証\n\n最初に [{PAGE}]({PAGE}) を開きます。\n' + '\n1. HTML冒頭の１枚・上限枚数での損益。\n2. ５分足と新規・返済点。\n3. 180分版との比較。必要な場合だけ全取引と監査資料。\n\n再現はプロジェクトルートで `python work/wave_v20/evaluate.py`、独立監査は `python work/wave_v20/audit_day28.py`、表示再生成は `python work/wave_v20/report.py`。新しい最適化や現在API取得を行いません。book/candle原本は読取専用です。\n', encoding='utf-8')
    artifacts = OUT/'資料'
    artifacts.mkdir(exist_ok=True)
    for path in WORK.iterdir():
        if path.is_file() and path.suffix in ['.json', '.py']:
            shutil.copy2(path, artifacts/path.name)
    # ----------------------------------------
    # 過去の作業を残して今回の入口だけを共通索引へ追加する。
    base = OUT.parent
    path = base/'README.md'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00015の[９月28日デイの結果]({FOLDER}/{PAGE})です。M3逆A00・360分版を変更せず追加日に適用しました。**', text, count=1)
    text = text.replace('`00014_M3逆A00の変数と安定性`（最新）','`00014_M3逆A00の変数と安定性`')
    text = re.sub(r'^\| `00015_.*\n','',text,flags=re.M)
    row = f'| `{FOLDER}`（最新） | 固定済み360分版を追加日に適用 | [結果と５分足]({FOLDER}/{PAGE}) | [報告]({FOLDER}/検証結果.md)・[案内]({FOLDER}/README.md) |\n'
    text = text.replace('| --- | --- | --- | --- |\n','| --- | --- | --- | --- |\n'+row,1).replace('`00015_内容`','`00016_内容`')
    path.write_text(text,encoding='utf-8')
    path = base/'index.html'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<!--00015開始-->.*?<!--00015終了-->','',text,flags=re.S)
    text = text.replace('class="task latest"','class="task"').replace('<span class="badge">最新</span>','')
    text = re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新は９月28日デイの固定候補検証。前回の主候補を変更せず、新しいデータへ適用しました。</p>',text,count=1)
    article = f'<!--00015開始--><article class="task latest"><div class="number">作業00015 <span class="badge">最新</span></div><h2>９月28日デイの固定候補検証</h2><p>M3逆A00・360分版の利益・損失・収支。５分足と売買点、180分版との比較。</p><a class="button" href="{FOLDER}/{PAGE}">本日の結果を開く →</a><p><a href="{FOLDER}/README.md">資料案内</a></p></article><!--00015終了-->'
    text = text.replace('</header>','</header>'+article,1)
    text = re.sub(r'<footer>最新作業は.*?</footer>','<footer>最新作業は00015です。次の作業は00016以降へ追加します。</footer>',text,count=1)
    path.write_text(text,encoding='utf-8')
    print(str(OUT/PAGE))


if __name__ == '__main__':
    main()
