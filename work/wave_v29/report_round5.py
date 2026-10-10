"""利益保護の第５反復を、旧主案と同一入口の基準に照らして表示する。"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from html import escape
import importlib.util
import json
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = '00024_部分利確と最高利益の保護'
OUT = ROOT / 'アルゴリズム調査' / NAME
PREVIOUS = '00022_中期方向と板の入口を分離'
PREVIOUS_TASK = '00023_保有撤回と損失上限の再設計'
V27 = HERE.parent / 'wave_v27'
SYMBOLS = ('TOPIX', 'NK225')
BASE = 'H019__D273'

# ----------------------------------------
# 表示用の関数だけを再利用し、注文器・データ取得器は読み込まない。
_spec = importlib.util.spec_from_file_location('v27_round4_display', V27 / 'report_round3.py')
previous = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(previous)
helpers = previous.helpers
table, details, link = helpers.table, helpers.details, helpers.link
money, amount, ratio = helpers.money, helpers.amount, helpers.ratio
save = previous.save


def read(path: Path, default: object = None) -> object:
    """機能: 報告用の保存物だけを読む。

    引数: path (Path)、default (object)。返り値: 保存内容 (object)。現在保存領域は拒否する。
    """
    assert 'live' not in path.parts, '現在スナップショットを読みません'
    return previous.read(path, default)


def complete_random(item: dict) -> bool:
    """機能: ２方式×64試行を要約と全seed保存物で確認する。

    引数: item (dict)。返り値: 完了判定 (bool)。売買の再計算はしない。
    """
    modes = item.get('summary', [])
    if len(modes) != 2 or {m['発火時刻限定'] for m in modes} != {False, True} or any(m['試行数'] != 64 for m in modes):
        return False
    full = read(HERE / 'randomized' / (item['candidate']['id'] + '.json.gz'))
    if not full or full['summary'] != modes or full['candidate'] != item['candidate']:
        return False
    pairs = {(x['gated'], x['seed']) for x in full['results']}
    if len(full['results']) != 128 or pairs != {(gated, seed) for gated in (False, True) for seed in range(64)}:
        return False
    for mode in modes:
        values = [x for x in full['results'] if x['gated'] == mode['発火時刻限定']]
        count = sum(all(x['symbols'][s]['net_yen'] >= item['candidate']['symbols'][s]['net_yen'] for s in SYMBOLS) for x in values)
        if count != mode['両銘柄で候補以上の収支seed数']:
            return False
    return True


def completeness(gate: dict | None, first: list | None, random_results: list | None,
                 random_plan: list | None, episode: dict | None, selected: dict | None,
                 random_checked: dict) -> dict:
    """機能: 未保存・不足した段階を通過とせず、対象集合の完了を判定する。

    引数: gate/episode/selected (dict|None)、first/random_results/random_plan (list|None)、random_checked (dict)。
    返り値: 各段階の完了状態 (dict)。選抜規則は変更しない。
    """
    main_done = bool(gate and gate['全条件数'] == 4800)
    planned = {x['id'] for x in gate['反証候補']} if gate else set()
    actual = [x['candidate']['id'] for x in first] if first is not None else []
    first_done = main_done and first is not None and len(actual) == len(planned) and set(actual) == planned
    actual_random = [x['candidate']['id'] for x in random_results] if random_results is not None else []
    planned_random = {x['id'] for x in random_plan} if random_plan is not None else set()
    random_done = (first_done and random_plan is not None and random_results is not None
                   and len(actual_random) == len(planned_random) and set(actual_random) == planned_random
                   and all(random_checked.get(i, False) for i in actual_random))
    wave_done = False
    if first_done and episode is not None:
        expected = {x['candidate']['id'] for x in first if not x['first_stage_failures']} | {BASE, 'F32__G08', 'D016__D065', 'P02__D065'}
        counts = {x['method']: x['対象区間数'] for x in episode['方法別要約']}
        wanted = {(wave, symbol) for wave in ('W01', 'W02', 'W03', 'W04') for symbol in SYMBOLS}
        wave_done = all(counts.get(i) == 8 and len([r for r in episode['結果'] if r['method'] == i]) == 8
                        and {(r['wave'], r['symbol']) for r in episode['結果'] if r['method'] == i} == wanted for i in expected)
    return {'探索完了': main_done, '一次反証完了': first_done, '乱数対照完了': random_done,
            '指定波完了': wave_done, '研究候補固定保存': selected is not None,
            '最終資料完備': bool(main_done and first_done and random_done and wave_done and selected is not None)}


def result_data(identifier: str) -> dict:
    """機能: 保存済み13セッションの円額・枚数と期間集計を照合する。

    引数: identifier (str)。返り値: rowsとsymbols (dict)。
    """
    root = V27 if identifier == BASE else HERE
    signal_id = identifier.split('__')[0]
    rows = next(x for x in read(root / 'sessions' / (signal_id + '.json.gz')) if x['id'] == identifier)['rows']
    candidate = next(x for x in read(root / 'summaries' / (signal_id + '.json'))['candidates'] if x['id'] == identifier)
    assert len(rows) == 26 and len({(r['session'], r['symbol']) for r in rows}) == 26
    for symbol in SYMBOLS:
        total = helpers.sum_rows([r for r in rows if r['symbol'] == symbol])
        for key, value in total.items():
            assert abs(value - candidate['symbols'][symbol][key]) < .01
    return {'rows': rows, 'symbols': candidate['symbols']}


def stage_label(identifier: str, first: list, episode: dict | None, selected: dict | None,
                state: dict, checked: dict) -> str:
    """機能: 手法の未実施・棄却・研究候補を区別する。

    引数: identifier (str)、first (list)、episode/selected (dict|None)、state/checked (dict)。
    返り値: 状態の説明 (str)。
    """
    if identifier == BASE:
        return '第３反復の固定比較。今回の新候補ではない'
    if identifier.endswith('__K000'):
        return '同じ入口の旧D273を再現する基準。新しい改善として数えない'
    item = next((x for x in first if x['candidate']['id'] == identifier), None)
    if item is None:
        return '一次反証は未保存または対象外'
    if item['first_stage_failures']:
        return '一次反証未達：' + '、'.join(item['first_stage_failures'])
    if not checked.get(identifier, False):
        return '一次通過／乱数対照は未完了または対象外'
    if not state['最終資料完備']:
        return '判定資料または研究候補の固定待ち'
    if any(x['id'] == identifier for x in selected['候補']):
        return '事前基準内の研究候補。新しい未知検証は未実施'
    rejected = next((x for x in selected['棄却'] if x['candidate']['id'] == identifier), None)
    return '未達：' + '、'.join(rejected['reasons']) if rejected else '思想別の選定対象外（最大２案）'


def order_description(manager: dict) -> str:
    """機能: 初期管理と利益割合保護・追跡短縮を日本語化する。

    引数: manager (dict)。返り値: 条件の説明 (str)。
    """
    p = {'entry_atr': .25, 'ttl_seconds': 300., 'stop_atr': 1., 'activation_atr': 1.5,
         'main_trail': 3., 'split_target': 2., 'signal_exit': 0, 'neutral_min': 0.,
         'max_same_losses': 0, 'session_budget_r': 0., 'timeout_min': 360., 'cooldown_min': 5.,
         'lock_fraction': 0., 'lock_activation_r': 1., 'tighten_atr': 0., 'tight_width': 1.}
    p.update(manager['changes'])
    text = (f"TOPIXミニ5枚／NKマイクロ10枚。買いは追跡安値から、売りは追跡高値から{p['entry_atr']:g}ATRの反発・反落で入る。"
            f"新規注文は最長{p['ttl_seconds']:g}秒、入口方向の撤回で取消。組全体の損切り基準は初期枚数×{p['stop_atr']:g}ATR。"
            f"{p['activation_atr']:g}ATR順行から{p['main_trail']:g}ATR幅で追跡返済。")
    text += (f"{p['split_target']:g}ATR順行で一度だけ半分を整数切捨て利確（TOPIX2枚・3枚残し／NK5枚・5枚残し）。"
             if p['split_target'] else '部分利確せず全玉を追跡する。')
    if p['lock_fraction']:
        text += (f"当組の実現＋含み利益の最高額が{p['lock_activation_r']:g}Rに達した後、その最高額の{p['lock_fraction']:.0%}を返済基準の床にする。"
                 'この保護は部分利確前にも動く。')
    else:
        text += '最高利益の割合保護は使わない。'
    if p['tighten_atr']:
        text += f"建値から{p['tighten_atr']:g}ATR順行した後は追跡幅を{p['tight_width']:g}ATRへ短縮する。"
    else:
        text += '追跡幅の途中短縮は使わない。'
    text += '中期反転や中立だけを理由に返済しない。'
    return text + f"最長{p['timeout_min']:g}分、返済後{p['cooldown_min']:g}分待って再新規。"


def paired_comparison(identifier: str, data: dict) -> str:
    """機能: 新条件と同じ入口のK000基準を、小さな円額・枚数表で比較する。

    引数: identifier (str)、data (dict)。返り値: 折り畳みHTML (str)。再選抜は行わない。
    """
    paired_id = identifier.split('__')[0] + '__K000'
    rows, ratios = [], []
    for symbol in SYMBOLS:
        original, own = data[paired_id]['symbols'][symbol], data[identifier]['symbols'][symbol]
        rows.append([paired_id, symbol, amount(original['gross_profit_yen']), amount(original['gross_loss_yen']),
                     money(original['net_yen']), amount(original['profit_units']), amount(original['loss_units']),
                     money(original['profit_units'] - original['loss_units']), amount(original['zero_units']),
                     amount(original['drawdown_yen'])])
        defined = original['net_yen'] > 0 and original['drawdown_yen'] > 0
        ratios.append([symbol, money(own['net_yen'] - original['net_yen']), money(own['drawdown_yen'] - original['drawdown_yen']),
                       f"{own['net_yen'] / original['net_yen']:.0%}" if defined else '比較基準外',
                       f"{own['drawdown_yen'] / original['drawdown_yen']:.0%}" if defined else '比較基準外'])
    body = '<p>同じ入口・同じTOPIX5枚／NK10枚で、割合保護も追跡短縮も加えない基準です。差は新条件−K000。収支差が正、下落差が負なら改善です。</p>'
    body += table('paired-money-' + identifier, ['基準', '銘柄', '利益 円', '損失 円', '収支 円', '利益枚数', '損失枚数', '枚数差', '同値枚数', '最大下落 円'], rows)
    body += table('paired-ratio-' + identifier, ['銘柄', '収支差 円', '下落差 円', 'K000の収支比', 'K000の下落比'], ratios)
    body += '<p>両銘柄のK000が黒字かつ最大下落が正であることを前提に、各々で収支75%以上・下落80%以下も要求します。旧主案との比較だけでは機構の改善と判定しません。</p>'
    return details(identifier + '：同じ入口のK000と比較', body)


def check_selection(selected: dict, first: list, random_results: list, episode: dict, data: dict) -> None:
    """機能: 保存済み選定が既定条件を満たすことだけを照合する。

    引数: selected/data/episode (dict)、first/random_results (list)。返り値: なし (None)。再選抜はしない。
    """
    for item in selected['候補']:
        identifier = item['id']
        assert not next(x for x in first if x['candidate']['id'] == identifier)['first_stage_failures']
        wave = next(x for x in episode['方法別要約'] if x['method'] == identifier)
        assert wave['対象区間数'] == wave['目安達成区間数'] == 8
        for symbol in SYMBOLS:
            own, base = data[identifier]['symbols'][symbol], data[BASE]['symbols'][symbol]
            assert own['net_yen'] >= .75 * base['net_yen'] - 1e-8
            assert own['drawdown_yen'] <= .80 * base['drawdown_yen'] + 1e-8
            paired = data[identifier.split('__')[0] + '__K000']['symbols'][symbol]
            assert paired['net_yen'] > 0 and paired['drawdown_yen'] > 0
            assert own['net_yen'] >= .75 * paired['net_yen'] - 1e-8
            assert own['drawdown_yen'] <= .80 * paired['drawdown_yen'] + 1e-8
        for mode in next(x for x in random_results if x['candidate']['id'] == identifier)['summary']:
            assert mode['両銘柄で候補以上の収支seed数'] <= 3
            assert all(mode['symbols'][s]['候補以上のPF_seed数'] <= 6 for s in SYMBOLS)


def sensitivity(identifier: str, full: dict) -> str:
    """機能: 近傍と遅延・部品対照を変数カテゴリごとに表示する。

    引数: identifier (str)、full (dict)。返り値: HTML (str)。
    """
    labels = {'entry': '入口幅', 'management': '出口管理', 'clock': '時計窓と相手遅延',
              'confirmation': '短期確認閾値', 'loss_controls': '損失・撤回制限', 'peer': '相手遅延',
              'stop_atr': '損切り基準', 'main_trail': '追跡幅', 'lock_fraction': '利益保護',
              'timeout_min': '保有期限', 'session_budget_r': '場内損失予算', 'max_same_losses': '連敗回数', 'neutral_min': '中立継続時間'}
    labels.update(lock_activation_r='割合保護の開始R', tighten_atr='追跡短縮の開始ATR', tight_width='短縮後の追跡幅')
    rows = []
    for title, values in [('判定カテゴリ', full['カテゴリ判定']), ('個別変数', full['個別変数診断'])]:
        for key, part in values.items():
            unused = part['構造的不使用']
            cells = ['—'] * 4 if unused else [money(part['symbols'][s][n]) for s in SYMBOLS for n in ('中央値', '最悪')]
            rows.append([title, labels.get(key, key), '不使用' if unused else f"{part['通過数']}/{part['有効条件数']}", *cells,
                         '除外' if unused else ('通過' if part['通過'] else '未達')])
    body = table('sensitivity-' + identifier, ['範囲', '変数', '両黒字PF≥1.2', 'TOP中央値 円', 'TOP最悪 円', 'NK中央値 円', 'NK最悪 円', '保存判定'], rows)
    cases = [[c['case'], money(c['symbols']['TOPIX']['net_yen']), ratio(c['symbols']['TOPIX']['money_ratio']),
              money(c['symbols']['NK225']['net_yen']), ratio(c['symbols']['NK225']['money_ratio']),
              '同一' if c['ledger_hash'] == full['cases'][0]['ledger_hash'] else '相違'] for c in full['cases']]
    body += details('各変更の収支と遅延・観測価格・部品対照', table('cases-' + identifier, ['変更', 'TOP収支 円', 'PF', 'NK収支 円', 'PF', '元の台帳'], cases))
    body += f"<p>有効な信号近傍{full['有効信号近傍数']}件のうち、実際に使う入力が基準と同じものは{full['基準と実際の使用入力完全一致の近傍数']}件。形式的通過と、異なる判断を試せた件数は分けて読みます。</p>"
    return body


def supplementary_evidence(data: dict) -> tuple[str, dict]:
    """機能: 部品比較・全探索対照・独立会計の保存結果を表示する。

    引数: data (dict) は表示手法の保存集計。返り値: HTMLと表示した診断の要約 (tuple[str, dict])。
    候補を追加・再順位付けせず、現在データや注文器を読み込まない。
    """
    body, summary = '', {}
    components = read(HERE / 'protection_component_audit.json')
    if components:
        targets = components['二重改善目標の記述件数']
        summary['二重改善目標の記述件数'] = targets
        comparisons = [dict(row, axis='同入口K000との差') for row in components['同一入口基準との差']] + components['全軸']
        rows = [[r['axis'], r['symbol'], amount(r['対応組数']), money(r['収支差中央値円']),
                 money(r['DD差中央値円']), f"{r['収支改善率']:.1%}", f"{r['DD改善率']:.1%}",
                 f"{r['両改善率']:.1%}"] for r in comparisons]
        target_rows = [[label, amount(value['両銘柄該当数']), amount(value['うち探索最低基準も通過'])]
                       for label, value in targets['条件別'].items()]
        part = ('<p>上位だけでなく全4,800条件を確認しても、収支75%以上・最大下落80%以下を両銘柄で満たす条件は、同入口との比較・旧主案との比較・両方との比較のいずれも０件でした。</p>'
                f"<p>同入口K000が両銘柄黒字かつ下落が正となる入口は{targets['同入口基準が両銘柄黒字かつ正DDの入口数']}/96。"
                f"同入口比較の対象は{targets['同入口比較の適格条件数']:,}条件です。非黒字や下落ゼロの基準へ比率条件を適用しません。</p>")
        assert all(value['両銘柄該当数'] == 0 for value in targets['条件別'].values()), '全件0との説明を更新する必要があります'
        part += table('improvement-counts', ['比較基準', '両銘柄で金額目標達成', 'うち探索最低基準も通過'], target_rows)
        part += table('component-comparison', ['追加する条件', '銘柄', '対応組', '収支差中央値 円', '下落差中央値 円',
                                              '収支改善率', '下落改善率', '両改善率'], rows)
        part += ('<p>差は追加側−基準側。収支差が正、下落差が負なら改善。関連する既知条件の割合であり、未知の成功確率ではありません。'
                 'K000との自己比較は改善率の分母から除きます。全差分と二重改善目標の件数は保存JSONに残しています。</p>')
        part += '<p>' + link('protection_component_audit.json', '全対応・同入口基準・二重改善目標の記録') + '</p>'
        body += details('部品ごとの比較：割合保護と追跡短縮は効いたか', part)
    broad = read(HERE / '探索全体対照の結果.json')
    if broad:
        assert broad['全条件数'] == sum(broad['反復別条件数'].values())
        assert len(broad['全符号対照']) == broad['符号組合せ数'] == 128
        assert sum(x['全探索最大値'] >= broad['元データ最大値'] for x in broad['全符号対照']) == broad['探索最大値が元最大値以上の組合せ数']
        summary['全探索対照の条件数'] = broad['全条件数']
        summary['元最大値以上の符号組合せ'] = broad['探索最大値が元最大値以上の組合せ数']
        rows = [[name, f"{row['元の統計量']:.3f}", f"{row['探索最大値がこれ以上の符号組合せ数']}/128"]
                for name, row in broad['固定候補'].items()]
        part = (f"<p>保存対象の全{broad['全条件数']:,}条件を対象に、７開始日の損益符号を全128通り変え、その都度の探索最大値を比較しました。"
                f"元の探索最大値以上となったのは{broad['探索最大値が元最大値以上の組合せ数']}/128通り。"
                '個別候補の乱数対照を通過しても、多数探索全体を考慮した強い証拠になったとは言えません。</p>'
                '<p>比較値は銘柄ごとの「日別R合計÷日別Rの二乗和平方根」の弱い側。金額や両銘柄収支の合算ではありません。'
                '各日の同じ符号を全手法・両銘柄に共通して掛け、各組合せで最良値を取り直します。</p>')
        part += table('all-search-control', ['旧固定比較', '元の比較値', '探索最大値が比較値以上'], rows)
        part += ('<p>日別の独立性・符号対称性は確認できておらず、正式なp値ではありません。価格経路の再生でもなく、'
                 '現データの利益を否定する検査でもありません。今回の候補採否や再順位付けには使いません。</p>')
        body += details(f"多数の候補から選ぶ効果：全{broad['全条件数']:,}条件の対照", part)
    accounting = read(HERE / 'selected_accounting_audit.json')
    if accounting:
        assert accounting['固定ファイル不変'] and accounting['通信拒否'] and accounting['API取得回数'] == 0
        rows = []
        for candidate in accounting['候補']:
            assert candidate['保存資料不変']
            assert len(candidate['sessions']) == 26
            for session in candidate['sessions']:
                assert session['最終残玉'] == 0 and session['買売反射一致']
            if candidate['id'] in data:
                for symbol in SYMBOLS:
                    for key, value in candidate['symbols'][symbol].items():
                        assert abs(value - data[candidate['id']]['symbols'][symbol][key]) < .01
            purpose = '追加の構造診断・未採用' if candidate['id'].endswith('__K020') else accounting['監査目的']
            rows.append([candidate['id'], purpose, amount(len(candidate['sessions'])),
                         amount(sum(s['検算した観測行数'] for s in candidate['sessions'])), '一致', '一致'])
        summary['独立会計入力数'] = sum(len(c['sessions']) for c in accounting['候補'])
        summary['独立会計観測行数'] = sum(s['検算した観測行数'] for c in accounting['候補'] for s in c['sessions'])
        part = (f"<p>監査対象{len(accounting['候補'])}条件の全{summary['独立会計入力数']}入力・{summary['独立会計観測行数']:,}観測行について、"
                '注文から現金・買売保有・時価・最大下落を、全返済から利益／損失／枚数を独立に再計算しました。</p>')
        part += '<p>内訳は探索上位の説明用４条件と、仕組みを確認するK020の２条件です。研究候補６件を選んだという意味ではありません。同入口K000も別途同数の入力を会計照合しています。</p>'
        part += table('accounting-evidence', ['対象', '位置付け', '入力数', '観測行数', '会計・上限・場内返済', '未来切断・改変・上下反射'], rows)
        part += '<p>実装と台帳の検査です。監査通過によって未採用条件を研究候補へ昇格させません。</p>'
        body += details('独立会計：利益玉・損失玉・残玉をすべて照合', part)
        differences = []
        for candidate in accounting['候補']:
            if candidate['id'].endswith('__K000'):
                continue
            paired = candidate['K000対照']['symbols']
            top, nk = paired['TOPIX'], paired['NK225']
            differences.append([candidate['id'], money(top['期間収支差円']), money(top['期間DD差円']),
                                money(nk['期間収支差円']), money(nk['期間DD差円']),
                                f"{nk['注文台帳同一セッション数']}/13・{nk['返済台帳同一セッション数']}/13",
                                '全13区間一致' if nk['全13セッション金銭経路一致'] else '相違あり'])
        part = ('<p><strong>同じ設定でもTOPIXとNKで作用が違います。</strong>TOPIXは5枚中2枚（40%）を利確して3枚残し、NKは10枚中5枚（50%）を利確します。この整数切捨ての差で、組利益を守る床の実効価格が変わります。</p>'
                '<p>K040は3R到達後に最高利益の50%、K020は2R到達後に25%を保護する条件です。NKでは既存の3ATR追跡に含まれて新しい返済効果が出ない経路があります。今回のH011/H019では、K040はK000と全13区間の注文・返済まで完全一致。K020は金銭経路が全13区間一致し、返済理由だけ異なる各１区間があるため厳密な台帳一致は12/13です。</p>'
                '<p>TOPIXでは保護が作用しましたが、K040はH011で収支改善、H019で悪化しました。部分利確の比率差は「作用するか」の説明であり、利益改善を保証しません。下表は同入口K000との差。K020は追加診断で、候補への追加ではありません。</p>')
        part += table('rounding-comparison', ['条件', 'TOP収支差 円', 'TOP下落差 円', 'NK収支差 円', 'NK下落差 円', 'NK注文・返済の完全一致', 'NK金銭経路'], differences)
        part += '<p>Rは初回枚数×初回ATR×初期損切り幅です。部分利確後の3R到達と3ATR順行は同義ではありません。' + link('partial_rounding_diagnostic.md', '通常経路の式と実台帳の差分') + 'で、価格の飛び・呼値・行内順序を含む一般保証とは分けて確認しています。</p>'
        body += details('TOPIXとNKの差：半分利確の整数切捨てが効く', part)
    attribution = read(HERE / '最大下落の帰属.json')
    if attribution:
        reference = next(row for row in attribution['結果'] if row['手法'] == BASE and row['銘柄'] == 'TOPIX')
        assert reference['既存最大下落と収支一致']
        assert abs(sum(reference['分類別寄与円'].values()) + reference['最大下落円']) < .01
        rows = [[label, money(value)] for label, value in reference['分類別寄与円'].items()]
        part = (f"<p>旧H019__D273のTOPIX最大下落{amount(reference['最大下落円'])}円は、"
                '山の時点で持っていた玉の利益返上51,000円と、その後の新規取引の損失72,500円に分かれました。'
                '保有中の利益保護だけを強めても、再エントリーの損失まで必ず防げるわけではありません。</p>')
        part += table('drawdown-attribution', ['山から谷までの寄与', '損益差 円'], rows)
        part += '<p>同時刻にも複数の原本行があるため、山と谷はセッション順・原本行で区切って照合。谷より後の返済理由を原因へ混ぜていません。旧条件の１区間の会計説明で、将来の予測ではありません。</p>'
        part += '<p>' + link('最大下落の帰属.md', '旧２条件の最大下落の分解') + '</p>'
        body += details('何で利益が削られたか：旧主案の最大下落', part)
        summary['旧主案TOPIX最大下落の帰属'] = reference['分類別寄与円']
    return body, summary


def update_index(final: bool, lead: str) -> None:
    """機能: 00024を最新に保ち、過去成果を変更せず調査目次を更新する。

    引数: final (bool)、lead (str)。返り値: なし (None)。
    """
    status, label = ('検証結果', '結果を見る') if final else ('検証中', '進捗を見る')
    target = OUT.parent / 'index.html'
    text = target.read_text(encoding='utf-8')
    text = re.sub(r'<!--00024開始-->.*?<!--00024終了-->', '', text, flags=re.S)
    text = text.replace('task latest', 'task').replace('<span class="badge">最新</span>', '')
    text = re.sub(r'<p class="lead">.*?</p>', f'<p class="lead">最新は00024（第５反復の{status}）。前回の一回照合は00022に保存しています。</p>', text, count=1)
    card = (f'<!--00024開始--><article class="task latest"><div class="number">作業00024 <span class="badge">最新</span></div><h2>部分利確と最高利益の保護</h2><p>{escape(lead)}</p>'
            f'<a class="button" href="{NAME}/部分利確と利益保護.html">{label} →</a><p><a href="{NAME}/README.md">資料案内</a> · <a href="{PREVIOUS}/中期方向と入口の検証.html">前回の結果</a></p></article><!--00024終了-->')
    target.write_text(text.replace('</header>', '</header>' + card, 1), encoding='utf-8')
    target = OUT.parent / 'README.md'
    text = target.read_text(encoding='utf-8')
    text = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00024の[部分利確と利益保護]({NAME}/部分利確と利益保護.html)（{status}）。前回の結果・一回照合は[00022]({PREVIOUS}/中期方向と入口の検証.html)に保存しています。**', text, count=1)
    text = re.sub(r'^\| `00024_.*?\r?\n', '', text, flags=re.M).replace('（最新）', '')
    row = f'| `{NAME}`（最新） | 同じ入口と枚数で利益保護4,800設定 | [第５反復]({NAME}/部分利確と利益保護.html) | [資料案内]({NAME}/README.md) |'
    target.write_text(text.replace('| --- | --- | --- | --- |', '| --- | --- | --- | --- |\n' + row, 1), encoding='utf-8')


def main() -> None:
    """機能: 保存済みの段階から報告を生成し、数表・コピー・リンクを検査する。

    引数: なし。返り値: なし (None)。売買再生・通信・計算コードの変更はしない。
    """
    OUT.mkdir(exist_ok=True)
    helpers.TABLES.clear()
    fixed, design = read(HERE / '探索条件の固定.json'), read(V27 / 'hierarchy_design_fixed.json')
    progress, gate = read(HERE / '進捗.json', {'完了信号': 0}), read(HERE / '反証前の候補固定.json')
    first, random_results = read(HERE / '一次反証の結果.json'), read(HERE / '無関係対照の要約.json')
    random_plan, episode = read(HERE / '無関係対照前の候補固定.json'), read(HERE / 'episode_audit.json')
    selected = read(HERE / '研究候補の固定.json')
    checked = {x['candidate']['id']: complete_random(x) for x in (random_results or [])}
    state = completeness(gate, first, random_results, random_plan, episode, selected, checked)
    count = len(fixed['signals']) * len(fixed['managers'])
    assert count == 4800
    completed = count if state['探索完了'] else progress['完了信号'] * len(fixed['managers'])
    first, random_results = first or [], random_results or []
    passed = [x for x in first if not x['first_stage_failures']]
    old_fixed = read(V27 / '探索条件の固定.json')
    base_method = {'id': BASE, 'signal': next(x for x in old_fixed['signals'] if x['id'] == 'H019'),
                   'manager': next(x for x in old_fixed['managers'] if x['id'] == 'D273')}
    chosen = list(selected['候補']) if state['最終資料完備'] else []
    if not chosen and gate:
        chosen = [{'id': c['id'], 'signal': next(s for s in fixed['signals'] if s['id'] == c['signal_id']),
                   'manager': next(m for m in fixed['managers'] if m['id'] == c['manager_id'])} for c in gate['上位30'][:4]]
    displayed = [base_method] + chosen
    data = {m['id']: result_data(m['id']) for m in displayed}
    for item in chosen:
        paired_id = item['id'].split('__')[0] + '__K000'
        if paired_id not in data:
            data[paired_id] = result_data(paired_id)
    if state['最終資料完備']:
        check_selection(selected, first, random_results, episode, data)
        guard = read(HERE / '選抜整合の監査.json')
        assert guard and guard['完全性検査通過'], '検証付き選抜の保存監査が必要です'
        assert sha256((HERE / '研究候補の固定.json').read_bytes()).hexdigest() == guard['選抜JSON_SHA256']
        for name, expected in guard['入力SHA256'].items():
            path = Path(name).resolve()
            assert path.is_relative_to(ROOT) and 'live' not in path.parts
            assert sha256(path.read_bytes()).hexdigest() == expected, name
    lead = f'検証中：{completed:,} / 4,800条件。改善候補はまだ確定していません。'
    if state['探索完了']:
        lead = (f'全4,800条件の探索は完了。一次反証は{len(passed)}/{len(first)}件通過、最終判定は未完了です。'
                if first else '全4,800条件の探索は完了。一次反証の結果保存と最終判定を待っています。')
    if state['最終資料完備']:
        lead = ('改善基準を満たす研究候補：' + '、'.join(x['id'] for x in selected['候補']) + '。未知データでの確認はまだです。'
                if selected['候補'] else '第５反復も、両銘柄同時の「利益75%維持＋最大下落20%削減」には届きませんでした。')
    stamp = datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y/%m/%d %H:%M')
    body = f'<p class="eyebrow">作業00024 · 第５反復 · 更新 {stamp}</p><h1>部分利確と、最高利益の返上を調べる</h1><p class="lead"><strong>{escape(lead)}</strong></p>'
    body += '<p>入口と枚数を揃え、最高利益の割合保護とトレーリング幅の短縮を比較します。旧主案・同じ入口のK000の両方に対し、両銘柄で収支75%以上・最大下落80%以下を目標にしています。</p><p class="muted">同じ既知13セッションの再探索。費用０・指定価格約定。新しい現在照合は行っていません。</p>'
    body += '<nav><a href="#methods">入口・出口と損益</a><a href="#validation">検証の段階</a><a href="#waves">指定波</a><a href="#limits">仕組みと限界</a></nav>'
    overview = []
    for item in displayed:
        for symbol in SYMBOLS:
            row, base = data[item['id']]['symbols'][symbol], data[BASE]['symbols'][symbol]
            overview.append([item['id'], symbol, money(row['net_yen']), ratio(row['money_ratio']), amount(row['drawdown_yen']),
                             f"{row['net_yen'] / base['net_yen']:.0%}", f"{row['drawdown_yen'] / base['drawdown_yen']:.0%}",
                             '旧主案' if item['id'] == BASE else ('２項目達成' if row['net_yen'] >= .75 * base['net_yen'] and row['drawdown_yen'] <= .8 * base['drawdown_yen'] else '金額目標未達')])
    body += details('旧主案との期間収支・最大下落の比較', table('overview', ['手法', '銘柄', '全期間収支 円', 'PF', '最大下落 円', '旧主案の収支比', '旧主案の下落比', '銘柄内の金額目標'], overview))
    if chosen and not (state['最終資料完備'] and selected['候補']):
        body += '<p><strong>表示は事前の探索順位上位４件で、改善の推奨を意味しません。</strong>K000は同じ入口の旧D273を再現する基準で、新しい好成績として数えません。反証は保存された段階まで表示します。</p>'
    body += '<p class="muted">収支比75%以上・下落比80%以下が金額目標。銘柄間の円額は合算せず、それぞれ旧主案と比較します。</p>'
    # ----------------------------------------
    # 手法別の全26行・開始週・全期間を、保存済み集計と照合して折り畳む。
    body += '<h2 id="methods">手法と損益</h2><p>勝ち・負けは決済枚数。枚数差＝勝ち−負けで、残玉ではありません。同値決済も別記します。</p><p class="muted">TOPIXミニ1pt＝1,000円、NKマイクロ1pt＝10円。初回5枚／10枚、追加玉なし。9/21開始週10区間、9/28開始週3区間です。</p>'
    if (OUT / '５分足と売買.html').exists():
        body += '<p>' + link('５分足と売買.html', '５分足・売買と入口／中期方向の状態帯') + ' / ' + link('../' + PREVIOUS + '/５分足と売買.html', '旧主案の５分足') + '</p>'
    for item in displayed:
        description = previous.direction_description(item['signal'], design) + ' ' + order_description(item['manager'])
        body += helpers.method_section(item['id'], description, stage_label(item['id'], first, episode, selected, state, checked), data[item['id']])
        if item['id'] != BASE and not item['id'].endswith('__K000'):
            body += paired_comparison(item['id'], data)
    body += '<p>全玉を日中15:35／夜間05:50の判断後、次の有効な原本行で返済します。新規は開始20分後から返済判断時刻の5分前まで。セッションを跨ぎません。</p>'
    body += '<h2 id="validation">検証の段階</h2>'
    phases = [['全探索', f'{completed:,}/{count:,}', '完了' if state['探索完了'] else '進行中'],
              ['一次反証', f'{len(passed)}/{len(first)}候補通過', '全対象完了' if state['一次反証完了'] else '未完了'],
              ['無関係な方向の対照', f'{sum(checked.values())}/{len(random_plan or [])}候補・各64seed×2方式', '全対象完了' if state['乱数対照完了'] else '未完了'],
              ['指定４波×２銘柄', '全一次通過候補を診断', '全対象完了' if state['指定波完了'] else '未完了'],
              ['研究候補の固定', '保存済み' if selected is not None else '未保存', '資料整合済み' if state['最終資料完備'] else '判定待ち']]
    body += details('探索・反証・波診断・選抜の完了状況', table('phase', ['段階', '保存状態', '完了判定'], phases))
    validation = '<p>基準は両銘柄黒字、PF1.3以上、1枚平均利益/損失1.2以上、13組以上、7稼働・7黒字セッション以上。最大２勝ち組・セッション除外、日夜と開始週も別々に確認します。</p><p>入口を1/5/15秒遅延し、参考中期列も同時に遅らせますが、今回は中期撤回を使いません。観測価格約定は費用追加とは別の補足検査です。時計・相手遅延・短期閾値・入口幅・出口幅を別々に反証。割合保護の開始R、短縮開始ATRと短縮幅も±20%を試し、不使用設定は除外します。</p>'
    validation += table('first-results', ['対象', '一次判定', '未達理由'], [[x['candidate']['id'], '通過' if not x['first_stage_failures'] else '未達', '、'.join(x['first_stage_failures']) or '—'] for x in first]) if first else '<p>一次反証の結果は未保存です。</p>'
    for item in chosen:
        full = read(HERE / 'adversarial' / (item['id'] + '.json.gz'))
        if full:
            validation += details(item['id'] + '：設定・実行感度', sensitivity(item['id'], full))
    body += details('反証条件と候補別の判定', validation)
    random_body = '<p>入口を30分ごとの公平な乱数方向へ置換します。互換性のため参考中期列も同じ乱数へ置換しますが、今回の保有管理には使いません。発火時刻限定は元の入口時刻を残す対照で、完全な無情報ではありません。正式なp値とは呼びません。</p>'
    random_rows = []
    for item in random_results:
        for mode in item['summary']:
            random_rows.append([item['candidate']['id'], '入口時刻限定' if mode['発火時刻限定'] else '30分乱数',
                                f"{mode['両銘柄で候補以上の収支seed数']}/{mode['試行数']}", f"{mode['symbols']['TOPIX']['候補以上のPF_seed数']}/{mode['試行数']}",
                                f"{mode['symbols']['NK225']['候補以上のPF_seed数']}/{mode['試行数']}", '全seed保存済み' if checked[item['candidate']['id']] else '未完了'])
    random_body += table('random-summary', ['対象', '方式', '両銘柄収支が候補以上', 'TOPのPFが候補以上', 'NKのPFが候補以上', '保存状態'], random_rows) if random_rows else '<p>結果は未保存、または一次反証通過後の対象がありません。</p>'
    random_body += '<p>研究候補は両方式とも、両銘柄収支が候補以上のseedが3以下、各銘柄PFが候補以上のseedが6以下を要求します。</p>'
    body += details('無関係な方向64seed×２方式の対照', random_body)
    supplement, supplement_summary = supplementary_evidence(data)
    body += supplement
    if selected:
        rejected = [[x['candidate']['id'], '、'.join(x['reasons'])] for x in selected['棄却']]
        body += details('研究候補の棄却理由', table('rejected', ['対象', '保存された未達理由'], rejected) if rejected else '<p>保存対象に棄却はありません。</p>')
    body += '<h2 id="waves">指定された４つの波</h2><p>４波×両銘柄の全８区間で、正方向のネット保有を合計20分以上。連続20分を要求する指標ではありません。</p>'
    if episode:
        definitions = [[e['id'], e['name'], e['start'][11:16] + '〜' + e['end'][11:16], '買い' if e['side'] > 0 else '売り']
                       for e in episode['固定仕様']['規則']['対象']]
        wave_rows = [[r['method'], r['wave'], r['symbol'], f"{r['正方向信号分']:.1f}", f"{r['正方向管理分']:.1f}", f"{r['正方向ネット保有分']:.1f}",
                      f"{r['逆方向ネット保有分']:.1f}", money(r['時価損益差円']), '達成' if r['正方向ネット20分目安達成'] else '未達'] for r in episode['結果']]
        body += details('４波の定義・全診断対象の時間と損益', table('wave-definitions', ['波', '指定区間', '時間', '方向'], definitions)
                        + table('wave-results', ['手法', '波', '銘柄', '正方向入口 分', '正方向管理 分', '正方向保有 分', '逆方向保有 分', '波の時価差 円', '20分目安'], wave_rows))
        body += '<p>波の時価差は開始前の玉と終了時の含み損益も含みます。波の日時は診断にだけ使い、注文には渡していません。</p>'
    else:
        body += '<p>波診断は未保存です。一次反証の全通過候補を同じ方法で測ります。</p>'
    body += '<h2 id="limits">利益保護の仕組みと限界</h2>'
    limits = ('<p>96入口×50管理。初回はTOPIXミニ5枚／NKマイクロ10枚、追加・両建て・反転新規は使いません。入口は通常新規と未約定取消に作用し、保有中は価格注文・時間上限・場末で返済します。中期反転や中立による返済は追加しません。</p>'
              '<p>主方向は確定1分足を120秒遅延して計算し、相手確認はさらに60秒遅れた方向を使います。短期入口が消えただけで保有を返済する条件はありません。</p>'
              '<p>ATRは確定5分足のTR＝max(高値−安値, |高値−前終値|, |安値−前終値|)を、α=1/12・adjust=False・最低3本で指数平滑。最低２原本呼値幅を取り、足始から360秒後（完了後１分）に公開します。新規注文の準備時点の値を固定し、注文価格は呼値へ丸めます。</p>'
              '<p><strong>1R＝初回枚数×初回ATR×初期損切り幅（ATR倍率）</strong>の予定損失です。円表示なら契約倍率を掛けます。組の最高利益は、その組の実現利益＋残玉含み利益の合計が過去に達した最大額。口座全体や利益玉だけの最大値ではありません。</p>'
              '<p>最高利益が1／2／3Rに達した後、その最高額の25／50／75%を組の返済基準の床にします。最高額が増せば床も上がり、一度上げた床は下げません。<strong>割合保護は部分利確前にも作動します。</strong>順行2／3ATR後に3ATRの追跡を1.5／0.75ATRへ縮める条件も比較します。</p>'
              '<p><strong>保護額は発注基準で、実現利益の保証ではありません。</strong>設置行に遡って約定せず、次行以降に有効です。設置時点で既に通過した水準は次の観測価格で返済し、価格の飛び・呼値丸めで床を下回る場合があります。枚数上限10／20枚は別途守ります。</p>'
              '<p>「残玉の初回1ATR幅を維持する」案は、今回の2ATR部分利確・3ATR追跡では既存の追跡ストップに含まれるため、探索軸から外しました。residual_risk_capは全50管理で0。合成の包含検査と、K000が旧D273に一致する監査を別に保存しています。</p>'
              '<p>部分利確だけでは残玉１枚あたりの許容逆行が広がる場合があります。割合保護・追跡短縮を加えると早く降りる一方、一時的な戻りで大きな波を逃す可能性もあるため、全玉損益と指定波で判断します。</p>'
              '<p>旧版との一致、未来切断、上下反射、注文からの会計を監査しています。ただしCurrentPriceTimeは受信時刻ではなく、現実の通信・約定順を完全に再現したものではありません。</p>')
    body += details('Rと組の最高利益、保護の発動、残玉制限の除外理由', limits)
    body += '<p>' + link('../' + PREVIOUS_TASK + '/保有撤回と損失上限.html', '完了した第４反復の結果') + '</p>'
    body += '<p>新しい現在照合はありません。前回の一回照合で赤字となった保存結果は、' + link('../' + PREVIOUS + '/中期方向と入口の検証.html#current', '00022の現在照合') + 'に残しています。今回の探索・順位・合計・再試験には使っていません。</p>'
    sources = ['探索条件の固定.json', '管理設計の固定.json', '研究候補選抜の事前規則.json', '進捗.json', '反証前の候補固定.json',
               '反証規則の固定.json', '反証実装の固定.json', '一次反証の結果.json', '無関係対照前の候補固定.json', '無関係対照の要約.json', '研究候補の固定.json',
               'episode_audit.md', 'episode_audit.json', 'episode_audit_fixed.json',
               'protection_synthetic_audit.md', 'protection_synthetic_audit.json', 'protection_independent_audit.md', 'protection_independent_audit.json',
               'validation_round5.md', '近傍の事前検算.json',
               '反証合成検算.json', '部品対照の事前注釈.json', '観測モデル派生の固定.json',
               'select_verified.md', '選抜整合ガードの固定.json', '選抜整合の監査.json', 'select_verified_test.json',
               'selected_accounting_audit.md', 'selected_accounting_audit.json', 'selected_accounting_fixed.json',
               'protection_component_audit.md', 'protection_component_audit.json', 'protection_component_fixed.json',
               'partial_rounding_diagnostic.md', 'partial_rounding_diagnostic.json', '最大下落の帰属.md', '最大下落の帰属.json',
               'report_contract_audit.json',
               '探索全体対照の結果.json', '探索全体対照の固定.json', '全探索対照の合成検査.json']
    copied = []
    for name in sources:
        if (HERE / name).exists():
            shutil.copy2(HERE / name, OUT / name)
            copied.append(name)
    evidence = '<p>' + ' / '.join(link(n) for n in copied if n.endswith('.md')) + '</p><p>' + link('../../work/wave_v29/', '全条件・反証・再現コード') + ' / ' + link('表示データ.json', '表示値') + ' / ' + link('報告検査.json', '数表・リンク検査') + '</p>'
    evidence += details('保存JSON・固定仕様の一覧', '<p>' + ' / '.join(link(n) for n in copied if n.endswith('.json')) + '</p>')
    body += details('固定仕様・独立監査・全保存資料', evidence) + '<footer>' + link('README.md', '読む順序と再現手順') + ' / ' + link('../index.html', '調査一覧') + '</footer>'
    css = ':root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0b111c;color:#e4eaf3;font:15px/1.75 system-ui,"Yu Gothic",sans-serif}main{max-width:1250px;margin:auto;padding:28px 24px 60px}h1{font-size:29px;line-height:1.4}h2{font-size:21px;margin-top:28px}h3{font-size:16px}.eyebrow,.muted{font-size:13px;color:#a9b9ce}.lead{font-size:18px}.scroll{overflow:auto;margin:12px 0}table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}th,td{padding:8px 10px;border-bottom:1px solid #2b3d53;text-align:right}th{background:#1a2b40;color:#d2e2f2}th:first-child,td:first-child{text-align:left}tr:nth-child(even){background:#101d2e}details{background:#111d2c;border:1px solid #31465e;border-radius:7px;margin:12px 0}summary{padding:13px 15px;cursor:pointer;font-weight:650}.inside{padding:0 16px 17px}a{color:#8fc8ff}nav{display:flex;flex-wrap:wrap;gap:20px}footer{border-top:1px solid #31465e;padding-top:18px;margin-top:24px}@media(max-width:650px){main{padding:18px 12px}h1{font-size:24px}}'
    comment = '<!--\n[コンポーネント概要]\nmainは保存段階と結論、detailsは手法・数表・反証の折り畳み、.scrollは横長表です。\n通信や売買再生を行わない静的ダークテーマです。\n-->'
    html = '<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>00024 部分利確と利益保護</title><style>' + css + '</style></head><body>' + comment + '<main>' + body + '</main></body></html>'
    (OUT / '部分利確と利益保護.html').write_text(html, encoding='utf-8')
    state.update(探索保存条件数=completed, 一次通過=len(passed), 表示手法=[m['id'] for m in displayed], 新しい現在照合=False, 現在保存データの使用=False)
    save(OUT / '表示データ.json', {'状態': state, '代表手法': data, '追加診断': supplement_summary, '表示表': helpers.TABLES})
    readme = '# 作業00024：部分利確と最高利益の保護\n\n最初に [部分利確と利益保護.html](部分利確と利益保護.html) を開いてください。\n\n' + lead + '\n\n'
    readme += '読む順序：\n\n1. [HTMLの結論・手法別損益](部分利確と利益保護.html)：全期間・開始週・各セッションの利益／損失／収支と勝ち・負け・差・同値の決済枚数。\n2. [管理条件](管理設計の固定.json) と [研究候補の事前基準](研究候補選抜の事前規則.json)。\n3. [表示値](表示データ.json) と [合算・リンク検査](報告検査.json)。\n\n'
    if (OUT / '５分足と売買.html').exists():
        readme += '[５分足と売買](５分足と売買.html)：入口と参考中期方向の状態帯も表示します。中期は保有撤回には使わず、状態帯は保有量でもありません。[旧主案の図解](../' + PREVIOUS + '/５分足と売買.html)と比較できます。\n\n'
    readme += '同じ既知13セッションに対する96入口×50管理＝4,800条件です。初回TOPIXミニ5枚／NKマイクロ10枚、追加玉なし、上限は片方向10枚／20枚。開始週は9/21の10区間と9/28の3区間。利益玉・損失玉・同値返済をすべて含み、枚数差は残玉ではありません。\n\n'
    readme += 'K000は同じ入口の旧D273を再現する基準で、新しい改善として数えません。旧H019__D273と同一入口K000の両方に対し、各銘柄の収支75%以上・最大下落80%以下を要求します。\n\n'
    readme += '割合保護のRは初回枚数×初回ATR×初期損切り幅の予定損失。組の実現＋含み利益の過去最高額を保護し、部分利確前にも作動します。床は発注基準で、次行価格や呼値丸めで下回り得ます。残玉初回幅capは既存追跡に含まれるため探索から除外し、全50管理で0としています。\n\n'
    readme += f'現在APIは追加取得せず、[00022の一回照合](../{PREVIOUS}/中期方向と入口の検証.html#current)も探索・再生・順位・合計へ算入しません。未知検証ではありません。\n\n'
    extra_links = [('select_verified.md', '検証付き選抜'), ('selected_accounting_audit.md', '独立会計'),
                   ('protection_component_audit.md', '利益保護の全対応'), ('探索全体対照の結果.json', '探索全体の対照'),
                   ('partial_rounding_diagnostic.md', 'TOPIXとNKの部分利確比率'), ('最大下落の帰属.md', '旧主案の最大下落の内訳')]
    extra_links = [(path, label) for path, label in extra_links if (OUT / path).exists()]
    if extra_links:
        readme += '追加確認：' + '／'.join(f'[{label}]({path})' for path, label in extra_links) + '。保存済み資料だけを表示しています。\n\n'
    readme += '再現手順（プロジェクトルート、既知データだけ）：\n\n```powershell\npython -X utf8 work/wave_v29/protection_runner.py --workers 12\npython -X utf8 work/wave_v29/validation_round5.py --workers 8\npython -X utf8 work/wave_v29/validation_round5.py --random --workers 8\npython -X utf8 work/wave_v29/episode_audit.py --first-stage\npython -X utf8 work/wave_v29/select_verified.py\npython -X utf8 work/wave_v29/chart_report.py\npython -X utf8 work/wave_v29/report_round5.py\n```\n\n'
    readme += '結果が保存済みなら最後の報告生成だけで再作成できます。報告生成は売買・通信を行わず、00024と調査ルート目次を更新します。00023以前の成果、原計算、固定規則、原本は変更しません。\n\n'
    readme += 'コード：[探索](../../work/wave_v29/protection_runner.py) / [利益保護エンジン](../../work/wave_v29/engine_protection.py) / [反証](../../work/wave_v29/validation_round5.py) / [波診断](../../work/wave_v29/episode_audit.py) / [検証付き選抜](../../work/wave_v29/select_verified.py) / [報告](../../work/wave_v29/report_round5.py)。\n'
    (OUT / 'README.md').write_text(readme, encoding='utf-8')
    update_index(state['最終資料完備'], lead)
    # ----------------------------------------
    # 全セルを表示元と照合し、ファイル・ページ内アンカーも検査する。
    parser = helpers.ReportParser()
    parser.feed(html)
    assert not parser.stack and len(parser.tables) == len(helpers.TABLES)
    for identifier, expected in helpers.TABLES.items():
        assert parser.tables[identifier] == [expected['headers']] + expected['rows'], identifier
    for href in parser.links + re.findall(r'\]\(([^)]+)\)', readme):
        part = urlsplit(href)
        if part.scheme:
            continue
        target = (OUT / unquote(part.path)).resolve() if part.path else (OUT / '部分利確と利益保護.html')
        if target.name != '報告検査.json':
            assert target.exists(), target
        if part.fragment:
            if target.name == '部分利確と利益保護.html':
                assert part.fragment in parser.ids
            else:
                other = helpers.ReportParser()
                other.feed(target.read_text(encoding='utf-8'))
                assert part.fragment in other.ids, href
    for name in copied:
        assert (HERE / name).read_bytes() == (OUT / name).read_bytes()
    audit = {'生成時刻': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '状態': state,
             '表数': len(helpers.TABLES), '表データ行数': sum(len(x['rows']) for x in helpers.TABLES.values()),
             'セッション合算照合': len(displayed) * 26, '週と期間合算照合': len(displayed) * 6,
             '同入口基準を含む一意手法のセッション照合': len(data) * 26,
             '追加診断': supplement_summary,
             'HTMLタグID表セル一致': True, 'リンクとアンカー確認': len(parser.links), '原資料コピー一致': len(copied),
             'API取得': 0, '売買再生': False, '現在保存データの読取り': False, 'ルート目次の最新': '00024',
             '報告コードSHA256': sha256(Path(__file__).read_bytes()).hexdigest(),
             '表示共通コードSHA256': {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
                                  for p in [V27 / 'report_round3.py', HERE.parent / 'wave_v26' / 'report_round2.py', HERE.parent / 'wave_v25' / 'report_round.py']}}
    save(OUT / '報告検査.json', audit)
    print(json.dumps({'報告': str(OUT / '部分利確と利益保護.html'), **state, '表数': len(helpers.TABLES)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
