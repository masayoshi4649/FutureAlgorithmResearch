"""生板検証の集計を読み、日本語の報告と自己完結した売買図解を作成する。"""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from model import FAMILIES, MULTIPLIERS, OUT, ROOT, SESSIONS, SYMBOLS

DEST = ROOT / 'アルゴリズム調査' / '00004_生板を使う売買の検証'
DATA = '資料/work/wave_v8/'
GROUPS = ['固定価格条件', '価格のみ', '板のみ', '価格と板', '２銘柄の板']
LABELS = {
    'B01': '最良の買数量と売数量の差を合計で割り、±0.20を超える方向。',
    'B02': '上位５段の買数量と売数量の差を合計で割り、±0.15を超える方向。',
    'B03': '上位10段の買数量と売数量の差を合計で割り、±0.10を超える方向。',
    'B04': '最良数量の偏りから10段数量の偏りを引き、±0.15を超える方向。',
    'B05': '最良買い・売り気配の価格と数量の変化から求めるOFIを集計し、符号付き合計÷絶対値合計が±0.15を超える方向。',
    'B06': '最良買い・売り気配が上がった回数と下がった回数の差を合計で割り、±0.15を超える方向。',
    'B07': '前後の上位５段に共通する価格で増えた買数量と売数量の差を合計で割り、±0.15を超える方向。',
    'B08': '前後の上位５段に共通する価格で減った売数量と買数量の差を合計で割り、±0.15を超える方向。',
    'B09': '買数量増加＋売数量減少を正、売数量増加＋買数量減少を負として合計し、全増減数量で割った値が±0.12を超える方向。',
    'B10': '約定価格の直近変化方向で出来高増分を分類し、正負の差÷出来高全体が±0.20を超える方向。真の買い主導・売り主導を示す情報ではない。',
    'B11': '最良数量の偏りが±0.10、OFI比率が±0.075を超え、両方の方向が一致。',
    'B12': 'OFI比率・気配更新比率・数量純変化比率を各±0.10で分類し、同方向２票以上かつ反対票なし。',
    'P00': '確定１分足の値差をATRで割り、上向き累積=max(0,前値+変化−0.025)、下向き累積=min(0,前値+変化+0.025)。±0.6375到達で方向を更新し、両累積をリセット。逆側に到達するまで方向を保持。',
    'H01': '価格CUSUMの方向と、直近300秒のOFI比率による方向（B05）が一致。',
    'H02': '価格CUSUMの方向と、直近300秒の板フロー多数決（B12）が一致。',
    'C01': '自銘柄と他銘柄の300秒OFI比率（±0.15）の方向が一致。',
    'C02': '自銘柄の60秒OFIと他銘柄の300秒OFI（各±0.15）の方向が一致。',
    'C03': '自銘柄と他銘柄の300秒板フロー多数決（B12）の方向が一致。',
    'C04': '両銘柄の300秒最良数量偏り（±0.20）の方向が一致。',
    'C05': '両銘柄の300秒純数量変化比率（±0.12）の方向が一致。',
    'C06': '自銘柄の価格CUSUMと他銘柄の300秒OFI比率（±0.15）の方向が一致。',
    'C07': '自銘柄の価格CUSUMと他銘柄の300秒板フロー多数決（B12）の方向が一致。',
    'C08': '自銘柄の価格CUSUMと他銘柄の300秒気配更新方向（±0.15）が一致。',
    'C09': '自銘柄の300秒板フロー多数決（B12）を採用。ただし他銘柄の多数決が反対方向なら新規を抑制。',
    'C10': '両銘柄の価格CUSUMと自銘柄の300秒OFI方向がすべて一致。',
    'C11': '他銘柄の300秒板フロー多数決（B12）の方向を自銘柄の新規方向に使う。',
    'C12': '両銘柄のOFI・気配更新・純数量変化（計６票）について、同方向４票以上かつ反対票なし。',
}


def read_json(path: Path) -> object:
    """機能: UTF-8のJSONを読み込む。

    引数: path (Path)。返り値: 保存されている値 (object)。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def money(value: float, plus: bool = False) -> str:
    """機能: 円を読みやすい万円表記へ変換する。

    引数: value (float)、plus (bool)。返り値: 表示文字列 (str)。
    """
    number = float(value) / 10000
    return f'{number:+,.1f}' if plus else f'{number:,.1f}'


def summary(rows: pd.DataFrame) -> list[dict]:
    """機能: 群・銘柄ごとに確定損益と勝率の分母を集計する。

    引数: rows (DataFrame)。返り値: 集計行 (list[dict])。
    """
    result = []
    for group in dict.fromkeys(GROUPS + list(rows.群.unique())):
        for symbol in SYMBOLS:
            part = rows[rows.群.eq(group) & rows.銘柄.eq(symbol)]
            if part.empty:
                continue
            count, wins = int(part.取引数.sum()), int(part.勝ち数.sum())
            result.append(dict(群=group, 銘柄=symbol, 利益円=float(part.利益円.sum()),
                損失円=float(part.損失円.sum()), 収支円=float(part.収支円.sum()),
                費用倍収支円=float(part.費用倍収支円.sum()), 取引数=count, 勝ち数=wins,
                勝率=None if count == 0 else 100 * wins / count,
                未返済数=int(part.未返済数.sum()), 評価損益円=float(part.評価損益円.sum())))
    return result


def table(records: list[dict], include_session: bool = False) -> str:
    """機能: 確定利益・損失・収支と未返済を分けたHTML表を作る。

    引数: records (list[dict])、include_session (bool)。返り値: HTML (str)。
    """
    columns = [('群', '方式の群'), ('銘柄', '銘柄')]
    if include_session:
        columns = [('セッション', 'セッション'), ('銘柄', '銘柄'), ('群', '方式の群')]
    columns += [('利益円', '利益'), ('損失円', '損失'), ('収支円', '差引'),
                ('勝率', '勝ち／返済済み'), ('費用倍収支円', '追加費用４tick'), ('未返済', '未返済／評価損益')]
    rows = []
    for record in records:
        cells = []
        for key, _ in columns:
            style = ''
            if key.endswith('円'):
                value = money(record.get(key, 0), key != '利益円' and key != '損失円')
                if key in ['収支円', '費用倍収支円']:
                    style = ' class="pos"' if record.get(key, 0) > 0 else ' class="neg"' if record.get(key, 0) < 0 else ''
            elif key == '勝率':
                wins, count = int(record['勝ち数']), int(record['取引数'])
                value = f'{wins} / {count}' + (f'（{100*wins/count:.1f}%）' if count else '')
            elif key == '未返済':
                value = f'{int(record.get("未返済数", 0))} / {money(record.get("評価損益円", 0), True)}'
            else:
                value = html.escape(str(record.get(key, '')))
            cells.append(f'<td{style}>{value}</td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{v}</th>' for _, v in columns) + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'


def method_description(config: dict) -> str:
    """機能: 条件辞書から入口と出口を含む説明を作る。

    引数: config (dict)。返り値: 日本語の説明 (str)。
    """
    family = config['family']
    basis = LABELS.get(family, config.get('description', config.get('説明', FAMILIES.get(family, family))))
    window = config.get('window', 0)
    if family.startswith('B'):
        basis += f' 直近{window}秒に解放された板ブロックを集計し、その方向が30秒継続してから有効。'
    if family.startswith('C'):
        basis += ' 各板方向は30秒継続を確認。他銘柄は解放から60秒遅らせ、方向更新時の情報年齢180秒以内を参照する。方向を次の自特徴まで最大60秒保持するため新規条件作成時は最大240秒前の情報になりうる。発注後の中立化では取消せず、実約定時の方向一致は要求しない。受信時刻の同期は保証できない。'
    entry = '買いでは売り気配を安値追跡し、そこから発注時ATRの１倍だけ上昇したら新規。売りでは買い気配を高値追跡し、１ATR反落したら新規。' if config['entry'] == '追跡1ATR' else '条件作成時の売り気配を買い逆指値、買い気配を売り逆指値の閾値にする。次の観測以降で条件成立を確認する。'
    exit_text = '初期損切り2.5ATR、追跡幅4ATR。約定後に観測した最大順行が2.5ATRへ到達したら追跡幅を0.5ATRへ縮める。ストップは緩めない。'
    if config['exit'] == '板反転併用':
        exit_text += ' 加えて300秒OFIと気配更新がともに逆方向で60秒続いたら返済。'
    return basis + ' ' + entry + ' ' + exit_text


def candles() -> dict:
    """機能: 図解用の確定５分足を保存データから読み出す。

    引数: なし。返り値: 銘柄・セッション別の足配列 (dict)。
    """
    result = {}
    for symbol in SYMBOLS:
        for session in SESSIONS:
            root = ROOT / 'work' / 'wave_v7' / 'live' if session == SESSIONS[-1] else ROOT
            frame = pd.read_csv(root / 'candle_5min' / symbol / f'{session}.csv')
            frame = frame[frame.closed.astype(str).str.lower().eq('true')]
            result[f'{symbol}|{session}'] = [[pd.Timestamp(r.time).timestamp(), r.open, r.high, r.low, r.close] for r in frame.itertuples()]
    return result


def copy_materials() -> list[dict]:
    """機能: 小さい再現資料と入力足を元の相対構造のまま複製する。

    引数: なし。返り値: 複製ファイルの相対パス・SHA256一覧 (list[dict])。
    """
    archive = DEST / '資料'
    targets = list(OUT.glob('*.py')) + list(OUT.glob('*.md')) + list(OUT.glob('*.json')) + list(OUT.glob('*.csv'))
    targets += list((OUT / 'features').glob('*.npz')) + list((OUT / 'features').glob('*.csv')) + list((OUT / 'features').glob('*.json'))
    dependency = ROOT / 'アルゴリズム調査' / '00001_波検知と売買ポイントの調査' / '保存版' / 'work' / 'wave_v4' / 'signals.py'
    targets.append(dependency)
    for symbol in SYMBOLS:
        for session in SESSIONS:
            source = ROOT / 'work' / 'wave_v7' / 'live' if session == SESSIONS[-1] else ROOT
            for interval in [1, 5]:
                targets.append(source / f'candle_{interval}min' / symbol / f'{session}.csv')
    manifest = []
    for source in sorted(set(targets)):
        relative = source.relative_to(ROOT)
        target = archive / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest.append(dict(ファイル=str(relative).replace('\\', '/'), SHA256=hashlib.sha256(target.read_bytes()).hexdigest(), バイト=target.stat().st_size))
    (archive / '資料一覧とSHA256.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def load_cross(base: str) -> Path | None:
    """機能: 二銘柄検証の対応する結果ファイルを検出する。

    引数: base (str)。返り値: 存在するファイルまたはなし (Path|None)。
    """
    for name in [f'二銘柄_{base}', f'二銘柄{base}']:
        path = OUT / name
        if path.exists():
            return path
    return None


def wave_table(trades: list[dict], selected: dict) -> str:
    """機能: 指定された４波と同方向の保有区間が重なる時間を事後照合する。

    引数: trades (list[dict])、selected (dict)。返り値: 照合結果HTML (str)。
    """
    waves = [('9/21デイ ロング', SESSIONS[0], '2026-09-21 10:45', '2026-09-21 15:35', 1),
             ('9/22デイ ショート', SESSIONS[2], '2026-09-22 09:20', '2026-09-22 11:45', -1),
             ('9/23デイ ショート', SESSIONS[4], '2026-09-23 09:05', '2026-09-23 11:15', -1),
             ('9/22ナイト ロング', SESSIONS[3], '2026-09-23 00:40', '2026-09-23 03:20', 1)]
    rows, html_rows = [], []
    for name, session, from_time, to_time, direction in waves:
        start, end = [pd.Timestamp(t, tz='Asia/Tokyo').timestamp() for t in [from_time, to_time]]
        for group, method in selected.items():
            for symbol in SYMBOLS:
                matches = sorted([t for t in trades if t['方式'] == method and t['セッション'] == session and t['銘柄'] == symbol and t['side'] == direction and t['entry_time_s'] < end and t.get('exit_time_s', t.get('mark_time_s', 0)) > start], key=lambda t: t['entry_time_s'])
                held = sum(max(0, min(end, t.get('exit_time_s', t.get('mark_time_s', 0))) - max(start, t['entry_time_s'])) for t in matches)
                first = matches[0] if matches else None
                entry = pd.Timestamp(first['entry_time_s'], unit='s', tz='Asia/Tokyo').strftime('%H:%M:%S') if first else 'なし'
                overlap = pd.Timestamp(max(start, first['entry_time_s']), unit='s', tz='Asia/Tokyo').strftime('%H:%M:%S') if first else 'なし'
                row = dict(指定波=name, 群=group, 銘柄=symbol, 方式=method, 新規時刻=entry, 重複開始=overlap, 保有割合=100*held/(end-start), 波内保有分=held/60)
                rows.append(row)
                html_rows.append(f'<tr><td>{name}</td><td>{group}</td><td>{symbol}</td><td>{entry}</td><td>{overlap}</td><td>{row["保有割合"]:.1f}%</td><td>{held/60:.1f}</td></tr>')
    pd.DataFrame(rows).to_csv(OUT / '指定４波照合.csv', index=False, encoding='utf-8-sig')
    return '<div class="scroll"><table><thead><tr><th>指定波</th><th>方式の群</th><th>銘柄</th><th>最初の新規</th><th>波との重複開始</th><th>同方向保有割合</th><th>波内保有分</th></tr></thead><tbody>' + ''.join(html_rows) + '</tbody></table></div>'


def delay_table(cells: pd.DataFrame, selected: dict) -> str:
    """機能: 同じ固定候補の気配約定遅延による収支変化を集計する。

    引数: cells (DataFrame)、selected (dict)。返り値: HTML表 (str)。
    """
    frames = [cells, pd.read_csv(OUT / '約定遅延感度.csv')]
    cross = load_cross('約定遅延感度.csv')
    if cross:
        frames.append(pd.read_csv(cross))
    merged = pd.concat(frames, ignore_index=True)
    rows = []
    for group, method in selected.items():
        for symbol in SYMBOLS:
            for delay in ['次行', '２行後', '次時刻']:
                part = merged[merged.方式.eq(method) & merged.銘柄.eq(symbol) & merged.セッション.isin(SESSIONS[:5]) & merged.約定遅延.eq(delay)]
                if part.empty:
                    continue
                net = part.収支円.sum()
                rows.append(f'<tr><td>{group}</td><td>{symbol}</td><td>{delay}</td><td class="{"pos" if net>=0 else "neg"}">{money(net, True)}</td><td>{part.取引数.sum()}</td></tr>')
    return '<div class="scroll"><table><thead><tr><th>方式の群</th><th>銘柄</th><th>約定待機</th><th>差引万円</th><th>返済済取引</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'


def review_notes(cells: pd.DataFrame, selected: dict) -> tuple[str, str]:
    """機能: 遅延感度と未来非依存監査の要点を集計値から生成する。

    引数: cells (DataFrame)、selected (dict)。返り値: HTMLとMarkdownの補足 (tuple[str, str])。
    """
    paragraphs = []
    selected_board = selected.get('板のみ')
    delay = pd.read_csv(OUT / '約定遅延感度.csv')
    if selected_board:
        for symbol in SYMBOLS:
            original = cells[cells.方式.eq(selected_board) & cells.銘柄.eq(symbol) & cells.セッション.isin(SESSIONS[:5])].収支円.sum()
            slow = delay[delay.方式.eq(selected_board) & delay.銘柄.eq(symbol) & delay.セッション.isin(SESSIONS[:5]) & delay.約定遅延.eq('次時刻')].収支円.sum()
            paragraphs.append(f'板の探索候補 {selected_board} の{symbol}は、基本約定で{money(original, True)}万円、次の異なる最終約定時刻まで待つと{money(slow, True)}万円。')
    cross_path = load_cross('時計遅延感度.csv')
    cross_id = selected.get('２銘柄の板')
    if cross_path and cross_id:
        clock = pd.read_csv(cross_path)
        for symbol in SYMBOLS:
            results = []
            for lag in [60, 120, 300]:
                subset = cells[cells.方式.eq(cross_id) & cells.銘柄.eq(symbol) & cells.セッション.isin(SESSIONS[:5])] if lag == 60 else clock[clock.方式.eq(cross_id) & clock.銘柄.eq(symbol) & clock.セッション.isin(SESSIONS[:5]) & clock.他銘柄追加待機秒.eq(lag)]
                results.append(f'{lag}秒参照待機 {money(subset.収支円.sum(), True)}万円')
            paragraphs.append(f'二銘柄の探索候補 {cross_id} の{symbol}：' + '、'.join(results) + '。')
    audit = read_json(OUT / '売買未来非依存監査.json')
    raw = read_json(OUT / '生板未来非依存監査.json')
    paragraphs.append(f'生原本を途中で打ち切った{len(raw["途中打切り"])}組で過去の特徴と全気配が一致。別途、代表{audit["監査条件数"]}条件・{audit["照合セル数"]}セルでATR、方向、過去の確定取引が一致した。確定取引照合は延べ{audit["確定取引照合延べ数"]}件で、独立取引数ではない。')
    cross_audit_path = OUT / '二銘柄_独立因果監査.json'
    if cross_audit_path.exists():
        cross_audit = read_json(cross_audit_path)
        paragraphs.append(f'２銘柄の独立監査は{cross_audit["照合セル数"]}セル、過去の確定取引は延べ{cross_audit["確定取引照合延べ数"]}件を照合。自銘柄・相手銘柄を別々に途中で打ち切っても、過去の方向と確定取引が一致した。')
    paragraphs.append('２銘柄の未来側の価格・数量を変えても、それ以前の12方向と確定取引が変わらないことを別途確認。これらは保存行順に対する監査であり、実際にその時刻に受信済みだったことや実約定を証明しない。')
    paragraphs.append('全156条件×２銘柄×６セッション＝1,872セルを全取引から再集計し不一致なし。前回凍結した75ファイルのSHA256も一致し、前回の検証資料は変更していない。')
    paragraphs.append('逆向きシグナルで新規条件を取り消す行で、旧閾値にも到達していた場合は取消を優先する仮定。実APIの取消遅延、成立との競合、部分約定は再現していない。')
    collision_path = OUT / '取消成立競合監査.json'
    if collision_path.exists():
        collision = read_json(collision_path)
        paragraphs.append(f'採用対象{len(collision["対象条件"])}方式・{collision["対象セル数"]}セルでは、同じ生板行で反対方向取消と旧新規閾値が同時に成立した件数は{collision["同時成立延べ件数"]}件だった。この観測は実APIの競合が将来も発生しないことを意味しない。')
    paragraphs.append('今回の比較では、板を追加するだけで既存の固定価格条件を安定して上回る証拠は得られていない。板数量減少の偏りは検証候補として残すが、受信時刻付きの別期間で効果を確認するまで、常に必須の新規条件・返済条件として採用する根拠は不足している。')
    markup = ''.join(f'<p>{html.escape(p)}</p>' for p in paragraphs)
    return markup, '\n\n'.join(paragraphs)


def main() -> None:
    """機能: 集計・図解・説明・再現資料を同一作業フォルダへ生成する。

    引数: なし。返り値: なし (None)。
    """
    DEST.mkdir(parents=True, exist_ok=True)
    cell_frames = [pd.read_csv(OUT / '全条件セッション集計.csv')]
    forward_frames = [pd.read_csv(OUT / '時間順セッション集計.csv')]
    trade_rows = read_json(OUT / '全取引.json')
    selections = read_json(OUT / '時間順選択.json')
    finalists = read_json(OUT / '既知５セッション選択.json')
    conditions = read_json(OUT / '条件一覧.json')
    for base, target in [('全条件セッション集計.csv', cell_frames), ('時間順セッション集計.csv', forward_frames)]:
        source = load_cross(base)
        if source:
            target.append(pd.read_csv(source))
    for base, target in [('全取引.json', trade_rows), ('時間順選択.json', selections), ('条件一覧.json', conditions)]:
        source = load_cross(base)
        if source:
            target.extend(read_json(source))
    source = load_cross('既知５セッション選択.json')
    if source:
        finalists.update(read_json(source))
    cells, forward = pd.concat(cell_frames, ignore_index=True), pd.concat(forward_frames, ignore_index=True)
    conditions_by_id = {c['id']: c for c in conditions}
    for config in conditions:
        config['description'] = method_description(config)
    fixed_id = 'P00_0_追跡1ATR_利益保護'
    baseline_all = cells[cells.方式.eq(fixed_id)].copy()
    baseline_all['群'] = '固定価格条件'
    historical = pd.concat([baseline_all[baseline_all.セッション.isin(SESSIONS[2:5])], forward[forward.セッション.isin(SESSIONS[2:5])]], ignore_index=True)
    hist_summary = summary(historical)
    partial = pd.concat([baseline_all[baseline_all.セッション.eq(SESSIONS[-1])], forward[forward.セッション.eq(SESSIONS[-1])]], ignore_index=True)
    partial_summary = summary(partial)
    selected_ids = {'固定価格条件': fixed_id, **{group: value['採用']['方式'] for group, value in finalists.items() if value.get('採用')}}
    selected_cells = pd.concat([cells[cells.方式.eq(method) & cells.セッション.isin(SESSIONS[:5])].assign(群=group) for group, method in selected_ids.items()], ignore_index=True)
    all_summary = summary(selected_cells)
    baseline = cells[cells.方式.eq('P00_0_追跡1ATR_利益保護') & cells.セッション.isin(SESSIONS[:5])]
    # ----------------------------------------
    # 時間順成績と既知期間での候補探索は別表にする。
    conclusion = '板で方向を判断し、ATRで注文幅を決める機械的アルゴリズムを検証した。LSTMは使っていない。以下は保存済みデータでの再検証であり、将来の利益を確認した結果ではない。'
    group_net = {group: historical[historical.群.eq(group)].収支円.sum() for group in GROUPS if (historical.群 == group).any()}
    if '板のみ' in group_net and '固定価格条件' in group_net:
        relation = '上回った' if group_net['板のみ'] > group_net['固定価格条件'] else '下回った' if group_net['板のみ'] < group_net['固定価格条件'] else '同額だった'
        conclusion += f' ３セッションの確定収支合計は、時間順で選んだ板のみが{money(group_net["板のみ"], True)}万円、従来の固定価格条件が{money(group_net["固定価格条件"], True)}万円で、板のみは固定価格条件を{relation}。'
    if '２銘柄の板' in group_net:
        conclusion += f' ２銘柄の板を併用した群は{money(group_net["２銘柄の板"], True)}万円。'
    descriptions = ''.join(f'<article class="method"><small>{html.escape(group)}：{"従来から固定した参照" if group == "固定価格条件" else "既知５セッションで選んだ候補"}</small><h3>{html.escape(method)}</h3><p>{html.escape(conditions_by_id[method]["description"])}</p></article>' for group, method in selected_ids.items())
    sequence_rows = []
    for item in selections:
        adopted = item.get('採用')
        sequence_rows.append(f'<tr><td>{html.escape(item["群"])}</td><td>{len(item["学習"])}セッション</td><td>{html.escape(item["評価セッション"])}</td><td>{html.escape(adopted["方式"] if adopted else "なし")}</td></tr>')
    sequence_table = '<div class="scroll"><table><thead><tr><th>群</th><th>候補選択に使う過去</th><th>次の評価</th><th>採用条件</th></tr></thead><tbody>' + ''.join(sequence_rows) + '</tbody></table></div>'
    compact_trades = []
    for row in trade_rows:
        compact_trades.append(dict(method=row['方式'], session=row['セッション'], symbol=row['銘柄'], side=row['side'],
            entry=row['entry_time_s'], ep=row['entry_price'], exit=row.get('exit_time_s', row.get('mark_time_s')),
            xp=row.get('exit_price', row.get('mark_price')), closed=row['closed'], net=row['net_points'] * MULTIPLIERS[row['銘柄']],
            atr=row['atr'], reason=row.get('exit_reason', '未返済・評価値'), duration=row['duration_min']))
    payload = dict(candles=candles(), trades=compact_trades, cells=json.loads(cells.to_json(orient='records', force_ascii=False)),
                   conditions=conditions, selected=selected_ids, sessions=SESSIONS, groups=GROUPS)
    content = HTML.replace('__CONCLUSION__', html.escape(conclusion)).replace('__COUNT__', str(len(conditions)))
    content = content.replace('__HISTORICAL__', table(hist_summary)).replace('__PARTIAL__', table(partial_summary))
    content = content.replace('__EXPLORATORY__', table(all_summary)).replace('__BASELINE__', table(summary(baseline)))
    content = content.replace('__SEQUENCE__', sequence_table).replace('__DESCRIPTIONS__', descriptions)
    content = content.replace('__WAVES__', wave_table(trade_rows, selected_ids)).replace('__DELAYS__', delay_table(cells, selected_ids))
    ablation = pd.concat([baseline.assign(群='固定価格・利益保護'), cells[cells.方式.eq('P00_0_追跡1ATR_板反転併用') & cells.セッション.isin(SESSIONS[:5])].assign(群='同入口・板反転を追加')], ignore_index=True)
    content = content.replace('__EXIT_COMPARISON__', table(summary(ablation)))
    cross_links = ''
    if load_cross('全条件セッション集計.csv'):
        cross_links = '<p><a href="資料/work/wave_v8/二銘柄_全条件セッション集計.csv">二銘柄48条件・全セッション集計CSV</a> ／ <a href="資料/work/wave_v8/二銘柄_全取引.csv">二銘柄・全取引CSV</a> ／ <a href="資料/work/wave_v8/二銘柄_時計遅延感度.csv">相手銘柄の参照遅延60/120/300秒</a> ／ <a href="資料/work/wave_v8/二銘柄検証計画.md">二銘柄の追加計画</a></p>'
    content = content.replace('__CROSS_LINKS__', cross_links)
    content = content.replace('<div id="cross-links"></div>', cross_links)
    content = content.replace('<section id="chart-section">', '<section><h2>指定された４つの波との照合</h2><p>既知５セッションで選んだ代表条件と、従来の固定価格条件を照合。これは指定波との事後比較で、未来の波を売買条件や候補選択には使っていません。保有割合は、その時間帯のうち同方向の建玉を持っていた時間の割合です。</p><details><summary>２銘柄・４波の新規時刻と同方向の保有時間</summary>' + wave_table(trade_rows, selected_ids) + '</details></section><section id="chart-section">')
    content = content.replace('<section id="materials">', '<section><h2>同じ入口で、板を返済に加える効果</h2><p>既知５セッション、価格CUSUM＋１ATR追跡新規を共通にし、出口だけを比較。板を加えれば必ず改善するわけではありません。</p>' + table(summary(ablation)) + '<h2 style="margin-top:26px">約定を遅らせた場合</h2><p>同じ固定候補を既知５セッションへ適用。次行が基本、２行後はさらに１行待機、次時刻は最終約定時刻が変わるまで待機します。実際の受信遅延を秒で再現した試験ではありません。</p><details><summary>方式・銘柄ごとの約定遅延感度</summary>' + delay_table(cells, selected_ids) + '</details></section><section id="materials">')
    content = content.replace('<section id="historical"><h2>', '<section id="historical"><p class="notice">「固定価格条件」は従来のCUSUM＋１ATR追跡新規＋利益保護を選び直さず適用した参照です。「価格のみ」は価格群４候補から過去の成績で選び直した条件で、両者を区別してください。「板のみ」は方向判定が板由来で、注文幅は５分足ATRを使います。</p><h2>')
    review_html, review_md = review_notes(cells, selected_ids)
    content = content.replace('<section id="materials">', '<section><h2>感度・監査から分かること</h2>' + review_html + '<p><a href="資料/work/wave_v8/売買未来非依存監査.json">売買の原本打切り監査</a> ／ <a href="資料/work/wave_v8/二銘柄_独立因果監査.json">二銘柄の独立監査</a> ／ <a href="資料/work/wave_v8/二銘柄_未来改変監査.json">二銘柄の未来改変監査</a> ／ <a href="資料/work/wave_v8/前回資料不変確認.json">前回資料の不変確認</a></p></section><section id="materials">')
    content = content.replace('__PAYLOAD__', json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/'))
    (DEST / '板を使う売買の検証.html').write_text(content, encoding='utf-8')
    write_markdown(conclusion, hist_summary, partial_summary, selected_ids, conditions_by_id, selections, all_summary, len(conditions))
    report_path = DEST / '検証結果.md'
    report_path.write_text(report_path.read_text(encoding='utf-8') + '\n## 同じ入口での出口比較\n\n既知５セッション、価格CUSUM＋１ATR追跡新規を固定し出口だけ変更。\n\n' + markdown_table(summary(ablation)) + '\n\n## 感度と監査\n\n' + review_md + '\n', encoding='utf-8')
    manifest = copy_materials()
    print(f'{DEST}：{len(conditions)}条件、{len(compact_trades)}取引記録、再現資料{len(manifest)}ファイル', flush=True)


def markdown_table(rows: list[dict]) -> str:
    """機能: 要点の損益表をMarkdownへ変換する。

    引数: rows (list[dict])。返り値: Markdown (str)。
    """
    lines = ['| 群 | 銘柄 | 利益万円 | 損失万円 | 差引万円 | 勝ち/返済済 | 費用倍万円 | 未返済評価万円 |', '|---|---|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f'| {row["群"]} | {row["銘柄"]} | {money(row["利益円"])} | {money(row["損失円"])} | {money(row["収支円"], True)} | {row["勝ち数"]}/{row["取引数"]} | {money(row["費用倍収支円"], True)} | {money(row["評価損益円"], True)} |')
    return '\n'.join(lines)


def write_markdown(conclusion: str, history: list, partial: list, selected: dict, conditions: dict, selections: list, exploratory: list, count: int) -> None:
    """機能: 結果・具体条件・読む順序を日本語Markdownで保存する。

    引数: conclusion (str)、history/partial/selections/exploratory (list)、selected/conditions (dict)、count (int)。
    返り値: なし (None)。
    """
    method_text = '\n\n'.join(f'### {group}：{method}\n\n{conditions[method]["description"]}' for group, method in selected.items())
    report = f'''# 生板を使う売買の検証

{conclusion}

最初に [板を使う売買の検証.html](板を使う売買の検証.html) を開くと、セッション別収支と５分足上の売買位置を確認できる。

## 時間順で選んだ条件の比較

既知データの再評価。最初の２セッションで条件を選び３番目、最初の３つで選び４番目、最初の４つで選び５番目を評価した。対象は9/22デイ・9/22ナイト・9/23デイ。「固定価格条件」は従来のCUSUM＋１ATR追跡新規＋利益保護を選び直さず適用した参照。各銘柄ラージ１枚。実際の売買気配差を負担し、さらに往復２tickを追加費用として引く。表の勝率は費用後の確定取引勝率であり、方向予測の正答率ではない。「板のみ」は方向判定が板由来という意味で、注文幅は確定５分足ATRを使う。

{markdown_table(history)}

## 前回取得済み9/23ナイト19:14まで

今回は既知データであり、未見検証と呼ばない。５セッションで選んだ条件を使用。未返済の評価損益を確定収支に加えない。新API取得は０回。

{markdown_table(partial)}

## 既知５セッションで選んだ候補

固定価格条件を除き、以下は同じ５セッションで候補を選び、その５セッションの成績も示す探索結果。時間順の成績より楽観的になりうる。

{markdown_table(exploratory)}

{method_text}

## 共通の注文条件

- 生JSONLの行順に処理する。同じ最終約定時刻の連続行を、次の異なる時刻の先頭行が来てから方向判定に使う。注文とストップは全ての有効気配で監視する。
- 条件成立行で即時約定せず、次の有効気配へ進んでから買いは売り気配、売りは買い気配で１枚約定する仮定。指値の待ち順や注文IDは復元しない。
- ATRは確定５分足のTRの指数平均（係数1/12、３本以上、最低２tick）。確定からさらに１分待つ。新規条件を作った時点のATRを固定し、将来の最大値や極値は使わない。
- 新規条件は25分超で失効。逆方向シグナルで取消。中立では保持。同じ行で取消と旧条件成立が競合した場合は取消を優先する。実APIの取消遅延・部分約定は再現していない。開始45分後から新規、返済後45分休止。各銘柄１枚まで。
- 15:05／翌05:20以降は新規禁止。15:35／翌05:50以降の最初の有効行で返済要求し、次の有効行で返済。完全セッションは持越しなし。途中データは未返済を明記。
- 買い／売りの気配差に加え往復２tickを費用とし、追加費用４tickと約定を２行後／次の異なる時刻へ遅らせた感度も保存する。

## 調べた候補と限界

合計{count}条件。単独板12系統×60秒／300秒×入口２×出口２で96、価格CUSUM４、価格と板８。２銘柄の追加48条件を同じ作業にまとめる。全条件の利益・損失・差引は [基本108条件](資料/work/wave_v8/全条件セッション集計.csv) と [二銘柄48条件](資料/work/wave_v8/二銘柄_全条件セッション集計.csv) を参照。

最良数量だけを使う加重価格の偏りは最良数量偏りと同じ情報なので、独立した手法として数を増やしていない。数量増減は表示された残数量の変化であり、新規・取消・約定を区別できない。出来高の正負も直前価格変化による推定。受信時刻がなく、秒数は最終約定時刻を代用している。

直近60／300秒という窓は、直近のその期間に解放された板ブロックの集計であり、厳密にその秒数内に受信した全イベントの集合ではない。

２銘柄間の先行・遅行を正確な受信時刻で再現できないため、相手銘柄は60秒遅らせて参照する。方向更新時の情報年齢上限180秒、方向の保持は最大60秒のため、新規条件作成時の相手情報は最大240秒前。中立では既存の新規条件を保持し、実約定時に再び両方向一致することは要求していない。参照遅延120／300秒も比較した。今後採用する場合もまず方向確認や新規抑制の条件として位置づけ、既存ストップは相手銘柄が更新されなくても独立に動かす必要がある。

[指定４波の事後照合CSV](資料/work/wave_v8/指定４波照合.csv) は、ユーザーが示した時間帯と同方向の保有が重なった割合。指定した未来の波はアルゴリズムの条件選択や売買判定には使用していない。

OFIを使う発想の参考は [Cont・Kukanov・Stoikovの原論文](https://arxiv.org/abs/1011.6402)。米国株の研究であり、今回のOSE先物で利益が出ることを裏付けるものではない。

## 再現

資料フォルダにコード・必要な１分足／５分足・抽出済み板特徴・全気配配列・集計・監査・SHA256一覧を保存した。numpy／pandasを使えるPythonで、資料フォルダを作業ディレクトリとして `python -X utf8 work/wave_v8/research.py` を実行すると基本108条件を再計算できる。二銘柄は `python -X utf8 work/wave_v8/cross_research.py`。生原本からの再抽出／原本打切り監査には元のbookフォルダが必要で、巨大な原本はここへ重複保存していない。
'''
    (DEST / '検証結果.md').write_text(report, encoding='utf-8')
    readme = '''# 00004 生板を使う売買の検証

最初に **[板を使う売買の検証.html](板を使う売買の検証.html)** を開いてください。

読む順序：

1. HTML冒頭の時間順比較：価格のみ・板のみ・価格と板・２銘柄の板を比較。
2. HTMLの５分足図解：銘柄・セッション・方式を選び、入場と返済の位置を確認。下の表に各セッションの利益・損失・差引。
3. [検証結果.md](検証結果.md)：具体的な入口・出口・費用・評価上の限界。
4. [検証計画](資料/work/wave_v8/検証計画.md)・[板特徴の作成方法](資料/work/wave_v8/板特徴の作成方法.md)：事前条件と生板の扱い。
5. [全条件セッション集計](資料/work/wave_v8/全条件セッション集計.csv)・[全取引](資料/work/wave_v8/全取引.csv)・[約定遅延感度](資料/work/wave_v8/約定遅延感度.csv)：詳細な数値。
6. [資料一覧とSHA256](資料/資料一覧とSHA256.json)：再現資料、監査、追加の二銘柄資料一覧。

今回のAPI取得は０回。保存５セッションと前回取得済み9/23ナイト19:14までを再検証しています。既知データでの候補探索と時間順再評価、確定収支と未返済評価を分けています。

[全作業の一覧へ](../index.html)
'''
    (DEST / 'README.md').write_text(readme, encoding='utf-8')


HTML = r'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>00004 生板を使う売買の検証</title>
<style>
:root{--bg:#f3f5f8;--ink:#182737;--muted:#526172;--line:#dce3eb;--blue:#155fb5;--green:#0a735f;--red:#b13243}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.75 system-ui,"Yu Gothic",sans-serif}main{max-width:1320px;margin:auto;padding:28px 24px 60px}a{color:var(--blue)}header{padding:18px 0 26px}h1{font-size:32px;line-height:1.4;margin:10px 0 16px}h2{font-size:23px;margin:0 0 15px}h3{font-size:16px;overflow-wrap:anywhere}p{margin:10px 0}.eyebrow{color:var(--blue);letter-spacing:.08em;font-weight:700}.lead{font-size:17px;max-width:1120px}.tags{display:flex;gap:8px;flex-wrap:wrap;margin-top:15px}.tag{border:1px solid #c4d5e8;background:#eaf2fb;color:#204f80;border-radius:30px;padding:3px 12px;font-size:13px}section{background:white;border:1px solid var(--line);border-radius:14px;margin:20px 0;padding:24px}.note{color:var(--muted);font-size:13px}.notice{background:#fff7e7;border-left:4px solid #c8871d;padding:12px 16px;color:#704b13}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums;white-space:nowrap}th,td{text-align:right;padding:10px 12px;border-bottom:1px solid var(--line)}th{background:#f1f5f9;color:#41536a}th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}td.pos,.pos{color:var(--green);font-weight:650}td.neg,.neg{color:var(--red);font-weight:650}.controls{display:flex;flex-wrap:wrap;gap:14px;align-items:end;padding:8px 0 20px}.controls label{font-size:13px;color:var(--muted);display:grid;gap:5px}.controls select{font:inherit;font-size:14px;padding:9px 11px;border:1px solid #bfcddd;border-radius:7px;background:white;max-width:100%;color:var(--ink)}.controls .wide{flex:1;min-width:280px}.chartbox{position:relative;width:100%;height:470px;background:#fcfdff;border:1px solid var(--line);border-radius:8px;overflow:hidden}canvas{display:block;width:100%;height:100%}.tooltip{position:absolute;pointer-events:none;background:#182737ed;color:white;max-width:320px;min-width:160px;font-size:12px;padding:10px 13px;border-radius:8px;box-shadow:0 8px 22px #0002;display:none;z-index:2;white-space:pre-line}.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;margin:10px 0;color:var(--muted)}.explain{border-left:3px solid #7ba0ca;padding:9px 14px;background:#f5f8fc;margin:15px 0}.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.method{border:1px solid var(--line);border-radius:9px;padding:16px}.method small{color:var(--blue)}details{margin:15px 0}summary{cursor:pointer;font-weight:650}code{background:#eaf0f6;padding:2px 5px;border-radius:4px}nav{display:flex;gap:20px;flex-wrap:wrap;margin:20px 0}.metrics{display:flex;gap:20px;flex-wrap:wrap;margin:12px 0}.metrics b{font-size:21px}.metrics span{font-size:12px;color:var(--muted)}.trade-table{max-height:340px;overflow:auto}.trade-table thead{position:sticky;top:0}footer{font-size:13px;color:var(--muted)}@media(max-width:760px){main{padding:18px 12px}section{padding:17px}h1{font-size:26px}.cards{grid-template-columns:1fr}.chartbox{height:380px}.controls .wide{min-width:100%}}
</style></head><body><main>
<!--
[コンポーネント概要]
#historical は直前までのセッションで条件を選んだ確定収支の比較です。
#symbol、#session、#method は図解対象を選択します。
#chart は確定５分足と生板で再生した入場・返済を描画するcanvasです。
#tooltip は観測時刻・価格・費用後損益を示します。将来極値を使う判定は行いません。
#session-metrics と #trades は表示対象の確定損益・未返済と取引一覧を区別します。
#method-sessions は選択した同一条件の全セッションの利益・損失・差引です。
-->
<header><div class="eyebrow">調査 00004 ／ 保存された生板の検証</div><h1>板の変化を、エントリーと返済の条件にする</h1><p class="lead">__CONCLUSION__</p><div class="tags"><span class="tag">__COUNT__ 条件を比較</span><span class="tag">NK225・TOPIX ラージ各１枚</span><span class="tag">今回のAPI取得 ０回</span><span class="tag">完了セッションは持越しなし</span></div><nav><a href="#historical">時間順の比較</a><a href="#chart-section">５分足と売買位置</a><a href="#rules">具体的な条件</a><a href="#materials">全データ・監査</a><a href="../index.html">作業一覧</a></nav></header>
<section id="historical"><h2>直前までの期間で選び、次のセッションで比較</h2><p>最初の２セッションで選択 → 9/22デイ、３つで選択 → 9/22ナイト、４つで選択 → 9/23デイ。条件選択には評価対象セッションの損益を入れません。研究全体としては既知データの再評価です。</p><p class="note">金額は万円。利益・損失は各取引の費用後収支の正負を別々に合計。差引＝利益−損失。勝率は返済済み取引の勝率で、方向予測正答率ではありません。</p>__HISTORICAL__<p class="note">売買気配差を負担したうえで往復２tickを追加控除。「追加費用４tick」は追加部分を倍にした場合。無取引を最優秀に選ぶ方式は採用していません。</p><details><summary>各回に選ばれた条件</summary>__SEQUENCE__</details></section>
<section><h2>9/23ナイト 19:14までの参考結果</h2><p>前回取得した途中データです。今回は既知であり、未見の試験ではありません。５セッションで選んだ条件を適用しています。</p>__PARTIAL__<p class="notice">未返済は最終気配での評価損益です。確定収支・勝率には含めていません。評価値にも返済を仮定した往復追加費用を見込んでいます。</p></section>
<section id="chart-section"><h2>５分足上で、入場と返済を確認する</h2><p>足は位置を見るための表示です。売買判定とストップ監視には、保存された生板の行順を使っています。</p><div class="controls"><label>銘柄<select id="symbol"><option>NK225</option><option>TOPIX</option></select></label><label>セッション<select id="session"></select></label><label class="wide">方式<select id="method"></select></label></div><div class="chartbox"><canvas id="chart" aria-label="５分足と新規・返済の位置"></canvas><div class="tooltip" id="tooltip"></div></div><div class="legend"><span style="color:#155fb5">▲ ロング新規 ／ ▼ ショート新規</span><span style="color:#ad3ca4">◆ 返済</span><span style="color:#b27719">○ 未返済の評価</span><span>マウスを重ねると時刻・価格・収支</span></div><div id="session-metrics" class="metrics"></div><p id="method-description" class="explain"></p><div class="trade-table" id="trades"></div><details open><summary>この条件の各セッションの利益・損失・差引</summary><p class="note">同じ条件を全セッションに適用した表です。上の時間順の条件選択とは別です。単位：万円。</p><div id="method-sessions"></div></details></section>
<section id="rules"><h2>板を使う具体的な条件</h2><p>下記は既知５セッションで選んだ候補です。LSTMなどの学習モデルは使いません。板の方向判定、条件注文、観測後のストップ更新だけで実行できます。</p><div class="cards">__DESCRIPTIONS__</div><details open><summary>共通する新規・返済ルール</summary><ol><li>板の同一最終約定時刻の連続行を、次の異なる時刻の先頭行が来てから方向判定に使う。古い板や不正な板は方向確認から除外。</li><li>確定５分足ATR（係数1/12、３本以上、最低２tick）は確定から１分追加で待ち、新規条件作成時に固定。</li><li>条件成立行では約定させず、次の有効な板の買い気配／売り気配で１枚約定する仮定。損切りと追跡は同一時刻内も含む全有効気配で監視。</li><li>開始45分後から新規。発注25分超で失効、反対方向で取消、中立なら保持。返済後45分休止。</li><li>15:05／翌05:20以降は新規禁止。15:35／翌05:50以降に返済要求し、次の有効行で返済。途中終了のデータは未返済として区別。</li></ol></details><p class="notice">受信時刻・注文ID・個別約定情報がありません。数量の減少を「取消」「約定」に分解することはできません。時間窓は最終約定時刻の代理時計であり、実際の発注遅延や２銘柄の完全な同期を再現した結果ではありません。</p></section>
<section><h2>既知５セッションで選んだ候補の探索成績</h2><p>同じ５セッションの損益を使って候補を選び、その５セッションへ適用した結果です。採用判断の根拠として、冒頭の時間順比較より弱い成績です。</p>__EXPLORATORY__<details><summary>従来の価格CUSUM＋１ATR追跡新規＋利益保護を、今回の生板約定で再生</summary>__BASELINE__<p class="note">過去の分足約定による数字と直接比較しないでください。生板で全気配を監視し、実際の気配差と追加費用を負担させた評価です。</p></details></section>
<section id="materials"><h2>詳細な結果と再現資料</h2><p><a href="検証結果.md">日本語の検証結果</a> ／ <a href="資料/work/wave_v8/検証計画.md">事前の検証計画</a> ／ <a href="資料/work/wave_v8/板特徴の作成方法.md">板特徴の作成方法</a></p><p><a href="資料/work/wave_v8/全条件セッション集計.csv">基本108条件・全セッション集計CSV</a> ／ <a href="資料/work/wave_v8/全取引.csv">全取引CSV</a> ／ <a href="資料/work/wave_v8/約定遅延感度.csv">約定遅延の感度CSV</a></p><div id="cross-links"></div><p><a href="資料/work/wave_v8/生板未来非依存監査.json">原本打切り・未来非依存監査</a> ／ <a href="資料/work/wave_v8/同時刻ブロック内気配監査.json">同時刻内気配の監査</a> ／ <a href="資料/資料一覧とSHA256.json">再現資料一覧・SHA256</a></p><p class="note">コード、抽出済み板特徴と全気配配列、必要な足を資料へ同梱しています。生原本は重複保存していません。現在セッションの取得や発注は行っていません。</p></section><footer>新しい結果を見て閾値を調整していません。過去の少数セッションで見つかった候補の比較であり、将来の収益性が確立したことを意味しません。</footer>
</main><script id="dataset" type="application/json">__PAYLOAD__</script><script>
const data=JSON.parse(document.getElementById('dataset').textContent);
const $=id=>document.getElementById(id), yen=n=>(n>0?'+':'')+(n/10000).toFixed(1), esc=s=>String(s).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let targets=[], shownTrades=[];
/**
 * 機能: Unix秒を日本時間の日時へ整形する。
 * @param {number} seconds - Unix秒。
 * @param {boolean} full - 日付を含むか。
 * @returns {string} 日本時間の表示。
 */
function stamp(seconds,full=false){const d=new Date(seconds*1000);return new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',...(full?{month:'2-digit',day:'2-digit'}:{}),hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(d)}
/**
 * 機能: 現在選択している方式・銘柄・セッションを取得する。
 * @returns {Object} 選択した条件。
 */
function selection(){return {symbol:$('symbol').value,session:$('session').value,method:$('method').value}}
/**
 * 機能: 指定した集計行から収支表を作る。
 * @param {Array<Object>} rows - 集計行。
 * @returns {string} HTML表。
 */
function metricTable(rows){return '<div class="scroll"><table><thead><tr><th>セッション</th><th>銘柄</th><th>利益</th><th>損失</th><th>差引</th><th>勝ち／返済済</th><th>追加費用４tick</th><th>未返済／評価損益</th></tr></thead><tbody>'+rows.map(r=>`<tr><td>${esc(r.セッション)}</td><td>${r.銘柄}</td><td>${(r.利益円/10000).toFixed(1)}</td><td>${(r.損失円/10000).toFixed(1)}</td><td class="${r.収支円>=0?'pos':'neg'}">${yen(r.収支円)}</td><td>${r.勝ち数} / ${r.取引数}${r.取引数?'（'+(100*r.勝ち数/r.取引数).toFixed(1)+'%）':''}</td><td>${yen(r.費用倍収支円)}</td><td>${r.未返済数} / ${yen(r.評価損益円)}</td></tr>`).join('')+'</tbody></table></div>'}
/**
 * 機能: 選択条件に対応する取引・説明・集計を更新する。
 * @returns {void} 返り値なし。
 */
function update(){const s=selection();shownTrades=data.trades.filter(r=>r.symbol===s.symbol&&r.session===s.session&&r.method===s.method);const config=data.conditions.find(c=>c.id===s.method);$('method-description').textContent=config.description;const row=data.cells.find(r=>r.銘柄===s.symbol&&r.セッション===s.session&&r.方式===s.method);$('session-metrics').innerHTML=row?`<div><span>確定差引 万円</span><br><b class="${row.収支円>=0?'pos':'neg'}">${yen(row.収支円)}</b></div><div><span>勝ち／返済済み</span><br><b>${row.勝ち数} / ${row.取引数}</b></div><div><span>未返済数／評価 万円</span><br><b>${row.未返済数} / ${yen(row.評価損益円)}</b></div>`:'';$('trades').innerHTML='<table><thead><tr><th>方向</th><th>新規日時</th><th>価格</th><th>返済／評価日時</th><th>価格</th><th>費用後 万円</th><th>保有分</th><th>理由</th></tr></thead><tbody>'+shownTrades.map(t=>`<tr><td>${t.side>0?'ロング':'ショート'}</td><td>${stamp(t.entry,true)}</td><td>${t.ep}</td><td>${stamp(t.exit,true)}</td><td>${t.xp}</td><td class="${t.net>=0?'pos':'neg'}">${yen(t.net)}${t.closed?'':'（評価）'}</td><td>${t.duration.toFixed(1)}</td><td>${t.reason}</td></tr>`).join('')+(shownTrades.length?'':'<tr><td colspan="8">この条件・セッションでは新規約定なし</td></tr>')+'</tbody></table>';$('method-sessions').innerHTML=metricTable(data.cells.filter(r=>r.方式===s.method));draw()}
/**
 * 機能: 確定５分足と生板約定時点を描画する。
 * @returns {void} 返り値なし。
 */
function draw(){const s=selection(),bars=data.candles[s.symbol+'|'+s.session],canvas=$('chart'),box=canvas.parentElement,w=box.clientWidth,h=box.clientHeight,dpr=window.devicePixelRatio||1;canvas.width=w*dpr;canvas.height=h*dpr;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);targets=[];if(!bars.length)return;const pad={l:64,r:24,t:35,b:42};const times=shownTrades.flatMap(t=>[t.entry,t.exit]);const t0=Math.min(bars[0][0],...times)-150,t1=Math.max(bars.at(-1)[0]+300,...times)+150;const prices=bars.flatMap(b=>[b[2],b[3]]).concat(shownTrades.flatMap(t=>[t.ep,t.xp]));let lo=Math.min(...prices),hi=Math.max(...prices),range=hi-lo||1;lo-=range*.12;hi+=range*.12;const x=t=>pad.l+(t-t0)/(t1-t0)*(w-pad.l-pad.r),y=p=>h-pad.b-(p-lo)/(hi-lo)*(h-pad.t-pad.b);ctx.font='11px system-ui';ctx.textBaseline='middle';ctx.fillStyle='#526172';ctx.strokeStyle='#e1e7ee';ctx.lineWidth=1;for(let i=0;i<=5;i++){const price=lo+(hi-lo)*i/5,yy=y(price);ctx.beginPath();ctx.moveTo(pad.l,yy);ctx.lineTo(w-pad.r,yy);ctx.stroke();ctx.textAlign='right';ctx.fillText(price.toFixed(s.symbol==='TOPIX'?1:0),pad.l-8,yy)}const tickGap=(t1-t0)>10*3600?7200:3600;for(let t=Math.ceil(t0/tickGap)*tickGap;t<t1;t+=tickGap){const xx=x(t);ctx.strokeStyle='#edf1f5';ctx.beginPath();ctx.moveTo(xx,pad.t);ctx.lineTo(xx,h-pad.b);ctx.stroke();ctx.textAlign='center';ctx.fillText(stamp(t).slice(0,5),xx,h-pad.b+20)}const cw=Math.max(1,Math.min(12,(w-pad.l-pad.r)*220/(t1-t0)));for(const b of bars){const xx=x(b[0]+150),color=b[4]>=b[1]?'#168a76':'#d25263';ctx.strokeStyle=color;ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(xx,y(b[2]));ctx.lineTo(xx,y(b[3]));ctx.stroke();ctx.fillRect(xx-cw/2,Math.min(y(b[1]),y(b[4])),cw,Math.max(1,Math.abs(y(b[1])-y(b[4]))));targets.push({x:xx,y:(y(b[2])+y(b[3]))/2,kind:'bar',text:`５分足 ${stamp(b[0],true)} 開始\n始値 ${b[1]}　高値 ${b[2]}\n安値 ${b[3]}　終値 ${b[4]}`})}for(const t of shownTrades){const x1=x(t.entry),y1=y(t.ep),x2=x(t.exit),y2=y(t.xp);ctx.strokeStyle=t.net>=0?'#0a735f88':'#b1324388';ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#155fb5';ctx.beginPath();if(t.side>0){ctx.moveTo(x1,y1);ctx.lineTo(x1-6,y1+13);ctx.lineTo(x1+6,y1+13)}else{ctx.moveTo(x1,y1);ctx.lineTo(x1-6,y1-13);ctx.lineTo(x1+6,y1-13)}ctx.closePath();ctx.fill();ctx.strokeStyle=t.closed?'#ad3ca4':'#b27719';ctx.fillStyle=t.closed?'#ad3ca4':'#fff';ctx.beginPath();if(t.closed){ctx.moveTo(x2,y2-6);ctx.lineTo(x2+6,y2);ctx.lineTo(x2,y2+6);ctx.lineTo(x2-6,y2);ctx.closePath()}else ctx.arc(x2,y2,6,0,Math.PI*2);ctx.fill();ctx.stroke();targets.push({x:x1,y:y1,kind:'trade',text:`${t.side>0?'ロング':'ショート'} 新規\n${stamp(t.entry,true)}　${t.ep}\n固定ATR ${t.atr.toFixed(2)}\n${t.closed?'確定':'未返済評価'}収支 ${yen(t.net)}万円`},{x:x2,y:y2,kind:'trade',text:`${t.closed?'返済':'未返済の評価'}\n${stamp(t.exit,true)}　${t.xp}\n${t.reason}\n費用後 ${yen(t.net)}万円\n保有 ${t.duration.toFixed(1)}分`})}ctx.fillStyle='#182737';ctx.font='bold 12px system-ui';ctx.textAlign='left';ctx.fillText(`${s.symbol}　${s.session}　５分足・生板約定`,pad.l,17)}
/**
 * 機能: マウスに近い売買位置を優先して説明を表示する。
 * @param {MouseEvent} event - マウス移動イベント。
 * @returns {void} 返り値なし。
 */
function hover(event){const rect=$('chart').getBoundingClientRect(),xx=event.clientX-rect.left,yy=event.clientY-rect.top,trade=targets.filter(t=>t.kind==='trade').map(t=>({t,d:Math.hypot(t.x-xx,t.y-yy)})).sort((a,b)=>a.d-b.d)[0];let nearest=trade&&trade.d<24?trade.t:targets.filter(t=>t.kind==='bar').sort((a,b)=>Math.abs(a.x-xx)-Math.abs(b.x-xx))[0];if(!nearest)return;const tip=$('tooltip');tip.textContent=nearest.text;tip.style.display='block';tip.style.left=Math.max(5,Math.min(xx+14,rect.width-tip.offsetWidth-8))+'px';tip.style.top=Math.max(5,Math.min(yy+14,rect.height-tip.offsetHeight-8))+'px'}
// ----------------------------------------
// 初期表示と選択・寸法変更に応じた更新を登録する。
$('session').innerHTML=data.sessions.map(s=>`<option value="${s}">${s.replace('_Day',' デイ').replace('_Night',' ナイト')}${s===data.sessions.at(-1)?'（途中）':''}</option>`).join('');$('session').value='2026-09-23_Day';for(const group of data.groups){const configs=data.conditions.filter(c=>c.group===group);if(!configs.length)continue;const opt=document.createElement('optgroup');opt.label=group;opt.innerHTML=configs.map(c=>`<option value="${esc(c.id)}">${data.selected[group]===c.id?'★ ':''}${esc(c.id)}</option>`).join('');$('method').append(opt)}$('method').value=data.selected['板のみ']||data.conditions[0].id;for(const id of ['symbol','session','method'])$(id).addEventListener('change',update);$('chart').addEventListener('mousemove',hover);$('chart').addEventListener('mouseleave',()=>$('tooltip').style.display='none');new ResizeObserver(draw).observe($('chart').parentElement);update();
</script></body></html>'''


if __name__ == '__main__':
    main()
