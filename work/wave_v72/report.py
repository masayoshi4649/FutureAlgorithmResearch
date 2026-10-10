"""T1L1_R01の固定結果を、銘柄別の金額会計で単独レポートにする。"""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'アルゴリズム調査/00069_T1L1_R01の全セッションと金額評価'
MAIN = 'T1L1_R01の全セッション結果.html'
SYMBOLS = ('TOPIX', 'NK225')
FIELDS = ('profit', 'loss', 'net', 'gross', 'fees', 'wins', 'losses', 'trades',
          'winning_lots', 'losing_lots', 'flat_lots', 'campaign_profit', 'campaign_loss',
          'campaigns', 'campaign_wins', 'campaign_losses', 'campaign_flats')


def load(path: Path) -> object:
    """機能: UTF-8の保存JSONを読み取る。

    引数: path(Path)。返り値: JSONの保存内容(object)。
    """
    return json.loads(path.read_text(encoding='utf8'))


def save(path: Path, value: object) -> None:
    """機能: 今回の作業内へ日本語を維持したJSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE) or path.resolve().is_relative_to(OUT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def enrich(row: dict) -> dict:
    """機能: 同一銘柄の金額から損失割合と利益・損失比を計算する。

    引数: row(dict)。返り値: 金額指標を付けた会計(dict)。
    """
    a = dict(row)
    p, loss = a['campaign_profit'], a['campaign_loss']
    wins, losses, count = a['campaign_wins'], a['campaign_losses'], a['campaigns']
    a.update(money_loss_share=loss/(p+loss) if p+loss else None,
             profit_loss_ratio=p/loss if loss else None,
             loss_profit_ratio=loss/p if p else None,
             count_loss_rate=losses/count if count else None,
             average_win=p/wins if wins else None,
             average_loss=loss/losses if losses else None,
             average_payoff=(p/wins)/(loss/losses) if wins and losses else None)
    assert abs(p-loss-a['net']) < 1e-6
    return a


def aggregate(rows: list[dict], symbol: str, sessions: list[str]) -> dict:
    """機能: 指定期間を銘柄ごとに合計し、合計金額から比率を再計算する。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 合計会計(dict)。
    """
    subset = [r for r in rows if r['symbol'] == symbol and r['session'] in sessions]
    a = {k: sum(r[k] for r in subset) for k in FIELDS}
    a.update(symbol=symbol, active_sessions=sum(r['campaigns'] > 0 for r in subset),
             positive_sessions=sum(r['net'] > 0 for r in subset),
             negative_sessions=sum(r['net'] < 0 for r in subset),
             max_long=max((r['max_long'] for r in subset), default=0),
             max_short=max((r['max_short'] for r in subset), default=0),
             max_campaign_loss=max((r['max_campaign_loss'] for r in subset), default=0))
    return enrich(a)


def embedded(path: Path) -> dict:
    """機能: 既存HTMLに埋め込まれた固定図表データを読み取る。

    引数: path(Path)。返り値: 埋込データ(dict)。
    """
    match = re.search(r'<script id="report-data" type="application/json">(.*?)</script>',
                      path.read_text(encoding='utf8'), flags=re.S)
    assert match, path
    return json.loads(match.group(1))


def main() -> None:
    """機能: 旧28場と仕様を変えない追加再生を統合し、HTMLと証跡を生成する。

    引数: なし。返り値: なし(None)。入力原本・過去の成果は変更しない。
    """
    oldpath = ROOT / 'work/wave_v70/results/T1L1_R01.json'
    extra_path = HERE / 'replay/T1L1_R01_追加セッション.json'
    original = load(oldpath)
    extra = load(extra_path)
    assert original['config'] == extra['config'], '追加場の設定変更'
    rows = sorted(original['rows'] + extra['rows'], key=lambda r: (r['session'], r['symbol']))
    sessions = sorted(set(r['session'] for r in rows))
    old_sessions = sorted(set(r['session'] for r in original['rows']))
    extra_sessions = sorted(set(r['session'] for r in extra['rows']))
    assert len(sessions) == 29 and len(rows) == 58
    assert not set(old_sessions) & set(extra_sessions)
    for symbol in SYMBOLS:
        assert {r['session'] for r in rows if r['symbol'] == symbol} == set(sessions)
        a = aggregate(original['rows'], symbol, old_sessions)
        for k in FIELDS:
            assert a[k] == original['periods']['全28'][symbol][k], (symbol, k)
    # ----------------------------------------
    # 既存の公開済み売買時刻・五分足と追加場の固定表示データを接続する。
    old_public = ROOT / 'アルゴリズム調査/00067_両建て保険と途中管理/両建て保険と途中管理の説明と損益.html'
    old_display = embedded(old_public)
    old_method = next(m for m in old_display['methods'] if m['id'] == 'T1L1_R01')
    additional = load(HERE / 'replay/T1L1_R01_追加表示データ.json')
    orders = dict(old_method['orders'])
    bars = dict(old_display['bars'])
    assert not set(orders) & set(additional['orders'])
    orders.update(additional['orders'])
    bars.update(additional['bars'])
    assert len(orders) == len(bars) == 58
    groups = {}
    for session in sessions:
        day = date.fromisoformat(session[:10])
        monday = day-timedelta(days=day.weekday())
        groups.setdefault(monday.isoformat(), []).append(session)
    periods = {name: {s: aggregate(rows, s, keys) for s in SYMBOLS} for name, keys in
               [('既存28', old_sessions), ('追加デイ', extra_sessions), ('全29', sessions)]}
    weeks = {s: [dict(aggregate(rows, s, keys), label=f'{monday}週', sessions=keys)
                 for monday, keys in groups.items()] for s in SYMBOLS}
    data = dict(id='T1L1_R01', config=original['config'], sessions=sessions,
                old_sessions=old_sessions, extra_sessions=extra_sessions,
                rows=[enrich(r) for r in rows], periods=periods, weeks=weeks, orders=orders, bars=bars,
                金額損失割合の定義='費用後総損失÷（費用後総利益＋費用後総損失）。損失は絶対額。',
                利益損失比の定義='費用後総利益÷費用後総損失。銘柄別に計算。',
                率の集計='場ごとの率を平均せず、期間内の利益と損失を合計して再計算。',
                API取得数=0, 実注文数=0)
    # ----------------------------------------
    # 出力するHTMLと会計JSONは同じ固定データを参照する。
    OUT.mkdir(parents=True, exist_ok=True)
    template = (HERE / 'template.html').read_text(encoding='utf8')
    assert template.count('__DATA__') == 1
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
    (OUT / MAIN).write_text(template.replace('__DATA__', payload), encoding='utf8')
    save(OUT / '銘柄別の全セッション会計.json', data)
    proof = dict(対象=data['id'], 保存場数=len(sessions), 銘柄数=2, セッション口座数=len(rows),
                 既存条件変更なし=True, 同銘柄金額だけで計算=True,
                 API取得数=0, 実注文数=0,
                 入力SHA256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (oldpath, extra_path, old_public, HERE/'replay/T1L1_R01_追加表示データ.json')},
                 HTML_SHA256=hashlib.sha256((OUT/MAIN).read_bytes()).hexdigest(),
                 全29金額={s: periods['全29'][s] for s in SYMBOLS})
    save(HERE / '公開会計.json', proof)
    print(json.dumps(dict(保存場数=len(sessions), 全29={s: {k: periods['全29'][s][k]
                     for k in ('campaign_profit', 'campaign_loss', 'net', 'money_loss_share', 'profit_loss_ratio')}
                     for s in SYMBOLS}), ensure_ascii=False))


if __name__ == '__main__':
    main()
