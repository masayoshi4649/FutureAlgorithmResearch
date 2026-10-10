"""状態の転換から一度だけ発注する検証を、日本語の報告と図解へまとめる。"""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'work' / 'wave_v9'
DEST = ROOT / 'アルゴリズム調査' / '00004_生板を使う売買の検証' / '転換点からのエントリー'
SESSIONS = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day',
            '2026-09-22_Night', '2026-09-23_Day', '2026-09-23_Night']
SYMBOLS = ['NK225', 'TOPIX']
MULTIPLIERS = {'NK225': 1000, 'TOPIX': 10000}


def read_json(path: Path, default: object = None) -> object:
    """機能: UTF-8のJSONを読み、未作成時には指定値を返す。

    引数: path (Path)、default (object)。返り値: 保存値または指定値 (object)。
    """
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default


def money(value: float, signed: bool = False) -> str:
    """機能: 円を万円表記へ変換する。

    引数: value (float)、signed (bool)。返り値: 金額文字列 (str)。
    """
    value = float(value) / 10000
    if abs(value) < 0.000001:
        value = 0.0
    return f'{value:+,.1f}' if signed else f'{value:,.1f}'


def aggregate(frame: pd.DataFrame) -> list[dict]:
    """機能: 群と銘柄を単位として確定損益と未返済評価を集計する。

    引数: frame (DataFrame)。返り値: 集計済みの辞書配列 (list[dict])。
    """
    columns = ['利益円', '損失円', '収支円', '費用倍収支円', '取引数', '勝ち数', '未返済数', '評価損益円']
    if frame.empty:
        return []
    return json.loads(frame.groupby(['群', '銘柄'], sort=False)[columns].sum().reset_index().to_json(orient='records', force_ascii=False))


def html_table(rows: list[dict], session: bool = False) -> str:
    """機能: 確定利益・損失・差引・未返済を別々に示すHTML表を作る。

    引数: rows (list[dict])、session (bool)。返り値: HTML (str)。
    """
    if not rows:
        return '<p>該当する結果はありません。</p>'
    headers = ['セッション'] if session else []
    headers += ['方式の群', '銘柄', '利益', '損失', '差引', '勝ち／返済済', '追加費用４tickの差引', '未返済／評価損益']
    lines = []
    for row in rows:
        cells = [html.escape(str(row.get('セッション', '')))] if session else []
        cells += [html.escape(str(row.get('群', ''))), row['銘柄'], money(row['利益円']), money(row['損失円']), money(row['収支円'], True)]
        count, wins = int(row['取引数']), int(row['勝ち数'])
        cells += [f'{wins} / {count}' + (f'（{100*wins/count:.1f}%）' if count else ''), money(row['費用倍収支円'], True), f'{int(row["未返済数"])} / {money(row["評価損益円"], True)}']
        lines.append('<tr>' + ''.join(f'<td>{value}</td>' for value in cells) + '</tr>')
    return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{h}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join(lines) + '</tbody></table></div>'


def md_table(rows: list[dict]) -> str:
    """機能: 確定損益の要点をMarkdown表へ変換する。

    引数: rows (list[dict])。返り値: Markdown (str)。
    """
    lines = ['| 群 | 銘柄 | 利益万円 | 損失万円 | 差引万円 | 勝ち/返済済 | 費用４tick差引万円 | 未返済/評価万円 |',
             '|---|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f'| {r["群"]} | {r["銘柄"]} | {money(r["利益円"])} | {money(r["損失円"])} | {money(r["収支円"], True)} | {int(r["勝ち数"])}/{int(r["取引数"])} | {money(r["費用倍収支円"], True)} | {int(r["未返済数"])}/{money(r["評価損益円"], True)} |')
    return '\n'.join(lines)


def chart_candles() -> dict:
    """機能: 位置図解用の確定５分足を保存データから読む。

    引数: なし。返り値: 銘柄・セッション別の時刻とOHLC (dict)。
    """
    result = {}
    for symbol in SYMBOLS:
        for session in SESSIONS:
            source = ROOT / 'work' / 'wave_v7' / 'live' if session == SESSIONS[-1] else ROOT
            frame = pd.read_csv(source / 'candle_5min' / symbol / f'{session}.csv')
            frame = frame[frame.closed.astype(str).str.lower().eq('true')]
            result[f'{symbol}|{session}'] = [[pd.Timestamp(r.time).timestamp(), r.open, r.high, r.low, r.close] for r in frame.itertuples()]
    return result


def chart_averages() -> dict:
    """機能: 判定と同じ観測時点の移動平均を可視化資料から取り出す。

    引数: なし。返り値: 銘柄・セッション別の観測時刻とEMA (dict)。
    """
    data = read_json(OUT / '可視化移動平均.json', {})
    if data:
        return data
    from turning_signals import load_price_frame
    result = {}
    for symbol in SYMBOLS:
        for session in SESSIONS:
            frame = load_price_frame(session, symbol)
            values = frame[['ema3', 'ema8', 'ema21']].dropna()
            result[f'{symbol}|{session}'] = [[stamp.timestamp(), *row] for stamp, row in zip(values.index, values.to_numpy())]
    return result


def compact_trades(rows: list[dict]) -> list[dict]:
    """機能: 売買記録から転換検知・実約定・返済の図解用値を作る。

    引数: rows (list[dict])。返り値: 図解用取引 (list[dict])。
    """
    result = []
    for row in rows:
        signal_time = row.get('signal_time_s', row.get('order_time_s', row.get('event_time_s', row['entry_time_s'])))
        signal_price = row.get('signal_price', row.get('order_price', row['entry_price']))
        result.append(dict(method=row['方式'], symbol=row['銘柄'], session=row['セッション'], side=row['side'],
            origin=row.get('評価区分', '保存済み資料'),
            signal=signal_time, sp=signal_price, event=row.get('event_nonce', row.get('event_id', '')),
            condition=row.get('condition_time_s', signal_time),
            entry=row['entry_time_s'], ep=row['entry_price'], exit=row.get('exit_time_s', row.get('mark_time_s')),
            xp=row.get('exit_price', row.get('mark_price')), closed=row['closed'],
            net=row['net_points'] * MULTIPLIERS[row['銘柄']], atr=row['atr'],
            duration=row['duration_min'], reason=row.get('exit_reason', '未返済・評価値'),
            mfe=row.get('max_favorable', 0),
            giveback=row.get('max_favorable', 0) - row['side'] * (row.get('exit_price', row.get('mark_price')) - row['entry_price'])))
    return result


def selected_methods(finalists: dict) -> dict:
    """機能: 既知期間の選択記録から採用方式IDを取り出す。

    引数: finalists (dict)。返り値: 群をキーとする方式ID (dict)。
    """
    result = {}
    for group, item in finalists.items():
        adopted = item.get('採用') if isinstance(item, dict) else item
        if isinstance(adopted, dict):
            result[group] = adopted.get('方式', adopted.get('id'))
        elif isinstance(adopted, str):
            result[group] = adopted
    return {key: value for key, value in result.items() if value}


def wave_records(trades: list[dict], selected: dict) -> list[dict]:
    """機能: 指定された既知の４波と同方向の保有時間を事後照合する。

    引数: trades (list[dict])、selected (dict)。返り値: 波別照合結果 (list[dict])。
    """
    waves = [('9/21デイ ロング', SESSIONS[0], '2026-09-21 10:45', '2026-09-21 15:35', 1),
        ('9/22デイ ショート', SESSIONS[2], '2026-09-22 09:20', '2026-09-22 11:45', -1),
        ('9/22ナイト ロング', SESSIONS[3], '2026-09-23 00:40', '2026-09-23 03:20', 1),
        ('9/23デイ ショート', SESSIONS[4], '2026-09-23 09:05', '2026-09-23 11:15', -1)]
    records = []
    for name, session, start_text, end_text, side in waves:
        start, end = [pd.Timestamp(value, tz='Asia/Tokyo').timestamp() for value in [start_text, end_text]]
        for group, method in selected.items():
            for symbol in SYMBOLS:
                matches = sorted([t for t in trades if t['method'] == method and t['session'] == session and t['symbol'] == symbol and t['side'] == side and t['entry'] < end and t['exit'] > start], key=lambda t: t['entry'])
                held = sum(max(0, min(end, t['exit']) - max(start, t['entry'])) for t in matches)
                first = matches[0] if matches else None
                stamp = lambda value: pd.Timestamp(value, unit='s', tz='Asia/Tokyo').strftime('%H:%M:%S')
                records.append(dict(指定波=name, 群=group, 銘柄=symbol, 方式=method,
                    最初の検知=stamp(first['signal']) if first else 'なし', 最初の新規=stamp(first['entry']) if first else 'なし',
                    同方向保有割合=round(100 * held / (end - start), 2), 波内保有分=round(held / 60, 2), 重なる取引数=len(matches)))
    return records


def generic_table(records: list[dict], keys: list[str] | None = None) -> str:
    """機能: 指定列をもつ日本語の比較表を作る。

    引数: records (list[dict])、keys (list[str]|None)。返り値: HTML (str)。
    """
    if not records:
        return '<p>該当する結果はありません。</p>'
    keys = keys or list(records[0])
    return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{html.escape(key)}</th>' for key in keys) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + html.escape(str(row.get(key, ''))) + '</td>' for key in keys) + '</tr>' for row in records) + '</tbody></table></div>'


def copy_materials() -> list[dict]:
    """機能: 検証コード・出力・依存入力を同じ相対構造で複製する。

    引数: なし。返り値: 複製資料のパス・SHA256一覧 (list[dict])。
    """
    archive = DEST / '資料'
    targets = [p for p in OUT.rglob('*') if p.is_file() and p.suffix in ['.py', '.md', '.json', '.csv', '.npz', '.jsonl'] and '__pycache__' not in p.parts and 'live_fixture_saved' not in p.parts]
    v8 = ROOT / 'work' / 'wave_v8'
    targets += [v8 / name for name in ['model.py', 'raw_features.py', 'cross_research.py', '全条件セッション集計.csv']]
    targets += [ROOT / 'work' / 'wave_v7' / 'fetch_once.py', ROOT / 'work' / 'wave_v7' / 'live' / '取得記録.json']
    targets += [p for p in (v8 / 'features').glob('*') if p.suffix in ['.npz', '.csv', '.json']]
    targets.append(ROOT / 'アルゴリズム調査' / '00001_波検知と売買ポイントの調査' / '保存版' / 'work' / 'wave_v4' / 'signals.py')
    for symbol in SYMBOLS:
        for session in SESSIONS:
            source = ROOT / 'work' / 'wave_v7' / 'live' if session == SESSIONS[-1] else ROOT
            targets.extend(source / f'candle_{interval}min' / symbol / f'{session}.csv' for interval in [1, 5])
    manifest = []
    for source in sorted(set(targets)):
        if not source.exists():
            continue
        relative = source.relative_to(ROOT)
        target = archive / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest.append(dict(ファイル=relative.as_posix(), SHA256=hashlib.sha256(target.read_bytes()).hexdigest(), バイト=target.stat().st_size))
    (archive / '資料一覧とSHA256.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def audit_text() -> str:
    """機能: 完了した監査の記録へのリンクを列挙する。

    引数: なし。返り値: 監査説明のHTML (str)。
    """
    names = [p.name for p in OUT.glob('*.json') if '監査' in p.name or '不変' in p.name or '確認' in p.name]
    links = ' ／ '.join(f'<a href="資料/work/wave_v9/{html.escape(name)}">{html.escape(name)}</a>' for name in sorted(names))
    return '<p>原本の途中打切り、ATRの独立再計算、注文の手計算照合を別の監査処理で確認。検査対象と照合数は下記の完了記録に記載しています。</p><p>' + links + '</p>'


def enrich_conditions(conditions: list[dict]) -> None:
    """機能: 固定した入口定義と注文幅から各条件の日本語説明を補う。

    引数: conditions (list[dict])。返り値: なし (None)。配列内の辞書を更新する。
    """
    definitions = {}
    for line in (OUT / '転換入口の定義.md').read_text(encoding='utf-8').splitlines():
        if line.startswith('|T'):
            fields = line.strip('|').split('|')
            definitions[fields[0]] = fields[2]
    for config in conditions:
        basis = definitions[config['family']]
        config['family_description'] = basis + ' 売りは対称。'
        entry = '条件設定時の最良売り気配を買い逆指値、最良買い気配を売り逆指値の閾値にし、後続の観測で成立を確認する。' if config['entry'] == '初動逆指値' else '条件設定後、買いは最良売り気配の安値から0.25A反発、売りは最良買い気配の高値から0.25A反落を待つ。'
        width = {'追跡1ATR': '約定後は常に1A幅で追跡して返済する。', '追跡2ATR': '約定後は常に2A幅で追跡して返済する。', '順行1ATRで保護': '約定後は2A幅で追跡し、最大順行が1Aへ到達すると0.5A幅へ縮める。'}[config['exit']]
        config['description'] = basis + ' 売りは対称。' + entry + width + ' Aは新規条件設定時のATR。転換検知から10分で失効し、同じ転換は一度だけ使う。'


def comparison_records(cells: pd.DataFrame, trades: list[dict]) -> list[dict]:
    """機能: 同じT12入口仮説で発注と出口を変えた比較値を作る。

    引数: cells (DataFrame)、trades (list[dict])。返り値: 比較記録 (list[dict])。
    """
    subset = cells[cells.方式.str.startswith('T12_') & cells.セッション.isin(SESSIONS[:5])]
    rows = []
    for (method, symbol), frame in subset.groupby(['方式', '銘柄'], sort=False):
        part = [t for t in trades if t['method'] == method and t['symbol'] == symbol and t['session'] in SESSIONS[:5] and t['closed']]
        entry, exit_name = method.split('_')[1:]
        rows.append(dict(入口=entry, 出口=exit_name, 銘柄=symbol, 利益万円=money(frame.利益円.sum()),
            損失万円=money(frame.損失円.sum()), 差引万円=money(frame.収支円.sum(), True), 返済済=int(frame.取引数.sum()),
            費用４tick万円=money(frame.費用倍収支円.sum(), True), 平均保有分=round(np.mean([t['duration'] for t in part]), 1) if part else 0,
            平均利益後退ATR=round(np.mean([t['giveback']/t['atr'] for t in part]), 2) if part else 0))
    return rows


def current_check() -> tuple[str, str]:
    """機能: 条件凍結後の一回照合を、保存探索と分けて説明する。

    引数: なし。返り値: HTML節とMarkdown節 (tuple[str, str])。
    """
    path = OUT / '現在照合_セッション集計.csv'
    if not path.exists():
        return '', ''
    cells = pd.read_csv(path)
    frozen = read_json(OUT / '現在照合_凍結記録.json')
    record = read_json(OUT / '現在照合_取得記録.json')
    cells['群'] = cells['方式']
    rows = cells.to_dict('records')
    stamp = lambda value: pd.Timestamp(value).strftime('%m/%d %H:%M:%S')
    text = f'条件を{stamp(frozen["fixed_at"])}に凍結し、現在セッションを１回（６URLを各１回）だけ取得した。主評価は、以前の保存上限{stamp(frozen["known_cutoff"])}以降〜{stamp(record["cutoff"])}未満に検知した新しい転換に由来する取引。17時から注文・保有状態を継続して再生し、途中でリセットしていない。'
    note = '未読だった追加区間を、取得前に固定した条件で照合した結果。区間自体は条件凍結より前に発生しているため、実時間で将来を待った運用実績ではない。途中終了の未返済は評価損益として分け、確定利益には加えない。取得後の条件選び直しは行わない。'
    highlights = [row for row in rows if row['方式'] in [frozen['selected_groups'].get('転換方式全体'), 'T12_追跡0.25ATR_追跡2ATR']]
    added = [row for row in read_json(OUT / '現在照合_全取引.json', []) if row['評価区分'] == '追加区間の新規転換']
    trade_rows = []
    for row in added:
        symbol = row['銘柄']
        trade_rows.append(dict(条件=row['方式'], 銘柄=symbol, 方向='買い' if row['side'] > 0 else '売り',
            転換検知=stamp(pd.Timestamp(row['signal_time_s'], unit='s', tz='Asia/Tokyo')),
            新規約定=stamp(pd.Timestamp(row['entry_time_s'], unit='s', tz='Asia/Tokyo')),
            返済または評価=stamp(pd.Timestamp(row.get('exit_time_s', row.get('mark_time_s')), unit='s', tz='Asia/Tokyo')),
            状態='確定' if row['closed'] else '未返済評価', 損益万円=money(row['net_points'] * MULTIPLIERS[symbol], True)))
    detail = '追加区間のT12は３件とも買い。NK225は途中の費用後評価が最高＋9万円まで進んだ後、−5万円で返済し、14万円の利益後退があった。TOPIXの１件目は返済可能な価格が建値へ一度も届かず、入口の方向が外れた。２件目は検知から９分49秒後の約定で、古い転換を使った点も課題。損失の原因をすべて出口に帰すことはできない。'
    detail_html = '<p class="explain">' + detail + '</p><p><a href="資料/work/wave_v9/現在照合_T12明細.md">３件の検知・発注・約定・最大順行の明細</a></p>' if (OUT / '現在照合_T12明細.md').exists() else ''
    markup = '<section id="current"><h2>条件を固定してから、一回だけ現在セッションで照合</h2><p>' + html.escape(text) + '</p><p class="notice">' + html.escape(note) + '</p><p>T12の固定候補と、全84条件から選んだT13を先に表示。単位：万円。</p>' + html_table(highlights) + detail_html + '<details><summary>固定７条件をすべて見る</summary>' + html_table(rows) + '</details><details><summary>追加区間の転換から発注した取引</summary>' + generic_table(trade_rows) + '</details><p><a href="資料/work/wave_v9/現在照合_セッション集計.csv">追加区間の集計</a> ／ <a href="資料/work/wave_v9/現在照合_全取引.json">今回の全取引</a> ／ <a href="資料/work/wave_v9/現在照合_凍結記録.json">取得前の条件凍結</a> ／ <a href="資料/work/wave_v9/現在照合_取得記録.json">一回の取得記録</a> ／ <a href="資料/work/wave_v9/現在照合_監査.json">今回照合の監査</a></p></section>'
    markdown = '\n## 条件凍結後の一回の現在照合\n\n' + text + '\n\n' + note + '\n\n' + md_table(rows) + '\n\n' + detail + '\n'
    return markup, markdown


def current_chart(payload: dict) -> str:
    """機能: 一回取得した夜間を旧途中資料と別の図解対象へ追加する。

    引数: payload (dict)。返り値: 冒頭に示す現在照合の要点 (str)。
    """
    path = OUT / '現在照合_セッション集計.csv'
    if not path.exists():
        return ''
    import turning_signals
    record = read_json(OUT / '現在照合_取得記録.json')
    frozen = read_json(OUT / '現在照合_凍結記録.json')
    session = frozen['session']
    alias = session + '_現在照合'
    live = OUT / 'live'
    payload['sessions'].append(alias)
    payload['liveSession'] = alias
    payload['liveLabel'] = '2026-09-23 ナイト（一回現在照合 ' + pd.Timestamp(record['cutoff']).strftime('%H:%M') + 'まで）'
    payload['liveMethods'] = frozen['selected_ids']
    original = turning_signals.ROOT
    turning_signals.ROOT = live
    try:
        for symbol in SYMBOLS:
            source = live / 'work' / 'wave_v7' / 'live' / 'candle_5min' / symbol / f'{session}.csv'
            frame = pd.read_csv(source)
            frame = frame[frame.closed.astype(str).str.lower().eq('true')]
            payload['candles'][f'{symbol}|{alias}'] = [[pd.Timestamp(row.time).timestamp(), row.open, row.high, row.low, row.close] for row in frame.itertuples()]
            last_time = pd.read_csv(live / 'features' / f'{symbol}_{session}.csv', usecols=['time_s']).time_s.max()
            averages = turning_signals.load_price_frame(session, symbol, float(last_time))[['ema3', 'ema8', 'ema21']].dropna()
            payload['averages'][f'{symbol}|{alias}'] = [[stamp.timestamp(), *row] for stamp, row in zip(averages.index, averages.to_numpy())]
    finally:
        turning_signals.ROOT = original
    new_trades = compact_trades(read_json(OUT / '現在照合_全取引.json'))
    for row in new_trades:
        row['session'] = alias
    payload['trades'].extend(new_trades)
    cells = pd.read_csv(path)
    chart_cells = cells.copy()
    chart_cells['セッション'] = alias
    payload['cells'].extend(json.loads(chart_cells.to_json(orient='records', force_ascii=False)))
    parts = []
    for method, label in [('T12_追跡0.25ATR_追跡2ATR', '注目したT12'), (frozen['selected_groups']['転換方式全体'], '全84条件から選んだT13')]:
        item = cells[cells.方式.eq(method)]
        parts.append(label + 'は' + '／'.join(symbol + money(item[item.銘柄.eq(symbol)].収支円.sum(), True) + '万円' for symbol in SYMBOLS))
    return 'その後、条件を固定して一回取得した19:14〜' + pd.Timestamp(record['cutoff']).strftime('%H:%M') + 'の追加区間では、' + '、'.join(parts) + '。T12の過去の好成績は、今回の追加区間では再現しなかった。'


def delay_records(cells: pd.DataFrame) -> list[dict]:
    """機能: 同じ固定候補の約定待機だけを変えた感度を集計する。

    引数: cells (DataFrame)。返り値: 条件・銘柄・遅延別の記録 (list[dict])。
    """
    frame = pd.concat([cells, pd.read_csv(OUT / '約定遅延感度.csv')], ignore_index=True)
    subset = frame[frame.方式.isin(['T12_追跡0.25ATR_追跡2ATR', 'T13_初動逆指値_追跡2ATR']) & frame.セッション.isin(SESSIONS[:5])]
    result = []
    for (method, symbol, delay), part in subset.groupby(['方式', '銘柄', '約定遅延'], sort=False):
        result.append(dict(条件=method, 銘柄=symbol, 約定待機=delay, 差引万円=money(part.収支円.sum(), True), 返済済=int(part.取引数.sum())))
    return result


def main() -> None:
    """機能: 集計結果から転換点検証のHTML・Markdown・再現資料を生成する。

    引数: なし。返り値: なし (None)。
    """
    DEST.mkdir(parents=True, exist_ok=True)
    conditions = read_json(OUT / '条件一覧.json')
    cells = pd.read_csv(OUT / '全条件セッション集計.csv')
    forward = pd.read_csv(OUT / '時間順セッション集計.csv')
    trades = compact_trades(read_json(OUT / '全取引.json'))
    selections = read_json(OUT / '時間順選択.json', [])
    selected = selected_methods(read_json(OUT / '既知５セッション選択.json', {}))
    enrich_conditions(conditions)
    by_id = {c['id']: c for c in conditions}
    history = aggregate(forward[forward.セッション.isin(SESSIONS[2:5])])
    partial = aggregate(forward[forward.セッション.eq(SESSIONS[-1])])
    chosen = pd.concat([cells[cells.方式.eq(method) & cells.セッション.isin(SESSIONS[:5])].assign(群=group) for group, method in selected.items()], ignore_index=True) if selected else cells.iloc[:0].copy()
    exploratory = aggregate(chosen)
    fixed_frames = []
    for family in ['T01', 'T06', 'T12']:
        method = f'{family}_追跡0.25ATR_追跡2ATR'
        fixed_frames.append(cells[cells.方式.eq(method) & cells.セッション.isin(SESSIONS[:5])].assign(群=f'固定{family}'))
    fixed_comparison = aggregate(pd.concat(fixed_frames, ignore_index=True))
    prior = pd.read_csv(ROOT / 'work' / 'wave_v8' / '全条件セッション集計.csv')
    prior_reference = aggregate(prior[prior.方式.eq('P00_0_追跡1ATR_利益保護') & prior.セッション.isin(SESSIONS[2:5])].assign(群='従来の固定CUSUM＋ATR'))
    tradeoff_rows = comparison_records(cells, trades)
    pd.DataFrame(tradeoff_rows).to_csv(OUT / '入口と微細な波の比較.csv', index=False, encoding='utf-8-sig')
    wave_rows = wave_records(trades, selected)
    pd.DataFrame(wave_rows).to_csv(OUT / '指定４波照合.csv', index=False, encoding='utf-8-sig')
    seq_rows = []
    for row in selections:
        adopted = row.get('採用')
        seq_rows.append(dict(群=row.get('群', ''), 選択に使う過去=f'{len(row.get("学習", []))}セッション',
            次の評価=row.get('評価セッション', ''), 採用条件=adopted.get('方式', adopted.get('id', '')) if isinstance(adopted, dict) else adopted or 'なし'))
    rule_cards = ''.join('<article class="method"><small>' + html.escape(group) + '／既知５セッションの探索候補</small><h3>' + html.escape(method) + '</h3><p>' + html.escape(by_id[method]['description']) + '</p></article>' for group, method in selected.items())
    family_cards = []
    for family in dict.fromkeys(config['family'] for config in conditions):
        configs = [c for c in conditions if c['family'] == family]
        first = configs[0]
        family_cards.append(dict(番号=family, 群=first['group'], 仮説=first.get('family_description', first.get('signal_description', first['description']))))
    payload = dict(candles=chart_candles(), averages=chart_averages(), trades=trades,
        cells=json.loads(cells.to_json(orient='records', force_ascii=False)), conditions=conditions,
        selected=selected, sessions=list(SESSIONS), groups=list(dict.fromkeys(c['group'] for c in conditions)))
    current_lead = current_chart(payload)
    conclusion = '移動平均の収束や板の反転を「転換の候補」として検知し、観測できた初動の方向へ一度だけ発注する方式を検証した。返済後、同じ方向が続いているだけでは入り直さず、次の新しい転換を待つ。LSTMは使わない。'
    content = HTML.replace('__CONCLUSION__', html.escape(conclusion)).replace('__COUNT__', str(len(conditions)))
    for token, value in [('__HISTORY__', html_table(history)), ('__PARTIAL__', html_table(partial)),
        ('__EXPLORATORY__', html_table(exploratory)), ('__SELECTIONS__', generic_table(seq_rows)),
        ('__WAVES__', generic_table(wave_rows, ['指定波', '群', '銘柄', '最初の検知', '最初の新規', '同方向保有割合', '波内保有分', '重なる取引数'])),
        ('__RULES__', rule_cards), ('__FAMILIES__', generic_table(family_cards)), ('__AUDITS__', audit_text())]:
        content = content.replace(token, value)
    content = content.replace('__FIXED__', html_table(fixed_comparison)).replace('__PRIOR__', html_table(prior_reference)).replace('__TRADEOFF__', generic_table(tradeoff_rows))
    content = content.replace('__DELAYS__', generic_table(delay_records(cells)))
    content = content.replace('__KEYWAVES__', generic_table([row for row in wave_rows if row['群'] == '価格と板の転換'], ['指定波', '銘柄', '最初の検知', '最初の新規', '同方向保有割合', '波内保有分']))
    key_results = [r for r in history if r['群'] in ['転換方式全体', '価格と板の転換']]
    result_text = '時間順の３セッションでは、' + '、'.join(f'{group}が' + '／'.join(f'{r["銘柄"]}{money(r["収支円"], True)}万円' for r in key_results if r['群'] == group) for group in ['価格と板の転換', '転換方式全体']) + '。価格と板を組み合わせる群には改善候補があるが、全84条件から事前の選択基準で選んだ結果は小幅な利益にとどまる。'
    content = content.replace('__RESULT__', html.escape(result_text))
    content = content.replace('__CURRENT_LEAD__', '<p class="notice">' + html.escape(current_lead) + '</p>' if current_lead else '')
    live_html, live_md = current_check()
    content = content.replace('__CURRENT__', live_html)
    content = content.replace('__PAYLOAD__', json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/'))
    (DEST / '転換点と売買の検証.html').write_text(content, encoding='utf-8')
    method_lines = '\n\n'.join(f'### {group}：{method}\n\n{by_id[method]["description"]}' for group, method in selected.items())
    report = f'''# 転換点を検知して入り、トレーリングで返済する検証

{conclusion}

最初に [転換点と売買の検証.html](転換点と売買の検証.html) を開くと、転換検知・実約定・返済とセッションごとの利益・損失・差引を確認できる。

## 今回の考え方

前回は「板が買い優勢であり続ける」など、状態の持続を方向条件にした。今回は「平均線が収束した後に上向きへ再び開く」「売り優勢だった板フローが買い優勢へ変わる」など、状態が変わった時を入口の根拠にする。収束だけでは方向を決めず、その後に観測した傾き・価格・板の初動を使う。

１つの転換イベントにつき新規条件を１回だけ作る。返済しても同じイベントでは再発注しない。途中の小さな反転をどこまで許すかは出口の追跡幅で比較する。

## 時間順に選んだ条件の結果

最初の２セッションで選択して３番目、３つで選択して４番目、４つで選択して５番目を評価した。既に閲覧済みの履歴による時間順再評価で、独立した未見データでの証明ではない。ラージ各１枚。実際の売買気配差に加え往復２tickを控除。利益・損失は取引ごとの費用後収支の正負別合計。勝率は返済済み取引の勝率で、方向予測の正答率ではない。

{md_table(history)}

{result_text}

{current_lead}

T12群へ結果を見て着目していることと、事前に全84条件から選ぶ運用の成績は異なる。T12だけを後から最良として取り出し、最初から選べたかのようには扱わない。

固定T12はNK225の9/22日中ショートと翌00:40以降ロング、TOPIXの9/23日中ショートを捉えた。一方でNK225の9/21後半ロングと9/23日中ショート、TOPIXの9/22日中ショートと翌00:40以降ロングは捉えられなかった。要望のすべてを満たした完成版ではない。

## 注目するT12の具体的な入口

EMA3とEMA8の下向き乖離が拡大した後、まだEMA3がEMA8より下のまま２分続けて乖離が縮む。これと５分以内に、板圧力が売り優勢から買い優勢へ反転する。板圧力は60秒OFI・気配更新方向・表示数量純変化の平均で、+0.10以上を２ブロック確認する。２条件がそろった時点で買い候補を一度だけ作る。売りは上下対称。これは価格反転の確定ではなく、勢いの変化の検知である。

既知５セッションでのT12選択は0.25ATR追跡入口＋2ATR追跡出口。買いは気配の安値を追跡し0.25A反発してから入り、約定後の売却可能価格の最高値から2A下のストップを追随させる。Aは発注条件設定時のATRで固定する。

## 事前に固定した３仮説の比較

T01（MA乖離の収束）・T06（OFI反転）・T12（両者を組合せ）の0.25ATR追跡入口＋2ATR追跡出口を共通にした既知５セッションの成績。

{md_table(fixed_comparison)}

T12で0.25ATR追跡入口を固定した既知５セッションでは、出口1ATRがNK225−53万円／TOPIX−40.5万円、出口2ATRがNK225＋109万円／TOPIX＋38.5万円。狭い追跡幅はこの資料では止まりすぎた。平均利益後退と全６組合せはHTMLおよび入口と微細な波の比較.csvに記載する。

以前から固定したCUSUM＋ATRを同じ３セッションへ適用した参考値：

{md_table(prior_reference)}

従来方式は開始待機・入口幅・出口も異なるため、この比較だけで入口仮説の追加効果とは言えない。

## 既知５セッションで選んだ候補

同じ期間で選択と集計を行った探索成績であり、上の時間順評価より楽観的になりうる。

{md_table(exploratory)}

{method_lines}

## 共通する入口と出口

{COMMON_MARKDOWN}

## 前回保存した9/23ナイト19:14まで

今回は既知の途中資料。探索には保存資料だけを使用。途中の未返済を強制決済したことにせず、評価損益として別記する。完成したセッションはセッション内で返済する。

{md_table(partial)}

## 資料

- [全条件のセッション別損益](資料/work/wave_v9/全条件セッション集計.csv)
- [全取引](資料/work/wave_v9/全取引.csv)
- [時間順の選択記録](資料/work/wave_v9/時間順選択.json)
- [指定４波との照合](資料/work/wave_v9/指定４波照合.csv)
- [資料一覧とSHA256](資料/資料一覧とSHA256.json)

生板に受信時刻と注文IDがないため、数量減少を取消と約定に分解できない。最終約定時刻を代理の時計に使った保存行順の検証であり、実注文の遅延・待ち順・部分約定や２銘柄の受信同期を再現した結果ではない。

板圧力指標の参考：[Cont・Kukanov・Stoikov「The Price Impact of Order Book Events」](https://arxiv.org/abs/1011.6402)。最良気配OFIと短時間の価格変化の関係を米国株で分析した研究であり、NK225・TOPIXの転換検知や今回の収益性を証明するものではない。
'''
    (DEST / '検証結果.md').write_text(report + live_md, encoding='utf-8')
    (DEST / 'README.md').write_text('''# 00004の追加検証：転換点からのエントリー

最初に **[転換点と売買の検証.html](転換点と売買の検証.html)** を開いてください。５分足上に転換検知・新規約定・返済を表示し、90条件の銘柄・セッションを切り替えられます。

読む順序：

1. HTMLの冒頭で、状態の持続と状態の転換の違い、時間順での成績を確認する。
2. HTMLのチャートで、検知から約定、返済までとセッションごとの利益・損失・差引を見る。
3. [検証結果.md](検証結果.md) で機械的な入口・出口の規則を読む。
4. [資料/work/wave_v9](資料/work/wave_v9) の全条件・全取引・監査と再現コードを見る。

この小フォルダは同じ00004作業に対する考え方の修正と追加検証です。前回の[板を使う売買の検証](../板を使う売買の検証.html)は比較資料として残しています。

`資料/work/wave_v9/live_fixture_saved` は現在照合器の動作確認に使った既知入力の写しです。本番の現在照合結果、HTML集計、再現資料一覧には使用していません。

## 再計算

PythonとNumPy・pandasを利用します。このREADMEのあるフォルダを基準に、`資料` を作業ディレクトリとして実行します。

```powershell
Set-Location -LiteralPath ./資料
python -X utf8 work/wave_v9/research.py
python -X utf8 work/wave_v9/live_check.py --evaluate
```

１行目の研究再計算は、複製した足と抽出済み板特徴・全気配配列から90条件を再生します。現在照合の `--evaluate` は今回取得分の保存済み生板と足だけを読み、通信なしで７固定条件を再計算します。取得処理の再実行は必要ありません。

過去５セッションの巨大な `book` 原本はこの資料へ複製していません。過去の原本打切り監査を最初からやり直す場合は、プロジェクト元の `book` が必要です。成果に同梱した監査結果を読むことと、原本から監査を再実行することは区別してください。
''', encoding='utf-8')
    manifest = copy_materials()
    fixture = DEST / '資料' / 'work' / 'wave_v9' / 'live_fixture_saved'
    if fixture.exists():
        (fixture / 'README.md').write_text('# 単体試験用の既知資料\n\nこのフォルダは現在照合器を通信なしで動作確認した際の既知入力の写しです。新しく取得した現在セッションのデータではありません。HTMLの損益、現在照合の主集計、再現資料一覧には含めていません。\n', encoding='utf-8')
    print(json.dumps(dict(出力=str(DEST), 条件数=len(conditions), 取引記録数=len(trades), 資料数=len(manifest)), ensure_ascii=False))


COMMON_MARKDOWN = '''- セッション開始20分後から新規判定。返済後10分休止。１銘柄１建玉とし、両建てしない。
- 確定１分足のEMA3・8・21は足の確定からさらに１分待つ。ATRは確定５分足TRの指数平均（係数1/12、３本以上、最低２tick）で、確定からさらに１分待ち、新規条件作成時の値Aを固定する。
- 同一最終約定時刻の板は次の時刻の先頭行を観測後に方向判定へ使う。発注とストップは保存された全有効気配で監視し、条件成立した行の次の有効行で買いは売り気配、売りは買い気配で約定させる。
- 新規は①新規条件設定時の気配を閾値とする初動逆指値、②条件設定後の安値から0.25A反発して買い／高値から0.25A反落して売り、の２方式。転換検知から10分で失効し、同じ転換では再発注しない。開始待機などにより検知と新規条件設定の時刻は異なりうる。
- 未成立の新規条件は反対転換で取り消す。同じ行で旧注文の閾値にも届いた場合は旧注文の成立を優先する。成立後の注文を新情報で遡って取り消さない。出口は反対シグナルには依存しない。
- 出口は①常に1A、②常に2A、③初め2Aで最大順行が1Aに達したら0.5Aへ縮める、の３方式。いずれも約定からの順行方向へ追跡し、ストップは緩めない。
- 新規停止は15:05／翌05:20、返済要求は15:35／翌05:50。条件成立行の次の有効気配で返済する。セッションを跨ぐ保有は行わない。'''


HTML = r'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>00004 転換点からのエントリー</title><style>
:root{--bg:#f3f5f8;--ink:#192e3e;--muted:#526675;--line:#d9e2e8;--blue:#175a9a;--green:#087a65;--red:#b13b4d;--gold:#ad6d0c}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--bg);font:15px/1.75 system-ui,"Yu Gothic",sans-serif}main{max-width:1360px;margin:auto;padding:28px 24px 56px}header{padding:14px 0 20px}h1{font-size:32px;line-height:1.4;margin:9px 0 18px}h2{font-size:23px;margin:0 0 12px}h3{font-size:17px;overflow-wrap:anywhere}p{margin:10px 0}a{color:var(--blue)}section{background:white;border:1px solid var(--line);padding:24px;border-radius:14px;margin:20px 0}.eyebrow{font-weight:700;color:var(--blue);letter-spacing:.05em}.lead{font-size:17px;max-width:1120px}.tags,nav{display:flex;flex-wrap:wrap;gap:12px}.tags{margin:16px 0}.tag{padding:2px 12px;border:1px solid #b7d3e0;background:#e8f3f8;color:#21566c;border-radius:22px;font-size:13px}nav{gap:20px;margin-top:20px}.steps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:20px 0}.step{background:#f0f6fb;border:1px solid #d2e0ed;border-radius:10px;padding:15px}.step b{display:block;color:var(--blue);margin-bottom:7px}.step small{color:var(--muted)}.note{font-size:13px;color:var(--muted)}.notice{background:#fff7e7;border-left:4px solid #c8871d;color:#714c16;padding:12px 15px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap;font-variant-numeric:tabular-nums}th,td{padding:9px 12px;border-bottom:1px solid var(--line);text-align:right}th{background:#eff4f8;color:#405566}th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}.pos{color:var(--green);font-weight:700}.neg{color:var(--red);font-weight:700}.controls{display:flex;flex-wrap:wrap;gap:14px;align-items:end;margin:15px 0}.controls label{display:grid;gap:4px;font-size:13px;color:var(--muted)}select{font:inherit;font-size:14px;border:1px solid #bccbd5;border-radius:7px;background:white;padding:8px 10px;color:var(--ink);max-width:100%}.wide{flex:1;min-width:300px}.chartbox{height:490px;position:relative;border:1px solid var(--line);background:#fcfdff;border-radius:8px;overflow:hidden}canvas{display:block;width:100%;height:100%}.tooltip{display:none;position:absolute;pointer-events:none;background:#152b3cf0;color:white;padding:10px 12px;border-radius:7px;max-width:340px;font-size:12px;white-space:pre-line;z-index:2}.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--muted);margin:10px 0}.metrics{display:flex;flex-wrap:wrap;gap:24px;margin:14px 0}.metrics b{font-size:22px}.metrics span{font-size:12px;color:var(--muted)}.explain{border-left:3px solid #6798bb;padding:10px 15px;background:#f2f7fb}.trade-table{max-height:360px;overflow:auto}.trade-table thead{position:sticky;top:0}.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.method{border:1px solid var(--line);border-radius:10px;padding:16px}.method small{color:var(--blue)}details{margin:16px 0}summary{cursor:pointer;font-weight:700}footer{font-size:13px;color:var(--muted)}.family-table td:last-child{white-space:normal;min-width:440px;text-align:left}@media(max-width:760px){main{padding:16px 12px}section{padding:16px}h1{font-size:26px}.steps,.cards{grid-template-columns:1fr}.chartbox{height:390px}.wide{min-width:100%}}
</style></head><body><main>
<!--
[コンポーネント概要]
#forward は前のセッションだけで条件を選んだ時間順成績です。
#symbol、#session、#method は５分足図解の銘柄・セッション・注文方式を選択します。
#chart は確定５分足と既に観測できたEMA、約定した取引に対応する転換検知・約定・返済を示します。
#tooltip はマウスに近い検知・約定・返済・足の正確な値を表示します。
#metrics、#trades、#sessions は表示条件の確定損益・未返済評価・全セッションの損益です。
-->
<header><div class="eyebrow">調査 00004 ／ 転換点からのエントリー</div><h1>収束と板の反転から入り、<br>伸びる間は追跡して返済する</h1><p class="lead">__CONCLUSION__</p><div class="tags"><span class="tag">__COUNT__ 条件</span><span class="tag">NK225・TOPIX 各１枚</span><span class="tag">単独銘柄／２銘柄を比較</span><span class="tag">探索は保存データのみ</span></div><nav><a href="#idea">考え方</a><a href="#forward">時間順の成績</a><a href="#chart-section">転換検知と売買位置</a><a href="#rules">条件の詳細</a><a href="../板を使う売買の検証.html">前回の検証</a></nav></header>
<section id="idea"><h2>「買い優勢が続く」から、「売り優勢が変わる瞬間」へ</h2><p>前回の中心は、板の方向が一定時間続いていることでした。今回は、平均線の収束後の再拡散や、板の売り優勢から買い優勢への変化を入口の根拠にします。移動平均の収束だけでは上か下か決まらないため、収束は準備とし、その後に観測できた初動で方向を決めます。</p><div class="steps"><div class="step"><b>① 準備を見る</b>平均線が近づく／売り買いの勢いが弱まる。<br><small>収束だけでは注文しない。</small></div><div class="step"><b>② 転換を検知</b>傾きの反転・再拡散／板フローの反転を確認。<br><small>その時点までの値で方向を決める。</small></div><div class="step"><b>③ 一度だけ発注</b>初動の逆指値、または0.25ATR反発・反落。<br><small>同じ転換では発注し直さない。</small></div><div class="step"><b>④ 追跡して返済</b>高値・安値の更新にストップを追随させる。<br><small>1ATR／2ATR／利益後0.5ATRを比較。</small></div></div><p class="note">「転換」は将来の高値・安値を見て貼ったラベルではなく、ここで定義した条件が過去の観測だけで成立したイベントです。実際の相場がその後も転換するとは限りません。</p></section>
<section id="forward"><h2>前の期間で選び、次のセッションで比較</h2><p>最初の２セッションで選択 → 9/22デイ、３つで選択 → 9/22ナイト、４つで選択 → 9/23デイ。評価するセッションの成績を、その回の条件選択には使いません。研究全体では既知データの時間順再評価です。</p><p class="explain">__RESULT__</p>__CURRENT_LEAD__<p class="note">金額は万円。利益・損失は費用後の取引損益の正負別合計。差引＝利益−損失。勝率は返済済み取引の勝率であり、方向予測の正答率ではありません。</p>__HISTORY__<p class="note">売買気配差を負担したうえで往復２tickを追加控除。「追加費用４tick」は追加部分を倍にした場合。新規も返済も条件成立行では約定させず、次の有効な気配で評価します。</p><p class="notice">T12の群に結果を見て着目しています。「転換方式全体」はT00を除く84条件から事前の基準で選んだ結果です。T12だけを後から取り出した成績と、最初からT12を選べたかは区別が必要です。</p><details><summary>各回に選ばれた条件</summary>__SELECTIONS__</details><details><summary>従来の固定CUSUM＋ATRを同じ３セッションへ適用した参考値</summary>__PRIOR__<p class="note">従来は開始待機45分・１ATR追跡新規・別の利益保護出口です。待機や出口も違うため、この差を入口だけの効果とは扱いません。</p></details></section>
<section id="chart-section"><h2>検知 → 新規約定 → 返済を５分足で見る</h2><p>丸い印は約定した取引に対応する転換の検知、三角は実際の新規約定、ひし形は返済です。５分足は位置の表示で、ストップは足の確定を待たず全有効気配で監視します。</p><div class="controls"><label>銘柄<select id="symbol"><option>NK225</option><option>TOPIX</option></select></label><label>セッション<select id="session"></select></label><label class="wide">方式<select id="method"></select></label></div><div class="chartbox"><canvas id="chart" aria-label="５分足、移動平均、転換検知、新規約定と返済"></canvas><div class="tooltip" id="tooltip"></div></div><div class="legend"><span style="color:#c47a0c">○ 転換検知</span><span style="color:#175a9a">▲ ロング新規 ／ ▼ ショート新規</span><span style="color:#a33ea4">◆ 返済</span><span style="color:#8c722b">□ 未返済評価</span><span style="color:#08a393">EMA3</span><span style="color:#d49117">EMA8</span><span style="color:#8661a7">EMA21</span></div><p class="note">EMAは確定１分足から計算し、足の確定後にさらに１分待って参照できる時刻に描きます。検知印は約定した取引に対応するものだけです。約定しなかった転換はこの図には表示していません。</p><p id="chart-status" class="notice" hidden></p><div id="metrics" class="metrics"></div><p id="description" class="explain"></p><div id="trades" class="trade-table"></div><details open><summary>この同一条件を適用した全セッションの利益・損失・差引</summary><p class="note">上の時間順選択とは別の、固定した１条件の結果です。単位：万円。</p><div id="sessions"></div></details></section>
<section id="rules"><h2>機械的に実行する入口と出口</h2><p>14の転換仮説とCUSUM転換の比較条件に、入口２通り・出口３通りを組み合わせます。ATRは注文幅をその時点の値動きに合わせるために使い、方向は各転換仮説で決めます。</p><article class="method"><h3>T12：MAの勢い低下と、板圧力の反転を組み合わせる</h3><p>買いは、EMA3−EMA8の負の乖離が0.1ATR以上に広がった後、まだ負のまま２分続けて縮むことを確認します。この前後５分以内に、板圧力も売り優勢から買い優勢へ変われば、２条件がそろった時点で買い候補を一度だけ作ります。売りは対称です。</p><p>板圧力は、60秒のOFI・気配更新方向・表示数量純変化の３つの正規化値の平均。既に負方向だった値が+0.10以上へ２ブロック続くと買いへの反転です。MAだけで底を確定せず、板側にも同方向への変化を要求します。</p><p>既知５セッションで選ばれたT12は、0.25ATR反発・反落で入り、2ATR幅で追跡して返済。価格自体の反転が確定したという判定ではなく、勢いが変わった兆候を使う方式です。</p></article><details><summary>15種類の転換仮説をすべて見る</summary><p class="note">g＝EMA3−EMA8、L＝EMA3−EMA21、H＝（EMA3−EMA13）からその５分EMAを引いた値。板反転は最初の方向成立では発火せず、いったん確認した方向から反対側へ変わる場合に限ります。</p><div class="family-table">__FAMILIES__</div><p><a href="資料/work/wave_v9/転換入口の定義.md">数式・閾値・鮮度・２銘柄同期の詳細</a></p></details><div class="cards">__RULES__</div><details open><summary>共通の注文条件</summary><ol><li>開始20分後から新規判定。返済後10分休止。１銘柄１建玉。新しい転換につき１回だけ新規条件を作り、<strong>転換検知から10分</strong>で失効。</li><li>確定１分足のEMAは確定からさらに１分待つ。確定５分足ATR（指数係数1/12、３本以上、最低２tick）も確定から１分待ち、新規条件設定時の値Aで注文幅を固定。開始待機などにより、転換検知と新規条件設定の時刻は異なりえます。</li><li>入口は新規条件設定時の気配を閾値とする初動逆指値、または条件設定後の安値から0.25A反発して買い／高値から0.25A反落して売り。条件成立後の次の有効行で、買いは売り気配、売りは買い気配を使う。</li><li>未成立の新規条件は反対転換で取り消す。同じ行で旧注文の閾値にも届いた場合は旧注文成立を優先し、成立後は新情報で遡って取り消さない。</li><li>出口は常に1A、常に2A、または初め2Aで最大順行が1Aに届いたら0.5Aへ縮める。観測した順行に追跡し、ストップを緩めない。返済も条件成立後の次の有効行。反対シグナルでは返済しない。</li><li>15:05／翌05:20で新規停止、15:35／翌05:50で返済要求。完成したセッションはセッション内で返済し、途中資料の未返済は評価値として区別する。</li></ol></details><p class="notice">板には受信時刻・注文IDがありません。数量減少を取消と約定へ分けず、数量の変化として使います。最終約定時刻が同じ連続行は次の時刻を観測してから方向判定へ解放します。２銘柄は相手情報を追加で待って参照しますが、受信同期や実発注の遅延を保証するものではありません。</p></section>
<section><h2>入口の早さと、微細な波で返済する幅の比較</h2><p>T12の転換検知は共通で、初動逆指値／0.25ATR追跡新規と、出口３種類だけを変えた既知５セッションの比較です。狭い出口は利益後退を小さくする一方、継続する大きな波でも途中の戻しで返済します。</p><p class="explain">0.25ATR追跡入口を固定すると、出口1ATRはNK225−53万円／TOPIX−40.5万円、出口2ATRはNK225＋109万円／TOPIX＋38.5万円。今回の資料では、狭い出口で利益を守る以上に、継続する波から降りる影響が大きくなりました。</p>__TRADEOFF__<p class="note">平均利益後退ATR＝（約定後に観測した最大順行−返済時の価格差損益）÷発注条件時ATR、の取引平均。取引手数料は含まず、実際の売買気配差と次行返済を含みます。将来最高値で売買する判定には使っていません。</p><details><summary>固定したT01・T06・T12を、同じ入口・出口で比較する</summary><p>結果を見る前に固定した0.25ATR追跡新規＋2ATR追跡返済。T01はMA乖離収束、T06はOFI反転、T12はMA収束と板圧力反転。既知５セッションの成績です。</p>__FIXED__</details></section>
<section><h2>指定された４つの波との照合</h2><p>まず固定T12（0.25ATR追跡新規＋2ATR追跡返済）を表示します。同方向保有割合は、その波の時間帯のうち同方向の建玉を持っていた割合です。入口の正答率を表す指標ではありません。</p>__KEYWAVES__<p class="notice">固定T12はNK225の9/21後半ロングと9/23日中ショート、TOPIXの9/22日中ショートと翌00:40以降のロングを捉えていません。要望のすべてを満たした完成版ではありません。</p><details><summary>各群の探索候補による、４波の検知時刻・新規時刻・保有時間</summary>__WAVES__</details></section>
<section><h2>既知５セッションで選んだ候補の探索成績</h2><p>５セッションの損益で候補を選び、その同じ５セッションに適用した成績です。時間順の成績と区別して見てください。</p>__EXPLORATORY__</section>
<section><h2>9/23ナイト19:14までの保存済み参考資料</h2><p>以前に取得済みの途中データです。今回は未見の検証ではありません。５セッションで選んだ条件を適用し、未返済を確定利益へ含めず分けて示します。</p>__PARTIAL__</section>
__CURRENT__
<section><h2>約定をさらに遅らせた場合</h2><p>同じ固定T12・T13の既知５セッションで、次の有効行・２行後・次の異なる最終約定時刻まで待つ場合を比較します。実際の通信遅延を秒単位で再現した試験ではありません。</p><details><summary>約定待機別の収支</summary>__DELAYS__</details></section>
<section id="materials"><h2>監査と再現資料</h2>__AUDITS__<p><a href="検証結果.md">日本語の検証結果</a> ／ <a href="資料/work/wave_v9/検証計画.md">検証計画</a> ／ <a href="資料/work/wave_v9/条件一覧.json">全条件の定義</a></p><p><a href="資料/work/wave_v9/全条件セッション集計.csv">全条件セッション集計</a> ／ <a href="資料/work/wave_v9/全取引.csv">全取引</a> ／ <a href="資料/work/wave_v9/時間順選択.json">時間順の選択記録</a> ／ <a href="資料/work/wave_v9/指定４波照合.csv">指定４波照合</a> ／ <a href="資料/資料一覧とSHA256.json">資料一覧とSHA256</a></p><p class="note">探索と条件選択は保存データで完了させています。実注文は行っていません。保存データに対する因果性の監査は、実際の時刻に受信済みだったことや実約定を保証するものではありません。</p></section><footer><p>板圧力指標の参考：<a href="https://arxiv.org/abs/1011.6402">Cont・Kukanov・Stoikov「The Price Impact of Order Book Events」</a>。米国株における最良気配OFIと短時間価格変化の関係を分析した研究です。NK225・TOPIXの転換検知や今回の収益性の証明ではありません。</p>前回の方向持続条件と今回の転換条件を区別するため、00004内に追加の検証として保存しています。</footer>
</main><script id="dataset" type="application/json">__PAYLOAD__</script><script>
const data=JSON.parse(document.getElementById('dataset').textContent);
const $=id=>document.getElementById(id),yen=n=>(n>0?'+':'')+(n/10000).toFixed(1),esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let shown=[],targets=[];
/**
 * 機能: Unix秒を日本時間の表示へ変換する。
 * @param {number} seconds - Unix秒。
 * @param {boolean} full - 日付を含めるか。
 * @returns {string} 日本時間の文字列。
 */
function stamp(seconds,full=false){return new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',...(full?{month:'2-digit',day:'2-digit'}:{}),hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date(seconds*1000))}
/**
 * 機能: 図解の現在の対象を取得する。
 * @returns {Object} 銘柄・セッション・方式。
 */
function selection(){return {symbol:$('symbol').value,session:$('session').value,method:$('method').value}}
/**
 * 機能: セッションごとの確定損益と未返済を表示する表を作る。
 * @param {Array<Object>} rows - 集計記録。
 * @returns {string} HTML表。
 */
function metricTable(rows){return '<div class="scroll"><table><thead><tr><th>セッション</th><th>銘柄</th><th>利益</th><th>損失</th><th>差引</th><th>勝ち／返済済</th><th>費用４tick差引</th><th>未返済／評価</th></tr></thead><tbody>'+rows.map(r=>`<tr><td>${esc(r.セッション)}</td><td>${r.銘柄}</td><td>${(r.利益円/10000).toFixed(1)}</td><td>${(r.損失円/10000).toFixed(1)}</td><td class="${r.収支円>=0?'pos':'neg'}">${yen(r.収支円)}</td><td>${r.勝ち数} / ${r.取引数}${r.取引数?'（'+(100*r.勝ち数/r.取引数).toFixed(1)+'%）':''}</td><td>${yen(r.費用倍収支円)}</td><td>${r.未返済数} / ${yen(r.評価損益円)}</td></tr>`).join('')+'</tbody></table></div>'}
/**
 * 機能: 選択条件に対応する説明・損益・取引と図解を更新する。
 * @returns {void} 返り値なし。
 */
function update(){const s=selection();$('chart-status').hidden=s.session!==data.liveSession;$('chart-status').textContent='現在照合の主集計は19:14以降の転換から発注した取引だけです。チャートと取引表には17時からの状態を確認できるよう既知区間の転換に由来する取引も淡色で表示します。';shown=data.trades.filter(t=>t.symbol===s.symbol&&t.session===s.session&&t.method===s.method);$('description').textContent=data.conditions.find(c=>c.id===s.method).description;const row=data.cells.find(r=>r.銘柄===s.symbol&&r.セッション===s.session&&r.方式===s.method);$('metrics').innerHTML=row?`<div><span>確定差引 万円</span><br><b class="${row.収支円>=0?'pos':'neg'}">${yen(row.収支円)}</b></div><div><span>勝ち／返済済</span><br><b>${row.勝ち数} / ${row.取引数}</b></div><div><span>未返済／評価 万円</span><br><b>${row.未返済数} / ${yen(row.評価損益円)}</b></div>`:'';$('trades').innerHTML='<table><thead><tr><th>方向</th><th>評価区分</th><th>転換検知</th><th>条件設定</th><th>新規約定</th><th>価格</th><th>返済／評価</th><th>価格</th><th>費用後 万円</th><th>保有分</th><th>返済理由</th></tr></thead><tbody>'+shown.map(t=>`<tr><td>${t.side>0?'ロング':'ショート'}</td><td>${esc(t.origin)}</td><td>${stamp(t.signal,true)}</td><td>${stamp(t.condition,true)}</td><td>${stamp(t.entry,true)}</td><td>${t.ep}</td><td>${stamp(t.exit,true)}</td><td>${t.xp}</td><td class="${t.net>=0?'pos':'neg'}">${yen(t.net)}${t.closed?'':'（評価）'}</td><td>${t.duration.toFixed(1)}</td><td>${esc(t.reason)}</td></tr>`).join('')+(shown.length?'':'<tr><td colspan="11">この条件・セッションでは新規約定なし</td></tr>')+'</tbody></table>';$('sessions').innerHTML=metricTable(data.cells.filter(r=>r.方式===s.method));draw()}
/**
 * 機能: ５分足・観測済みEMA・転換検知と約定返済を描く。
 * @returns {void} 返り値なし。
 */
function draw(){const s=selection(),key=s.symbol+'|'+s.session,bars=data.candles[key]||[],averages=data.averages[key]||[],canvas=$('chart'),box=canvas.parentElement,w=box.clientWidth,h=box.clientHeight,dpr=window.devicePixelRatio||1;canvas.width=w*dpr;canvas.height=h*dpr;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);ctx.fillStyle='#fcfdff';ctx.fillRect(0,0,w,h);targets=[];if(!bars.length)return;const pad={l:64,r:25,t:35,b:42},times=shown.flatMap(t=>[t.signal,t.entry,t.exit]),t0=Math.min(bars[0][0],...times)-150,t1=Math.max(bars.at(-1)[0]+300,...times)+150,prices=bars.flatMap(b=>[b[2],b[3]]).concat(shown.flatMap(t=>[t.sp,t.ep,t.xp]));let lo=Math.min(...prices),hi=Math.max(...prices),range=hi-lo||1;lo-=range*.12;hi+=range*.12;const x=t=>pad.l+(t-t0)/(t1-t0)*(w-pad.l-pad.r),y=p=>h-pad.b-(p-lo)/(hi-lo)*(h-pad.t-pad.b);ctx.font='11px system-ui';ctx.textBaseline='middle';ctx.lineWidth=1;for(let i=0;i<=5;i++){const price=lo+(hi-lo)*i/5,yy=y(price);ctx.strokeStyle='#e2e8ee';ctx.beginPath();ctx.moveTo(pad.l,yy);ctx.lineTo(w-pad.r,yy);ctx.stroke();ctx.fillStyle='#526675';ctx.textAlign='right';ctx.fillText(price.toFixed(s.symbol==='TOPIX'?1:0),pad.l-8,yy)}const gap=t1-t0>36000?7200:3600;for(let t=Math.ceil(t0/gap)*gap;t<t1;t+=gap){ctx.strokeStyle='#edf1f5';ctx.beginPath();ctx.moveTo(x(t),pad.t);ctx.lineTo(x(t),h-pad.b);ctx.stroke();ctx.fillStyle='#526675';ctx.textAlign='center';ctx.fillText(stamp(t).slice(0,5),x(t),h-pad.b+20)}const cw=Math.max(1,Math.min(12,(w-pad.l-pad.r)*220/(t1-t0)));for(const b of bars){const xx=x(b[0]+150),color=b[4]>=b[1]?'#15957f':'#d1596b';ctx.strokeStyle=color;ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(xx,y(b[2]));ctx.lineTo(xx,y(b[3]));ctx.stroke();ctx.fillRect(xx-cw/2,Math.min(y(b[1]),y(b[4])),cw,Math.max(1,Math.abs(y(b[1])-y(b[4]))));targets.push({x:xx,y:(y(b[2])+y(b[3]))/2,kind:'bar',text:`５分足 ${stamp(b[0],true)} 開始\n始値 ${b[1]}　高値 ${b[2]}\n安値 ${b[3]}　終値 ${b[4]}`})}for(const [column,color] of [[1,'#08a393'],[2,'#d49117'],[3,'#8661a7']]){ctx.strokeStyle=color;ctx.lineWidth=1.3;ctx.beginPath();let started=false;for(const a of averages){if(a[0]<t0||a[0]>t1||!Number.isFinite(a[column]))continue;if(started)ctx.lineTo(x(a[0]),y(a[column]));else{ctx.moveTo(x(a[0]),y(a[column]));started=true}}ctx.stroke()}ctx.lineWidth=1.3;for(const t of shown){ctx.globalAlpha=t.origin==='既知区間の転換'?.28:1;const xs=x(t.signal),ys=y(t.sp),xe=x(t.entry),ye=y(t.ep),xx=x(t.exit),yx=y(t.xp);ctx.strokeStyle='#c47a0c';ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(xs,ys);ctx.lineTo(xe,ye);ctx.stroke();ctx.strokeStyle=t.net>=0?'#087a6580':'#b13b4d80';ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(xe,ye);ctx.lineTo(xx,yx);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#fff7df';ctx.strokeStyle='#c47a0c';ctx.beginPath();ctx.arc(xs,ys,5,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.fillStyle='#175a9a';ctx.beginPath();if(t.side>0){ctx.moveTo(xe,ye);ctx.lineTo(xe-6,ye+13);ctx.lineTo(xe+6,ye+13)}else{ctx.moveTo(xe,ye);ctx.lineTo(xe-6,ye-13);ctx.lineTo(xe+6,ye-13)}ctx.closePath();ctx.fill();ctx.strokeStyle=t.closed?'#a33ea4':'#8c722b';ctx.fillStyle=t.closed?'#a33ea4':'#fff';ctx.beginPath();if(t.closed){ctx.moveTo(xx,yx-6);ctx.lineTo(xx+6,yx);ctx.lineTo(xx,yx+6);ctx.lineTo(xx-6,yx);ctx.closePath()}else ctx.rect(xx-5,yx-5,10,10);ctx.fill();ctx.stroke();targets.push({x:xs,y:ys,kind:'trade',text:`${t.side>0?'上向き':'下向き'}転換の検知\n${t.origin}\n${stamp(t.signal,true)}　${t.sp}\nイベント ${t.event}\nこの検知から１回だけ発注`},{x:xe,y:ye,kind:'trade',text:`${t.side>0?'ロング':'ショート'} 新規約定\n${stamp(t.entry,true)}　${t.ep}\n条件設定 ${stamp(t.condition,true)}\n検知から約定まで ${((t.entry-t.signal)/60).toFixed(1)}分\n固定ATR ${t.atr.toFixed(2)}`},{x:xx,y:yx,kind:'trade',text:`${t.closed?'返済':'未返済の評価'}\n${stamp(t.exit,true)}　${t.xp}\n${t.reason}\n費用後 ${yen(t.net)}万円\n保有 ${t.duration.toFixed(1)}分`})}ctx.globalAlpha=1;ctx.fillStyle='#192e3e';ctx.font='bold 12px system-ui';ctx.textAlign='left';ctx.fillText(`${s.symbol}　${s.session}　５分足／転換検知・生板約定`,pad.l,17)}
/**
 * 機能: マウスに最も近い検知・売買位置を優先して説明を表示する。
 * @param {MouseEvent} event - マウス移動イベント。
 * @returns {void} 返り値なし。
 */
function hover(event){const rect=$('chart').getBoundingClientRect(),xx=event.clientX-rect.left,yy=event.clientY-rect.top,trade=targets.filter(t=>t.kind==='trade').map(t=>({t,d:Math.hypot(t.x-xx,t.y-yy)})).sort((a,b)=>a.d-b.d)[0],nearest=trade&&trade.d<24?trade.t:targets.filter(t=>t.kind==='bar').sort((a,b)=>Math.abs(a.x-xx)-Math.abs(b.x-xx))[0];if(!nearest)return;const tip=$('tooltip');tip.textContent=nearest.text;tip.style.display='block';tip.style.left=Math.max(5,Math.min(xx+14,rect.width-tip.offsetWidth-8))+'px';tip.style.top=Math.max(5,Math.min(yy+14,rect.height-tip.offsetHeight-8))+'px'}
// ----------------------------------------
// 対象選択と画面寸法の変化を登録し、初期表示を行う。
/**
 * 機能: 現在照合は凍結した７条件だけを選べるよう、方式の選択肢を作る。
 * @returns {void} 返り値なし。
 */
function methodOptions(){const previous=$('method').value,live=$('session').value===data.liveSession;const configs=data.conditions.filter(c=>!live||data.liveMethods.includes(c.id));$('method').innerHTML='';for(const group of data.groups){const part=configs.filter(c=>c.group===group);if(!part.length)continue;const opt=document.createElement('optgroup');opt.label=group;opt.innerHTML=part.map(c=>`<option value="${esc(c.id)}">${data.selected[group]===c.id?'★ ':''}${esc(c.id)}</option>`).join('');$('method').append(opt)}$('method').value=configs.some(c=>c.id===previous)?previous:'T12_追跡0.25ATR_追跡2ATR'}
$('session').innerHTML=data.sessions.map(s=>`<option value="${s}">${s===data.liveSession?data.liveLabel:s.replace('_Day',' デイ').replace('_Night',' ナイト')+(s==='2026-09-23_Night'?'（既知19:14まで）':'')}</option>`).join('');$('session').value='2026-09-22_Night';methodOptions();$('method').value='T12_追跡0.25ATR_追跡2ATR';$('session').addEventListener('change',()=>{methodOptions();update()});for(const id of ['symbol','method'])$(id).addEventListener('change',update);$('chart').addEventListener('mousemove',hover);$('chart').addEventListener('mouseleave',()=>$('tooltip').style.display='none');new ResizeObserver(draw).observe($('chart').parentElement);update();
</script></body></html>'''


if __name__ == '__main__':
    main()
