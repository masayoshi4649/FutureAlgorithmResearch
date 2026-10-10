"""第三反復を保存段階ごとに報告し、収益性・目的適合・未完了を区別する。"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from html import escape
from pathlib import Path
from urllib.parse import unquote, urlsplit
import importlib.util
import json
import re
import shutil
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'アルゴリズム調査' / '00022_中期方向と板の入口を分離'
SYMBOLS = ('TOPIX', 'NK225')

# ----------------------------------------
# 前報告の表示と合算検査だけを利用し、売買・通信モジュールは読み込まない。
_spec = importlib.util.spec_from_file_location('v26_report_helpers', HERE.parent / 'wave_v26' / 'report_round2.py')
display = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(display)
helpers = display.helpers
read, save = display.read, display.save
table, details, link = helpers.table, helpers.details, helpers.link
money, amount, ratio = helpers.money, helpers.amount, helpers.ratio


def stage_label(identifier: str, first: list[dict], random_results: list[dict], episode: dict | None, selected: dict | None) -> str:
    """機能: 完了した検査の状態だけを候補の表示へ反映する。

    引数: identifier (str)、first・random_results (list[dict])、episode・selected (dict | None)。
    返り値: 判定状態 (str)。未保存の検査は合格と扱わない。
    """
    if not identifier.startswith('H'):
        return '過去からの固定比較'
    item = next((value for value in first if value['candidate']['id'] == identifier), None)
    if item is None:
        return '一次反証は未完了または対象外'
    if item['first_stage_failures']:
        return '一次反証未達'
    if not any(value['candidate']['id'] == identifier for value in random_results):
        return '一次通過／乱数対照は未完了または対象外'
    if not episode or not any(value['method'] == identifier for value in episode['方法別要約']):
        return '一次通過／波診断待ち'
    if selected is None:
        return '必要資料保存済み／最終選定待ち'
    if any(value['id'] == identifier for value in selected['候補']):
        return '今回の事前基準内で選定／未知性能は未確認'
    rejected = next((value for value in selected['対照不合格'] if value['candidate']['id'] == identifier), None)
    if rejected:
        return '、'.join(rejected['reasons'])
    return '一次通過／今回の選定対象外'


def direction_description(spec: dict, design: dict) -> str:
    """機能: 中期方向と短期入口を日本語で説明する。

    引数: spec (dict)、design (dict)。返り値: 説明 (str)。
    """
    params = spec['params']
    main = design['主方向'][params['main_kind']]['rule']
    if params['main_kind'] in ('ema8_30', 'ema15_60'):
        raw = design['主方向'][params['main_kind']]
        factor = params['time_multiplier'] * params['clock_multiplier']
        fast, slow, slope = [max(1, int(raw[key] * factor + .5)) for key in ('fast', 'slow', 'slope_bars')]
        main = f'EMA{fast}/{slow}の差が±0.15ATRを超え、長期EMAの{slope}本前との差も同方向へ0.02ATR超なら開始。短長差が逆符号へ変わるまで方向を保持し、反対の開始条件で反転。'
    entry = design['入口'][params['entry_kind']]
    entry = entry if isinstance(entry, str) else entry['rule']
    peer = '相手市場の中期方向も60秒遅延した値で同方向を確認。' if params['peer_confirm'] else '相手市場の方向確認は使わない。'
    return f'主方向：{main} 入口：{entry} {peer}' if params['main_kind'] in ('ema8_30', 'ema15_60') else f'主方向：{main} 時間倍率{params["time_multiplier"]}倍を適用。入口：{entry} {peer}'


def manager_description(spec: dict) -> str:
    """機能: 元の管理条件へ変更値を重ね、入口・出口の主要設定を説明する。

    引数: spec (dict)。返り値: 機械的な注文条件の説明 (str)。
    注意: 追加玉や両建ては同じ組として管理し、利益玉だけの成績にしない。
    """
    config = {'entry_mode': 0, 'entry_atr': 0.25, 'stop_atr': 1., 'main_trail': 2., 'activation_atr': 1.,
              'timeout_min': 360., 'lock_fraction': 0., 'signal_exit': 0, 'breakeven_atr': 0., 'breakeven_floor': 0.,
              'split_target': 0., 'max_same_losses': 0, 'rearm_atr': 1., 'neutral_min': 0.}
    config.update(spec.get('changes', {}))
    if spec['id'] == 'D273':
        return ('新規はTOPIXミニ5枚／NKマイクロ10枚。買いは追跡安値から、売りは追跡高値から0.25ATR戻ったら入る。'
                '逆指値の新規追跡注文は最大300秒、方向信号が撤回されれば取消。'
                '損切りは部分利確を含む売買組全体で「初期枚数×1ATR相当」の損失枠。'
                '1.5ATR順行から3ATR幅の返済トレーリングを有効化し、2ATR到達で半分を整数切捨てで一度利確する'
                '（TOPIXは2枚返済・3枚残し、NKは5枚返済・5枚残し）。残玉も3ATR幅で追う。'
                '最長360分、遅くとも場末に全返済。追加玉・両建ては使わず、返済後5分から再エントリー可能。'
                'ATRは新規注文を準備した時点の値を固定し、最低2原本呼値幅。価格は原本呼値へ丸める。')
    entry_mode = int(config['entry_mode'])
    entry = {0: f"信号から{config['entry_atr']:g}ATRの順行を確認する逆指値", 1: f"{config['entry_atr']:g}ATRの反発・反落を追う新規トレーリング", 2: '判断の次の有効原本行で成行'}[entry_mode]
    exit_text = f"返済は組全体の初期損失枠{config['stop_atr']:g}ATR相当、{config['activation_atr']:g}ATR順行後に{config['main_trail']:g}ATR幅で追跡。"
    if config['lock_fraction'] > 0:
        exit_text += f"最高含み益が初期リスクを超えれば、その{config['lock_fraction']:.0%}を保護。"
    if config['breakeven_atr'] > 0:
        exit_text += f"{config['breakeven_atr']:g}ATR進めば最低{config['breakeven_floor']:g}ATR相当を保護。"
    if config['split_target'] > 0:
        exit_text += f"{config['split_target']:g}ATRで一部を返済。"
    if config['signal_exit']:
        exit_text += '反対の入口信号でも返済。'
    if config['neutral_min'] > 0:
        exit_text += f"中立信号が{config['neutral_min']:g}分続く場合にも返済。"
    if config['timeout_min'] > 0:
        exit_text += f"最長{config['timeout_min']:g}分。"
    exit_text += '遅くとも場末に全玉を返済。'
    return f'発注：{entry}。{exit_text} 条件固有の管理：{spec.get("description", spec["name"])}'


def baseline(identifier: str, candidate_map: dict[str, dict]) -> dict:
    """機能: 完了した候補のセッション明細と期間集計を読む。

    引数: identifier (str)、candidate_map (dict[str,dict])。返り値: rows・symbols (dict)。
    """
    if not identifier.startswith('H'):
        return display.baseline(identifier)
    full = read(HERE / 'adversarial' / f'{identifier}.json.gz')
    if full:
        case = next(value for value in full['cases'] if value['case'] == '基準再現')
        return {'rows': case['rows'], 'symbols': case['symbols']}
    signal_id = identifier.split('__')[0]
    entry = next(value for value in read(HERE / 'sessions' / f'{signal_id}.json.gz') if value['id'] == identifier)
    return {'rows': entry['rows'], 'symbols': candidate_map[identifier]['symbols']}


def search_control_body(control: dict | None) -> str:
    """機能: 全探索を毎回選び直す共通符号反転の参考対照を説明する。

    引数: control (dict | None)。返り値: HTML (str)。正式なp値として表示しない。
    """
    body = '<p>今回3反復の全76,220条件を対象に、各開始日の損益Rへ共通の±符号を掛け、128通りそれぞれで全手法から最大値を選び直します。合格候補だけへ母集団を絞りません。</p>'
    body += '<p>Rは売買組ごとの損益÷初回予定リスク。開始日ごとに合計し、銘柄ごとに「7日合計÷日別Rの二乗和の平方根」を算出、両銘柄の低い方を手法の値とします。これは円利益やPFではなく、日別Rの一貫性をみる尺度です。全日ゼロは0。</p>'
    if control is None:
        body += '<p><strong>まだ未実行または結果未保存。</strong>全3反復が完了してから集計します。事前固定済みの式・対象は、結果に合わせて変えません。</p>'
    else:
        body += f'<p>対象 {control["全条件数"]:,}条件・{len(control["開始日"])}開始日・{control["符号組合せ数"]}通り。元データの最大値 {control["元データ最大値"]:.4f} 以上となる探索最大値は、<strong>{control["探索最大値が元最大値以上の組合せ数"]}/{control["符号組合せ数"]}通り</strong>でした。</p>'
        body += table('search-control-percentiles', ['最小', '5%点', '中央値', '95%点', '最大'], [[f'{value:.4f}' for value in control['探索最大値の百分位']]])
        rows = [[identifier, f"{value['元の統計量']:.4f}", f"{value['探索最大値がこれ以上の符号組合せ数']}/{control['符号組合せ数']}"] for identifier, value in control['固定候補'].items()]
        body += table('search-control-candidates', ['固定候補', '元の統計量', '全探索最大値がこれ以上'], rows)
        if control.get('母集団にない固定比較'):
            body += '<p>全組合せ探索に存在しない補助対照は分母へ混ぜず、除外理由を保存しています。</p>'
        body += '<p>' + link('探索全体対照の結果.json', '全128通りと固定候補の結果') + '</p>'
    body += '<p><strong>正式な有意確率ではありません。</strong>開始日ごとの独立・符号対称性は未保証。実価格を作り直す再生ではなく、前の結果を読んで次の反復を設計した事実も消えません。さらに以前の調査は母集団に含まれません。この指標の首位へ採用候補を変更しません。</p>'
    return body


def parameter_body(identifier: str, data: dict) -> str:
    """機能: 共通の感度表を第三反復の短期閾値という意味へ合わせる。

    引数: identifier (str)、data (dict)。返り値: HTML (str)。
    第２反復の確認時間と第３反復の確認閾値を取り違えず、検査用表示値も揃える。
    """
    body = display.sensitivity_body(identifier, data)
    for row in helpers.TABLES[f'sensitivity-{identifier}']['rows']:
        if row[1] == '連続確認秒':
            row[1] = '短期確認閾値'
    return body.replace('連続確認秒', '短期確認閾値')


def main() -> None:
    """機能: 保存済み段階から第三反復の報告・資料案内・数値検査を作る。

    引数: なし。返り値: なし (None)。00022以外の成果・計算コード・ルート目次は変更しない。
    """
    OUT.mkdir(exist_ok=True)
    helpers.TABLES.clear()
    fixed = read(HERE / '探索条件の固定.json')
    design = read(HERE / 'hierarchy_design_fixed.json')
    progress = read(HERE / '進捗.json', {'完了信号': 0})
    gate = read(HERE / '反証前の候補固定.json')
    first = read(HERE / '一次反証の結果.json', [])
    random_results = read(HERE / '無関係対照の要約.json', [])
    episode = read(HERE / 'episode_audit.json')
    selected = read(HERE / '現在照合候補の固定.json')
    control = read(HERE / '探索全体対照の結果.json')
    current = read(HERE / 'live' / 'current_result.json')
    current_audit = read(HERE / 'current_accounting_audit.json')
    chart_ready = (OUT / '５分足と売買.html').exists()
    current_chart_ready = (OUT / '現在一回照合の５分足.html').exists()
    passed = [item for item in first if not item['first_stage_failures']]
    count = len(fixed['signals']) * len(fixed['managers'])
    assert count == 19776
    completed_count = count if gate else progress['完了信号'] * len(fixed['managers'])
    candidate_map = {item['candidate']['id']: item['candidate'] for item in first}
    if gate:
        candidate_map.update({item['id']: item for item in gate['上位30']})
    chosen = []
    if selected:
        chosen = [item for item in selected['候補'] if item['id'].startswith('H')]
    if not chosen and gate:
        for candidate in gate['上位30'][:4]:
            chosen.append({'id': candidate['id'], 'signal': next(value for value in fixed['signals'] if value['id'] == candidate['signal_id']),
                           'manager': next(value for value in fixed['managers'] if value['id'] == candidate['manager_id']),
                           '用途': '発見上位の説明用代表。合格・採用を意味しない。'})
    if selected:
        chosen += [item for item in selected['候補'] if not item['id'].startswith('H')]
    methods = {item['id']: baseline(item['id'], candidate_map) for item in chosen}
    waves = {item['method']: item for item in episode['方法別要約']} if episode else {}
    lead = '第三反復を計算中。未完了の結果を合格とは扱いません。'
    if gate and not first:
        lead = '全19,776条件の発見を完了。敵対検査・目的適合は判定待ちです。'
    if first and not selected:
        lead = f'一次反証は{len(passed)}/{len(first)}候補が通過。乱数対照・指定波・選定の完了までは採用未定です。'
    if selected:
        lead = f"今回の事前基準内の研究候補：{selected['主候補']}。未知相場の安定性は未確認です。" if selected['主候補'] else '今回の採用基準をすべて満たす手法はありません。条件を緩めて合格にしません。'
    live_primary = {item['銘柄']: item for item in current['結果'] if item['手法ID'] == selected['主候補']} if current and selected and selected['主候補'] else {}
    current_both_loss = len(live_primary) == 2 and all(item['合算損益円'] < 0 for item in live_primary.values())
    if current_both_loss:
        lead = ('有望な研究候補は残りましたが、解に到達したとは言えません。'
                f"現在の一回照合は両銘柄赤字：TOPIX {money(live_primary['TOPIX']['合算損益円'])}円、NK {money(live_primary['NK225']['合算損益円'])}円（実現＋含み）。")
    body = f'<p class="eyebrow">作業00022 · 第3反復 · 更新 {datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y/%m/%d %H:%M")}</p>'
    body += '<h1>有望候補は残る。<br>解に到達したとは言えない。</h1>' if current_both_loss else '<h1>中期の方向を主にして、<br>板は入るタイミングへ使う。</h1>'
    body += '<p class="lead"><strong>' + escape(lead) + '</strong></p>'
    if current_both_loss:
        body += f'<p>{escape(current["共通締切"])} の途中結果。17:25以降の今回初取得部分の増減も同額です。この一回だけで手法全体を否定しませんが、赤字を無視して成功とは扱いません。</p>'
    body += f'<p class="stages">探索 {completed_count:,}/{count:,}条件 · 最低基準 {gate["最低基準通過数"] if gate else "未集計"} · 一次反証 {len(first)}件／通過{len(passed)}件 · 乱数対照 {len(random_results)}件完了</p>'
    body += '<p>前回は黒字でも指定の波を逃しました。今回は、価格で中期方向を保持し、短期価格や板で新規の時機を絞ります。<strong>返済は既存の管理条件のまま</strong>で、中期方向を専用の返済入力へ渡した実装ではありません。</p>'
    if chosen:
        rows = []
        for item in chosen:
            identifier = item['id']
            top, nk = (methods[identifier]['symbols'][symbol] for symbol in SYMBOLS)
            wave = waves.get(identifier)
            rows.append([identifier, money(top['net_yen']), ratio(top['money_ratio']), money(nk['net_yen']), ratio(nk['money_ratio']),
                         f"{wave['目安達成区間数']}/8" if wave else '未診断', stage_label(identifier, first, random_results, episode, selected)])
        body += table('overview', ['手法（過去13完了セッション）', 'TOPIX期間収支 円', 'PF', 'NK期間収支 円', 'PF', '指定波20分', '現時点の判定'], rows)
    chosen_ids = {item['id'] for item in chosen}
    if {'H019__D273', 'H011__D273'} <= chosen_ids:
        body += '<p><strong>主案H019はEMA15/60、近接設定案H011は実質EMA16/60。</strong>長期EMAの傾き確認はそれぞれ3本・6本です。分類名は違っても非常に近い設定で、独立した2思想の裏付けとは扱いません。</p>'
    if control and selected and selected['主候補']:
        selected_control = control['固定候補'].get('wave_v27/' + selected['主候補'])
        if selected_control:
            body += f'<p class="muted">全候補から毎回選び直す日別符号対照では、主案以上が{selected_control["探索最大値がこれ以上の符号組合せ数"]}/{control["符号組合せ数"]}通り。正式なp値ではありませんが、好成績だけで統計的優位を主張できません。</p>'
    body += '<p class="muted">同じ既知13セッション・7開始日。費用0・指定価格約定・全玉場内返済。TOPIXミニ片方向10枚／NKマイクロ20枚以内。3反復計76,220条件は独立した相場の数ではありません。</p>'
    body += '<nav><a href="#methods">手法別の損益</a><a href="#validation">反証・設定耐性</a><a href="#waves">指定波</a><a href="#selection">選択効果</a><a href="#current">現在照合</a></nav>'

    # ----------------------------------------
    # 前の失敗と今回の仮説を短くつなぎ、実装していない返済を約束しない。
    prior = table('prior-rounds', ['作業', '探索条件', '判明した弱点'], [
        ['00020', '36,668', '黒字D016は指定4波×2銘柄で正方向保有0分。60秒→48秒で収益も大幅減。'],
        ['00021', '19,776', '選択2候補は各5/8波。9/21後半NKと9/22午前両銘柄は正方向保有0分。入口の大部分はF32。'],
        ['00022', '19,776', '中期方向と短期入口を分離。今回は8区間すべて20分以上を選定条件にも加える。'],
    ])
    prior += '<p>短期の板状態を厳しく確認するだけでは、中長時間の方向へ参加できませんでした。今回の入口のうち「主方向のみ」は板を使わない対照です。板が必要かも比較します。</p>'
    prior += '<p>新規判定は機械的で、波の日時や事後の利益は入力しません。一方、中期方向の状態を別系統で返済管理へ入力していないため、「主方向が続く限り玉を持ち続ける」「主方向だけで反転する」方式そのものを検証したことにはなりません。</p>'
    prior += '<p>' + link('../00020_大量探索と反証の反復/発見と反証.html', '第1反復') + ' / ' + link('../00021_時間窓への依存を減らす再探索/再探索と反証.html', '第2反復') + ' / ' + link('hierarchy_design.md', '今回の設計') + '</p>'
    body += details('前2反復の失敗と、今回変えた点・変えていない点', prior)
    design_rows = [[key, value['rule']] for key, value in design['主方向'].items()]
    design_body = table('main-direction-rules', ['主方向の方式', '機械的な条件（時間倍率適用前）'], design_rows)
    design_body += table('entry-rules', ['入口', '条件'], [[key, value if isinstance(value, str) else value['rule']] for key, value in design['入口'].items()])
    design_body += '<p>6主方向×時間倍率1/2倍×入口4方式×相手方向確認の有無＝96信号。確定1分足を120秒遅延し、相手確認はさらに60秒遅らせます。短期入口は発火後120秒まで保持し、主方向や相手確認が撤回されたら解除。開始20分待機、押し戻り準備期限10分です。</p>'
    body += details('中期方向6方式・短期入口4方式の固定条件', design_body)

    body += '<h2 id="methods">手法別の入口・出口と、利益・損失・収支</h2>'
    body += '<p>' + (link('５分足と売買.html', '5分足チャートでエントリー・返済を見る') if chart_ready else '5分足と売買の図解は準備中です。候補選定後に、実際の新規・返済位置を掲載します。') + '</p>'
    if not chosen:
        body += '<p>探索完了後の代表・選定候補をここへ掲載します。途中の好成績だけを抽出しません。</p>'
    body += '<p>損失玉を含め、全玉の返済を集計。枚数差は勝ち決済枚数−負け決済枚数で、保有残ではありません。同値決済を別記します。PF＝総利益÷総損失、1枚平均勝ち/負け＝（利益÷勝ち枚数）÷（損失÷負け枚数）。</p>'
    body += '<p class="muted">TOPIXミニ1pt=1,000円、NKマイクロ1pt=10円。NKはラージ原本の10pt格子を維持した換算です。9/21開始週10区間・9/28開始週3区間。最大DDは含み込みの資産減少。枚数が異なる候補を円額だけで順位付けしません。</p>'
    if {'H019__D273', 'H011__D273'} <= chosen_ids:
        body += details('選定2案の共通注文 — 最初の枚数と、新規・利確・損切り', '<p>' + escape(manager_description(next(item['manager'] for item in chosen if item['id'] == 'H019__D273'))) + '</p><p>新規は開始20分後から場末5分前まで。保有中の返済は上記の損失枠・追跡・期限・場末で決まり、中期方向の反転だけによる即時返済条件は加えていません。</p>')
    for item in chosen:
        identifier = item['id']
        if identifier.startswith('H'):
            description = direction_description(item['signal'], design) + ' ' + manager_description(item['manager'])
        elif identifier == 'D016__D065':
            description = 'OFIでタイミングを絞り両市場の30秒価格方向へ入る。実在主体の吸収を識別したものではない。' + manager_description(item['manager'])
        elif identifier == 'P02__D065':
            description = '両市場の60秒→30秒の価格方向反転で入る価格対照。板数量を使わないが、観測時刻は原本板に依存。' + manager_description(item['manager'])
        else:
            description = item['signal']['description'] + ' ' + manager_description(item['manager'])
        status = stage_label(identifier, first, random_results, episode, selected)
        body += helpers.method_section(identifier, description, status, methods[identifier])

    # ----------------------------------------
    # 一次基準と部品診断、未検査の状態を分離する。
    body += '<h2 id="validation">反証とパラメータ別の結果</h2>'
    body += '<p>時計・相手遅延・短期確認・入口幅・出口管理を分けて±20%変更。使わない変数は除外します。1/5/15秒遅延と観測価格約定も追加検査し、元の指定価格約定の成績と区別します。</p>'
    tick_diagnostic = read(HERE / 'entry_threshold_ticks.json')
    if tick_diagnostic:
        tick_rows = [part for part in tick_diagnostic['全期間'] if part['base'] == .05 and part['multiplier'] == 1 and part['unit'] == '解放板イベント']
        tick_rows.sort(key=lambda part: SYMBOLS.index(part['symbol']))
        proportions = '、'.join(f"{part['symbol']} {part['一呼値未満割合']:.1%}（半呼値未満{part['半呼値未満割合']:.1%}）" for part in tick_rows)
        body += f'<p class="muted">短期確認0.05ATRが原本1呼値未満の解放板イベントは{proportions}。±20%でも同じ離散価格判定にとどまる場合があり、信号不変だけで安定した設定範囲とは断定できません。仲値は半呼値刻みもあるため、閾値が無意味という結論でもありません。' + link('entry_threshold_ticks.json', '閾値と呼値の全診断') + '</p>'
    if first:
        rows = [[item['candidate']['id'], '一次通過' if not item['first_stage_failures'] else '未達', '、'.join(item['first_stage_failures']) or '指定した一次基準を通過'] for item in first]
        body += details(f'一次反証の全{len(first)}候補・通過{len(passed)}候補', table('all-first-stage', ['候補', '判定', '理由'], rows))
        for item in chosen:
            full = read(HERE / 'adversarial' / f"{item['id']}.json.gz")
            if full:
                body += details(item['id'] + ' の全パラメータ・部品対照', parameter_body(item['id'], full))
    else:
        body += '<p>一次反証の全結果はまだ保存されていません。未完了を通過とは扱いません。</p>'
    if random_results:
        rows = []
        for item in random_results:
            for part in item['summary']:
                top, nk = (part['symbols'][symbol] for symbol in SYMBOLS)
                rows.append([item['candidate']['id'], '元の発火時刻限定' if part['発火時刻限定'] else '30分コイントス',
                             money(top['収支0_5_50_95_100百分位'][2]), money(nk['収支0_5_50_95_100百分位'][2]),
                             f"{part['両銘柄で候補以上の収支seed数']}/64", f"{top['候補以上のPF_seed数']}/64", f"{nk['候補以上のPF_seed数']}/64"])
        random_body = '<p>64乱数×2方式。発火時刻限定は元のタイミング情報を残します。全試行は同じ既知経路の再生で、正式な有意確率にはしません。</p>'
        random_body += table('random-controls', ['候補', '対照方式', 'TOPIX中央値 円', 'NK中央値 円', '両収支以上', 'TOPIX PF以上', 'NK PF以上'], rows)
        body += details(f'無関係な方向との対照・{len(random_results)}候補を保存済み', random_body)
    else:
        body += '<p>無関係な方向との64乱数×2方式は、結果未保存です。</p>'
    body += '<p>' + link('validation_round3.md', '結果前に固定した反証基準') + '</p>'
    contribution = read(HERE / 'entry_contribution.json')
    contribution_body = '<p>主方向・時間倍率・管理条件を固定した全対応組で、短期入口の違いと相手確認の有無を比較します。利益だけでなく最大DD、売買組数、返済延べ枚数、同一台帳の比率も調べます。</p>'
    contribution_body += '<p>OFIを追加する比較は「OFIと短期価格」対「短期価格のみ」。相手確認は相手の中期価格方向です。入口方向が返済判断にも渡る管理があるため、入口だけの因果効果とは呼びません。波の信号時間と実際の保有時間は分けます。</p>'
    if contribution and (HERE / 'entry_contribution.md').exists():
        summaries = {(part['comparison'], part['symbol']): part for part in contribution['全対応集計']}
        ofi_parts = [summaries.get(('short_price→ofi_price', symbol)) for symbol in SYMBOLS]
        peer_parts = [summaries.get(('相手確認なし→あり', symbol)) for symbol in SYMBOLS]
        if all(ofi_parts):
            explanation = '、'.join(f"{part['symbol']} 収支{money(part['収支差円']['中央値'])}円／DD{money(part['最大DD差円']['中央値'])}円" for part in ofi_parts)
            contribution_body += '<p><strong>OFI条件を追加した対応差の中央値：</strong>' + explanation + '。今回のOFI条件では、利益を増やすより損失抑制と参加削減の交換が目立ちます。板一般が無価値という結論ではありません。</p>'
        if all(peer_parts):
            explanation = '、'.join(f"{part['symbol']} 収支{money(part['収支差円']['中央値'])}円／DD{money(part['最大DD差円']['中央値'])}円" for part in peer_parts)
            contribution_body += '<p>相手の中期方向確認の対応差中央値は' + explanation + '。銘柄によって収益への作用が異なります。</p>'
        labels = {'direction': '中期方向のみ', 'short_price': '短期価格', 'ofi_price': 'OFI＋短期価格', 'pullback_resume': '押し戻り再開'}
        comparison_rows = []
        for part in contribution['全対応集計']:
            label = part['comparison']
            for before, after in labels.items():
                label = label.replace(before, after)
            comparison_rows.append([label, part['symbol'], part['対応組数'], money(part['収支差円']['中央値']),
                                    f"{part['収支差円']['改善割合']:.1%}", money(part['最大DD差円']['中央値']),
                                    f"{part['最大DD差円']['改善割合']:.1%}", f"{part['売買組数差']['中央値']:+.1f}",
                                    f"{part['収支増かつDD減割合']:.1%}"])
        contribution_body += table('entry-contribution', ['後者−前者', '銘柄', '対応組数', '収支差中央値 円', '収支改善割合', 'DD差中央値 円', 'DD改善割合', '売買組数差中央値', '収支増かつDD減'], comparison_rows)
        contribution_body += '<p>全対応組を同じ重みで集計し、同一台帳も除きません。DD差は負が改善です。比較条件は強く依存するため、改善割合を独立試行の有意確率にはしません。主方向・管理思想別も原記録に残しています。</p>'
        signal_rows = [[part['comparison'], part['symbol'], f"{part['正方向信号分差']['中央値']:+.1f}",
                        f"{part['逆方向信号分差']['中央値']:+.1f}", f"{part['四波の20分目安達成数差']['中央値']:+.1f}"]
                       for part in contribution['全信号の波']['全対応集計']]
        contribution_body += details('全96方向の波区間比較（保有時間ではない）', table('entry-contribution-signals', ['比較', '銘柄', '正方向信号差 分', '逆方向信号差 分', '4波の20分目安数差'], signal_rows))
        holding = contribution.get('保有波の補足', {})
        if holding.get('実施'):
            holding_rows = [[part['comparison'], part['symbol'], part['対応波区間数'], f"{part['正方向保有分差']['中央値']:+.1f}",
                             f"{part['捕捉改善割合']:.1%}", f"{part['捕捉喪失割合']:.1%}"] for part in holding['全対応集計']]
            contribution_body += details('実保有の補足（一次通過候補と対応8条件に限定）', '<p>これは選別された候補の補足で、全探索の保有分布ではありません。</p>' + table('entry-contribution-holdings', ['比較', '銘柄', '波区間数', '正方向保有差 分', '捕捉改善割合', '捕捉喪失割合'], holding_rows))
            verification = contribution.get('波診断別実装との照合', {})
            if verification.get('全一致'):
                contribution_body += f'<p>独立した波診断との重複{verification["照合波区間数"]}区間で、正逆の保有時間・時価損益差・20分判定が一致しました。</p>'
        else:
            contribution_body += '<p>実保有の対応補足は未実施。信号時間の比較を、実際の保有時間の改善と読み替えません。</p>'
        contribution_body += '<p>全対応比較の結果が保存されました。' + link('entry_contribution.md', '比較結果と解釈') + ' / ' + link('entry_contribution.json', '全組・層別・波の記録') + '</p>'
    else:
        contribution_body += '<p><strong>結果はまだ未保存。</strong>板が利益に貢献したとは判定しません。</p>'
    body += details('板の入口・相手確認は何を加えたか — 全対応組の比較', contribution_body)

    body += '<h2 id="waves">指定された4波×2銘柄</h2>'
    if episode:
        rows = [[part['method'], f"{part['目安達成区間数']}/{part['対象区間数']}", len(part['正方向保有0区間'])] for part in episode['方法別要約']]
        body += table('wave-summary', ['手法', '正方向ネット保有20分以上', '正方向保有0区間'], rows)
        body += details('各波の日時・正逆保有時間・時価損益差', display.episode_body(episode))
    else:
        body += '<p>指定波の診断はまだ未完成です。収支が黒字でも波を取れたとは結論しません。</p>'
    body += '<p>今回の選定規則は8区間すべてで正方向ネット保有20分以上を要求します。既知の要求例に対する研究上の条件で、未知のすべての波を取る保証ではありません。前2反復では説明用だった目安を、今回から事前のふるいにも使っています。</p>'
    body += '<p>波の開始前からの保有と含みを含む時価損益差は、区間内に新規した玉だけの最終利益とは異なります。正逆が相殺する両建ては正方向ネット保有に数えません。</p>'

    body += '<h2 id="selection">選定と、大量探索による選択効果</h2>'
    if selected:
        body += f'<p>事前規則への適格候補 {len(selected["適格候補"])}件、対照・波条件の不合格 {len(selected["対照不合格"])}件。主候補は <strong>{escape(selected["主候補"] or "なし")}</strong>。現在の損益を見て選び直しません。</p>'
        rejected = [[part['candidate']['id'], '、'.join(part['reasons'])] for part in selected['対照不合格']]
        if rejected:
            body += details('最終選抜で残らなかった理由', table('selection-rejections', ['候補', '理由'], rejected))
    else:
        body += '<p>最終選定は未完了です。一次反証、乱数対照、指定8波の条件を確認した後、固定した順位と思想の違いで最大2件を選びます。対象外・未検査は合格としません。</p>'
    body += details('3反復の全手法から毎回最大を選び直す参考対照', search_control_body(control))

    # ----------------------------------------
    # 現在セッションは取得記録と最終結果の保存を分けて表示する。
    body += '<h2 id="current">現在セッションの一回照合</h2>'
    if current:
        body += display.current_body(current, selected)
        if current_audit:
            assert current_audit['監査済み銘柄条件数'] == len(current['結果'])
            assert current_audit['主副の注文返済曲線同一']
            assert all(item['ゼロ損益決済枚数'] == 0 for item in current_audit['結果'])
            source_rows = {(item['手法ID'], item['銘柄']): item for item in current['結果']}
            suffix_rows = {(item['手法ID'], item['銘柄']): item for item in current['前回未読部分の増減']}
            for item in current_audit['結果']:
                source = source_rows[item['手法ID'], item['銘柄']]
                for key in ['実現利益円', '実現損失円', '実現収支円', '含み損益円', '合算損益円', '保有買い枚数', '保有売り枚数', '利益決済枚数', '損失決済枚数']:
                    assert abs(item[key] - source[key]) < .01, (item['手法ID'], item['銘柄'], key)
                for key in ['17時25分時価損益円', '17時25分以降増減円']:
                    assert abs(item[key] - suffix_rows[item['手法ID'], item['銘柄']][key]) < .01
            body += '<p><strong>赤字の主因は、18:46〜19:04台に入った売りが短い反発で2回損切りになったこと。</strong>売り2回でTOPIX−35,000円、NK−15,000円。TOPIXは19:21の買いも19:42に損切りして−17,500円となり、20時台の回復では埋め切れませんでした。</p>'
            body += '<p>主案と近接設定案は、今回は全注文・返済・時価曲線が同一。固定比較を含む5手法×2銘柄の10入力で、独立復元した会計・決済枚数・17:25境界が一致しました。同値決済は全10入力で0枚です。事後の回復を見て損切り条件を変更したものではありません。</p>'
            body += '<p>' + link('current_accounting_audit.md', '現在の赤字の取引経過と独立会計監査') + ' / ' + link('current_accounting_audit.json', '全10入力の独立検算') + '</p>'
        if current_chart_ready:
            body += '<p>' + link('現在一回照合の５分足.html', '現在の一回照合を5分足で見る') + '。未返済玉は破線と白丸、返済は×で区別します。' + link('５分足と売買.html', '過去13完了セッションの図解') + 'とは別の途中結果です。</p>'
    elif (HERE / 'live' / '取得記録.json').exists():
        body += '<p>取得記録は保存済みですが、最終再生結果はまだありません。途中の状態を損益の結論にはしません。</p>'
    else:
        body += '<p><strong>現在セッションの追加取得は0回。</strong>要求適合まで確認した候補を固定してから、各URL一回の同じスナップショットで照合します。候補が残らなかった事実を、未取得データで修正しません。</p>'
    body += '<h2>因果性・会計・再現資料</h2>'
    evidence = '<p>信号の独立再計算・未来切断・相手の未来改変・対称性・押し戻り準備と発火の分離を監査しました。過去の確定足と解放済み板を使い、注文と約定を別行として扱います。</p>'
    evidence += '<p>CurrentPriceTimeは受信時刻ではないため、原本順の因果性と現実の二市場の到着順は別です。次行約定や秒遅延の検証も、実際の通信・約定保証ではありません。費用0と指定価格約定は今回のユーザー指定前提です。</p>'
    evidence += '<p>' + ' / '.join(link(name) for name in ['hierarchy_signal_audit.md', 'hierarchy_signal_audit.json', 'hierarchy_interface_audit.json', '反証合成検算.json']) + '</p>'
    if (HERE / 'selected_accounting_audit.md').exists():
        evidence += '<p>現在取得前に実施した選定2案・52銘柄セッションの独立会計監査も保存済み。' + link('selected_accounting_audit.md', '選定候補の独立会計・先読み監査') + ' / ' + link('selected_accounting_audit.json', '検算記録') + '</p>'
    body += details('独立監査とデータ・執行の限界', evidence)
    body += '<p>' + link('README.md', '読む順序・再現コード') + ' / ' + link('表示データ.json', '表示値') + ' / ' + link('報告検査.json', '合算・リンク検査') + ' / ' + link('../../work/wave_v27/', '全条件の保存領域') + '</p>'
    body += '<p class="muted">同じ既知期間を反復して調べています。候補が残った場合も、未知相場で安定して稼げることの確認とは区別します。</p>'
    body += '<footer>' + link('../index.html', '調査一覧') + '</footer>'

    css = ':root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0b111c;color:#e4eaf3;font:15px/1.7 system-ui,"Yu Gothic",sans-serif}main{max-width:1240px;margin:auto;padding:24px 28px 60px}h1{font-size:31px;line-height:1.35;margin:8px 0 16px}h2{font-size:23px;margin:30px 0 10px}h3{font-size:17px}.eyebrow,.muted{font-size:13px;color:#a6b5cc}.lead{font-size:17px}.stages{color:#76d7cc;font-weight:650}.scroll{overflow:auto;margin:12px 0}table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}th,td{padding:8px 11px;border-bottom:1px solid #2b3c51;text-align:right}th{background:#1b2a3e;color:#cfdded}th:first-child,td:first-child{text-align:left}tbody tr:nth-child(even){background:#111c2b}details{border:1px solid #2e4057;background:#111b2a;border-radius:7px;margin:10px 0}summary{padding:13px 16px;cursor:pointer;font-weight:650}summary:hover{background:#1a2a3f}.inside{padding:0 17px 17px}p{margin:10px 0}a{color:#8ec6ff;text-decoration:none}a:hover{text-decoration:underline}nav{display:flex;flex-wrap:wrap;gap:20px;margin:18px 0}footer{border-top:1px solid #2e4057;padding-top:18px;margin-top:25px}@media(max-width:700px){main{padding:18px 14px}h1{font-size:26px}.lead{font-size:16px}}'
    comment = '<!--\n[コンポーネント概要]\nmainは未完了を含む検証状態と結論、detailsは条件と損益の詳細、.scrollは横長表を表示します。\n外部通信を行わない静的なダークテーマです。\n-->'
    html = '<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>00022 中期方向と入口の検証</title><style>' + css + '</style></head><body>' + comment + '<main>' + body + '</main></body></html>'
    (OUT / '中期方向と入口の検証.html').write_text(html, encoding='utf-8')
    sources = ['hierarchy_design.md', 'hierarchy_design_fixed.json', '探索条件の固定.json', '進捗.json', '反証前の候補固定.json',
               'validation_round3.md', '反証規則の固定.json', '反証実装の固定.json', '一次反証の結果.json', '全条件の期間集計.json.gz',
               '無関係対照の要約.json', '現在照合選抜の事前規則.json', '現在照合候補の固定.json',
               'episode_audit.md', 'episode_audit.json', 'episode_audit_fixed.json', 'hierarchy_signal_audit.md', 'hierarchy_signal_audit.json',
               'hierarchy_interface_audit.json', '反証合成検算.json', '探索全体対照の固定.json', '探索全体対照の実装修正固定.json', '探索全体対照の結果.json',
               'entry_contribution_fixed.json', 'entry_contribution.md', 'entry_contribution.json', 'entry_threshold_ticks.json',
               'selected_accounting_audit.md', 'selected_accounting_audit.json', 'current_accounting_audit.md', 'current_accounting_audit.json']
    copied = []
    for name in sources:
        if (HERE / name).exists():
            shutil.copy2(HERE / name, OUT / name)
            copied.append(name)
    if current:
        for name in ['current_result.json', '取得記録.json', '現在照合の凍結記録.json']:
            shutil.copy2(HERE / 'live' / name, OUT / name)
            copied.append(name)
    status = {'探索完了': bool(gate), '探索保存条件数': completed_count, '一次反証保存件数': len(first), '一次通過': len(passed),
              '乱数保存候補数': len(random_results), '波診断保存': bool(episode), '選定保存': bool(selected),
              '全探索対照保存': bool(control), '現在照合保存': bool(current), '売買図解保存': chart_ready,
              '現在図解保存': current_chart_ready, '現在独立会計保存': bool(current_audit), '入口寄与保存': bool(contribution)}
    save(OUT / '表示データ.json', {'状態': status, '代表手法': methods, '表示表': helpers.TABLES})
    readme = '''# 00022 中期方向と板の入口を分離

最初に [中期方向と入口の検証.html](中期方向と入口の検証.html) を開いてください。保存済み段階に合わせて結果を表示し、未完成を合格とは扱いません。

## 読む順序

1. [HTML](中期方向と入口の検証.html)：結論・進行状態・各候補の入口と出口、全期間／開始週／各セッションの利益・損失・収支・決済枚数。
2. [今回の設計](hierarchy_design.md)、[反証基準](validation_round3.md)：中期方向と短期入口、別々のパラメータ検査。
3. [信号の独立監査](hierarchy_signal_audit.md)、[表示値](表示データ.json)、[報告検査](報告検査.json)。
4. [全結果・実行コード](../../work/wave_v27/)：探索、一次反証、64乱数×2対照、指定波、選定、探索全体対照は完成後にHTMLへ反映します。

同じ13セッション・7開始日を再利用する第三反復です。前2回36,668＋19,776、今回19,776の計76,220条件。未知の76,220相場を試したわけではありません。中期方向は信号内部の状態であり、中期方向を返済へ別入力する実装は加えていません。

費用0・指定価格約定。完了セッションは利益玉と損失玉を含め全玉場内返済し、途中の現在照合は実現・含み・保有を別記します。TOPIXミニは1pt=1,000円で片方向10枚以内、NKマイクロは1pt=10円で20枚以内。NKの原本はラージの10pt格子を維持しています。勝ち−負け枚数は決済枚数差で、保有残ではありません。同値決済枚数も表示します。

今回の選定には指定4波×両銘柄の全8区間で正方向ネット保有20分以上を要求します。既知の目的適合条件で、未知のあらゆる波への保証ではありません。全探索の共通符号反転は日別Rの一貫性の参考診断で、正式なp値ではありません。

## 再現コード

- [信号](../../work/wave_v27/hierarchy_signals.py)、[探索](../../work/wave_v27/hierarchy_runner.py)、[反証](../../work/wave_v27/validation_round3.py)。
- [指定波診断](../../work/wave_v27/episode_audit.py)、[選定](../../work/wave_v27/select_current.py)、[全探索対照](../../work/wave_v27/search_selection_control.py)。
- [現在の一回照合](../../work/wave_v27/current_validation.py)、[報告生成](../../work/wave_v27/report_round3.py)。

報告のみを再生成する場合は、プロジェクトルートで `python work/wave_v27/report_round3.py`。通信・売買計算を行わず、保存済みファイルだけを読みます。00022内のみを更新し、計算コード・原本・過去成果・ルート目次を変更しません。表示処理は00020/00021の報告用関数を再利用します。
'''
    readme += '\n生成時の状態：' + '、'.join(f'{key}={value}' for key, value in status.items()) + '。\n'
    if current_both_loss:
        readme += f'\n最終結論：有望候補は残りますが、解に到達したとは言えません。{current["共通締切"]} の一回途中照合は、主案の実現＋含みがTOPIX {money(live_primary["TOPIX"]["合算損益円"])}円／NK {money(live_primary["NK225"]["合算損益円"])}円。今回初取得の17:25以降も同じ増減です。一回の赤字で全否定せず、無視して成功とも扱いません。大量探索の参考対照も含め、将来利益や統計的優位の確証はありません。\n'
    if {'H019__D273', 'H011__D273'} <= chosen_ids:
        readme += '\n選定案はH019__D273（主案）とH011__D273（近接設定案）。EMA15/60と16/60、傾き確認3本と6本の差で、独立した2思想ではありません。共通管理はTOPIX初期5枚／NK10枚、0.25ATRの新規追跡、売買組全体の初期1ATR相当損失枠、2ATRで半分を整数切捨て利確（TOPIX2枚／NK5枚）、1.5ATR順行から3ATR追跡、最長360分・場内返済です。\n'
    readme += '\n図解：' + ('[5分足と売買](５分足と売買.html)。全13セッションの新規・返済位置を確認できます。' if chart_ready else '5分足と売買の図解は準備中です。候補選定後に作成します。') + '\n'
    if current_chart_ready:
        readme += '\n現在途中の図解：[現在一回照合の5分足](現在一回照合の５分足.html)。未返済は破線と白丸、返済は×で区別します。過去13完了セッションの図解とは別です。\n'
    if current_audit:
        readme += '\n現在の赤字の原因：[取引経過と独立会計監査](current_accounting_audit.md)、[全10入力の検算](current_accounting_audit.json)。主案と近接設定案の全注文・返済・時価曲線は同一。売り2敗とTOPIXの買い1敗を、その後の回復で埋め切れませんでした。会計と17:25境界の差額は一致しています。\n'
    if contribution and (HERE / 'entry_contribution.md').exists():
        readme += '\n追加診断：[板入口・相手確認の全対応比較](entry_contribution.md)。最終入口信号が返済にも作用するため、入口限定の因果寄与ではありません。\n'
    (OUT / 'README.md').write_text(readme, encoding='utf-8')
    parser = helpers.ReportParser()
    parser.feed(html)
    assert not parser.stack
    for table_id, expected in helpers.TABLES.items():
        assert parser.tables[table_id] == [expected['headers']] + expected['rows'], table_id
    for href in parser.links:
        parts = urlsplit(href)
        if parts.scheme:
            continue
        if parts.path:
            target = (OUT / unquote(parts.path)).resolve()
            if target.name != '報告検査.json':
                assert target.exists(), target
        else:
            assert parts.fragment in parser.ids
    for href in re.findall(r'\]\(([^)]+)\)', readme):
        target = (OUT / href).resolve()
        if target.name != '報告検査.json':
            assert target.exists(), target
    for name in copied:
        source = HERE / name if (HERE / name).exists() else HERE / 'live' / name
        assert source.read_bytes() == (OUT / name).read_bytes()
    save(OUT / '報告検査.json', {'生成時刻': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '状態': status,
                                '報告コードSHA256': sha256(Path(__file__).read_bytes()).hexdigest(),
                                '表示共通コードSHA256': {str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest() for path in [HERE.parent / 'wave_v26/report_round2.py', HERE.parent / 'wave_v25/report_round.py']},
                                '表数': len(helpers.TABLES), '表データ行数': sum(len(value['rows']) for value in helpers.TABLES.values()),
                                'リンク件数': len(parser.links), 'タグとID一致': True, '表表示一致': True,
                                '代表セッション合算検査': len(chosen) * 26, '原資料コピー一致': len(copied),
                                '報告生成によるAPI取得': 0, 'ルート目次変更': False})
    print(json.dumps({'報告': str(OUT / '中期方向と入口の検証.html'), **status, '表数': len(helpers.TABLES)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
