"""M3逆A00の変数比較を、固定１枚の報告と枚数切替付きHTMLにまとめる。"""

from __future__ import annotations

import argparse
from collections import defaultdict
import html
import json
from pathlib import Path
import re
import shutil

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
FOLDER = '00014_M3逆A00の変数と安定性'
OUT = ROOT / 'アルゴリズム調査' / FOLDER
PAGE = 'M3逆A00の変数と安定性.html'
SYMBOLS = ['TOPIX', 'NK225']
NAMES = {'TOPIX': 'TOPIXミニ', 'NK225': 'NK225マイクロ'}
FAMILY_IDEAS = {
    '基準': '元のM3逆A00を固定１枚で再現する。',
    '入口・損切り・追跡幅': '反転の確認幅と、損切り・利益の追跡幅の釣合いを変える。',
    '方向判定': '移動平均・確認回数・信号の鮮度・板の一致で、逆方向を狙う根拠を変える。',
    '追跡開始': '早く利益を守るか、動き始めの揺れを待つかを変える。',
    '利益後の幅短縮': '大きく順行した後だけ追跡幅を狭くし、含み益の減少を抑える。',
    '建値保護': '十分に順行した取引を、損失へ戻しにくくする。',
    '初動不発の縮小': '時間を使っても順行しない取引の損切りを縮める。',
    '再入場の間隔': '返済直後の小さな往復に入り直す頻度を変える。',
    '新規注文の寿命': '反転が来ない注文を、いつ取り消して判定し直すかを変える。',
    '追跡して新規': '固定した逆指値に代え、追跡安値・高値からの反転で入る。',
    '保有時間': '伸びない取引に使う時間と、長い波を待つ時間を変える。',
    '時間帯': '夜間の新規休止・全返済・追跡幅変更を比較する。',
    '判断撤回': '元の方向判断が反対へ変わった時点で保有を閉じる。',
    '利益割合の保護': '最高含み益の一定割合を残す返済条件を加える。',
}


def read(name: str):
    """保存済みJSONを読み込む。

    引数: name (str) は作業内ファイル名。返り値: JSONの値 (dict | list)。
    """
    return json.loads((WORK / name).read_text(encoding='utf-8'))


def esc(value: object) -> str:
    """表示値をHTML用にエスケープする。

    引数: value (object) は表示値。返り値: HTML文字列 (str)。
    """
    return html.escape(str(value), quote=True)


def money(value: float, signed: bool = False) -> str:
    """固定１枚の円額を表示する。

    引数: value (float) は円額、signed (bool) は正数の符号指定。返り値: 円表示 (str)。
    """
    number = round(value)
    return ('+' if signed and number > 0 else '') + f'{number:,}円'


def scaled(value: float, symbol: str, kind: str = 'money', tone: bool = False, extra: str = '') -> str:
    """１枚の基準値を持ち、表示枚数で切り替えられる要素を作る。

    引数: value (float)、symbol/kind/extra (str)、tone (bool) は符号色の指定。
    返り値: 倍率対応のspan (str)。
    """
    signed = kind.startswith('signed-')
    unit = '枚' if kind.endswith('units') else '円'
    integer = int(value + .5) if value >= 0 else int(value - .5)
    prefix = '約' if kind == 'approx-money' else ('+' if signed and integer > 0 else '')
    text = prefix + f'{integer:,}' + unit
    color = ('positive' if value >= 0 else 'negative') if tone else ''
    attrs = ' data-tone="sign"' if tone else ''
    return f'<span class="number {color} {extra}" data-symbol="{symbol}" data-base="{value}" data-kind="{kind}"{attrs}>{text}</span>'


def session_label(session: str) -> str:
    """夜間が翌朝まで続くことを明示したラベルを作る。

    引数: session (str) は日付と区分。返り値: 表示ラベル (str)。
    """
    date, part = session.split('_')
    day = int(date[-2:])
    return f'9/{day} 日中' if part == 'Day' else f'9/{day} 夜間 → 9/{day + 1} 朝'


def ratio(value: float | None) -> str:
    """損益比などを小数２桁へ整える。

    引数: value (float | None) は比率。返り値: 比率の文字列 (str)。
    """
    return '算定なし' if value is None else f'{value:.2f}'


def roles(identifier: str, selection: dict) -> str:
    """選択結果内での役割を日本語で示す。

    引数: identifier (str) は条件ID、selection (dict) は選択結果。返り値: 役割 (str)。
    """
    output = []
    if identifier == selection['baseline']:
        output.append('元の基準')
    if identifier == selection['primary']:
        output.append('主候補・近傍重視')
    if identifier == selection['single_point_best']:
        output.append('単独評価が最大')
    for symbol in SYMBOLS:
        if identifier == selection['by_symbol'].get(symbol):
            output.append(f'{NAMES[symbol]}の比較候補')
    return ' ／ '.join(output) if output else '近傍評価の比較候補'


def rules(record: dict, specs: dict) -> tuple[str, str, str]:
    """方向判定・新規・返済の機械的な条件を短く説明する。

    引数: record (dict) は条件、specs (dict) は信号ID辞書。
    返り値: 方向・入口・出口の３文 (tuple[str, str, str])。
    """
    config = record['config']
    direction = '両銘柄の上向きを確認したら売りを待ち、下向きなら買いを待つ。'
    if record['signal_id'] != 'S00':
        direction += ' ' + specs[record['signal_id']]['description']
    if config['entry_mode']:
        entry = f'追跡安値・高値から{config["entry_atr"]:g}ATRの反転で入る。'
    else:
        entry = f'狙う逆方向へ{config["entry_atr"]:g}ATR進めば逆指値で入る。'
    entry += f' 新規注文は{config["ttl_seconds"]:g}秒有効。'
    exit_text = f'初期損切り{config["stop_atr"]:g}ATR。{config["activation_atr"]:g}ATR順行後、極値から{config["main_trail"]:g}ATRの戻りで返済。{config["timeout_min"]:g}分は保有上限であり、損切り・追跡・場末返済が先に成立すればその時点で返済。'
    if record['family'] not in ['基準', '入口・損切り・追跡幅', '方向判定', '追跡開始', '新規注文の寿命', '追跡して新規', '保有時間']:
        exit_text += ' ' + record['description']
    return direction, entry, exit_text


def results_table(rows: list[dict], symbol: str, weekly: bool = False) -> str:
    """週またはセッションごとの金額と累計返済枚数を表にする。

    引数: rows (list[dict])、symbol (str)、weekly (bool)。返り値: 表のHTML (str)。
    """
    parts = ['<div class="table-wrap"><table class="pnl"><thead><tr><th>区間</th><th>利益／累計返済枚数</th><th>損失／累計返済枚数</th><th>収支／累計枚数差</th></tr></thead><tbody>']
    for row in rows:
        label = '１週間合計' if weekly else session_label(row['session'])
        parts.append(f'<tr><td>{esc(label)}</td><td>{scaled(row["gross_profit_yen"], symbol, tone=True)}<small>累計返済 {scaled(row["profit_units"], symbol, "units")}</small></td>')
        parts.append(f'<td>{scaled(-row["gross_loss_yen"], symbol, tone=True)}<small>累計返済 {scaled(row["loss_units"], symbol, "units")}</small></td>')
        parts.append(f'<td>{scaled(row["net_yen"], symbol, "signed-money", True)}<small>累計枚数差 {scaled(row["unit_balance"], symbol, "signed-units")}</small></td></tr>')
    parts.append('</tbody></table></div>')
    return ''.join(parts)


def overview(records: dict, selection: dict) -> str:
    """基準と主候補の改善幅を最初に示す。

    引数: records (dict) は条件辞書、selection (dict) は選択結果。返り値: HTML (str)。
    """
    main, base = records[selection['primary']], records[selection['baseline']]
    parts = [f'<section class="panel" id="overview"><h2>主候補は {esc(main["id"])}：{esc(main["family"])}</h2>',
             f'<p>{esc(main["description"])}</p>',
             '<div class="table-wrap"><table><thead><tr><th>銘柄</th><th>元の基準・週収支</th><th>主候補・週収支</th><th>基準からの差</th></tr></thead><tbody>']
    for symbol in SYMBOLS:
        old, new = base['weeks'][symbol], main['weeks'][symbol]
        parts.append(f'<tr data-overview="{symbol}"><td>{NAMES[symbol]}</td><td>{scaled(old["net_yen"], symbol, "signed-money", True)}</td><td>{scaled(new["net_yen"], symbol, "signed-money", True)}</td><td>{scaled(new["net_yen"] - old["net_yen"], symbol, "signed-money", True)}</td></tr>')
    parts.append('</tbody></table></div>')
    neighbor = main['neighbor']
    if set(main['changes']) == {'timeout_min'} and main['signal_id'] == base['signal_id']:
        parts.append(f'<p>基準から変えたのは、保有時間の上限を{base["config"]["timeout_min"]:g}分から{main["config"]["timeout_min"]:g}分に延ばした点だけです。方向判定・入口・損切り・追跡幅は共通です。</p>')
    parts.append(f'<p class="note">同じ設定を両銘柄に適用。周辺設定{neighbor["count"]}件のうち{neighbor["positive_count"]}件で、両銘柄の週収支と最大利益セッション除外収支が黒字です。近傍を含む選択条件を通過したのは{selection["stable_eligible_count"]}／{len(records)}条件。比較候補には損切り幅が異なるものもあります。</p>')
    parts.append(f'<p><b>残る弱点：</b>主候補のNK225は利益上位３取引を除くと {scaled(main["weeks"]["NK225"]["drop_top3_trades_net"], "NK225", "signed-money", True)}。大きな利益への依存は残ります。</p>')
    parts.append('<div class="callout"><p><b>最大勝ちの除外は２種類を分けます。</b>「セッション除外」は最も黒字の１区間全体、「取引除外」は最も利益が大きい１回の新規〜返済を取り除きます。残った寄与を調べる診断で、除外後の売買経路は再計算しません。</p></div></section>')
    return ''.join(parts)


def neighbor_table(record: dict, records: dict) -> str:
    """主候補の直近上下を全件、両銘柄の損益比と除外後収支で見せる。

    引数: record (dict) は主候補、records (dict) は全条件。
    返り値: 近傍表のHTML (str)。
    """
    labels = {'entry_atr': '入口', 'stop_atr': '損切り', 'main_trail': '追跡幅'}
    parts = ['<details id="primary-neighbors"><summary>主候補の周辺設定を全件見る</summary><div class="table-wrap"><table><thead><tr><th>条件・変更点</th><th>TOPIX 総利益／総損失</th><th>TOPIX 最大利益区間除外後</th><th>NK 総利益／総損失</th><th>NK 最大利益区間除外後</th></tr></thead><tbody>']
    for identifier in record['neighbor']['ids']:
        other = records[identifier]
        changes = '、'.join(f'{label} {other["config"][key]:g}ATR' for key, label in labels.items() if other['config'][key] != record['config'][key])
        parts.append(f'<tr data-neighbor="{identifier}"><td>{identifier}<small>{esc(changes)}</small></td>')
        for symbol in SYMBOLS:
            week = other['weeks'][symbol]
            parts.append(f'<td>{ratio(week["money_ratio"])}倍</td><td>{scaled(week["drop_best_session_net"], symbol, "signed-money", True)}<small>除外後PF {ratio(week["drop_best_session_pf"])}</small></td>')
        parts.append('</tr>')
    parts.append('</tbody></table></div></details>')
    return ''.join(parts)


def variant(record: dict, symbol: str, sessions: list[dict]) -> str:
    """１条件・１銘柄の週成績、最大勝ち除外とセッション明細を表示する。

    引数: record (dict)、symbol (str)、sessions (list[dict])。返り値: 銘柄版HTML (str)。
    """
    week = record['weeks'][symbol]
    parts = [f'<section class="variant {"topix" if symbol == "TOPIX" else "nk"}" data-record="{record["id"]}" data-variant-symbol="{symbol}"><h3>{NAMES[symbol]}</h3>',
             f'<div class="result-line"><span>週収支</span>{scaled(week["net_yen"], symbol, "signed-money", True, "big-number")}<span>黒字 {week["positive_sessions"]}／10セッション</span></div>',
             results_table([week], symbol, True),
             f'<div class="stats"><span>総利益／総損失 <b>{ratio(week["money_ratio"])}倍</b></span><span>１枚平均の利益／損失 <b>{ratio(week["unit_payoff"])}倍</b></span><span>最大下落 <b>{scaled(week["drawdown_yen"], symbol)}</b></span></div>',
             '<div class="table-wrap"><table class="exclusions"><thead><tr><th>寄与度の診断</th><th>残る週収支</th></tr></thead><tbody>',
             f'<tr><td>最大利益の１セッションを除外<small>{session_label(week["best_session"])}</small></td><td>{scaled(week["drop_best_session_net"], symbol, "signed-money", True)}</td></tr>',
             f'<tr><td>最大利益の１取引を除外<small>除く１取引の利益 {scaled(week["best_trade_yen"], symbol)}</small></td><td>{scaled(week["drop_best_trade_net"], symbol, "signed-money", True)}</td></tr>',
             '</tbody></table></div>',
             f'<p class="note">同時保有は固定 {scaled(1, symbol, "units")}。全返済累計 {scaled(week["closed_units"], symbol, "units")}、損益０の返済 {scaled(week["zero_units"], symbol, "units")}。取引{week["cycles"]}回、最長{week["longest_loss_streak"]}連敗。１枚平均は利益 約{money(week["avg_profit_per_unit"])}／損失 約{money(week["avg_loss_per_unit"])}です。</p>',
             f'<details class="sessions"><summary>10セッションの利益・損失・収支</summary>{results_table(sessions, symbol)}<p class="note">累計返済枚数は売買の繰返しの合計で、同時保有ではありません。全セッションの未返済残は０です。</p></details>',
             '<details class="contribution"><summary>前後半・日夜・大きな３取引への依存</summary><div class="table-wrap"><table><thead><tr><th>区分</th><th>収支</th></tr></thead><tbody>']
    for label, key in [('先頭５セッション', 'first_half_net'), ('後半５セッション', 'second_half_net'), ('日中合計', 'day_net'), ('夜間合計', 'night_net'), ('利益上位３取引を除外', 'drop_top3_trades_net'), ('最悪１取引の損失', 'worst_trade_yen')]:
        parts.append(f'<tr><td>{label}</td><td>{scaled(week[key], symbol, "signed-money", True)}</td></tr>')
    parts.append('</tbody></table></div></details></section>')
    return ''.join(parts)


def candidate_chapters(records: dict, selection: dict, specs: dict, cells: dict) -> str:
    """表示候補ごとに条件と両銘柄の結果をまとめる。

    引数: records/selection/specs/cells (dict) は集計・選択・信号・区間辞書。
    返り値: 条件別章のHTML (str)。
    """
    parts = []
    for identifier in selection['displayed']:
        record = records[identifier]
        direction, entry, exit_text = rules(record, specs)
        opened = ' open' if identifier == selection['primary'] else ''
        parts.extend([f'<details class="chapter" id="{identifier}"{opened}><summary>{esc(identifier)} · {esc(roles(identifier, selection))} · {esc(record["family"])}</summary>',
                      f'<header class="chapter-heading"><h2>{esc(record["description"])}</h2><div class="method-id">{identifier} ／ 信号 {record["signal_id"]}</div>',
                      f'<dl class="rules"><dt>方向</dt><dd>{esc(direction)}</dd><dt>入口</dt><dd>{esc(entry)}</dd><dt>出口</dt><dd>{esc(exit_text)}</dd></dl></header>'])
        parts.extend(variant(record, symbol, cells[(identifier, symbol)]) for symbol in SYMBOLS)
        if identifier == selection['primary']:
            parts.append(neighbor_table(record, records))
        neighbor = record['neighbor']
        parts.append(f'<p class="note">直近の周辺設定：{neighbor["positive_count"]}／{neighbor["count"]}件で両銘柄の週収支・最大利益セッション除外収支が黒字。入口・損切り・追跡幅を１項目だけ変えた近傍です。</p></details>')
    return ''.join(parts)


def families(records: dict, selection: dict) -> str:
    """思想別に試した条件数・通過数・代表結果を短く並べる。

    引数: records/selection (dict) は候補と順位。返り値: 思想別HTML (str)。
    """
    groups = defaultdict(list)
    for record in records.values():
        groups[record['family']].append(record)
    positions = {identifier: index for index, identifier in enumerate(selection['ranking'])}
    parts = ['<section class="panel" id="families"><h2>何を変えて試したか</h2><p class="note">各思想の代表は入口・損切り・追跡幅との組合せを含む、共通の選択順位の最上位です。単独変数の効果とは区別します。両銘柄の円額は合算していません。</p>']
    for family, rows in groups.items():
        best = min(rows, key=lambda row: positions[row['id']])
        common = sum(row['common_eligible'] for row in rows)
        stable = sum(row['stable_eligible'] for row in rows)
        parts.append(f'<details class="family" data-family="{esc(family)}"><summary>{esc(family)} — {len(rows)}条件、近傍込み通過{stable}件</summary>')
        parts.append(f'<p>{esc(FAMILY_IDEAS.get(family, family))}</p><p>両銘柄の条件を通過したのは{common}件、そのうち近傍込みは{stable}件。代表{best["id"]}の週収支は、TOPIXミニ {scaled(best["weeks"]["TOPIX"]["net_yen"], "TOPIX", "signed-money", True)}、NK225マイクロ {scaled(best["weeks"]["NK225"]["net_yen"], "NK225", "signed-money", True)}。</p>')
        if not stable:
            parts.append('<p class="note">この思想には近傍込みの選択条件を満たす設定がありません。代表値は比較用です。</p>')
        parts.append('</details>')
    parts.append('<details id="matched-controls"><summary>入口・損切り・追跡幅を基準に揃えた対照</summary><p class="note">入口0.25・損切り１・追跡２ATRを共通にした、各思想内の上位設定です。方向判定の群以外はS00の信号を使います。各行にはその思想の変更だけを加えています。</p><div class="table-wrap"><table><thead><tr><th>思想・設定</th><th>変更内容</th><th>TOPIX 週収支／基準差</th><th>NK 週収支／基準差</th></tr></thead><tbody>')
    baseline = records[selection['baseline']]
    for family, rows in groups.items():
        controls = [row for row in rows if row['config']['entry_atr'] == .25 and row['config']['stop_atr'] == 1 and row['config']['main_trail'] == 2 and (family == '方向判定' or row['signal_id'] == 'S00')]
        if not controls:
            continue
        best = min(controls, key=lambda row: positions[row['id']])
        parts.append(f'<tr data-control="{best["id"]}"><td>{esc(family)}<small>{best["id"]}</small></td><td>{esc(best["description"])}</td>')
        for symbol in SYMBOLS:
            parts.append(f'<td>{scaled(best["weeks"][symbol]["net_yen"], symbol, "signed-money", True)}<small>基準差 {scaled(best["weeks"][symbol]["net_yen"] - baseline["weeks"][symbol]["net_yen"], symbol, "signed-money", True)}</small></td>')
        parts.append('</tr>')
    parts.append('</tbody></table></div></details>')
    parts.append('<p><a href="資料/全条件一覧.json">全設定</a> · <a href="資料/週比較.json">全条件の週比較</a> · <a href="資料/セッション比較.json">全セッション結果</a></p></section>')
    return ''.join(parts)


def additional_diagnostics() -> str:
    """選択後の保有時間近傍を、順位の再選択と分けて表示する。

    引数: なし。返り値: 追加診断のHTML (str)。
    """
    summary, rows = read('追加近傍診断の要約.json'), read('追加近傍診断.json')
    lookup = {row['id']: row for row in rows}
    parts = ['<section class="panel" id="additional-diagnostics"><h2>保有時間の上限付近も追加確認</h2>',
             f'<p>主候補を選んだ後、保有時間300〜420分と入口・損切り・追跡幅の近くを{summary["count"]}条件再生しました。両銘柄の週黒字は{summary["both_positive"]}／{summary["count"]}、最大利益セッション除外後も両方黒字は{summary["both_drop_positive"]}／{summary["count"]}です。</p>',
             '<details><summary>保有時間だけを変えた５条件</summary><div class="table-wrap"><table class="holding-diagnostic"><thead><tr><th>保有上限</th><th>TOPIX 週収支</th><th>TOPIX 最大利益区間除外</th><th>NK 週収支</th><th>NK 最大利益区間除外</th></tr></thead><tbody>']
    for identifier in summary['holding_only']:
        row = lookup[identifier]
        parts.append(f'<tr data-holding="{identifier}"><td>{row["config"]["timeout_min"]:g}分' + ('<small>主候補を維持</small>' if row['config']['timeout_min'] == 360 else '') + '</td>')
        for symbol in SYMBOLS:
            parts.append(f'<td>{scaled(row["weeks"][symbol]["net_yen"], symbol, "signed-money", True)}</td><td>{scaled(row["weeks"][symbol]["drop_best_session_net"], symbol, "signed-money", True)}</td>')
        parts.append('</tr>')
    parts.append('</tbody></table></div></details>')
    parts.append(f'<p class="note">結果を見てから行った追加診断で、主候補を330分などへ選び直していません。最初の904条件＋追加135条件（１条件重複、異なる設定は1,038）。追加群で最も悪いNKの最大利益セッション除外収支は {scaled(summary["minimum_drop_net"]["NK225"], "NK225", "signed-money", True)} です。未知週の確認とは異なります。</p>')
    parts.append('<p><a href="資料/追加近傍診断.json">追加135条件の全結果</a> · <a href="資料/追加近傍診断の要約.json">追加診断の要約</a> · <a href="資料/追加診断前の固定記録.json">追加診断前の条件固定</a></p></section>')
    return ''.join(parts)


def supplement(records: dict, selection: dict) -> str:
    """選択と売買の前提を必要な人向けに表示する。

    引数: records/selection (dict) は比較結果。返り値: 補足HTML (str)。
    """
    return additional_diagnostics() + families(records, selection) + '''<section class="panel"><h2>選択条件と計算</h2><details><summary>主候補の選び方・検証の範囲</summary>
<p>各銘柄で、週黒字、総利益／総損失と１枚平均の利益／損失が１超、黒字６／10以上、稼働８／10以上、30取引以上を求めます。最大利益セッション・最大利益取引を別々に除いて黒字、前半・後半・日中・夜間もそれぞれ黒字とします。</p>
<p>さらに入口幅・損切り幅・追跡幅を１項目だけ変えた直近上下の近傍を調べます。３近傍以上、75％以上で両銘柄の週収支と最大利益セッション除外収支が黒字であることを求めます。通過後は、近傍の弱い銘柄側の除外後PF中央値、本人の同PF、変更項目の少なさの順です。</p>
<p>「単独評価が最大」は本人の最大利益セッション除外PFの弱い銘柄側が最大の条件で、週収支最大という意味ではありません。銘柄別比較候補も、表示した同じ設定を両方に適用した結果です。枚数は固定１枚で条件を選び、枚数による最適化はしていません。</p>
<p>基準S00では、確定１分足のEMA8−EMA30が±0.15ATR以上、EMA30の３本変化が同方向に±0.03ATR以上を２回確認します。自銘柄と、公開後さらに60秒遅らせた相手の方向一致を２回確認してM3の向きを決めます。弱まっただけでは状態を維持し、反対方向の確認で更新します。</p>
<p>ATRは確定５分足のTRを係数1/12で平滑化し、初回注文時点で固定。信号は公開済みの確定足と板を使用します。開始20分後から新規受付し、日中15:05・夜間05:20で締切。日中15:35・夜間05:50以降に返済を指示し、次の有効な原本行で全返済します。最大下落は含み損益込みの週の最高点からの下落です。</p>
<p>最大勝ちの除外は、該当損益を集計から除く寄与度診断です。後続のエントリー・資産曲線などは再計算しません。同じ既知週での探索・比較であり、未知期間で成績を確認したものではありません。</p>
<p><a href="資料/主候補の条件.json">主候補の条件</a> · <a href="資料/探索前の固定記録.json">探索前の条件固定</a> · <a href="資料/選択結果.json">選択結果</a> · <a href="資料/信号条件一覧.json">方向判定の条件</a> · <a href="資料/基準再現監査.json">元の基準との一致</a> · <a href="資料/audit.json">損益と選択の独立監査</a> · <a href="資料/audit_signals.json">信号の因果性監査</a> · <a href="資料/audit_causality.json">売買の因果性監査</a> · <a href="資料/audit_diagnostics.json">追加診断の監査</a> · <a href="資料/表示倍率検査.json">表示倍率の検査</a></p>
</details></section>'''


def markdown_report(records: dict, selection: dict, specs: dict, cells: dict) -> str:
    """固定１枚の条件・週・各セッションをMarkdown報告にする。

    引数: records/selection/specs/cells (dict)。返り値: 報告本文 (str)。
    """
    main = records[selection['primary']]
    diagnostic = read('追加近傍診断の要約.json')
    lines = ['# M3逆A00の変数と安定性', '', f'主候補は **{selection["primary"]}**。HTMLではTOPIXミニ１〜10枚、NK225マイクロ１〜20枚へ表示を変えられます。以下は全て固定１枚です。', '',
             f'基準から変えたのは保有上限180→{main["config"]["timeout_min"]:g}分のみ。方向判定・入口・損切り・追跡幅は共通です。上限まで必ず持つ意味ではなく、損切り・追跡・場末条件が先に成立すれば返済します。', '',
             f'{len(records)}条件を同じ既知１週間で探索しました。両銘柄の条件通過{selection["common_eligible_count"]}件、近傍込み通過{selection["stable_eligible_count"]}件。未知期間での評価ではありません。費用０・指定価格約定・場内全返済です。', '',
             '最大利益セッション除外と最大利益取引除外は別です。該当の損益寄与だけを除き、売買経路は再計算していません。', '',
             f'主候補のNK225は利益上位３取引を除くと{money(main["weeks"]["NK225"]["drop_top3_trades_net"], True)}となり、大きな利益への依存は残ります。', '',
             f'選択後に追加した近傍135条件では両銘柄週黒字{diagnostic["both_positive"]}件、最大利益セッション除外後も両方黒字{diagnostic["both_drop_positive"]}件。主候補は選び直していません。904探索＋135追加診断（１条件重複、異なる設定1,038）です。', '']
    for identifier in selection['displayed']:
        record = records[identifier]
        direction, entry, exit_text = rules(record, specs)
        lines.extend([f'## {identifier}：{roles(identifier, selection)}', '', record['description'], '', f'入口：{direction} {entry}', '', f'出口：{exit_text}', ''])
        for symbol in SYMBOLS:
            week = record['weeks'][symbol]
            lines.extend([f'### {NAMES[symbol]}・固定１枚', '',
                          f'週収支 {money(week["net_yen"], True)}。総利益／総損失 {ratio(week["money_ratio"])}倍、１枚平均の利益／損失 {ratio(week["unit_payoff"])}倍、最大下落 {money(week["drawdown_yen"])}。黒字{week["positive_sessions"]}／10区間。', '',
                          f'最大利益セッション除外後 {money(week["drop_best_session_net"], True)}、最大利益１取引除外後 {money(week["drop_best_trade_net"], True)}。', '',
                          '| 区間 | 利益／累計返済枚数 | 損失／累計返済枚数 | 収支／累計枚数差 |', '| --- | ---: | ---: | ---: |'])
            for label, row in [('週合計', week)] + [(session_label(row['session']), row) for row in cells[(identifier, symbol)]]:
                lines.append(f'| {label} | {money(row["gross_profit_yen"])}／{row["profit_units"]:,}枚 | {money(-row["gross_loss_yen"])}／{row["loss_units"]:,}枚 | {money(row["net_yen"], True)}／{row["unit_balance"]:+,}枚 |')
            lines.append('')
    lines.extend(['全条件・思想別の比較はHTMLと資料の全条件一覧・週比較をご覧ください。累計返済枚数は同時保有ではありません。', ''])
    return '\n'.join(lines)


def update_indexes() -> None:
    """新作業の確認後に、共通一覧の最新案内を00014へ更新する。

    引数: なし。返り値: なし。過去作業フォルダの内容は変更しない。
    """
    base = OUT.parent
    path = base / 'README.md'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00014の[M3逆A00の変数と安定性]({FOLDER}/{PAGE})です。入口・出口・方向判定などを比較し、基準と主候補、最大勝ち除外後の収支を確認できます。**', text, count=1)
    text = text.replace('`00013_共通上位４手法のスケールダウン`（最新）', '`00013_共通上位４手法のスケールダウン`')
    text = re.sub(r'^\| `00014_.*\n', '', text, flags=re.M)
    entry = f'| `{FOLDER}`（最新） | M3逆A00の変数・近傍・最大勝ち依存を比較 | [変数と安定性]({FOLDER}/{PAGE}) | [固定１枚の報告]({FOLDER}/検証結果.md)・[案内]({FOLDER}/README.md) |\n'
    text = text.replace('| --- | --- | --- | --- |\n', '| --- | --- | --- | --- |\n' + entry, 1).replace('`00014_内容`', '`00015_内容`')
    path.write_text(text, encoding='utf-8')
    path = base / 'index.html'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<!--00014開始-->.*?<!--00014終了-->', '', text, flags=re.S)
    text = text.replace('class="task latest"', 'class="task"').replace(' <span class="badge">最新</span>', '')
    text = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新はM3逆A00の変数比較。基準と主候補を、両銘柄の同じ設定・近傍・最大勝ち除外後の収支で確認します。</p>', text, count=1)
    entry = f'<!--00014開始--><article class="task latest"><div class="number">作業00014 <span class="badge">最新</span></div><h2>M3逆A00の変数と安定性</h2><p>方向判定・入口・出口などを比較。基準からの変化、思想別の結果、最大利益セッション／取引の除外を分けて掲載。</p><a class="button" href="{FOLDER}/{PAGE}">変数と安定性を開く →</a><p><a href="{FOLDER}/検証結果.md">固定１枚の報告</a> · <a href="{FOLDER}/README.md">読む順序</a></p></article><!--00014終了-->'
    text = text.replace('</header>', '</header>' + entry, 1)
    text = re.sub(r'<footer>最新作業は.*?</footer>', '<footer>最新作業は00014です。過去資料を残し、次の別作業は00015以降へ追加します。</footer>', text, count=1)
    path.write_text(text, encoding='utf-8')


def main() -> None:
    """確定した探索結果だけからHTML・報告・案内を作る。

    引数: コマンド行 --publish (bool) は共通索引更新。返り値: なし。
    """
    parser = argparse.ArgumentParser(description='M3逆A00の変数と安定性を表示')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    weeks, sessions, selection, specifications = [read(name) for name in ['週比較.json', 'セッション比較.json', '選択結果.json', '信号条件一覧.json']]
    records = {row['id']: row for row in weeks}
    specs = {row['id']: row for row in specifications}
    cells = defaultdict(list)
    for row in sessions:
        cells[(row['method_id'], row['symbol'])].append(row)
    for key in cells:
        cells[key].sort(key=lambda row: row['session'])
    assert all(len(cells[(identifier, symbol)]) == 10 for identifier in selection['displayed'] for symbol in SYMBOLS)
    controls = ''.join(f'<label>{NAMES[symbol]}<select data-scale-for="{symbol}" aria-label="{NAMES[symbol]}の表示枚数">' + ''.join(f'<option value="{number}">{number}枚</option>' for number in range(1, (10 if symbol == 'TOPIX' else 20) + 1)) + '</select></label>' for symbol in SYMBOLS)
    nav = '<nav class="nav" aria-label="比較条件">' + ''.join(f'<a href="#{identifier}">{identifier} · {esc(roles(identifier, selection))}</a>' for identifier in selection['displayed']) + '<a href="#families">思想別の結果</a></nav>'
    page = (WORK / 'report_template.html').read_text(encoding='utf-8')
    sections = {'__CONTROLS__': controls, '__OVERVIEW__': overview(records, selection), '__NAV__': nav,
                '__CHAPTERS__': candidate_chapters(records, selection, specs, cells), '__SUPPLEMENT__': supplement(records, selection)}
    for placeholder, content in sections.items():
        page = page.replace(placeholder, content)
    assert not re.search(r'__[A-Z]+__', page)
    OUT.mkdir(parents=True, exist_ok=True)
    artifacts = OUT / '資料'
    artifacts.mkdir(exist_ok=True)
    (OUT / PAGE).write_text(page, encoding='utf-8')
    (OUT / '検証結果.md').write_text(markdown_report(records, selection, specs, cells), encoding='utf-8')
    (OUT / 'README.md').write_text(f'''# 00014 M3逆A00の変数と安定性

最初に [{PAGE}]({PAGE}) を開いてください。

1. 冒頭で基準と主候補の週収支・改善幅を確認。初期表示は固定１枚です。
2. 主候補の章で入口・出口、両銘柄の週と各セッション、最大利益セッション／取引の除外を別々に確認。
3. 比較候補と思想別の章は必要なものを開きます。全{len(records)}条件は資料の週比較・全設定にあります。

表示枚数はTOPIXミニ１〜10枚、NK225マイクロ１〜20枚。設定は固定１枚で選び、表示枚数では選び直しません。各方式を別々に運用した場合です。累計返済枚数は同時保有枚数ではありません。

元の既知１週間での探索です。mini・micro自体の板や未知期間の成績ではありません。費用０・指定価格約定・セッション内全返済。最大勝ちの除外は寄与度診断で、除外後の売買経路は再計算しません。

- [固定１枚の報告書](検証結果.md)
- [主候補の条件](資料/主候補の条件.json)
- [条件と比較結果](資料/週比較.json)
- [選択結果](資料/選択結果.json)
- [探索前の固定記録](資料/探索前の固定記録.json)
- [表示倍率の検査](資料/表示倍率検査.json)
- [元集計と表示の照合](資料/表示静的検査.json)
- [損益・選択の独立監査](資料/audit.json)・[因果性と全許容枚数](資料/audit_causality.json)・[追加135条件の監査](資料/audit_diagnostics.json)

現在セッションAPIの取得は０回。全セッションで未返済残０を確認しています。実注文への接続はありません。

表示再生成はプロジェクトルートで `python work/wave_v19/report.py --publish`、元集計との表示照合は `python work/wave_v19/check_report.py`、倍率検査は `node work/wave_v19/check_report.js`。保存済みJSONだけを読み、表示生成は通信や売買再計算をしません。

探索本体は `python work/wave_v19/research.py`、選択後の追加診断は `python work/wave_v19/diagnose.py`。信号生成は `signal_variants.py`、売買本体は `engine.py` です。条件の再出力は `python work/wave_v19/export_candidate.py`。これらのコードと監査結果を資料へ保存しています。

ブラウザーの既存URLポリシー拒否を再試行せず、実画面は未確認です。数値・倍率・リンクをローカルで検査しています。
''', encoding='utf-8')
    payload = {'selection': selection, 'records': [records[identifier] for identifier in selection['displayed']], 'sessions': [row for row in sessions if row['method_id'] in selection['displayed']]}
    (artifacts / '表示集計.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    for path in WORK.iterdir():
        if path.is_file() and path.suffix in {'.py', '.js', '.json', '.md', '.html'}:
            shutil.copy2(path, artifacts / path.name)
    if args.publish:
        update_indexes()
    print(json.dumps({'作成': str(OUT / PAGE), '全条件': len(records), '表示条件': len(selection['displayed']), '索引更新': args.publish}, ensure_ascii=False))


if __name__ == '__main__':
    main()
