"""指定価格・費用ゼロの探索と固定後照合を暗色の日本語報告へまとめる。"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
import shutil

import numpy as np
import pandas as pd

import data

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
DEST = ROOT/'アルゴリズム調査'/'00008_指定価格と費用ゼロの再探索'
PAGE = '指定価格と費用ゼロの再探索.html'
PHILOSOPHIES = ['予測を固定時間で評価', '予測と単建玉管理', '新しい入口と利益保護',
                '予測と複数建玉管理', '方向予測なしの注文', '固定比較']
PHILOSOPHY_TEXT = {
    '予測を固定時間で評価': '方向を決める部分に価値があるかを、５・15・30・60分後の返済で調べる。入口と出口を複雑にせず、正方向と反対方向の両方を比較する。',
    '予測と単建玉管理': '方向予測に、即時型・追跡新規・逆指値を組み合わせる。固定利確、追跡、利益保護、板の反対向きに応じた短縮を比べ、波の途中から入って利益を残す。',
    '新しい入口と利益保護': '浅い・深い押し戻りへの指値、強い突破だけの逆指値、早い建値保護、利益75%保護、長時間停滞後の追跡短縮を追加する。入口の精度と利益を返し過ぎない出口を同時に検討する。',
    '予測と複数建玉管理': '３枚の段階利確、順行してから増玉、３枚に限定した逆行追加、２枚で早期利確と継続保有を比較する。残した負け玉の含み損を全資産評価に含める。',
    '方向予測なしの注文': '30分ごとの買い・売り・交互方向・固定コイントスを入口とし、両建て・上下逆指値・増玉・有限グリッド・段階利確を比べる。方向を事後に選ぶことはしない。',
    '固定比較': '以前注目した平均乖離反発・EMA収束と板反転・両銘柄板反転を固定比較に残す。以前の最悪条件に対応する板方向の５分返済も、正方向と反対方向で比較する。',
}


def load_json(name: str, default: object = None) -> object:
    """機能: 作業資料のJSONを、存在確認をして読み込む。

    引数: name (str)、default (object)。返り値: JSON値または既定値 (object)。
    """
    path = WORK/name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def clean(value: object) -> object:
    """機能: 非有限値を欠損へ置換して静的HTMLへ安全に埋め込む。

    引数: value (object)。返り値: JSON互換の値 (object)。
    """
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def money(value: float, signed: bool = True) -> str:
    """機能: 円の値を日本語の万円表記に変換する。

    引数: value (float)、signed (bool)。返り値: 万円表記 (str)。
    """
    if value is None or pd.isna(value):
        return '—'
    number = f'{abs(float(value))/10000:,.2f}'.rstrip('0').rstrip('.')
    sign = '−' if value < 0 else '＋' if value > 0 and signed else ''
    return sign+number+'万円'


def percent(value: float) -> str:
    """機能: 有効な割合だけをパーセント表示する。

    引数: value (float)。返り値: 表示文字列 (str)。
    """
    return '—' if value is None or pd.isna(value) else f'{value*100:.1f}%'


def session_label(session: str) -> str:
    """機能: セッション開始日で統一した日本語名称を返す。

    引数: session (str)。返り値: 表示名 (str)。
    """
    return session[5:10].replace('-', '/')+(' ナイト' if session.endswith('Night') else ' デイ')


def label_for(config: dict) -> str:
    """機能: 注文方式の内部名を日本語の表示へ置換する。

    引数: config (dict)。返り値: 日本語の方式名 (str)。
    """
    value = config['label']
    for key, label in {'single': '１枚追跡', 'simultaneous': '同時３枚・段階利確', 'pyramid': '順行増玉',
                       'grid': '有限グリッド', 'hedge': '両建て', 'straddle': '上下逆指値'}.items():
        value = value.replace('/'+key+'/', '/'+label+'/').replace('／'+key+'／', '／'+label+'／')
    return value


def aggregate(frame: pd.DataFrame) -> dict:
    """機能: 同じ方式・銘柄の結果を合計し、セッション最大下落を別に保つ。

    引数: frame (DataFrame)。返り値: 合計と最大値 (dict)。
    """
    sums = ['profit_yen', 'loss_yen', 'closed_net_yen', 'open_yen', 'net_yen', 'closed_count', 'win_count',
            'open_count', 'entry_count', 'cap_net_yen', 'ideal_fill_gap_count', 'ideal_fill_benefit_yen']
    result = {key: float(frame[key].sum()) if key in frame else 0. for key in sums}
    result['max_drawdown_yen'] = float(frame.max_drawdown_yen.max()) if len(frame) else 0.
    result['gross_peak'] = int(frame.gross_peak.max()) if len(frame) else 0
    result['cap'] = int(frame['設定最大枚数'].max()) if len(frame) else 0
    result['win_rate'] = result['win_count']/result['closed_count'] if result['closed_count'] else None
    return result


def html_table(headers: list[str], rows: list[list]) -> str:
    """機能: エスケープしたスクロール可能な表を生成する。

    引数: headers (list[str])、rows (list[list])。返り値: HTML表 (str)。
    """
    return '<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in headers)+\
        '</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in row)+'</tr>' for row in rows)+\
        '</tbody></table></div>'


def markdown_table(headers: list[str], rows: list[list]) -> str:
    """機能: 同じ数値をMarkdownの表へ変換する。

    引数: headers (list[str])、rows (list[list])。返り値: Markdown表 (str)。
    """
    def line(row: list) -> str:
        """機能: 表の１行に含まれる区切り記号を保護する。

        引数: row (list)。返り値: Markdown１行 (str)。
        """
        return '| '+' | '.join(str(x).replace('|', '\\|').replace('\n', ' ') for x in row)+' |'
    return '\n'.join([line(headers), line(['---']*len(headers)), *[line(row) for row in rows]])


class Document:
    """機能: 同じ文章と表からHTML・Markdownを一緒に組み立てる。

    引数: なし。返り値: 構築用インスタンス (Document)。
    """

    def __init__(self) -> None:
        """機能: 出力先を初期化する。

        引数: なし。返り値: なし (None)。
        """
        self.parts, self.markdown = [], []

    def section(self, key: str, title: str) -> None:
        """機能: 新しい章の見出しを追加する。

        引数: key/title (str)。返り値: なし (None)。
        """
        self.parts.append(f'<section id="{html.escape(key)}"><h2>{html.escape(title)}</h2>')
        self.markdown.append('\n## '+title+'\n')

    def end(self) -> None:
        """機能: HTML章を閉じる。

        引数: なし。返り値: なし (None)。
        """
        self.parts.append('</section>')

    def text(self, text: str, style: str = '') -> None:
        """機能: 両形式へ本文を追加する。

        引数: text/style (str)。返り値: なし (None)。
        """
        self.parts.append(f'<p class="{style}">{html.escape(text)}</p>')
        self.markdown.append(text+'\n')

    def table(self, headers: list[str], rows: list[list]) -> None:
        """機能: 同じ表を両形式へ追加する。

        引数: headers (list[str])、rows (list[list])。返り値: なし (None)。
        """
        self.parts.append(html_table(headers, rows))
        self.markdown.append(markdown_table(headers, rows)+'\n')

    def method(self, title: str, rules: list[str]) -> None:
        """機能: 方式名と具体条件を読みやすい小節へ追加する。

        引数: title (str)、rules (list[str])。返り値: なし (None)。
        """
        self.parts.append('<div class="method"><h3>'+html.escape(title)+'</h3><ol>'+''.join('<li>'+html.escape(t)+'</li>' for t in rules)+'</ol></div>')
        self.markdown.append('\n### '+title+'\n\n'+'\n'.join(f'{i+1}. {text}' for i, text in enumerate(rules))+'\n')


def rules_for(config: dict, profiles: dict) -> list[str]:
    """機能: 条件一覧の数値から実行できる入口・出口・枚数の説明を生成する。

    引数: config/profiles (dict)。返り値: 日本語説明 (list[str])。
    """
    cfg = config
    family = cfg['family']
    signal = profiles.get(family, {}).get('rules', profiles.get(family, {}).get('description', ''))
    if family == 'P23':
        signal = '確定１分足EMA3−EMA8の符号が過去２本と同じで、絶対乖離が拡大後２本連続で縮小し、２本前の乖離が0.1ATR以上なら乖離と逆方向。解放済み60秒のOFI・気配更新・同一価格数量増減の偏りの平均を板圧力とし、反対側の±0.1を２ブロック確認して反転とする。EMA収束と板反転が同方向で300秒以内に揃った時に通知。'
    elif family == 'P24':
        signal = '両銘柄それぞれで60秒のOFI・気配更新・同一価格数量増減の偏りの平均を板圧力とする。圧力が反対側の±0.1を２ブロック確認した反転が同方向なら通知。自銘柄は５分以内、他銘柄は元の解放時刻から３分以内で、他銘柄の参照はさらに60秒待機する。'
    elif family in ['N10', 'N18']:
        signal += ' 各セッションで学習状態を初期化し、通知時点で10分後の正解が確定済みの例だけを使う。LSTMは用いない。'
    if not signal:
        signal = {'Q01': '開始20分後から30分ごとに買い方向。', 'Q02': '開始20分後から30分ごとに売り方向。',
                  'Q03': '開始20分後から30分ごとに買い・売りを交互にする。',
                  'Q04': '開始20分後から30分ごとに、セッション日・日夜・銘柄で固定した乱数のコイントス方向。'}[family]
    result = ['方向の判定：'+signal+(' 検知した方向を反転して売買する。' if cfg.get('signal_multiplier', 1) < 0 else '')]
    width = cfg.get('entry_atr', 0)
    entry = cfg.get('entry_mode', 'trail')
    if entry == 'market':
        text = '検知した次の有効な原本行のCurrentPriceで新規。'
    elif entry == 'trail':
        text = f'検知後、買いは追跡安値から{width:g}ATR上昇、売りは追跡高値から{width:g}ATR下落する指定価格へ到達したら新規。'
    elif entry == 'stop':
        text = f'買いは通知採用時の価格＋{width:g}ATR、売りは同価格−{width:g}ATRの逆指値に、後の原本行が到達したら新規。'
    elif entry == 'limit':
        text = f'買いは通知採用時の価格−{width:g}ATR、売りは同価格＋{width:g}ATRの指値に、後の原本行が到達したら新規。'
    else:
        text = f'上下に{width:g}ATR離した逆指値を置き、先に到達した方向を新規として反対側を取り消す。'
    result.append('エントリー：'+text+f' 待機期限{cfg.get("max_age_min", 10):g}分、返済後{cfg.get("cooldown_min", 5):g}分は次の新規を待つ。')
    stop = cfg.get('initial_stop_atr', 1.)
    target, trail = cfg.get('target_atr'), cfg.get('trail_atr', 2.)
    exits = [f'初期損切り{stop:g}ATR' if stop is not None else '価格幅による初期損切りなし']
    if target is not None:
        exits.append(f'利確{target:g}ATR')
    if trail is not None:
        start_text = f'{cfg.get("trail_start_atr", 0):g}ATR順行後' if cfg.get('trail_start_atr', 0) else '新規後から追跡を開始し'
        exits.append(f'{start_text}、順行極値から{trail:g}ATR反転で追跡返済')
    if cfg.get('tighten_trigger_atr') is not None:
        exits.append(f'{cfg["tighten_trigger_atr"]:g}ATR順行後、追跡幅を{cfg.get("tighten_width_atr", .5):g}ATRへ短縮')
    if cfg.get('protect_trigger_atr') is not None:
        exits.append(f'{cfg["protect_trigger_atr"]:g}ATR順行後、最大順行利益の{cfg.get("protect_fraction", 0)*100:g}%をストップで保護')
    if cfg.get('breakeven_trigger_atr') is not None:
        exits.append(f'{cfg["breakeven_trigger_atr"]:g}ATR順行後に建値保護')
    if cfg.get('time_tighten_min') is not None:
        exits.append(f'{cfg["time_tighten_min"]:g}分保有後に追跡幅{cfg.get("time_width_atr", .5):g}ATRへ短縮')
    if cfg.get('weak_width_atr') is not None:
        exits.append(f'{cfg.get("state_trigger_atr", 0):g}ATR順行後、OFI・気配更新・同一価格数量増減の偏りの平均圧力が反対側の±0.1に達したら追跡幅{cfg["weak_width_atr"]:g}ATRへ短縮。入口の通知が再び出る必要はない')
    if cfg.get('holding_min') is not None:
        exits.append(f'保有{cfg["holding_min"]:g}分到達後の次行で返済')
    result.append('イグジット：'+'。'.join(exits)+'。'+('追跡で一度強めた利益保護は緩めない。' if trail is not None else ''))
    cap, add = cfg.get('max_legs', 1), cfg.get('add_mode', 'none')
    extra = {'none': '追加なし', 'simultaneous': '同時に同方向へ建てる', 'pyramid': f'{cfg.get("add_step_atr", .5):g}ATR順行ごとに追加',
             'grid': f'{cfg.get("add_step_atr", .5):g}ATR逆行ごとに追加', 'hedge': '同時に買い１枚・売り１枚で開始'}[add]
    if cfg.get('leg_targets'):
        extra += '。各脚の利確幅は'+ ' / '.join('追跡で継続' if x is None else f'{x:g}ATR' for x in cfg['leg_targets'])
    result.append(f'枚数：対象１銘柄で最大{cap}枚。{extra}。すべての建玉を評価損益に含める。')
    result.append('時間とATR：開始20分は待機。デイ15:05・ナイト05:20以降の新規は禁止し、15:35・05:50の次の有効行でセッション内返済。ATRは確定５分足のTRを係数1/12で平滑化し、最少３本・下限２呼値。通知を採用した原本行時点のATRで幅を固定する。'+
                  (' 米国株開始15分前〜30分後の新規を休止する。' if cfg.get('us_pause') else ' 米国株開始前後も同じルールを使う。'))
    return result


def load_stages(args: argparse.Namespace) -> list[dict]:
    """機能: 明示的に許可された評価区間だけを読み込む。

    引数: args (Namespace)。返り値: 区間別の表・足読取先 (list[dict])。
    """
    definitions = [('学習代表', '探索内・６セッション', data.TRAIN, ROOT, 'train')]
    if args.holdout_prefix:
        definitions.append((args.holdout_prefix, '条件固定後・9/24デイ', [data.HOLDOUT], ROOT, 'holdout'))
    if args.live_prefix:
        if not args.live_session or not args.live_root:
            raise ValueError('現在照合には明示的なセッション名と足保存先が必要です')
        record = load_json(f'{args.live_prefix}_評価記録.json', {})
        cutoff = pd.Timestamp(record['cutoff']).strftime('%H:%M') if record.get('cutoff') else '取得末尾'
        definitions.append((args.live_prefix, f'固定後に初取得・ナイト{cutoff}未満', [args.live_session], Path(args.live_root), 'live'))
    stages = []
    for prefix, label, sessions, root, key in definitions:
        frame = pd.read_csv(WORK/f'{prefix}_セッション集計.csv')
        if not frame['セッション'].isin(sessions).all():
            raise ValueError(f'{prefix}に許可していないセッションがあります')
        stages.append(dict(prefix=prefix, label=label, sessions=sessions, root=root, key=key, frame=frame,
                           trades=load_json(f'{prefix}_全取引.json'), curves=load_json(f'{prefix}_資産曲線.json')))
    return stages


def results_rows(stages: list[dict], ids: dict[str, str], session_level: bool = False) -> list[list]:
    """機能: 銘柄ごとの固定条件を評価区間別に集計する。

    引数: stages (list[dict])、ids (dict)、session_level (bool)。返り値: 表の行 (list[list])。
    """
    result = []
    for stage in stages:
        for symbol, method in ids.items():
            frame = stage['frame']
            part = frame[frame['銘柄'].eq(symbol) & frame['方式'].eq(method)]
            groups = list(part.groupby('セッション', sort=False)) if session_level else [(stage['label'], part)]
            for label, group in groups:
                s = aggregate(group)
                name = session_label(label) if session_level else label
                result.append([symbol, name, method, money(s['profit_yen']), money(s['loss_yen']), money(s['closed_net_yen']),
                               money(s['open_yen']), money(s['net_yen']), int(s['closed_count']), int(s['open_count']), percent(s['win_rate']),
                               f'{s["gross_peak"]}/{s["cap"]}', money(s['max_drawdown_yen'], False)])
    return result


def build_document(stages: list[dict], configs: dict, profiles: dict, selected: dict,
                   full: pd.DataFrame, walk: pd.DataFrame) -> Document:
    """機能: 思想・具体条件・探索と照合結果を章ごとに整理する。

    引数: stages (list[dict])、configs/profiles/selected (dict)、full/walk (DataFrame)。返り値: 報告本文 (Document)。
    """
    doc = Document()
    primary = {symbol: item['採用']['方式'] for symbol, item in selected['主候補'].items() if item['採用']}
    headers = ['銘柄', '評価区間', '固定条件', '利益', '損失', '確定収支', '含み損益', '全建玉評価', '返済脚数', '未返済枚数', '脚勝率', '実最大/上限', '区間内最大下落']
    doc.section('main', '１．今回の前提と、固定した主候補の結果')
    doc.text(f'費用をゼロとし、指定価格に到達すればその価格で約定する条件で、{len(configs):,}条件を再探索した。旧24系統と新18系統について正方向・反対方向を試し、方向予測なしの注文方式も比較した。')
    doc.text('手数料０、追加の呼値控除０、売買気配差控除０。数量不足による未約定も仮定しない。板のスプレッドや数量は予測材料に使うが、費用として利益から差し引かない。', 'callout')
    doc.text('金額はラージ相当で、NK225は価格差×1,000円、TOPIXは価格差×10,000円。主候補は各銘柄１枚、複数建玉の方式は表に記載した枚数上限で評価する。')
    current_record = load_json('現在照合_評価記録.json') if any(s['key'] == 'live' for s in stages) else None
    if current_record:
        cutoff = pd.Timestamp(current_record['cutoff']).strftime('%m/%d %H:%M')
        doc.text(f'現在ナイトは、条件固定後に初めて取得したセッション開始17:00から{cutoff}未満までを、原本順で再生した結果。未完了のため確定損益と含み損益を分ける。取得は６URL各１回で、結果を見て主候補を選び直していない。')
    doc.table(headers, results_rows(stages, primary))
    forward = walk[walk['選択対象思想'].eq('全方式')]
    forward_text = '、'.join(f'{symbol}{money(forward.loc[forward["銘柄"].eq(symbol), "net_yen"].sum())}' for symbol in data.SYMBOLS)
    doc.text('探索で選んだ固定候補の成績と、未知の次区間での成績は分ける。過去だけで毎回選び直す４回の評価合計は'+forward_text+'だった。選び直す方針の成績は第３章に示す。', 'callout')
    doc.text('利益と損失は返済済みの各脚を集計した値。全建玉評価＝確定収支＋未返済の全脚の含み損益。脚勝率は利益を出した返済脚数/返済脚数で、複数脚を独立した予測回数とは扱わない。探索６セッションの最大下落欄は「１セッション内最大値」の最大で、６セッションをつないだ最大下落ではない。', 'note')
    if len(stages) < 3:
        doc.text('この版に未掲載の照合区間は、未開封または報告へ取り込み前である。未掲載を収支ゼロと解釈しない。', 'note')
    for symbol, method in primary.items():
        doc.method(f'{symbol}の固定主候補：{method}', rules_for(configs[method], profiles))
    doc.end()

    # ----------------------------------------
    # 図解の操作欄は本文と同じ条件・全脚データを参照する。
    doc.section('charts', '２．５分足と、全建玉のエントリー・イグジット')
    doc.text('銘柄・固定条件・セッションを選ぶと、その条件のすべての新規脚と返済を表示する。売買時刻は生データの原本順で判定し、５分足の高安から売買順を推測していない。')
    doc.parts.append('''<div class="chart-controls"><label>銘柄<select id="symbol"><option>NK225</option><option>TOPIX</option></select></label><label class="wide">固定条件<select id="method"></select></label><label>セッション<select id="session"></select></label><button id="primary">この銘柄の主候補</button><button id="reset">セッション全体</button></div>
    <div id="rule" class="chart-rule"></div><div id="chart-summary" class="stats"></div>
    <div class="legend"><span class="green">▲ 買い新規</span><span class="orange">▼ 売り新規</span><span class="blue">● 返済</span><span class="purple">◇ 未返済評価</span><span>破線：条件判定 → 新規</span></div>
    <div class="chart-box"><canvas id="price" height="490" aria-label="５分足と全脚の売買図"></canvas><div id="tooltip" class="tooltip"></div></div>
    <div class="chart-box"><canvas id="equity" height="190" aria-label="含み損益を含む評価収支"></canvas></div>
    <p id="chart-note" class="note"></p><div id="trade-table" class="table-wrap"></div>''')
    doc.markdown.append(f'５分足・売買線・全脚明細・含み損益曲線は[{PAGE}]({PAGE}#charts)を参照。\n')
    doc.end()

    doc.section('time', '３．過去だけで条件を選ぶ方針は、次の区間でも利益になったか')
    doc.text('先頭２→３、３→４、４→５、５→６セッションで、過去だけで条件を選び、その次を評価した。下表は「条件を選ぶ方針」の４回合計であり、最後の固定主候補をそのまま４セッションに当てた成績ではない。以前の研究で既知だった期間を含むため、研究全体として完全に未使用の標本ではない。')
    rows = []
    for philosophy in ['全方式', *PHILOSOPHIES]:
        for symbol in data.SYMBOLS:
            part = walk[walk['選択対象思想'].eq(philosophy) & walk['銘柄'].eq(symbol)]
            if part.empty:
                continue
            s = aggregate(part)
            rows.append([philosophy, symbol, money(s['profit_yen']), money(s['loss_yen']), money(s['net_yen']),
                         money(s['cap_net_yen']), int(s['closed_count']), percent(s['win_rate'])])
    doc.table(['選択対象', '銘柄', '利益', '損失', '収支', '設定上限１枚換算', '返済脚数', '脚勝率'], rows)
    doc.parts.append('<details><summary>各回で実際に選んだ条件を見る</summary>')
    rows = [[r['選択対象思想'], r['銘柄'], int(r['学習数']), session_label(r['セッション']), r['方式'], money(r['net_yen'])] for r in walk.to_dict('records')]
    doc.table(['選択対象', '銘柄', '学習セッション数', '次の評価区間', '採用した条件', '収支'], rows)
    doc.parts.append('</details>')
    doc.text('選択得点＝設定枚数上限で割ったセッション収支の中央値＋平均−0.25×同じ換算の平均最大下落。最低３返済脚・最低２有取引セッションを要求し、取引しない条件は主候補にしない。換算値は証拠金利益率ではない。', 'note')
    doc.end()

    doc.section('scope', '４．既存と新規、正方向と反対方向をどこまで試したか')
    rows = []
    for philosophy in PHILOSOPHIES:
        sub = full[full['思想'].eq(philosophy)]
        sums = sub.groupby('方式').net_yen.sum()
        rows.append([philosophy, len(sums), int((sums > 0).sum()), int((sums < 0).sum()), int((sums == 0).sum()), money(sums.max()) if len(sums) else '—'])
    doc.table(['思想', '条件数', '探索合計黒字', '探索合計赤字', '探索合計ゼロ', '探索内最高収支'], rows)
    doc.text('この表の収支は学習６セッション・両銘柄の実額合計。枚数が異なる方式を含むため、主候補の選択は別途設定枚数上限で換算している。探索内の最高額を、将来成績の予測とは扱わない。', 'note')
    doc.text('注文条件は、４入口×６出口×米国開始前後の休止有無、追加６種類の入口/利益保護、４種類の有限複数玉、固定時間返済を組み合わせた。正方向と反対方向を対称に試した。定刻注文は買い・売り・交互・固定コイントスに６注文方式と３幅を組み合わせた。')
    doc.end()

    # ----------------------------------------
    # 各章は思想→数値ルール→探索/保留/現在の同じ順序にそろえる。
    for number, philosophy in enumerate(PHILOSOPHIES, start=5):
        doc.section(f'philosophy-{number}', f'{number}．{philosophy}')
        doc.text(PHILOSOPHY_TEXT[philosophy])
        ids = {}
        for symbol in data.SYMBOLS:
            item = selected['思想別代表'].get(f'{symbol}|{philosophy}')
            if item and item['採用']:
                ids[symbol] = item['採用']['方式']
        if ids:
            doc.table(headers, results_rows(stages, ids))
        for symbol, method in ids.items():
            doc.method(f'{symbol}の探索で選んだ代表：{method}', rules_for(configs[method], profiles))
        if philosophy == '固定比較':
            fixed_rows = []
            for stage in stages:
                for method in selected['固定比較']:
                    for symbol in data.SYMBOLS:
                        part = stage['frame'][stage['frame']['方式'].eq(method) & stage['frame']['銘柄'].eq(symbol)]
                        if len(part):
                            s = aggregate(part)
                            fixed_rows.append([method, symbol, stage['label'], money(s['profit_yen']), money(s['loss_yen']), money(s['net_yen']), int(s['closed_count'])])
            doc.table(['固定比較', '銘柄', '区間', '利益', '損失', '全建玉評価', '返済脚数'], fixed_rows)
            doc.text('旧条件を新しい注文器へ移植している。新規の通知は受信した行でのみ採用し、保有中・注文待機中・クールダウン中に見送った信号を後から拾い直さない。v11以前の注文器とはこの採用タイミングも異なるため、費用と価格だけを置換した厳密な再現ではない。', 'callout')
        doc.end()

    doc.section('sessions', '11．固定主候補のセッション別の利益・損失・収支')
    doc.table(headers, results_rows(stages, primary, session_level=True))
    doc.text('日付はセッション開始日。ナイトは翌朝までを同じセッションとして扱う。現在ナイトの途中打切りでは未返済を「打切り時評価」と表示し、実際に返済したことにはしない。未完了でも予定の強制返済ルールは変更しない。', 'note')
    doc.parts.append('<details><summary>以前の主候補「平均乖離反発」のセッション別比較を読む</summary>')
    doc.table(headers, results_rows(stages, {symbol: '旧主候補_P01' for symbol in data.SYMBOLS}, session_level=True))
    doc.parts.append('</details>')
    neighbors_path = WORK/'主候補の設定近傍.csv'
    if neighbors_path.exists():
        neighbors = pd.read_csv(neighbors_path)
        doc.parts.append('<details><summary>入口・出口設定を近くで変えたときの探索内の差を読む</summary>')
        doc.text('設定近傍は学習区間だけの比較。最大３項目まで異なる条件を含むため、すべてが一つの変数だけを変えた対比ではない。保留デイ・現在ナイトの結果で再選択していない。')
        doc.table(['銘柄', '方式', '変更項目', '利益', '損失', '学習６セッション収支', '返済脚数'],
                  [[r['銘柄'], r['方式'], r['変更項目'], money(r['profit_yen']), money(r['loss_yen']), money(r['closed_net_yen']), int(r['closed_count'])] for r in neighbors.to_dict('records')])
        doc.parts.append('</details>')
    doc.end()

    doc.section('signals', '12．信号の思想と、今回追加した研究の着想')
    for origin, label in [('既存', '旧24系統'), ('新規', '新18系統')]:
        doc.parts.append('<details><summary>'+label+'の全条件を読む</summary>')
        rows = [[p['id'], p['name'], p['group'], p.get('rules', p.get('description', ''))] for p in profiles.values() if p['origin'] == origin]
        doc.table(['ID', '名称', '群', '方向を決める条件'], rows)
        doc.parts.append('</details>')
    doc.text('新規では滑らかな持続波、カルマン状態推定、適応平均、分散比で順張り/逆張りを切替、方向変化イベント、過去の滞在帯、逐次ridge回帰、近い道筋、板の補充と価格応答、２銘柄ベータ残差を加えた。オンライン学習は10分後の正解が既に確定した過去入力だけで更新する。LSTMは必要としない。')
    doc.parts.append('<p><a href="資料/新規仮説と文献.md">研究の着想・一次資料・旧方式との違いを読む</a></p>')
    doc.markdown.append('[研究の着想・一次資料](資料/新規仮説と文献.md)\n')
    sources = {}
    for p in profiles.values():
        if p.get('source'):
            sources[p['source']] = p.get('source_name', '参考研究')
    doc.parts.append('<div class="sources">'+''.join(f'<a href="{html.escape(link)}">{html.escape(name)}</a>' for link, name in sources.items())+'</div>')
    doc.markdown.append(' / '.join(f'[{name}]({link})' for link, name in sources.items())+'\n')
    doc.end()

    doc.section('methodology', '13．指定価格の解釈と、未来を使わないための確認')
    doc.text('価格条件は前行までに設定し、その後の生CurrentPriceが到達したら指定値で成立する。条件価格を飛び越えた場合も指定値で約定する。即時型の新規・保有時間返済・セッション返済は、判断の次の有効原本行のCurrentPriceを使う。同じ行で変更した追跡価格を同じ行へさかのぼって適用しない。')
    doc.text('指定価格は呼値へ丸める。NK225は10、TOPIXは0.5。上方向へ到達する条件は切上げ、下方向へ到達する条件は切下げる。買い玉の損切り価格は切下げ、売り玉の損切り価格は切上げで、実際の幅は呼値分だけ変わり得る。')
    doc.text('価格飛越し時の指定価格約定は、今回ユーザーが指定した理想モデルの一部である。主損益から差額を引き直さない。記録に残した飛越し件数はこのモデルが発動した頻度の説明に使い、費用を再導入した合否判定には使わない。')
    doc.text('確定１分足は開始＋２分、５分ATRは開始＋６分で利用する。原本の同一約定時刻ブロックは次時刻になるまで特徴を解放しない。他銘柄は追加60秒待機し、180秒を越える古い素材を使わない。原本の時刻は約定時計で、受信時計ではない。')
    frozen = load_json('現在照合_凍結記録.json')
    if frozen:
        doc.text('最終選択を'+pd.Timestamp(frozen['fixed_at']).strftime('%Y/%m/%d %H:%M:%S 日本時間')+'に固定し、16条件を保留デイ・現在ナイトへそのまま持ち込んだ。現在ナイトは固定後の初取得で、保留デイの成績も選択へ戻していない。')
    audits = []
    for filename in ['入力対応と足差分の監査.json', '指定価格再生の手計算と未来打切り監査.json', '指定価格再生の独立監査.json',
                     '新規信号_打切り監査.json', '固定照合_会計独立監査.json', '固定照合_未来打切り独立監査.json',
                     '指定波照合の独立監査.json']:
        value = load_json(filename)
        if value is not None:
            audits.append([filename, '資料に保存'])
    doc.table(['監査記録', '参照先'], audits)
    doc.parts.append('<p><a href="資料/入力データ監査.md">入力データの監査</a> · <a href="資料/検証計画.md">開封前の検証計画</a> · <a href="README.md">資料の読む順序</a></p>')
    doc.markdown.append('[入力データの監査](資料/入力データ監査.md) / [検証計画](資料/検証計画.md) / [資料案内](README.md)\n')
    for filename, label in [('主候補の条件と機械実行の補足.md', '主候補・比較候補の計算式と注文実行の補足'),
                            ('独立監査まとめ.md', '独立監査の確認内容と結果')]:
        if (WORK/filename).exists():
            doc.parts.append(f'<p><a href="資料/{filename}">{label}</a></p>')
            doc.markdown.append(f'[{label}](資料/{filename})\n')
    doc.text('短い期間で多数を探索したため、探索内で利益が出ることと、別の期間でも安定して利益が出ることは分けて見る。保留デイと現在ナイトは、固定した条件をそのまま適用し、結果を見て採用し直さない。')
    doc.end()
    waves = load_json('指定した４波の照合.json')
    if waves:
        doc.section('waves', '14．指定された４つの波に、固定主候補は乗っていたか')
        doc.text('以前指定された波と、固定済み主候補の同方向保有時間を事後に照合した。条件選択や調整には使っていない。指定開始より前の新規でも、窓内で同方向保有が続いていれば含む。')
        rows = []
        for row in waves['区間']:
            start, end = pd.Timestamp(row['指定開始']), pd.Timestamp(row['指定終了'])
            minutes = (end-start).total_seconds()/60
            rows.append([row['銘柄'], session_label(row['セッション']), start.strftime('%H:%M')+'〜'+end.strftime('%H:%M'),
                         row['指定方向'], f'{row["同方向保有分"]:.1f} / {minutes:g}分', percent(row['指定区間内保有割合']),
                         money(row['該当脚の最終収支円'])])
        doc.table(['銘柄', 'セッション', '指定時間帯', '方向', '同方向保有/区間', '時間の重なり', '該当脚の最終収支'], rows)
        doc.text('時間の重なりは、値幅の捕捉率や予測正答率ではない。最終収支は該当売買の全保有期間で、指定窓外の損益を含む。NK225の9/23デイは下落中にショートを持っていたが、最終収支は−８万円。波に乗ることと、出口で利益を残すことは別の課題として残った。', 'callout')
        doc.parts.append('<p><a href="資料/指定した４波の照合.md">該当売買の全新規・返済時刻を読む</a></p>')
        doc.markdown.append('[該当売買の全新規・返済時刻](資料/指定した４波の照合.md)\n')
        doc.end()
    comparison = 'P16_R1_E1_X5_U0'
    if comparison in selected['照合ID']:
        doc.section('board-candidate', '15．板を使う、事前に固定した別枠の比較候補')
        doc.text('NK225の「既存系の代表」として、保留・現在の開封前に別枠で選んだ条件。通知から0.25ATRの追跡新規を待ち、利益が出た後に板が反対なら追跡幅を短縮する。主候補へ事後に昇格させず、比較候補として結果を残す。')
        doc.table(headers, results_rows(stages, {symbol: comparison for symbol in data.SYMBOLS}))
        doc.method(comparison+'：板方向を入口と利益保護に使う', rules_for(configs[comparison], profiles))
        doc.parts.append('<button id="board-chart">NK225・この比較候補の売買図を見る</button>')
        doc.text('今回のNK225では「探索６セッションの合計・保留デイ・現在ナイト」の３評価区分が黒字だった。探索中の9/22デイは−34万円で、全セッションが黒字という意味ではない。同じ条件のTOPIXでは探索合計と現在ナイトが赤字であり、２銘柄共通の安定した規則が確認できたとは評価しない。', 'note')
        if any(s['key'] == 'live' for s in stages):
            doc.text('現在ナイトのNK225は確定＋16万円・含み０円だが、未返済が１枚ある。評価時点の価格が建値と同じであり、全返済済みを意味しない。TOPIXも未返済１枚で含み−2.5万円を含めた評価となる。', 'note')
        doc.end()
    return doc


def chart_data(stages: list[dict], configs: dict, profiles: dict, selected: dict) -> dict:
    """機能: 読取を許可された区間の５分足・全脚・資産曲線をまとめる。

    引数: stages (list[dict])、configs/profiles/selected (dict)。返り値: 図解用データ (dict)。
    """
    candles, trades, curves, summaries, session_names = {}, [], {}, {}, {}
    for stage in stages:
        for session in stage['sessions']:
            session_names[session] = session_label(session)+('【探索】' if stage['key'] == 'train' else '【固定後・保留】' if stage['key'] == 'holdout' else '【初取得・23:19未満】')
            for symbol in data.SYMBOLS:
                frame = pd.read_csv(stage['root']/f'candle_5min/{symbol}/{session}.csv')
                candles[f'{session}|{symbol}'] = [[pd.Timestamp(r['time']).timestamp(), r['open'], r['high'], r['low'], r['close'], str(r.get('closed', True)).lower() == 'true'] for r in frame.to_dict('records')]
        curves.update(stage['curves'])
        for row in stage['frame'].to_dict('records'):
            summaries[f'{row["方式"]}|{row["セッション"]}|{row["銘柄"]}'] = row
        for t in stage['trades']:
            trades.append(dict(method=t['方式'], session=t['セッション'], symbol=t['銘柄'], condition=t['条件設定時刻'],
                entry=t['新規時刻'], exit=t['返済評価時刻'], ep=t['新規価格'], xp=t['返済評価価格'],
                side=int(t['方向']), closed=bool(t['返済済み']), pnl=t['収支円'], reason=t['返済理由'],
                leg=int(t['脚番号'])+1, cycle=int(t['サイクル番号'])+1, atr=t['固定ATR'],
                mfe=t['最大順行幅'], holding=t['保有分'], entry_seq=int(t['新規原本行番号']),
                exit_seq=int(t['返済評価原本行番号'])))
    methods = {key: dict(label=label_for(configs[key]), rules=rules_for(configs[key], profiles), cap=configs[key]['max_legs']) for key in selected['照合ID']}
    return clean(dict(candles=candles, trades=trades, curves=curves, summaries=summaries, methods=methods,
                     sessions=session_names, primary={s:r['採用']['方式'] for s,r in selected['主候補'].items()},
                     symbols=data.SYMBOLS))


CSS = '''
:root{color-scheme:dark;--bg:#0b1019;--panel:#121b29;--panel2:#182338;--text:#e4edf8;--muted:#a5b4c9;--line:#30435f;--blue:#83bfff;--green:#5adeb3;--orange:#ffb36b;--purple:#c1a2ff;font-family:"Yu Gothic UI","Meiryo",sans-serif}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font-size:15px;line-height:1.85}main{max-width:1440px;margin:auto;padding:38px 30px 80px}header{padding:38px 40px;background:linear-gradient(125deg,#173753,#17213a 65%,#171f30);border:1px solid var(--line);border-radius:20px;margin-bottom:24px}.eyebrow{letter-spacing:.16em;color:#9bc7ef;font-size:12px;font-weight:700}h1{font-size:clamp(26px,3.2vw,45px);line-height:1.45;margin:12px 0 18px}h2{font-size:24px;line-height:1.5;margin:0 0 20px}h3{font-size:17px;line-height:1.7;margin:0 0 10px}p{margin:12px 0 18px}.lead{font-size:17px;color:#c1d3e7}.badges{display:flex;gap:10px;flex-wrap:wrap}.badges span{border:1px solid #527492;border-radius:20px;padding:3px 13px;background:#163148}nav{display:flex;flex-wrap:wrap;gap:10px 22px;padding:14px 2px 28px}a{color:var(--blue);text-underline-offset:3px}section{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:28px;margin:24px 0;scroll-margin-top:18px}.note{font-size:13px;color:var(--muted)}.callout{padding:16px 18px;border-left:4px solid var(--green);background:#133039}.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:9px;margin:18px 0}table{width:100%;border-collapse:collapse;font-size:13px}th{background:#1b2a40;color:#cadbef;text-align:left;white-space:nowrap}td,th{padding:10px 12px;border-bottom:1px solid #2b3a51;vertical-align:top}td{white-space:nowrap}tbody tr:nth-child(even){background:#152032}tbody tr:last-child td{border-bottom:0}.method{padding:21px 23px;background:#172337;border:1px solid #32445f;border-radius:10px;margin:18px 0}.method ol{padding-left:21px;margin:0}.method li{margin:8px 0}.sources{display:flex;flex-wrap:wrap;gap:8px 19px}details{padding:15px 17px;border:1px solid #32445f;border-radius:9px;margin:18px 0}summary{cursor:pointer;color:#bddcff;font-weight:700}details table td:last-child{white-space:normal;min-width:350px}.chart-controls{display:flex;flex-wrap:wrap;gap:13px;align-items:end}.chart-controls label{display:flex;flex-direction:column;font-size:12px;color:#b5c6dc;min-width:145px}.chart-controls label.wide{flex:1;min-width:310px}select,button{background:#1c2b43;color:var(--text);border:1px solid #567193;border-radius:7px;padding:10px;font:inherit}select{width:100%;font-size:13px}button{cursor:pointer;font-size:13px;font-weight:700}button:hover{background:#2b466d}button:focus-visible,select:focus-visible,a:focus-visible{outline:3px solid var(--orange);outline-offset:3px}.chart-rule{padding:16px;margin-top:15px;background:#0f1827;border-radius:8px;font-size:13px;color:#c5d5e8}.stats{display:flex;flex-wrap:wrap;gap:10px;margin:15px 0}.stats div{flex:1;min-width:135px;background:#1b2a40;padding:10px 15px;border-radius:8px}.stats small{display:block;color:var(--muted)}.stats b{font-size:19px}.green{color:var(--green)}.orange{color:var(--orange)}.blue{color:var(--blue)}.purple{color:var(--purple)}.legend{display:flex;flex-wrap:wrap;gap:10px 20px;font-size:12px;margin:15px 0}.chart-box{position:relative;background:#0b1422;border:1px solid #32445f;border-radius:10px;margin:12px 0;overflow:hidden}canvas{display:block;width:100%;touch-action:pan-y}.tooltip{display:none;position:absolute;z-index:3;pointer-events:none;background:#243751ef;border:1px solid #6c85a6;border-radius:8px;padding:10px;max-width:380px;font-size:12px;line-height:1.7;color:#edf5ff}.trade-row{cursor:pointer}.trade-row:hover td{background:#2b4160}.selected td{background:#304962}.positive{color:#69e0b8}.negative{color:#ffb37e}footer{color:var(--muted);font-size:13px;padding:15px 0}@media(max-width:700px){main{padding:16px 10px 55px}header{padding:24px 19px}section{padding:18px 13px}h2{font-size:20px}.method{padding:16px}.chart-controls label.wide{min-width:100%}.stats div{min-width:120px}}
'''

SCRIPT = r'''
const DATA=JSON.parse(document.getElementById('data').textContent);
const $=id=>document.getElementById(id);
let selectedTrade=-1,windowRange=null,visibleTrades=[],chartGeometry=null;
const COLORS={bg:'#0b1422',line:'#293b54',text:'#b3c4da',up:'#5adeb3',down:'#ffb36b',exit:'#83bfff',open:'#c1a2ff'};

/**
 * 円の数値を万円で表示する。
 * @param {number} value - 円の値。
 * @returns {string} 万円の文字列。
 */
function yen(value){return (value>0?'＋':value<0?'−':'')+(Math.abs(value)/10000).toLocaleString('ja-JP',{maximumFractionDigits:2})+'万円';}
/**
 * 日本時間の時刻を表示する。
 * @param {number} value - Unix秒。
 * @returns {string} 時分秒。
 */
function timeText(value){return new Date(value*1000).toLocaleTimeString('ja-JP',{timeZone:'Asia/Tokyo',hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});}
/**
 * 表示文字をHTMLへ安全に入れる。
 * @param {unknown} value - 表示対象。
 * @returns {string} エスケープした文字。
 */
function esc(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
/**
 * 現在の選択に対応するデータキーを返す。
 * @returns {string} 方式・セッション・銘柄のキー。
 */
function key(){return [$('method').value,$('session').value,$('symbol').value].join('|');}
/**
 * 高密度画面に合わせてキャンバスを準備する。
 * @param {string} id - 対象ID。
 * @param {number} height - 描画高さ。
 * @returns {object} 文脈と表示サイズ。
 */
function context(id,height){const el=$(id),ratio=window.devicePixelRatio||1,w=el.clientWidth;el.width=w*ratio;el.height=height*ratio;el.style.height=height+'px';const ctx=el.getContext('2d');ctx.scale(ratio,ratio);ctx.fillStyle=COLORS.bg;ctx.fillRect(0,0,w,height);ctx.font='12px "Yu Gothic UI",sans-serif';return {ctx,w,h:height};}
/**
 * 値幅・時間の目盛線を描く。
 * @param {object} target - 文脈とサイズ。
 * @param {number[]} bounds - 最小最大価格・時刻。
 * @param {boolean} moneyMode - 金額の表示か。
 * @returns {object} 座標変換関数と範囲。
 */
function axes(target,bounds,moneyMode=false){const {ctx,w,h}=target,[lo,hi,start,end]=bounds,p={l:75,r:w-25,t:24,b:h-36};const X=t=>p.l+(t-start)/(end-start)*(p.r-p.l),Y=v=>p.b-(v-lo)/(hi-lo)*(p.b-p.t);ctx.lineWidth=1;for(let i=0;i<=5;i++){const v=lo+(hi-lo)*i/5,y=Y(v);ctx.strokeStyle=COLORS.line;ctx.beginPath();ctx.moveTo(p.l,y);ctx.lineTo(p.r,y);ctx.stroke();ctx.fillStyle=COLORS.text;ctx.textAlign='right';ctx.fillText(moneyMode?(v/10000).toFixed(1)+'万':v.toLocaleString('ja-JP',{maximumFractionDigits:1}),p.l-10,y+4);}for(let i=0;i<=6;i++){const t=start+(end-start)*i/6,x=X(t);ctx.strokeStyle=COLORS.line;ctx.beginPath();ctx.moveTo(x,p.t);ctx.lineTo(x,p.b);ctx.stroke();ctx.fillStyle=COLORS.text;ctx.textAlign='center';ctx.fillText(timeText(t).slice(0,5),x,h-12);}return {X,Y,p,start,end,lo,hi};}
/**
 * 三角または菱形で新規・末尾評価を示す。
 * @param {CanvasRenderingContext2D} ctx - 文脈。
 * @param {number} x - 横位置。
 * @param {number} y - 縦位置。
 * @param {number} side - 売買方向。
 * @param {boolean} diamond - 菱形か。
 * @returns {void} 返り値なし。
 */
function marker(ctx,x,y,side,diamond=false){ctx.beginPath();if(diamond){ctx.moveTo(x,y-6);ctx.lineTo(x+6,y);ctx.lineTo(x,y+6);ctx.lineTo(x-6,y);}else{ctx.moveTo(x,y-side*7);ctx.lineTo(x-6,y+side*5);ctx.lineTo(x+6,y+side*5);}ctx.closePath();ctx.fill();ctx.strokeStyle='#07101d';ctx.lineWidth=1.5;ctx.stroke();}
/**
 * 選択条件のローソク足・全脚・評価曲線を描く。
 * @returns {void} 返り値なし。
 */
function draw(){const session=$('session').value,symbol=$('symbol').value,bars=DATA.candles[session+'|'+symbol]||[];const surface=context('price',490);if(!bars.length){surface.ctx.fillStyle=COLORS.text;surface.ctx.fillText('足がありません',25,35);return;}let start=windowRange?windowRange[0]:bars[0][0]-180,end=windowRange?windowRange[1]:Math.max(bars[bars.length-1][0]+480,...visibleTrades.map(t=>t.exit+120));const shown=bars.filter(b=>b[0]+300>=start&&b[0]<=end);const prices=shown.flatMap(b=>[b[2],b[3]]);for(const t of visibleTrades){if(t.entry>=start&&t.entry<=end)prices.push(t.ep);if(t.exit>=start&&t.exit<=end)prices.push(t.xp);}let lo=Math.min(...prices),hi=Math.max(...prices),pad=Math.max((hi-lo)*.11,symbol==='NK225'?30:1.5);lo-=pad;hi+=pad;const g=axes(surface,[lo,hi,start,end]);chartGeometry={...g,bars,session,symbol};const {ctx}=surface;ctx.save();ctx.beginPath();ctx.rect(g.p.l,g.p.t,g.p.r-g.p.l,g.p.b-g.p.t);ctx.clip();const bw=Math.max(2,Math.min(13,(g.p.r-g.p.l)*250/(end-start)));for(const b of shown){const x=g.X(b[0]+150),color=b[4]>=b[1]?COLORS.up:COLORS.down;ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,g.Y(b[2]));ctx.lineTo(x,g.Y(b[3]));ctx.stroke();const top=Math.min(g.Y(b[1]),g.Y(b[4])),bh=Math.max(1.5,Math.abs(g.Y(b[1])-g.Y(b[4])));ctx.fillRect(x-bw/2,top,bw,bh);}visibleTrades.forEach((t,index)=>{if(t.exit<start||t.entry>end)return;const color=t.side>0?COLORS.up:COLORS.down;ctx.globalAlpha=selectedTrade<0||selectedTrade===index?.88:.3;ctx.strokeStyle=color;ctx.lineWidth=selectedTrade===index?2.5:1.2;ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(g.X(t.condition),g.Y(t.ep));ctx.lineTo(g.X(t.entry),g.Y(t.ep));ctx.stroke();ctx.setLineDash([]);ctx.beginPath();ctx.moveTo(g.X(t.entry),g.Y(t.ep));ctx.lineTo(g.X(t.exit),g.Y(t.xp));ctx.stroke();ctx.fillStyle=color;marker(ctx,g.X(t.entry),g.Y(t.ep),t.side);ctx.fillStyle=t.closed?COLORS.exit:COLORS.open;if(t.closed){ctx.beginPath();ctx.arc(g.X(t.exit),g.Y(t.xp),4.3,0,Math.PI*2);ctx.fill();}else marker(ctx,g.X(t.exit),g.Y(t.xp),0,true);});ctx.restore();ctx.globalAlpha=1;ctx.fillStyle=COLORS.text;ctx.textAlign='left';ctx.fillText('５分足 ／ 原本順の指定価格約定',80,16);drawEquity(start,end);}
/**
 * 確定損益と全建玉評価を同じ軸で描く。
 * @param {number} start - 表示開始。
 * @param {number} end - 表示終了。
 * @returns {void} 返り値なし。
 */
function drawEquity(start,end){const target=context('equity',190),curve=(DATA.curves[key()]||[]).filter(r=>r[0]>=start-60&&r[0]<=end+60);if(!curve.length)return;let values=curve.flatMap(r=>[r[2],r[5]]),lo=Math.min(0,...values),hi=Math.max(0,...values),pad=Math.max((hi-lo)*.15,10000);const g=axes(target,[lo-pad,hi+pad,start,end],true),ctx=target.ctx;for(const [column,color] of [[5,'#71859f'],[2,COLORS.exit]]){ctx.beginPath();curve.forEach((r,i)=>{const x=g.X(r[0]),y=g.Y(r[column]);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.strokeStyle=color;ctx.lineWidth=column===2?2:1;ctx.stroke();}ctx.fillStyle=COLORS.text;ctx.textAlign='left';ctx.fillText('青：全建玉評価（含み込み）　灰：確定損益',80,16);}
/**
 * 選択状態から数値・全脚明細と図を更新する。
 * @returns {void} 返り値なし。
 */
function update(){selectedTrade=-1;windowRange=null;const method=$('method').value,symbol=$('symbol').value,session=$('session').value;visibleTrades=DATA.trades.filter(t=>t.method===method&&t.symbol===symbol&&t.session===session).sort((a,b)=>a.entry-b.entry||a.leg-b.leg);const summary=DATA.summaries[key()]||{},definition=DATA.methods[method];$('rule').textContent=definition?definition.label+' ／ '+definition.rules[0]:'';const stats=[['利益',yen(summary.profit_yen||0)],['損失',yen(summary.loss_yen||0)],['全建玉評価',yen(summary.net_yen||0)],['含み損益',yen(summary.open_yen||0)],['最大下落',yen(-(summary.max_drawdown_yen||0))],['返済脚／未返済',`${summary.closed_count||0}／${summary.open_count||0}`]];$('chart-summary').innerHTML=stats.map(([label,value])=>'<div><small>'+label+'</small><b>'+value+'</b></div>').join('');const rows=visibleTrades.map((t,i)=>'<tr class="trade-row" data-index="'+i+'"><td>'+`${t.cycle}–${t.leg}`+'</td><td class="'+(t.side>0?'green':'orange')+'">'+(t.side>0?'買い':'売り')+'</td><td>'+timeText(t.entry)+'</td><td>'+t.ep.toLocaleString('ja-JP')+'</td><td>'+timeText(t.exit)+'</td><td>'+t.xp.toLocaleString('ja-JP')+'</td><td class="'+(t.pnl>=0?'positive':'negative')+'">'+yen(t.pnl)+'</td><td>'+t.holding.toFixed(1)+'分</td><td>'+esc(t.reason)+'</td><td>'+t.atr.toFixed(2)+'</td></tr>').join('');$('trade-table').innerHTML='<table><thead><tr>'+['組–脚','方向','新規時刻','新規価格','返済/評価時刻','返済/評価価格','収支','保有','理由','固定ATR'].map(x=>'<th>'+x+'</th>').join('')+'</tr></thead><tbody>'+rows+'</tbody></table>';$('chart-note').textContent='表の行を選ぶとその建玉の前後へ拡大します。「セッション全体」で戻せます。全'+visibleTrades.length+'脚を表示。ラージ換算。'+(summary.open_count?'未返済の脚は紫の菱形で末尾評価を示します。':'この区間の建玉はすべて返済済みです。');draw();}
/**
 * 売買の行を選択して周辺へ表示を拡大する。
 * @param {number} index - 売買一覧の添字。
 * @returns {void} 返り値なし。
 */
function focusTrade(index){selectedTrade=index;const t=visibleTrades[index];windowRange=[Math.min(t.condition,t.entry)-900,t.exit+900];document.querySelectorAll('.trade-row').forEach(el=>el.classList.toggle('selected',+el.dataset.index===index));draw();$('price').scrollIntoView({behavior:'smooth',block:'center'});}
/**
 * ポインター近傍の足と売買を表示する。
 * @param {MouseEvent} event - 移動イベント。
 * @returns {void} 返り値なし。
 */
function hover(event){if(!chartGeometry)return;const rect=$('price').getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top,g=chartGeometry,tip=$('tooltip');if(x<g.p.l||x>g.p.r||y<g.p.t||y>g.p.b){tip.style.display='none';return;}const t=g.start+(x-g.p.l)/(g.p.r-g.p.l)*(g.end-g.start),bar=g.bars.reduce((a,b)=>Math.abs(b[0]+150-t)<Math.abs(a[0]+150-t)?b:a);let text=timeText(bar[0]).slice(0,5)+' ５分足<br>始 '+bar[1]+'　高 '+bar[2]+'<br>安 '+bar[3]+'　終 '+bar[4];const near=visibleTrades.filter(r=>Math.abs(g.X(r.entry)-x)<12||Math.abs(g.X(r.exit)-x)<12).slice(0,4);for(const r of near)text+='<br>'+`${r.cycle}–${r.leg} `+(r.side>0?'買い':'売り')+' '+timeText(r.entry)+' → '+timeText(r.exit)+' '+yen(r.pnl);tip.innerHTML=text;tip.style.display='block';tip.style.left=Math.max(6,Math.min(x+14,rect.width-355))+'px';tip.style.top=Math.max(8,Math.min(y+12,320))+'px';}

// ----------------------------------------
// 選択要素と描画イベントを初期化する。
$('method').innerHTML=Object.entries(DATA.methods).map(([id,value])=>'<option value="'+esc(id)+'">'+esc(id+' ／ '+value.label)+'</option>').join('');
$('session').innerHTML=Object.entries(DATA.sessions).map(([id,label])=>'<option value="'+id+'">'+label+'</option>').join('');
$('method').value=DATA.primary.NK225;$('session').value=Object.keys(DATA.sessions).at(-1);
for(const id of ['method','session'])$(id).addEventListener('change',update);
$('symbol').addEventListener('change',()=>{$('method').value=DATA.primary[$('symbol').value];update();});
$('primary').addEventListener('click',()=>{$('method').value=DATA.primary[$('symbol').value];update();});
if($('board-chart'))$('board-chart').addEventListener('click',()=>{$('symbol').value='NK225';$('method').value='P16_R1_E1_X5_U0';update();$('charts').scrollIntoView({behavior:'smooth',block:'start'});});
$('reset').addEventListener('click',()=>{selectedTrade=-1;windowRange=null;document.querySelectorAll('.trade-row').forEach(el=>el.classList.remove('selected'));draw();});
$('trade-table').addEventListener('click',event=>{const row=event.target.closest('.trade-row');if(row)focusTrade(+row.dataset.index);});
$('price').addEventListener('mousemove',hover);$('price').addEventListener('mouseleave',()=>{$('tooltip').style.display='none';});
window.addEventListener('resize',draw);update();
'''


def write_navigation() -> None:
    """機能: 過去作業を変えず、調査全体の最新リンクだけを更新する。

    引数: なし。返り値: なし (None)。
    """
    folder = DEST.name
    readme_path = DEST.parent/'README.md'
    content = readme_path.read_text(encoding='utf-8')
    lead = f'**最新は00008の[指定価格と費用ゼロの再探索]({folder}/{PAGE})です。費用ゼロ・指定価格約定で既存と新しい手法を比較し、条件固定後の保留・現在データを分けて評価しています。**'
    content = re.sub(r'\*\*最新は.*?\*\*', lead, content, count=1)
    content = re.sub(r'^\| `00008_.*\n', '', content, flags=re.M)
    content = content.replace('`00007_最悪成績の反転検証`（最新）', '`00007_最悪成績の反転検証`')
    line = f'| `{folder}`（最新） | 費用ゼロ・指定価格、旧24＋新18系統、正逆方向、有限複数玉、時間順と固定後照合 | [検証と５分足売買図]({folder}/{PAGE}) | [検証結果]({folder}/検証結果.md)・[資料案内]({folder}/README.md) |\n'
    content = content.replace('| --- | --- | --- | --- |\n', '| --- | --- | --- | --- |\n'+line, 1)
    content = content.replace('`00008_内容`', '`00009_内容`')
    readme_path.write_text(content, encoding='utf-8')
    index = DEST.parent/'index.html'
    content = index.read_text(encoding='utf-8')
    content = re.sub(r'\s*<!--00008開始-->.*?<!--00008終了-->', '', content, flags=re.S)
    content = content.replace('class="task latest"', 'class="task"').replace(' <span class="badge">最新</span>', '')
    content = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新は、追加データを含めて費用ゼロ・指定価格約定で再探索し、固定後の区間で確認した資料です。</p>', content, count=1, flags=re.S)
    card = f'''\n  <!--00008開始--><article class="task latest" aria-labelledby="exact-title">
    <div class="number">作業 00008 <span class="badge">最新</span></div>
    <h2 id="exact-title">指定価格と費用ゼロの再探索</h2>
    <p>費用ゼロ・指定価格での約定を前提に、旧24＋新18系統、正逆方向、トレーリング、利益保護、複数枚、両建て・有限グリッドを再探索。思想別の結果と固定後照合を分けて掲載しました。</p>
    <a class="button" href="{folder}/{PAGE}">検証結果と５分足売買図を開く →</a>
    <ul><li><a href="{folder}/検証結果.md">入口・出口とセッション別損益</a></li><li><a href="{folder}/README.md">資料の読む順序</a></li></ul>
    <p class="folder">保存先：{folder}</p>
  </article><!--00008終了-->\n'''
    content = content.replace('</header>', '</header>'+card, 1)
    index.write_text(content, encoding='utf-8')


def main() -> None:
    """機能: 完了済みの許可された検証結果から配布資料を生成する。

    引数: CLIの照合prefix・保存先 (str|None)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--holdout-prefix')
    parser.add_argument('--live-prefix')
    parser.add_argument('--live-session')
    parser.add_argument('--live-root')
    args = parser.parse_args()
    stages = load_stages(args)
    configs = {c['id']:c for c in load_json('条件一覧.json')}
    profiles = {p['id']:p for p in load_json('信号条件一覧.json')}
    selected = load_json('最終選択.json')
    full = pd.read_csv(WORK/'全条件_セッション集計.csv')
    walk = pd.read_csv(WORK/'時間順評価.csv')
    doc = build_document(stages, configs, profiles, selected, full, walk)
    chart = chart_data(stages, configs, profiles, selected)
    DEST.mkdir(parents=True, exist_ok=True)
    materials = DEST/'資料'
    materials.mkdir(exist_ok=True)
    for path in WORK.iterdir():
        if path.is_file() and path.suffix in ['.py', '.md', '.csv', '.json'] and not path.name.startswith('新規通知_'):
            shutil.copy2(path, materials/path.name)
    serialized = json.dumps(chart, ensure_ascii=False, allow_nan=False, separators=(',', ':')).replace('</', '<\\/')
    page = '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>指定価格と費用ゼロの再探索｜00008</title><style>'''+CSS+'''</style></head><body>
<!--
[コンポーネント概要]
本文は思想・固定した条件・評価区間ごとの結果を表示する静的資料です。
#symbol/#method/#session は銘柄・条件・セッションの選択欄です。
#price は５分足と全建玉の新規・返済を、#equity は含み損益を含む評価収支を表示します。
#trade-table の行を選ぶと対象取引の前後へ拡大し、#reset でセッション全体へ戻ります。
#tooltip は足と近隣取引の詳細です。外部へのデータ通信は行いません。
-->
<main><header><div class="eyebrow">作業 00008 ／ NK225・TOPIX先物</div><h1>指定価格と費用ゼロで<br>方向予測と注文方法を再探索</h1><p class="lead">過去で選んだ結果と、条件を固定してから確認した結果を分けて読む。</p><div class="badges"><span>手数料 0</span><span>気配差控除 0</span><span>指定価格で成立</span><span>セッション内返済</span><span>１銘柄 最大３枚</span></div></header>
<nav><a href="#main">主候補の結果</a><a href="#charts">５分足と売買</a><a href="#time">時間順の検証</a><a href="#scope">探索の全体</a><a href="#sessions">セッション別収支</a><a href="#methodology">計算と監査</a><a href="../index.html">作業一覧</a></nav>'''+''.join(doc.parts)+'''<footer>全額はラージ換算。NK225：１ポイント1,000円、TOPIX：１ポイント10,000円。<br>原本と過去の作業フォルダは変更していません。資料はオフラインで開けます。</footer></main><script type="application/json" id="data">'''+serialized+'''</script><script>'''+SCRIPT+'</script></body></html>'
    (DEST/PAGE).write_text(page, encoding='utf-8')
    (DEST/'検証結果.md').write_text('# 指定価格と費用ゼロの再探索\n\n[５分足と全脚の売買図]('+PAGE+')\n\n'+'\n'.join(doc.markdown), encoding='utf-8')
    guide = f'''# 00008 指定価格と費用ゼロの再探索

**最初に見るファイル：[指定価格と費用ゼロの再探索]({PAGE})**

読む順序：

1. HTML冒頭で、探索６セッション・条件固定後の保留デイ・現在ナイトを分けた主候補の結果を確認する。
2. HTML第２章で５分足と全建玉の入口・出口を見る。表の行を選ぶと拡大できる。
3. 第３章で「過去だけから条件を選ぶ方針」の成績を確認し、第５章以降で思想別の具体条件と結果を読む。
4. [検証結果.md](検証結果.md)で数値と条件を文字で読む。
5. [検証計画](資料/検証計画.md)、[新規仮説と文献](資料/新規仮説と文献.md)、[入力データ監査](資料/入力データ監査.md)を確認する。

今回の主前提は費用ゼロ・気配差控除ゼロ・指定価格での理想約定。以前の費用込み結果と混同しない。

主な詳細資料：

- [全条件のセッション集計](資料/全条件_セッション集計.csv)
- [最終選択](資料/最終選択.json)
- [時間順評価](資料/時間順評価.csv)
- [条件一覧](資料/条件一覧.json)
- [信号条件一覧](資料/信号条件一覧.json)
- [学習代表の全脚](資料/学習代表_全取引.json)
- [学習代表のセッション集計](資料/学習代表_セッション集計.csv)
- [新規信号の未来打切り監査](資料/新規信号_打切り監査.json)
- [指定価格再生の独立監査](資料/指定価格再生の独立監査.json)
- [保留デイのセッション集計](資料/保留日中_セッション集計.csv)
- [現在ナイトのセッション集計](資料/現在照合_セッション集計.csv)
- [条件凍結の記録](資料/現在照合_凍結記録.json)
- [現在データ６要求の取得記録](資料/現在照合_取得記録.json)
- [指定された４波との照合](資料/指定した４波の照合.md)

資料フォルダのソースは参照用コピーである。再実行には `work/wave_v13` と既存 `work/wave_v7〜wave_v11` の依存コード・元データが必要。過去の凍結検証を変更せず、新しい作業側で読取先を設定している。

含み損益を含む全資産評価を掲載しており、利益玉だけ返済して残った損失を無視してはいない。保留・現在結果を見ての条件選び直しは行わない。
'''
    (DEST/'README.md').write_text(guide, encoding='utf-8')
    write_navigation()
    print(f'報告を生成しました: {DEST/PAGE}')
    print(f'図解: {len(chart["methods"])}方式、{len(chart["sessions"])}セッション、{len(chart["trades"])}脚')


if __name__ == '__main__':
    main()
