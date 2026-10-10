"""追加２セッションの固定条件検証を記録し、調査一覧へ追加する。"""

from __future__ import annotations

from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
import shutil


WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
TARGET = ROOT / 'M3_逆_A00_360分版'
FOLDER = '00017_9月28日夜と29日昼の固定候補検証'
OUT = ROOT / 'アルゴリズム調査' / FOLDER
PAGE = '追加２セッションの結果.html'
SESSIONS = ['2026-09-28_Night', '2026-09-29_Day']
NAMES = {'TOPIX': 'TOPIXミニ', 'NK225': 'NK225マイクロ'}
CAPS = {'TOPIX': 10, 'NK225': 20}
FIELDS = ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units', 'cycles']


def read(path: Path) -> object:
    """機能: UTF-8の検証資料を読み込む。

    引数: path (Path)。返り値: JSONの内容 (object)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def yen(value: float, signed: bool = False) -> str:
    """機能: 円額に桁区切りと符号を付ける。

    引数: value (float)、signed (bool)。返り値: 金額表記 (str)。
    """
    return ('＋' if signed and value > 0 else '−' if value < 0 else '') + f'{abs(value):,.0f}円'


def label(session: str) -> str:
    """機能: セッション識別子を日本語の表示名へ変換する。

    引数: session (str)。返り値: セッション表示名 (str)。
    """
    return session[:10] + (' ナイト' if session.endswith('Night') else ' デイ')


def sum_rows(rows: list[dict]) -> dict:
    """機能: 金額と決済枚数を同じ銘柄内で合計する。

    引数: rows (list[dict])。返り値: 合計値 (dict)。
    """
    return {field: sum(row[field] for row in rows) for field in FIELDS}


def cells(row: dict) -> str:
    """機能: 固定１枚の損益・枚数と上限枚数の収支を表にする。

    引数: row (dict)。返り値: 表のセルHTML (str)。
    """
    cls = 'gain' if row['net_yen'] > 0 else 'loss' if row['net_yen'] < 0 else ''
    return (f'<td>{NAMES[row["symbol"]]}</td><td>{yen(row["gross_profit_yen"])}</td>'
            f'<td>{yen(row["gross_loss_yen"])}</td><td class="{cls}"><strong>{yen(row["net_yen"], True)}</strong></td>'
            f'<td>{row["profit_units"]} / {row["loss_units"]} / {row["zero_units"]}枚</td>'
            f'<td>{row["cycles"]}回</td><td class="{cls}">{yen(row["net_yen"] * CAPS[row["symbol"]], True)}</td>')


def main() -> None:
    """機能: 新規分だけを抽出し、初回結果・検証資料・索引を保存する。

    引数: なし。返り値: なし (None)。原本や売買条件の変更は行わない。
    """
    payload = read(TARGET / 'セッション損益.json')
    previous = read(WORK / '実行前_セッション損益.json')
    lookup = {(r['session'], r['symbol']): r for r in payload['records']}
    assert len(payload['records']) == 26 and not payload['pending']
    assert all(lookup[(r['session'], r['symbol'])] == r for r in previous['records'])
    assert payload['update_counts'] == dict(reused=11, seeded=0, replayed=2)
    for name in ['固定条件.json', '固定条件の照合.json']:
        assert (TARGET / name).read_bytes() == (WORK / ('実行前_' + name)).read_bytes()
    rows = [lookup[(session, symbol)] for session in SESSIONS for symbol in NAMES]
    totals = {symbol: sum_rows([r for r in rows if r['symbol'] == symbol]) for symbol in NAMES}
    after = {symbol: sum_rows([r for r in payload['records'] if r['symbol'] == symbol and r['phase'] == '条件固定後']) for symbol in NAMES}
    all_totals = {symbol: sum_rows([r for r in payload['records'] if r['symbol'] == symbol]) for symbol in NAMES}
    trades = [t for session in SESSIONS for t in read(ROOT / 'work/wave_v21' / session / '再生記録.json')['trades']]
    status = dict(合格=True, 過去11セッション不変=True, 固定条件とコード照合不変=True,
                  追加セッション=SESSIONS, 新規集計数=len(rows), 新規取引数=len(trades),
                  API取得数=0, パラメータ再探索数=0, 追加合計=totals, 条件固定後合計=after, 全期間合計=all_totals)
    (WORK / '更新前後の確認.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    # ----------------------------------------
    # 作業時点の結果を保存し、継続台帳の次回更新から独立させる。
    OUT.mkdir(parents=True, exist_ok=True)
    archive = OUT / '資料'
    archive.mkdir(exist_ok=True)
    for name in ['セッション損益.json', '固定条件.json', '固定条件の照合.json']:
        shutil.copy2(TARGET / name, archive / name)
    for session in SESSIONS:
        shutil.copy2(ROOT / 'work/wave_v21' / session / '再生記録.json', archive / (session + '_再生記録.json'))
    for path in WORK.iterdir():
        if path.is_file() and path.suffix in ('.py', '.js', '.json'):
            shutil.copy2(path, archive / path.name)
    # ----------------------------------------
    # 冒頭は追加分の損益だけを短く示し、取引明細と検査は折り畳む。
    header = '<thead><tr><th>セッション</th><th>銘柄</th><th>利益</th><th>損失</th><th>収支</th><th>利益 / 損失 / ±0枚数</th><th>取引</th><th>上限枚数の収支</th></tr></thead>'
    table_rows = ''.join(f'<tr><th>{label(r["session"])}</th>{cells(r)}</tr>' for r in rows)
    total_rows = ''.join(f'<tr><th>追加２セッション合計</th>{cells(dict(total, symbol=symbol))}</tr>' for symbol, total in totals.items())
    intro = '28日ナイトは両銘柄とも黒字、29日デイは両銘柄とも赤字でした。追加２セッションの合計は両銘柄とも黒字です。'
    explanation = '29日デイは両銘柄とも買いのみ。下落が続く間に損切りを繰り返し、後半の反発で取り返しても赤字が残りました。NKは７敗後の最後の１勝（＋6,500円）で損失の大半を回収しています。'
    cumulative = '条件固定後３セッションの収支：' + '、'.join(f'{NAMES[s]} {yen(v["net_yen"], True)}' for s, v in after.items()) + '。'
    cumulative_all = '全13セッションの収支：' + '、'.join(f'{NAMES[s]} {yen(v["net_yen"], True)}' for s, v in all_totals.items()) + '。いずれも固定１枚。'
    trade_rows = ''.join('<tr>' + ''.join(f'<td>{escape(value)}</td>' for value in [label(t['session']), NAMES[t['symbol']], t['side'], datetime.fromisoformat(t['entry_time']).strftime('%m/%d %H:%M:%S'), f'{t["entry_price"]:,.1f}', datetime.fromisoformat(t['exit_time']).strftime('%m/%d %H:%M:%S'), f'{t["exit_price"]:,.1f}', yen(t['net_yen'], True), t['reason']]) + '</tr>' for t in trades)
    audit_links = ''.join(f'<li><a href="資料/{name}">{text}</a></li>' for name, text in [
        ('入力監査.json', '追加データの確認'), ('損益監査.json', '売買明細からの独立検算'),
        ('更新前後の確認.json', '条件・既存結果が変わっていないことの確認'), ('表示監査.json', '損益HTMLの表示確認'),
        ('再集計足の補助確認.json', '生板から再集計した足による補助再生')])
    css = 'body{margin:0;background:#0b111c;color:#e5edf8;font:15px/1.75 "Yu Gothic UI",Meiryo,sans-serif}main{max-width:1250px;margin:auto;padding:32px 22px}h1{font-size:28px}h2{font-size:20px}a{color:#91c8ff}.note{color:#aebed2;font-size:13px}.box,details{background:#121e2e;border:1px solid #2c405b;border-radius:10px;padding:20px;margin:20px 0}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;white-space:nowrap;text-align:right;font-variant-numeric:tabular-nums}td,th{padding:10px 12px;border-bottom:1px solid #30415a}th:first-child{text-align:left}thead{font-size:12px;color:#b3c8e2}tfoot{background:#1d2e44;font-weight:bold}.gain{color:#8eecc7}.loss{color:#ffa3a3}summary{cursor:pointer}a:focus-visible,summary:focus-visible{outline:2px solid #f2c577;outline-offset:3px}'
    page = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>追加２セッションの固定候補検証</title><style>{css}</style></head><body>
<!--
[コンポーネント概要]
main は9月28日ナイトと29日デイの固定条件による損益を示します。
最初の表は固定１枚の結果、末尾の列だけはTOPIX10枚・NK20枚の比例換算です。
details に全売買明細と検算資料を格納し、過去の損益台帳は変更せず当時の値を資料へ保存します。
--><main><p class="note">作業00017 ／ M3_逆_A00・360分版（V0800）</p><h1>追加２セッションの結果</h1><p>{intro}</p>
<p><a href="../../M3_逆_A00_360分版/損益.html">更新済みの損益台帳を開く →</a></p>
<div class="box"><h2>固定１枚の損益</h2><div class="scroll"><table>{header}<tbody>{table_rows}</tbody><tfoot>{total_rows}</tfoot></table></div>
<p class="note">上限枚数＝TOPIXミニ10枚／NK225マイクロ20枚。利益・損失枚数は累計決済数。費用０・指定価格約定。全取引はセッション内で返済しました。</p></div>
<p>{explanation}</p><p>{cumulative}</p><p class="note">{cumulative_all}最初の10セッションは条件調整に使用した期間です。</p>
<details><summary>全28取引の新規・返済位置</summary><div class="scroll"><table><thead><tr><th>セッション</th><th>銘柄</th><th>方向</th><th>新規時刻</th><th>新規価格</th><th>返済時刻</th><th>返済価格</th><th>収支</th><th>返済理由</th></tr></thead><tbody>{trade_rows}</tbody></table></div></details>
<details><summary>データと検算</summary><p>２銘柄・２セッションを固定条件のまま生板価格で再生。既存11セッションは不変です。現在セッションAPI取得・パラメータ再探索は行っていません。</p><p>保存足と生板から再集計した足には一部OHLCの差がありましたが、補助再生でも全売買の時刻・価格・理由・収支は一致しました。夜間に足のない時間は生板の価格時刻にも存在せず、無約定か配信欠損かは判別できません。足の補完は行っていません。</p><ul>{audit_links}</ul></details>
<p class="note"><a href="README.md">資料案内</a> · <a href="検証結果.md">短い報告書</a> · <a href="../index.html">調査一覧</a></p></main></body></html>'''
    (OUT / PAGE).write_text(page, encoding='utf-8')
    markdown = ['# 追加２セッションの固定候補検証', '', intro, '', 'M3_逆_A00・360分版（V0800）の条件変更なし。費用０・指定価格約定。金額は固定１枚。', '',
                '| セッション | 銘柄 | 利益 | 損失 | 収支 | 利益／損失／±0枚数 |', '|---|---|---:|---:|---:|---:|']
    markdown += [f'| {label(r["session"])} | {NAMES[r["symbol"]]} | {yen(r["gross_profit_yen"])} | {yen(r["gross_loss_yen"])} | {yen(r["net_yen"], True)} | {r["profit_units"]}／{r["loss_units"]}／{r["zero_units"]} |' for r in rows]
    markdown += ['', explanation, '', cumulative, '', cumulative_all, '', '全28取引をセッション内に返済。元の11セッション・条件ファイルは不変。現在API取得０回、条件再探索０回。', '', '保存足と生板再集計足の少数の差も確認し、再集計足による補助再生で全売買・収支の一致を確認。夜間に価格時刻のない分足は補完していません。']
    (OUT / '検証結果.md').write_text('\n'.join(markdown), encoding='utf-8')
    (OUT / 'README.md').write_text(f'# 00017 9月28日夜と29日昼の固定候補検証\n\n最初に [{PAGE}]({PAGE}) を開きます。\n\n1. 追加２セッションの利益・損失・収支。\n2. 必要なら折り畳まれた全28取引と監査資料。\n3. 全期間は [継続損益台帳](../../M3_逆_A00_360分版/損益.html)。\n\n[短い報告書](検証結果.md)／[この時点の固定１枚台帳](資料/セッション損益.json)。\n\n再生はプロジェクトルートで `python "M3_逆_A00_360分版/更新.py"`。この作業フォルダには13セッション時点の記録を保存しており、以降の台帳更新でも上書きしません。\n', encoding='utf-8')
    # ----------------------------------------
    # 過去の作業を残し、今回の記録を調査一覧の先頭へ加える。
    base = OUT.parent
    path = base / 'README.md'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00017の[追加２セッションの検証]({FOLDER}/{PAGE})です。9月28日夜・29日昼を固定条件で再生し、[継続損益台帳](../M3_逆_A00_360分版/損益.html)も13セッションへ更新しました。**', text, count=1)
    text = text.replace('`00016_M3逆360分版の継続損益台帳`（最新）', '`00016_M3逆360分版の継続損益台帳`')
    text = re.sub(r'^\| `00017_.*\n', '', text, flags=re.M)
    row = f'| `{FOLDER}`（最新） | 条件を固定した追加２セッションの損益 | [追加分の結果]({FOLDER}/{PAGE}) | [報告]({FOLDER}/検証結果.md)・[資料案内]({FOLDER}/README.md) |\n'
    text = text.replace('| --- | --- | --- | --- |\n', '| --- | --- | --- | --- |\n' + row, 1).replace('`00017_内容`', '`00018_内容`')
    path.write_text(text, encoding='utf-8')
    path = base / 'index.html'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<!--00017開始-->.*?<!--00017終了-->', '', text, flags=re.S)
    text = text.replace('class="task latest"', 'class="task"').replace('<span class="badge">最新</span>', '')
    text = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新は9月28日夜・29日昼の固定条件検証。継続損益台帳も13セッションへ更新しました。</p>', text, count=1)
    article = f'<!--00017開始--><article class="task latest"><div class="number">作業00017 <span class="badge">最新</span></div><h2>9月28日夜・29日昼の固定候補検証</h2><p>追加２セッションの利益・損失・収支と全売買明細。</p><a class="button" href="{FOLDER}/{PAGE}">追加分の結果を開く →</a><p><a href="../M3_逆_A00_360分版/損益.html">継続損益台帳</a> · <a href="{FOLDER}/README.md">資料案内</a></p></article><!--00017終了-->'
    text = text.replace('</header>', '</header>' + article, 1)
    text = re.sub(r'<footer>最新作業は.*?</footer>', '<footer>最新作業は00017です。次の作業は00018以降へ追加します。</footer>', text, count=1)
    path.write_text(text, encoding='utf-8')
    print(str(OUT / PAGE))


if __name__ == '__main__':
    main()
