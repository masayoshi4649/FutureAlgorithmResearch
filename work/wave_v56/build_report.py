"""価格形成の短い説明と、保存された観測診断を静的HTMLへまとめる。"""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / 'アルゴリズム調査/00053_価格が動く理由と板データの再点検'


def read(path: Path) -> dict:
    """機能: 保存済みJSONを読み込む。

    引数: path(Path)。返り値: JSON内容(dict)。通信・売買はしない。
    """
    return json.loads(path.read_text(encoding='utf8'))


def main() -> None:
    """機能: 原理、観測限界、既存取引の診断を静的HTMLに保存する。

    引数: なし。返り値: なし(None)。新しい条件や損益は計算しない。
    """
    book = read(HERE / 'diagnosis/板の観測可能性.json')
    trades = read(HERE / 'diagnosis/入口途中出口の診断.json')
    correction = read(HERE / 'measurement/表示範囲補正とOFIの全数監査.json')
    quotes = []
    for symbol, d in book['気配と最終価格の比較'].items():
        quotes.append('<tr><td>' + html.escape(symbol) + '</td>'
                      f'<td>{d["最終価格変化数"]:,}</td>'
                      f'<td>{d["最終価格変化で両最良気配不変数"]:,}</td>'
                      f'<td>{100*d["最終価格変化中の両最良気配不変割合"]:.1f}%</td></tr>')
    candidate = next(m for m in trades['手法別'] if m['手法ID'] == 'P03_W05')
    removed = []
    for symbol, d in correction['銘柄別'].items():
        full = d['全比較']
        removed.append('<tr><td>' + html.escape(symbol) + '</td>'
                       f'<td>{full["bid_best_disappeared"]:,.0f}</td>'
                       f'<td>{full["ask_best_disappeared"]:,.0f}</td></tr>')
    entries = []
    for symbol, d in candidate['銘柄別'].items():
        full = d['全体']
        first = full['1W先着内訳']
        entries.append('<tr><td>' + html.escape(symbol) + '</td>'
                       f'<td>{full["組数"]:,}</td><td>{first["順行先着"]:,}</td>'
                       f'<td>{first["逆行先着"]:,}</td><td>{first["双方未観測"]:,}</td></tr>')
    # ----------------------------------------
    # 詳細な監査は完成後に追記可能とし、未完了の結果を合格と表示しない。
    audit_path = HERE / 'review/レポート追記.json'
    audit = read(audit_path) if audit_path.exists() else {'status': '売買代金と出来高の同期を独立点検中です。完了結果は後から追記します。', 'items': []}
    audit_html = '<p>' + html.escape(audit['status']) + '</p>'
    for item in audit.get('items', []):
        audit_html += '<p>' + html.escape(item) + '</p>'
    for link in audit.get('links', []):
        audit_html += '<p><a href="' + html.escape(link['href'], quote=True) + '">' + html.escape(link['label']) + '</a></p>'
    template = (HERE / 'report_template.html').read_text(encoding='utf8')
    content = template.replace('__QUOTE_ROWS__', ''.join(quotes)).replace('__ENTRY_ROWS__', ''.join(entries)).replace('__REMOVED_ROWS__', ''.join(removed)).replace('__AUDIT__', audit_html)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / '価格が動く理由と板データ.html'
    path.write_text(content, encoding='utf8')
    meta = {'主HTML': str(path), 'SHA256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'バイト数': path.stat().st_size, '動的スクリプト': 0, '現在API取得': 0, '新規戦略選択': False}
    (OUTPUT / '生成記録.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(meta, ensure_ascii=True))


if __name__ == '__main__':
    main()
