"""確定済み条件の会計を、短い説明と全33場の表へ表示する。売買再生は行わない。"""

import argparse
import hashlib
from html import escape
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FOLDER = '00103_往復帯の回避と損失後再参加の統合検証'
TITLE = '改善手法と全セッション損益.html'
SYMBOLS = ('TOPIX', 'NK225')
NAMES = {'TOPIX': 'TOPIXミニ10枚', 'NK225': '日経225マイクロ20枚'}
DIAGNOSIS_KEYS = ('収支変化', '避けた基準損失', '失った基準利益',
                  '共通入口の出口変化', '新たな入口の収支')


def text(value: object) -> str:
    """
    機能: 動的な文字列をHTML本文・属性へ安全に挿入する。
    引数: value(object)は表示する値。
    返り値: strは引用符もエスケープした文字列。
    """
    return escape(str(value), quote=True)


def yen(value: float) -> str:
    """
    機能: 円額を三桁区切りで表示する。
    引数: value(float)は有限の金額。
    返り値: strは整数円。小数点以下の計算誤差を丸める。
    """
    assert math.isfinite(value)
    return '0' if abs(value) < .5 else f'{value:,.0f}'


def money(value: float, loss: bool = False) -> str:
    """
    機能: 収支と正数保存の損失額を意味に沿った色で表示する。
    引数: value(float)は金額、loss(bool)は損失の絶対額表示か。
    返り値: strは表示用HTML。会計値は変更しない。
    """
    color = ('negative' if value > 1e-5 else 'neutral') if loss else (
        'positive' if value > 1e-5 else 'negative' if value < -1e-5 else 'neutral')
    return f'<span class="{color}">{yen(value)}</span>'


def percentage(value: float | None) -> str:
    """
    機能: 金額利益割合の既知値と未定義を区別する。
    引数: value(float|None)は0から1の割合又は未定義。
    返り値: strは百分率又は未定義記号。
    """
    return '—' if value is None else f'{100 * value:.1f}%'


def ratios(summary: dict) -> tuple[str, str]:
    """
    機能: 総利益損失比と平均勝負比を別の指標として表示する。
    引数: summary(dict)は保存された同一商品の全場会計。
    返り値: tuple[str,str]はPFと平均勝負比。無取引を無限大にしない。
    """
    profit, loss = summary['profit'], summary['loss']
    pf = f'{profit / loss:.2f}' if loss > 0 else '∞' if profit > 0 else '—'
    payoff = summary['payoff']
    average = f'{payoff:.2f}' if payoff is not None else (
        '損失なし' if profit > 0 and loss == 0 else '—')
    return pf, average


def validate(data: dict) -> None:
    """
    機能: 完了会計・条件一覧・33場66商品期間と表示合計の一致を検査する。
    引数: data(dict)は根担当の金融results.json。
    返り値: None。不足や会計不一致がある場合は公開前に停止する。
    """
    assert data['全合格'] is True, '金融結果が未合格です'
    sessions, configs = data['sessions'], data['configs']
    assert len(sessions) == len(set(sessions)) == 33
    assert len(configs) > 0 and len(configs) == len({config['id'] for config in configs})
    assert set(data['cases']) == {config['id'] for config in configs}
    assert set(data['evaluation']['results']) == set(data['cases'])
    assert len(data['selected']) == len(set(data['selected'])) == 3
    assert all(ident in data['cases'] for ident in data['selected'])
    assert data['baseline'] == 'C_N30_B4' and data['baseline'] in data['cases']
    for config in configs:
        assert config['quantity'] == {'TOPIX': 10, 'NK225': 20}
        case = data['cases'][config['id']]
        rows = case['rows']
        assert len(rows) == 66
        assert {(row['session'], row['symbol']) for row in rows} == {
            (session, symbol) for session in sessions for symbol in SYMBOLS}
        for row in rows:
            for key in ('profit', 'loss', 'net', 'fees'):
                assert math.isfinite(row[key])
            assert row['profit'] >= 0 and row['loss'] >= 0 and row['fees'] >= 0
            assert math.isclose(row['net'], row['profit'] - row['loss'], abs_tol=1e-4)
            for key in ('winning_lots', 'losing_lots', 'campaigns',
                        'winning_campaigns', 'losing_campaigns'):
                assert row[key] >= 0 and row[key] == int(row[key])
        for symbol in SYMBOLS:
            summary = case['summary'][symbol]
            assert summary == data['evaluation']['results'][config['id']]['symbols'][symbol]
            subset = [row for row in rows if row['symbol'] == symbol]
            for key in ('profit', 'loss', 'net', 'fees', 'winning_lots', 'losing_lots',
                        'campaigns', 'winning_campaigns', 'losing_campaigns'):
                assert math.isclose(summary[key], sum(row[key] for row in subset),
                                    abs_tol=1e-4), (config['id'], symbol, key)
            active = [row for row in subset if row['campaigns'] > 0]
            assert summary['active_sessions'] == len(active)
            assert summary['positive_sessions'] == sum(row['net'] > 1e-5 for row in active)
            assert summary['losing_sessions'] == sum(row['net'] < -1e-5 for row in active)
            assert summary['no_trade_sessions'] == 33 - len(active)
            assert all(row['profit'] == row['loss'] == row['net'] == 0
                       for row in subset if row['campaigns'] == 0)
            assert math.isclose(summary['worst_session_loss'],
                max([0.] + [-row['net'] for row in subset]), abs_tol=1e-4)
            assert math.isclose(summary['without_best_net'],
                summary['net'] - max(row['net'] for row in subset), abs_tol=1e-4)
            total = summary['profit'] + summary['loss']
            assert (summary['profit_share'] is None if total == 0 else
                math.isclose(summary['profit_share'], summary['profit'] / total, abs_tol=1e-10))
        # ----------------------------------------
        # 原因内訳は新しい売買の予測精度とは呼ばず、保存差額にだけ対応させる。
        if config['id'] in data['diagnosis']:
            for symbol in SYMBOLS:
                value = data['diagnosis'][config['id']][symbol]
                assert all(math.isfinite(value[key]) for key in DIAGNOSIS_KEYS)
                expected = (value['避けた基準損失'] - value['失った基準利益']
                            + value['共通入口の出口変化'] + value['新たな入口の収支'])
                assert math.isclose(value['収支変化'], expected, abs_tol=1e-4)


def validate_stability(data: dict, stability: dict) -> None:
    """
    機能: 大勝ち依存の追加点検が全条件・両商品に存在するか確認する。
    引数: data(dict)は正式会計、stability(dict)は根担当の追加集約。
    返り値: None。未測定を0へ補完せず、不足時は公開を停止する。
    """
    assert set(stability) == set(data['cases'])
    for ident in data['cases']:
        for symbol in SYMBOLS:
            value = stability[ident][symbol]
            assert math.isfinite(value['median_session_net'])
            assert math.isfinite(value['without_top3_net'])
            share = value['best_session_share_of_session_positive_net']
            assert share is None or math.isfinite(share) and 0 <= share <= 1 + 1e-10


def robust(stability: dict, ident: str) -> bool:
    """
    機能: 中央値と上位3利益場除外の両商品黒字を確認する。
    引数: stability(dict)は追加集約、ident(str)は条件ID。
    返り値: boolは両商品で両条件が正か。候補順を変更しない。
    """
    return all(stability[ident][symbol]['median_session_net'] > 0
               and stability[ident][symbol]['without_top3_net'] > 0 for symbol in SYMBOLS)


def description(config: dict) -> tuple[str, str, str]:
    """
    機能: 固定条件を入口・途中・出口の三行へ平易化する。
    引数: config(dict)は金融前に固定された一条件。
    返り値: tuple[str,str,str]は三段階の説明。閾値を再選択しない。
    """
    if config['entry_id'].startswith('REGIME_'):
        mode = config['mode']
        trend = f'両市場の5分間6点で同じ方向へ{config["trend_bp"]/100:.2f}%以上進んだ時、同方向の板定着で追従する'
        reversal = (f'両市場の6点の純移動/総移動が{config["range_er"]:g}以下で、双方の範囲が4呼値以上なら、'
            '進行失敗後の反転を選ぶ。自己の範囲中心へ届く手数料後利益が初期損失の1.25倍以上ある時だけ入る')
        entry = trend+'。' if mode=='C_ONLY' else reversal+'。' if mode=='R_ONLY' else reversal+'。それ以外は'+trend+'。'
        during = '往復分類を優先し、余地不足でも追従へ救済しない。追加建てなし。保有中は新規時に決めた出口を維持し、場内で返済。デイ09:15までは新規なし。'
        trail = '費用幅＋実初期損失幅の2倍の順行後、同損失幅で利益追尾' if config['C_exit']=='R21' else '始値0.4%幅の広い利益追尾'
        exits = '追従は支持4呼値外と始値0.1%幅の近い停止線、'+trail+'。反転は同じ停止線と判断時に固定した範囲中心へ到達した時の返済。全て判断後の次正常気配。'
        return entry,during,exits+' 6点の効率は全ティック経路の効率ではない。'
    entry = {
        'C_OWN': '板の活動後に新しい価格が定着した方向へ入る。相手市場は条件にしない。',
        'C_N30': '価格定着で入る。相手市場の直前30秒が反対・不明・曖昧なら見送る。既知の中立は通す。',
        'U_P10': '価格定着の追従と進行失敗の反転を選ぶ。相手市場の直前10秒も同方向で、自己の根拠が競合しない時だけ入る。',
        'R_OWN': '板の数量が回復し、それまでの進行が失敗した後、反対側の新価格が定着したら反転方向へ入る。',
        'P_OWN': '価格定着の追従と、進行失敗後の反転を別の枠で同時運転する。相手市場の方向を条件にしない。',
        'P_N30': '相手の30秒逆行を避ける価格定着の追従と、自己の進行失敗後の反転を別の枠で同時運転する。',
    }[config['entry_id']]
    mode, window = config['filter_mode'], config['window']
    if mode != 'NONE':
        additions = []
        if 'E' in mode:
            subject = '両市場' if 'P' in mode else '自己市場'
            additions.append(f'{subject}の直前{window}秒の方向付き純移動÷総移動が0.5超')
        if 'N' in mode:
            additions.append(f'現在の清算気配から初期停止線までの余裕が、自己の直前{window}秒の最大逆行幅より大きい')
        entry += ' さらに' + '、'.join(additions) + '場合だけ参加する（既知3観測以上）。'
        if config['own_path'] == 'PUBLIC':
            entry += ' 自己の往復量は同価格時計の先頭観測だけで測る。'
        else:
            entry += ' 自己の往復量は同時計内の更新も含める。'
    during = []
    if 'allocations' in config:
        allocations = config['allocations']
        if len(config.get('components',[]))==2:
            during.append(f'追従/反転の保有枠はTOPIX {allocations["TOPIX"][0]}/{allocations["TOPIX"][1]}枚、日経 {allocations["NK225"][0]}/{allocations["NK225"][1]}枚で固定し、空き枠を貸さない')
        else:
            during.append('反転手法だけへTOPIX10枚・日経20枚を配分する')
    if config['reentry_band']:
        during.append('赤字返済後の同方向・同支持帯への再参加を止め、帯外の新しい根拠が揃うまで待つ')
    if config['session_brake']:
        during.append('当時の清算損失が開始時の損失予算に達したら返済し、その場の新規を止める')
    if not during:
        during.append('追加建て・数量復元なし。返済後30秒は新規を休む')
    else:
        during.append('追加建てなし、返済後30秒休止')
    if config.get('thesis_enabled'):
        during.append(f'自己の初期支持を1呼値以上破り、相手の直前{config["thesis_window"]}秒両気配も逆へ1呼値以上進む状態を{config["thesis_confirm_seconds"]:g}秒確認したら返済を判断する')
    if config.get('quiet_mode'):
        labels = {'J':'デイ08:45〜09:15', 'U':'NYSE開場の前後15分',
                  'JU':'デイ08:45〜09:15とNYSE開場の前後15分'}
        during.append(labels[config['quiet_mode']]+'は新規を止め、開始時に保有を返済する')
    stop = f'支持の{config["support_ticks"]}呼値外と始値0.1%幅（最低2呼値）の有利な停止線を使う。'
    if config['r_profit']:
        exit_text = (stop + f'実約定時の料金込み初期リスク幅を固定し、費用幅＋{config["alpha"]:g}倍の順行で利益追尾を発動、'
                     f'{config["beta"]:g}倍幅で追う。')
    elif config['profit_trail']:
        exit_text = (stop + f'費用幅＋{config["support_ticks"]}呼値の順行後は、'
                     f'{config["support_ticks"]}呼値幅で利益を追う。')
    else:
        exit_text = stop + '利益は始値0.4%幅の広い追尾で伸ばす。'
    if 'daily_profit_multiple' in config:
        goal = config['daily_profit_multiple']
        limit = config['daily_loss_multiple']
        risk = '始値0.1%を呼値切上げした幅（最低2呼値）×枚数×商品倍率'
        budget_text = ('損失予算は追加しない' if limit is None else
                       f'清算損失が開始時予算の{limit:g}倍に達した時も停止する')
        exit_text += (f' 口座の手数料後時価利益が開始時予算の{goal:g}倍に達したら全返済を判断し、'
                      f'次の正常気配で約定してその場の新規を止める。{budget_text}。'
                      f'予算＝{risk}で、約定額の保証ではない。')
    if config.get('goal_ticks') is not None:
        loss = config['loss_ticks']
        stop_text = '追加の口座損失上限なし' if loss is None else f'口座損失{loss}呼値分でも終了'
        exit_text += (f' 口座全体の手数料後清算利益が{config["goal_ticks"]}呼値×上限枚数×商品倍率に達したら、'
                      f'次の正常気配で残玉を全返済し、その場の取引を終了する。{stop_text}。')
    return entry, '。'.join(during) + '。', exit_text + ' 場内で全返済する。'


def conclusion(data: dict, stability: dict) -> str:
    """
    機能: 金額利益80%・全場黒字・採用の達否を別々に述べる。
    引数: data(dict)は会計と確定評価、stability(dict)は大勝ち依存の追加点検。
    返り値: strは短い結論のHTML。未知性能の保証を加えない。
    """
    judged = data['evaluation']['results']
    all_positive = [ident for ident, item in judged.items() if all(
        item['symbols'][symbol]['positive_sessions'] == 33 for symbol in SYMBOLS)]
    eighty = [ident for ident, item in judged.items() if all(
        item['symbols'][symbol]['profit'] > 0
        and item['symbols'][symbol]['profit_share'] is not None
        and item['symbols'][symbol]['profit_share'] >= .8 for symbol in SYMBOLS)]
    adopted = data['evaluation']['adopted']
    retained = [ident for ident in adopted if robust(stability, ident)]
    lead = ('両銘柄の既定採用基準と、中央値・上位3利益場を除いても黒字という条件を満たしたのは'
            + str(len(retained)) + '件。' if retained else
            '金額利益80%と、大勝ちに依存しない安定性を両銘柄で満たす手法は見つからなかった。')
    return ('<p class="note">保存会計の集計：' + str(len(data['configs'])) + '条件。追加検証の進捗はREADMEに記載。</p>'
            + '<p class="lead">' + text(lead) + '</p><p>'
            + f'両銘柄で全33場黒字：{"達成" if all_positive else "未達"}。'
            + f'両銘柄で金額利益80%：{"達成" if eighty else "未達"}。'
            + '未知データでの確認は0件で、全33場は既知の探索対象。</p>'
            + '<p class="note">中央値が0以下、または上位3利益場を除いた収支が0以下の候補は、有望と断定しない。</p>')


def comparison(data: dict, configs: dict[str, dict], stability: dict) -> str:
    """
    機能: 確定した三候補と同数量の基準を商品別に比較する。
    引数: data(dict)は会計、configs(dict[str,dict])は条件索引、stability(dict)は追加点検。
    返り値: strは安定性比較表。収益順で候補を再選択しない。
    """
    identifiers = list(dict.fromkeys([*data['selected'], data['baseline']]))
    rows = []
    for ident in identifiers:
        title = text(configs[ident]['id'])
        tag = '基準' if ident == data['baseline'] else '既定・追加基準を達成' if (
            data['evaluation']['results'][ident]['adopted'] and robust(stability, ident)) else '比較候補'
        for symbol in SYMBOLS:
            total = data['cases'][ident]['summary'][symbol]
            stable = stability[ident][symbol]
            pf, payoff = ratios(total)
            same = total['active_sessions'] - total['positive_sessions'] - total['losing_sessions']
            counts = f'{total["positive_sessions"]} / {total["losing_sessions"]} / {total["no_trade_sessions"]}'
            if same:
                counts += f'（同値{same}）'
            rows.append(f'<tr><th><a href="#session-detail" data-open="{title}">{title}</a>'
                + f'<span class="tag">{tag}</span></th><td>{NAMES[symbol]}</td>'
                + f'<td>{money(total["net"])}</td><td>{counts}</td>'
                + f'<td>{percentage(total["profit_share"])}</td><td>{pf}</td><td>{payoff}</td>'
                + f'<td>{money(total["worst_session_loss"], loss=True)}</td>'
                + f'<td>{money(stable["without_top3_net"])}</td>'
                + f'<td>{money(stable["median_session_net"])}</td>'
                + f'<td>{percentage(stable["best_session_share_of_session_positive_net"])}</td></tr>')
    return ('<div class="table-scroll"><table class="comparison"><thead><tr>'
            '<th>手法ID</th><th>商品</th><th>収支（円）</th><th>黒字 / 赤字 / 無取引の場数</th>'
            '<th>金額利益割合</th><th>PF</th><th>平均勝ち/負け</th><th>最大赤字場（円）</th>'
            '<th>上位3利益場除外（円）</th><th>中央値（円）</th><th>最大黒字場の寄与</th>'
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
            '<p class="note">金額利益割合＝総利益÷（総利益＋総損失）。PF＝総利益÷総損失。'
            '平均勝ち/負けは一組当たりの平均利益÷平均損失。最大黒字場の寄与は黒字場収支合計に対する割合。'
            '中央値は無取引を含む33場の収支で、無取引は黒字に数えない。</p>')


def session_table(data: dict, ident: str) -> str:
    """
    機能: 全33セッションの両商品損益と勝負の延べ返済枚数を表示する。
    引数: data(dict)は会計、ident(str)は表示する条件ID。
    返り値: strは33行と合計行を持つ表。欠損場を0円に補完しない。
    """
    case = data['cases'][ident]
    index = {(row['session'], row['symbol']): row for row in case['rows']}
    rows = []
    for session in data['sessions']:
        label = session.replace('_Day', ' デイ').replace('_Night', ' ナイト')
        cells = ['<th>' + text(label) + '</th>']
        for symbol in SYMBOLS:
            value = index[(session, symbol)]
            cells += [f'<td>{yen(value["profit"])}</td>',
                      f'<td>{money(value["loss"], loss=True)}</td>',
                      f'<td>{money(value["net"])}</td>',
                      f'<td>{int(value["winning_lots"]):,}</td>',
                      f'<td>{int(value["losing_lots"]):,}</td>']
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    sums = ['<th>全33場合計</th>']
    for symbol in SYMBOLS:
        total = case['summary'][symbol]
        sums += [f'<td>{yen(total["profit"])}</td>',
                 f'<td>{money(total["loss"], loss=True)}</td>',
                 f'<td>{money(total["net"])}</td>',
                 f'<td>{int(total["winning_lots"]):,}</td>',
                 f'<td>{int(total["losing_lots"]):,}</td>']
    headers = '<th>利益</th><th>損失</th><th>収支</th><th>勝ち枚数</th><th>負け枚数</th>'
    return ('<div class="table-scroll"><table class="sessions"><thead><tr>'
            '<th rowspan="2">セッション</th><th colspan="5">TOPIXミニ・片方向上限10枚</th>'
            '<th colspan="5">日経225マイクロ・片方向上限20枚</th></tr><tr>'
            + headers + headers + '</tr></thead><tbody>' + ''.join(rows)
            + '</tbody><tfoot><tr>' + ''.join(sums) + '</tr></tfoot></table></div>')


def diagnosis_table(data: dict, ident: str) -> str:
    """
    機能: 基準との差を避けた損失・失った利益・出口変更・新規機会へ分ける。
    引数: data(dict)は保存分解、ident(str)は条件ID。
    返り値: strは折り畳みの事後分解。欠けた診断を0に補完しない。
    """
    if ident not in data['diagnosis']:
        return ''
    rows = []
    for symbol in SYMBOLS:
        value = data['diagnosis'][ident][symbol]
        cells = ['<th>' + NAMES[symbol] + '</th>']
        cells += ['<td>' + money(value[key], loss=key == '失った基準利益') + '</td>'
                  for key in DIAGNOSIS_KEYS]
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    return ('<details><summary>基準との差の内訳（円）</summary><div class="table-scroll">'
            '<table><thead><tr><th>商品</th><th>収支変化</th><th>避けた基準損失</th>'
            '<th>失った基準利益</th><th>共通入口の出口変化</th><th>新たな入口の収支</th>'
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
            '<p class="note">収支変化＝避けた損失−失った利益＋共通入口の出口変化＋新たな入口の収支。'
            '事後の会計分解であり、見送った入口すべてを予測改善とは呼ばない。</p></details>')


def render(data: dict, stability: dict) -> str:
    """
    機能: 確定会計から短い比較と全条件切替を持つダークHTMLを作る。
    引数: data(dict)は合格済み33場の全条件会計、stability(dict)は追加集約。
    返り値: strは単独で閲覧できるHTML。ファイルや金融へ副作用はない。
    """
    validate(data)
    validate_stability(data, stability)
    configs = {config['id']: config for config in data['configs']}
    first = data['selected'][0]
    options, panels = [], []
    for config in data['configs']:
        ident = config['id']
        options.append(f'<option value="{text(ident)}"'
                       + (' selected' if ident == first else '') + '>' + text(ident) + '</option>')
        entry, during, exits = description(config)
        explanation = ('<dl><dt>入口</dt><dd>' + text(entry) + '</dd><dt>途中</dt><dd>'
                       + text(during) + '</dd><dt>出口</dt><dd>' + text(exits) + '</dd></dl>')
        flags = data['evaluation']['results'][ident]
        state = '既定・追加基準を達成' if flags['adopted'] and robust(stability, ident) else (
            '比較候補' if flags['eligible'] else '候補資格未達')
        panels.append(f'<section class="case" data-case="{text(ident)}"'
            + ('' if ident == first else ' hidden') + '><h3>' + text(ident) + '</h3>'
            + '<p class="state">' + state + '。' + text(config['explanation']) + '</p>'
            + explanation + session_table(data, ident) + diagnosis_table(data, ident) + '</section>')
    # ----------------------------------------
    # 数値はHTMLへ安全な本文として挿入し、操作用JSへJSONを埋め込まない。
    css = '''
:root{color-scheme:dark;--bg:#0b1120;--panel:#131e31;--line:#334155;--fg:#e2e8f0;--muted:#a7b5ca;--plus:#72ddb5;--minus:#ff9398;--accent:#8fc7ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.7 system-ui,sans-serif}
main{max-width:1320px;margin:auto;padding:28px 22px 60px}h1{font-size:26px;line-height:1.5;margin:0 0 12px}h2{font-size:21px;margin:30px 0 12px}h3{font-size:18px;overflow-wrap:anywhere}
a{color:var(--accent)}p{margin:10px 0}.lead{font-size:19px;font-weight:650}.note{color:var(--muted);font-size:13px}.intro,.case{background:var(--panel);padding:20px;border:1px solid var(--line);border-radius:10px}
.table-scroll{overflow-x:auto;max-width:100%;border:1px solid var(--line);border-radius:7px}table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}th,td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:right;font-variant-numeric:tabular-nums}th:first-child,td:first-child{text-align:left}thead th{background:#1c2c44;color:#d9e7fb}tbody tr:nth-child(even){background:#162238}tbody tr:hover{background:#22324d}tfoot{font-weight:700;background:#23354f}tfoot th,tfoot td{border-top:2px solid #6c85a7;border-bottom:0}
.comparison th:first-child{white-space:normal;min-width:210px;max-width:280px;overflow-wrap:anywhere}.comparison td:nth-child(2){text-align:left}.positive{color:var(--plus)}.negative{color:var(--minus)}.neutral{color:var(--muted)}.tag{display:block;font-size:11px;color:var(--muted);font-weight:400}
select{width:100%;max-width:830px;background:#162238;color:var(--fg);border:1px solid #6682a4;border-radius:6px;padding:12px;font:inherit;margin:8px 0 18px}label{font-weight:650}dl{display:grid;grid-template-columns:45px 1fr;gap:7px 12px;margin:14px 0 20px}dt{font-weight:650;color:#c4d9f4}dd{margin:0;overflow-wrap:anywhere}.state{color:var(--muted)}details{margin-top:18px}summary{cursor:pointer;color:var(--accent)}[hidden]{display:none!important}footer{margin-top:24px;color:var(--muted);font-size:13px}
@media(max-width:640px){main{padding:18px 12px 36px}h1{font-size:22px}.intro,.case{padding:14px}body{font-size:14px}th,td{padding:7px 9px}dl{grid-template-columns:34px 1fr;gap:7px 8px}}
'''
    script = '''
/**
 * 手法の選択に応じて全33場の表を切り替える。
 * @param {string} id - selectで指定された保存条件ID。
 * @returns {void} 対応する一章を表示する。計算や通信はしない。
 */
function showCase(id){
  document.querySelectorAll('[data-case]').forEach(node=>{node.hidden=node.dataset.case!==id;});
  document.getElementById('method').value=id;
}
document.getElementById('method').addEventListener('change',event=>showCase(event.target.value));
document.querySelectorAll('[data-open]').forEach(node=>node.addEventListener('click',()=>showCase(node.dataset.open)));
'''
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>' + TITLE + '</title>'
        '<style>' + css + '</style></head><body><main><h1>往復帯の回避と損失後再参加の統合検証</h1>'
        '<div class="intro">' + conclusion(data, stability) + '</div><h2>比較例三つと基準</h2>'
        + comparison(data, configs, stability)
        + '<p class="note">比較例は赤字頻度・予算に対する損失規模を優先した保存評価の順。採用推奨ではない。'
        '全額は両側手数料後で、異なる商品の円額を相殺しない。</p>'
        + '<h2 id="session-detail">手法の説明と全33セッション</h2>'
        + f'<label for="method">{len(data["configs"])}条件から選択</label>'
        + '<select id="method">' + ''.join(options) + '</select>'
        + '<p class="note">開始5分後から新規、終了5分前は新規停止、通常区切り1分前に返済予約。'
        '次の正常ラージ気配で仮想約定し、セッションを跨がない。勝ち/負け枚数は延べ返済枚数。'
        '同時保有枚数ではなく、収支0の決済枚数は含まない。</p>'
        + '<p class="note">原行順と価格時刻で再生。共通受信時計が未保存のため、実際の両市場受信順の完全な再現は未確認。</p>'
        + ''.join(panels) + '<footer>2026-09-21デイ〜2026-10-13デイの33場。'
        '<a href="公開会計.json">公開会計</a> · <a href="README.md">資料案内</a>'
        '</footer></main><script>' + script + '</script></body></html>')


def readme() -> str:
    """
    機能: 一つのHTMLで比較・説明・全場損益を読む案内を作る。
    引数: なし。
    返り値: strは公開フォルダ用Markdown。
    """
    return f'''# 往復帯の回避と損失後再参加の統合検証

最初に[改善手法と全セッション損益]({TITLE})を開いてください。

1. 三候補と基準の比較で、赤字の頻度・最大赤字・損小利大、上位3利益場除外と中央値を確認。
2. 手法選択で、入口・途中・出口の説明と全33セッションの損益・延べ返済枚数を確認。
3. 必要なら折り畳みの「基準との差の内訳」と[公開会計](公開会計.json)を確認。

TOPIXミニは片方向10枚、日経225マイクロは20枚。両側立会手数料を含み、ラージの次の正常気配を使う仮想約定です。セッションを跨ぎません。無取引は勝ちに数えません。

33場はすべて既知の探索対象です。未知データでの確認は0件で、保存評価の採用・不採用を将来の安定利益の保証にはしません。中央値が0以下、または上位3利益場を除いた収支が0以下なら、有望と断定しません。

根拠：[固定条件](../../work/wave_v106/catalog.py)、[安定性評価](../../work/wave_v106/evaluation.py)、[金融結果](../../work/wave_v106/finance/results.json)、[表示コード](../../work/wave_v106/report.py)。
'''


def main() -> None:
    """
    機能: 完了した結果だけから新しい公開フォルダ三資料を生成する。
    引数: --input/--stability(Path)は会計と追加集約、--destination(Path)は新規保存先。
    返り値: None。既存公開資料は上書きせず、金融・API・注文を実行しない。
    """
    parser = argparse.ArgumentParser(description='確定会計から短い比較と全33場のHTMLを生成する。')
    parser.add_argument('--input', '--results', dest='results', type=Path,
                        default=HERE / 'finance/final_results.json')
    parser.add_argument('--stability', type=Path, default=HERE / 'finance/stability.json')
    parser.add_argument('--destination', type=Path, default=ROOT / 'アルゴリズム調査' / FOLDER)
    args = parser.parse_args()
    content = args.results.read_bytes()
    data = json.loads(content.decode('utf-8-sig'))
    if 'stability' in data:
        stability, stability_sha = data['stability'], hashlib.sha256(content).hexdigest()
    else:
        stability_content = args.stability.read_bytes()
        supplement = json.loads(stability_content.decode('utf-8-sig'))
        assert supplement.get('全合格', True) is True
        stability = supplement['stability'] if 'stability' in supplement else supplement
        stability_sha = hashlib.sha256(stability_content).hexdigest()
    html = render(data, stability)
    public = dict(data)
    display_fields = ('session','symbol','profit','loss','net','gross','fees','campaigns',
        'winning_campaigns','losing_campaigns','flat_campaigns','winning_lots','losing_lots','flat_lots','lots',
        'profit_share','average_win','average_loss','payoff','equity_drawdown','budget_unit','order_count','maximums')
    public['cases'] = {ident:{key:([{field:row[field] for field in display_fields if field in row}
        for row in value] if key=='rows' else value) for key,value in case.items()
        if key in ('rows','summary','first_half','second_half')}
        for ident,case in data['cases'].items()}
    public['stability'] = stability
    public['公開根拠'] = dict(元会計=str(args.results.resolve().relative_to(ROOT)).replace('\\', '/'),
        元会計SHA256=hashlib.sha256(content).hexdigest(),
        表示sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        追加安定性SHA256=stability_sha,
        新金融再生=0, 未知確認=0, 欠けた場のゼロ補完=0)
    accounting = json.dumps(public, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    outputs = {TITLE: html, 'README.md': readme(), '公開会計.json': accounting}
    assert not args.destination.exists(), '公開先が既存です。自動上書きしません'
    args.destination.mkdir(parents=True)
    for name, value in outputs.items():
        (args.destination / name).write_text(value, encoding='utf-8', newline='\n')
    print(json.dumps(dict(全合格=True, 条件数=len(data['configs']), 場数=33,
        公開先=str(args.destination), HTML_SHA256=hashlib.sha256(html.encode('utf-8')).hexdigest(),
        元会計SHA256=hashlib.sha256(content).hexdigest(), 新金融再生=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
