"""固定したM3逆A00のセッション台帳を、単独で開ける暗色HTMLへ整える。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
import json
import math
from pathlib import Path


OUT = Path(__file__).resolve().parent
NAMES = {'TOPIX': 'TOPIXミニ', 'NK225': 'NK225マイクロ'}
CAPS = {'TOPIX': 10, 'NK225': 20}
FIELDS = ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units',
          'loss_units', 'zero_units', 'unit_balance', 'cycles']


def money(value: float, signed: bool = False) -> str:
    """機能: 円額を符号と桁区切り付きの文字列へ整える。

    引数: value (float) は円額、signed (bool) は正数への符号付与。
    返り値: 円単位の表示文字列 (str)。
    """
    number = round(value)
    return ('＋' if signed and number > 0 else '−' if number < 0 else '') + f'{abs(number):,}円'


def summed(rows: list[dict]) -> dict:
    """機能: 金額・決済枚数・取引回数を銘柄内で合算する。

    引数: rows (list[dict]) は同じ銘柄の固定１枚記録。
    返り値: 集計値と区間件数 (dict)。
    """
    return {**{key: sum(row[key] for row in rows) for key in FIELDS}, 'count': len(rows)}


def number_class(value: float) -> str:
    """機能: 金額の正負に応じた表示クラスを返す。

    引数: value (float)。返り値: クラス名 (str)。
    """
    return 'positive' if value > 0 else 'negative' if value < 0 else 'muted'


def cells(row: dict) -> str:
    """機能: 利益・損失・収支・枚数・回数の表セルを組み立てる。

    引数: row (dict) は１区間または合計。
    返り値: 表セルのHTML (str)。
    """
    balance = int(row['unit_balance'])
    delta = f'+{balance}' if balance > 0 else str(balance)
    return (f'<td>{money(row["gross_profit_yen"])}</td><td>{money(row["gross_loss_yen"])}</td>'
            f'<td class="{number_class(row["net_yen"])}"><strong>{money(row["net_yen"], True)}</strong></td>'
            f'<td>{int(row["profit_units"])} / {int(row["loss_units"])} / {int(row["zero_units"])}枚</td>'
            f'<td>{delta}枚</td><td>{int(row["cycles"])}回</td>')


def header(first: str) -> str:
    """機能: 共通の集計表見出しを生成する。

    引数: first (str) は先頭列名。返り値: 見出しHTML (str)。
    """
    return f'<thead><tr><th scope="col">{escape(first)}</th><th scope="col">利益</th><th scope="col">損失</th><th scope="col">収支</th><th scope="col">利益 / 損失 / ±0枚数</th><th scope="col">枚数差</th><th scope="col">取引</th></tr></thead>'


def tables(rows: list[dict], symbol: str) -> str:
    """機能: 全セッションと週ごとの集計を初期HTMLへ描く。

    引数: rows (list[dict]) は時刻順記録、symbol (str) は銘柄。
    返り値: JavaScriptなしでも読める２つの表 (str)。
    """
    total = summed(rows)
    body = []
    weeks = {}
    for row in reversed(rows):
        day, part = row['session'].split('_')
        badge = '固定後' if row['phase'] == '条件固定後' else '調整使用'
        style = 'new' if badge == '固定後' else ''
        body.append(f'<tr><th scope="row">{day} {"デイ" if part == "Day" else "ナイト"}<small class="tag {style}">{badge}</small></th>{cells(row)}</tr>')
        start = date.fromisoformat(day)
        monday = start - timedelta(days=start.weekday())
        weeks.setdefault(monday.isoformat(), []).append(row)
    weekly = ''.join(f'<tr><th scope="row">{week}の週<small>{len(group)}セッション収録</small></th>{cells(summed(group))}</tr>' for week, group in sorted(weeks.items(), reverse=True))
    return (f'<div class="scroll"><table aria-label="{NAMES[symbol]}のセッション別損益">{header("セッション（新しい順）")}'
            f'<tbody id="sessions-{symbol}">{"".join(body)}</tbody>'
            f'<tfoot id="total-{symbol}"><tr><th scope="row">表示分の合計</th>{cells(total)}</tr></tfoot></table></div>'
            f'<h3>週別合計</h3><div class="scroll"><table aria-label="{NAMES[symbol]}の週別損益">{header("週の開始日")}'
            f'<tbody id="weeks-{symbol}">{weekly}</tbody></table></div>')


def panel(rows: list[dict], symbol: str) -> str:
    """機能: 銘柄ごとの枚数選択・概要・集計表を作成する。

    引数: rows (list[dict])、symbol (str)。返り値: 銘柄パネルHTML (str)。
    """
    total = summed(rows)
    options = ''.join(f'<option value="{i}">{i}枚</option>' for i in range(1, CAPS[symbol] + 1))
    return f'''<section id="{symbol}" class="panel">
<div class="section-head"><div><h2>{NAMES[symbol]}</h2><p class="muted">片方向の同時保有上限：{CAPS[symbol]}枚</p></div>
<label class="control">１回の保有枚数 <select id="qty-{symbol}" aria-label="{NAMES[symbol]}の１回の保有枚数">{options}</select></label></div>
<div class="summary" id="summary-{symbol}" aria-live="polite">
<div><span>表示分の収支</span><strong class="{number_class(total['net_yen'])}">{money(total['net_yen'], True)}</strong></div>
<div><span>利益合計</span><strong>{money(total['gross_profit_yen'])}</strong></div>
<div><span>損失合計</span><strong>{money(total['gross_loss_yen'])}</strong></div>
<div><span>収録セッション</span><strong>{len(rows)}<small>区間</small></strong></div></div>
<div id="tables-{symbol}">{tables(rows, symbol)}</div></section>'''


def validate(payload: dict) -> None:
    """機能: 重複・混在・欠損値・金額と枚数の計算を検査する。

    引数: payload (dict) は更新スクリプトの出力。返り値: なし (None)。
    """
    assert payload['strategy_id'] == 'V0800'
    seen = set()
    for row in payload['records']:
        key = (row['session'], row['symbol'])
        assert key not in seen, f'同じ区間が重複しています: {key}'
        seen.add(key)
        assert row['method_id'] == 'V0800' and row['quantity'] == 1
        assert row['symbol'] in CAPS and row['phase'] in ('調整に使用', '条件固定後')
        assert all(isinstance(row[field], (int, float)) and math.isfinite(row[field]) for field in FIELDS)
        assert row['gross_profit_yen'] >= 0 and row['gross_loss_yen'] >= 0
        assert abs(row['gross_profit_yen'] - row['gross_loss_yen'] - row['net_yen']) < .01
        assert row['profit_units'] - row['loss_units'] == row['unit_balance']
        assert row['profit_units'] + row['loss_units'] + row['zero_units'] == row['cycles']


def main() -> None:
    """機能: 固定１枚台帳を検査し、最新データを内蔵した損益HTMLを生成する。

    引数: なし。返り値: なし (None)。ネットワーク通信は行わない。
    """
    payload = json.loads((OUT / 'セッション損益.json').read_text(encoding='utf-8'))
    validate(payload)
    rows = sorted(payload['records'], key=lambda row: (row['session'], row['symbol']))
    sessions = sorted({row['session'] for row in rows})
    span = f'{sessions[0][:10]} 〜 {sessions[-1][:10]} ／ {len(sessions)}セッション' if sessions else '確定したセッションはまだありません'
    pending = payload.get('pending', [])
    pending_html = ''
    if pending:
        pending_html = '<aside class="pending"><strong>集計待ち</strong><ul>' + ''.join(f'<li>{escape(str(item.get("session", "")))}：{escape(str(item.get("reason", item)))}</li>' for item in pending) + '</ul></aside>'
    content = ''.join(panel([row for row in rows if row['symbol'] == symbol], symbol) for symbol in CAPS)
    template = (OUT / '損益テンプレート.html').read_text(encoding='utf-8')
    embedded = json.dumps(rows, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    updated = datetime.fromisoformat(payload['updated_at']).strftime('%Y/%m/%d %H:%M:%S（日本時間）')
    page = template.replace('%%UPDATED%%', escape(updated)).replace('%%PERIOD%%', span)
    page = page.replace('%%PENDING%%', pending_html).replace('%%PANELS%%', content).replace('%%DATA%%', embedded)
    temporary = OUT / '損益.html.tmp'
    temporary.write_text(page, encoding='utf-8')
    temporary.replace(OUT / '損益.html')
    print(f'損益.htmlを更新しました：{len(sessions)}セッション、{len(rows)}集計。')


if __name__ == '__main__':
    main()
