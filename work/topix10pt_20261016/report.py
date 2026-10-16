"""十ポイント方向予兆を、選択期と別枠を分けて簡潔な非金融レポートにする。"""

from datetime import datetime, timedelta, timezone
from html import escape
import hashlib
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT / 'アルゴリズム調査/00118_TOPIX十ポイントの予兆と多尺度方向予測'
RESULT = HERE / 'measurement/十ポイント予兆の結果.json'
READY = HERE / 'report_check/ready'
HTML_NAME = '十ポイント方向予兆の候補と全セッション結果.html'
JSON_NAME = '十ポイント予兆の公開採点.json'
PERIODS = ('学習', '選択', '時系列別枠', '追加別枠', '別枠10', '別枠デイ', '別枠ナイト', '全37')
COUNTS = ('順先', '逆先', '窓末未決', 'EOF未決', '基準不可')
GROUPS = ('全体', '買い', '売り', '常時買い', '常時売り')
RISKS = (2.5, 5., 10.)
JST = timezone(timedelta(hours=9))
THOUGHTS = {
    '整列継続': '短期と長期の向きが揃い、現在値もその方向を維持している場面を選ぶ。',
    '収束拡散': '値幅や移動平均の間隔が縮んだ後、新しい方向へ動き始めた場面を選ぶ。',
    '高安突破': '既に確定した過去の高値・安値を越え、現在値も抜けた側にある場面を選ぶ。',
    '押し戻り': '大きい方向は続いていると判断し、短い押し・戻りの後の再進行を選ぶ。',
    '反発': '過去の帯の端へ行き過ぎた後、短期の価格が戻り始めた場面を選ぶ。',
    '二市場': 'TOPIXと、先に確定した日経の価格変化が同じ方向を示す場面を選ぶ。',
    '活動': '価格の向きに加え、公表出来高の増え方が条件を満たす場面を選ぶ。',
    '板': '閉じた1分間の表示数量や最良気配の変化が、価格の方向と一致する場面を選ぶ。',
    '学習': '前21セッションだけで価格・移動平均などと先着の関係を学び、そのモデルを後の場へ固定適用する。'
}


# ----------------------------------------


def check(condition: bool, name: str) -> None:
    """
    機能: 表示前の分母とschemaの不一致を停止させる。
    引数: condition(bool)、name(str) は成否と内容。
    返り値: None。値を修正したり未決を勝ちへ振り替えたりしない。
    """
    assert condition, name


def near(a: float | None, b: float | None) -> bool:
    """
    機能: Noneを未定義として保ち有限値の丸め前一致を確認する。
    引数: a/b(float|None) は比較値。
    返り値: bool は一致。Noneを0へ正規化しない。
    """
    if a is None or b is None:
        return a is b
    return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)


def percentage(value: float | None) -> str:
    """
    機能: 分母なしを数値0と区別して率を表示する。
    引数: value(float|None) は割合。
    返り値: str は百分率又は横棒。
    """
    return '—' if value is None else f'{value * 100:.1f}%'


def number(value: float | None) -> str:
    """
    機能: 未保存値を横棒、有限値を短い十進表記にする。
    引数: value(float|None) は値。
    返り値: str は表示文字。負の0は0に揃える。
    """
    if value is None:
        return '—'
    value = 0 if value == 0 else value
    return f'{value:,.4f}'.rstrip('0').rstrip('.')


def at(value: float | None) -> str:
    """
    機能: 保存価格時計を日本時間の日時へ変換する。
    引数: value(float|None) はepoch秒。
    返り値: str は日時又は未保存。実受信日時や逆行先着時刻を推定しない。
    """
    if value is None:
        return '—'
    return datetime.fromtimestamp(value, JST).isoformat(timespec='seconds').replace('T', ' ').replace('+09:00', '')


def validate_cell(cell: dict, name: str) -> None:
    """
    機能: 五つの排他的状態と二種類の率を純算術で照合する。
    引数: cell(dict)、name(str) は集計と名称。
    返り値: None。無信号や未決を成功扱いしない。
    """
    for key in COUNTS:
        check(isinstance(cell[key], int) and cell[key] >= 0, name + key)
    n = sum(cell[key] for key in COUNTS)
    resolved = cell['順先'] + cell['逆先']
    check(cell['n'] == n and cell['resolved'] == resolved, name + '分母')
    for key, expected in (
        ('全候補順先率', cell['順先'] / n if n else None),
        ('解決内順先率', cell['順先'] / resolved if resolved else None),
        ('解決率', resolved / n if n else None)):
        check(near(cell[key], expected), name + key)


def selected_qualification(summary: dict) -> bool:
    """
    機能: 保存された選択期の件数資格だけを確認する。
    引数: summary(dict) は一候補の全期間集計。
    返り値: bool は選択6場で12件・4活動場・買売各3件を満たすか。優位性合格ではない。
    """
    cell = summary['periods']['選択']
    return cell['予兆数'] >= 12 and cell['活動場数'] >= 4 and cell['買い数'] >= 3 and cell['売り数'] >= 3


def validate(result: dict) -> dict:
    """
    機能: 44条件・37場の保存値を再集計し、公開する数値の対応を確認する。
    引数: result(dict) は許可後に一回だけ読み取った非金融結果。
    返り値: dict は候補と場行のlookup。売買規則や採点の再生はしない。
    """
    check(result['全合格'] and result['金融'] is False, '完成した非金融結果')
    check(result['counts'] == dict(旧原NPZ=66, 新JSONL=8, 新金融=0, API=0), '入力回数')
    sessions = result['sessions']
    check(len(sessions) == len(set(sessions)) == 37, '37場')
    split = result['splits']
    check([len(split[key]) for key in PERIODS[:4]] == [21, 6, 6, 4], '時系列分割')
    check(sum((split[key] for key in PERIODS[:4]), []) == sessions, '分割の重複と順序')
    holdout = split['時系列別枠'] + split['追加別枠']
    periods = dict(split, 別枠10=holdout, 別枠デイ=[s for s in holdout if s.endswith('_Day')],
                   別枠ナイト=[s for s in holdout if s.endswith('_Night')], 全37=sessions)
    check(result['periods'] == periods, '保存期間')
    specs = {item['id']: item for item in result['specifications']}
    summaries = {item['id']: item for item in result['summaries']}
    check(len(specs) == len(summaries) == 44 and specs.keys() == summaries.keys(), '44候補')
    accounts = {(item['id'], item['session']): item for item in result['accounts']}
    check(len(accounts) == len(result['accounts']) == 44 * 37, '場行一意')
    check(set(accounts) == {(identity, session) for identity in specs for session in sessions}, '場行直積')
    for (identity, session), row in accounts.items():
        n = row['採用予兆数']
        check(n == row['買い数'] + row['売り数'] == len(row['records']), identity + session + '予兆数')
        check(row['公開候補数'] >= n, identity + session + '非重複前')
        for ri, risk in enumerate(RISKS):
            cell = row['risks'][ri]
            check(cell['逆行幅'] == risk, '逆行幅固定')
            for group in GROUPS:
                target = cell if group == '全体' else cell[group]
                validate_cell(target, identity + session + group)
            check(cell['n'] == cell['常時買い']['n'] == cell['常時売り']['n'] == n, '同時点対照分母')
            check(cell['買い']['n'] == row['買い数'] and cell['売り']['n'] == row['売り数'], '方向分母')
            for name in COUNTS:
                check(cell[name] == cell['買い'][name] + cell['売り'][name], '方向加算')
        for item in row['records']:
            check(item['方向'] in (-1, 1) and len(item['labels']) == 3, '具体例方向')
            check(item['公開原row'] >= 0 and item['公開秒'] >= item['確定分末'], '公開行時計')
            check(item['基準'] > 0, '公開時Last')
            if item['十pt到達秒'] is not None:
                check(item['十pt到達原row'] > item['公開原row'] and item['十pt到達秒'] >= item['公開秒'], '公開後十pt')
        for ri in range(3):
            observed = [item['labels'][ri] for item in row['records']]
            for code, name in ((1, '順先'), (-1, '逆先'), (0, '窓末未決'), (2, 'EOF未決'), (-2, '基準不可')):
                check(row['risks'][ri][name] == observed.count(code), '具体例と場集計')
    for identity, summary in summaries.items():
        check(summary['id'] == specs[identity]['id'], '候補対応')
        for period, subset in periods.items():
            saved = summary['periods'][period]
            rows = [accounts[identity, session] for session in subset]
            check(saved['場数'] == len(subset), '期間場数')
            for target, source in (('予兆数', '採用予兆数'), ('買い数', '買い数'), ('売り数', '売り数')):
                check(saved[target] == sum(row[source] for row in rows), '期間件数')
            check(saved['活動場数'] == sum(row['採用予兆数'] > 0 for row in rows), '活動場数')
            check(saved['無信号場数'] + saved['活動場数'] == len(subset), '無信号分離')
            for ri in range(3):
                for group in GROUPS:
                    cell = saved['risks'][ri][group]
                    validate_cell(cell, identity + period + group)
                    for name in COUNTS:
                        check(cell[name] == sum((row['risks'][ri] if group == '全体' else row['risks'][ri][group])[name] for row in rows), '期間加算')
            primary = saved['risks'][1]
            check(saved['主評価'] == primary, '主評価10対5')
            rate = primary['全体']['全候補順先率']
            expected = None if rate is None else rate - max(primary['常時買い']['全候補順先率'], primary['常時売り']['全候補順先率'])
            check(near(saved['対固定方向改善'], expected), '固定方向との差')
    selection = result['selection']
    check(selection['選択期'] == '選択', '選択は6場だけ')
    for key in ('正式候補', '比較参照'):
        ids = selection[key]
        check(len(ids) == len(set(ids)) <= 3 and set(ids) <= specs.keys(), '保存候補ID')
    check(all(selected_qualification(summaries[identity]) for identity in selection['正式候補']), '正式候補の選択資格')
    return dict(specs=specs, summaries=summaries, accounts=accounts, periods=periods)


# ----------------------------------------


def display_ids(selection: dict) -> list[str]:
    """
    機能: 保存済み正式候補を先頭に、候補数不足時だけ保存比較参照を添える。
    引数: selection(dict) は選択6場だけで保存されたID。
    返り値: list[str] は最大3表示ID。別枠の成績を順位へ使用しない。
    """
    selected = list(selection['正式候補'])
    for identity in selection['比較参照']:
        if len(selected) >= 3:
            break
        if identity not in selected:
            selected.append(identity)
    return selected


def examples(identity: str, accounts: dict, sessions: list[str]) -> list[dict]:
    """
    機能: 別枠10場から時系列順の成功・失敗・後の到達・未決を少数提示する。
    引数: identity(str)、accounts(dict)、sessions(list[str]) は固定ID・場行・別枠。
    返り値: list[dict] は最大4例。最大利益や事後に都合のよい時刻を探さない。
    """
    records = [dict(session=session, **item) for session in sessions for item in accounts[identity, session]['records']]
    chosen = []
    seen = set()
    for category in ('順先', '逆先', '逆先後に到達', '未決'):
        for item in records:
            label = item['labels'][1]
            match = (category == '順先' and label == 1 or category == '逆先' and label == -1
                     or category == '逆先後に到達' and label == -1 and item['十pt到達秒'] is not None
                     or category == '未決' and label in (0, 2))
            key = item['session'], item['公開原row']
            if match and key not in seen:
                chosen.append(dict(表示区分=category, **item))
                seen.add(key)
                break
    return chosen


def explanation(spec: dict) -> dict:
    """
    機能: 規則と学習の保存説明を、思想と実際の入口条件へ分ける。
    引数: spec(dict) は固定候補定義。
    返り値: dict は短い日本語説明。未保存の入口閾値を補完しない。
    """
    family = spec['family']
    condition = spec.get('condition', spec.get('description'))
    check(isinstance(condition, str) and bool(condition), '入口条件説明')
    if family == '学習':
        condition += ' 選んだ方向のモデル見込みが' + percentage(spec['threshold']) + '以上、反対方向との差が0.10以上となった初回。価格30連続足以上。'
    return dict(思想=THOUGHTS.get(family, '保存した価格・活動条件が当時揃う場面を選ぶ。'),
                入口条件=condition,
                共通条件='公開済み足があり、閉足の公開遅れ60秒以内・窓末5分前まで。起点は公開原行の現在Last。'+
                          '同方向の条件持続中は連射せず、採点では前予兆の±10pt先着又は窓末まで重複を除く。')


def build(result: dict, result_sha: str) -> dict:
    """
    機能: 完成結果だけから表示用の小採点と固定候補の説明を作る。
    引数: result(dict)、result_sha(str) は一読結果と同bytesSHA。
    返り値: dict は非金融の公開採点。別枠成績による候補の選び直しはしない。
    """
    lookup = validate(result)
    shown = display_ids(result['selection'])
    periods = lookup['periods']
    summaries = lookup['summaries']
    items = []
    for identity in shown:
        official = identity in result['selection']['正式候補']
        qualified = selected_qualification(summaries[identity])
        status = '正式候補' if official else '件数資格未達の比較参照' if not qualified else '正式選定外の比較参照'
        items.append(dict(id=identity, status=status, official=official, selection_qualified=qualified,
            **explanation(lookup['specs'][identity]),
            例=examples(identity, lookup['accounts'], periods['別枠10'])))
    rows = []
    for spec in result['specifications']:
        for session in result['sessions']:
            original = lookup['accounts'][spec['id'], session]
            rows.append({key: value for key, value in original.items() if key != 'records'})
    return dict(schema_version=1, 全合格=True, 金融=False, 試行=result['試行'],
        result=dict(path=RESULT.relative_to(ROOT).as_posix(), SHA256=result_sha), source_SHA256=result['source_SHA256'],
        sessions=result['sessions'], splits=result['splits'], periods=periods,
        selection=result['selection'], displayed=items, specifications=result['specifications'],
        summaries=result['summaries'], rows=rows,
        表示規則='選択6場で保存した正式候補を優先。不足時だけ保存比較参照で最大3候補を表示。全44は元の条件ID順。別枠成績で再選択しない。',
        留保=[
            '10pt到達と、指定逆行幅に触れる前の10pt先着は別。後から到達しても逆先を成功へ変更しない。',
            '観測できたLastの先着。完全な約定テープや、除外区間にも反対閾値へ触れなかった証明ではない。',
            '未決・基準不可は成功に含めない。無信号セッションも成功に数えない。',
            '物理的受信時刻がない価格時計模型。分足公開を過去行へ巻き戻さない。',
            '過去33場内の後6場は既に過去研究で使ったデータ。追加4場も過去すべての未読を証明した完全未見ではない。',
            'モデルは学習21場の5分おきで先着が解決した行だけのbinary logistic。見込み45/55/65%は未決を含む全候補の到達確率に校正した値でも実測的中率でもない。評価では未決も分母に含める。',
            '相関する多数MAも独立した証拠の数ではない。',
            '実注文・手数料後収支は測っていない。平均1セッション10万円の達成を示すレポートではない。'])


# ----------------------------------------


def cell_text(cell: dict) -> str:
    """
    機能: 順先の分子・全候補分母・率を同時に表示する。
    引数: cell(dict) は一集計。
    返り値: str はHTMLへ入れる短い採点文字列。
    """
    return f"{cell['順先']}/{cell['n']}（{percentage(cell['全候補順先率'])}）"


def render(public: dict) -> str:
    """
    機能: 固定候補の要点と全44条件の37場を切り替えられるダークHTMLを作る。
    引数: public(dict) は検査済み非金融公開採点。
    返り値: str はネットワーク不要のHTML。数値選択や採点をJavaScriptへ委譲しない。
    """
    summaries = {item['id']: item for item in public['summaries']}
    specs = {item['id']: item for item in public['specifications']}
    selected = {item['id']: item for item in public['displayed']}
    primary = []
    bias_rows = []
    cards = []
    official = public['selection']['正式候補']
    improved = sum(summaries[identity]['periods']['別枠10']['対固定方向改善'] is not None and
                   summaries[identity]['periods']['別枠10']['対固定方向改善'] > 0 for identity in official)
    if official:
        conclusion = f'選択6場で固定した正式候補{len(official)}個のうち、別枠10場で同時点の固定買い・固定売りの両方を上回ったのは{improved}個。'
    else:
        conclusion = '選択6場の件数・活動・買売の資格を満たす正式候補はありません。以下は資格未達の比較参照です。'
    for item in public['displayed']:
        identity = item['id']
        summary = summaries[identity]
        hold = summary['periods']['別枠10']
        p = hold['主評価']
        total = p['全体']
        pending = total['窓末未決'] + total['EOF未決']
        delta = '—' if hold['対固定方向改善'] is None else f"{hold['対固定方向改善'] * 100:+.1f}pt"
        primary.append('<tr data-method="' + escape(identity) + '"><th><a href="#method-' + escape(identity) + '">' +
            escape(identity) + '</a><small>' + escape(item['status']) + '</small></th><td>' + cell_text(total) +
            f"</td><td>{total['逆先']}</td><td>{pending}<small>窓末{total['窓末未決']}／EOF{total['EOF未決']}</small></td>" +
            '<td>' + cell_text(p['常時買い']) + '</td><td>' + cell_text(p['常時売り']) + f'</td><td>{delta}</td>' +
            f"<td>{hold['活動場数']}/{hold['場数']}</td></tr>")
        for label, cell in (
            ('別枠デイ', summary['periods']['別枠デイ']['主評価']['全体']),
            ('別枠ナイト', summary['periods']['別枠ナイト']['主評価']['全体']),
            ('買い予兆', p['買い']), ('売り予兆', p['売り'])):
            bias_rows.append('<tr><th>' + escape(identity) + '</th><td>' + label + '</td><td>' + cell_text(cell) +
                f"</td><td>{cell['逆先']}</td><td>{cell['窓末未決'] + cell['EOF未決']}</td></tr>")
        period_rows = []
        for label in PERIODS:
            saved = summary['periods'][label]
            q = saved['主評価']
            total = q['全体']
            title = {'学習': '学習内21場', '選択': '選択6場', '時系列別枠': '既知の後6場',
                     '追加別枠': '追加4場', '別枠10': '別枠10場', '別枠デイ': '別枠のデイ',
                     '別枠ナイト': '別枠のナイト', '全37': '全37場（合算参考）'}[label]
            period_rows.append('<tr><th>' + title + '</th><td>' + cell_text(total) + f"</td><td>{total['逆先']}</td>" +
                f"<td>{total['窓末未決'] + total['EOF未決']}</td><td>{saved['活動場数']}/{saved['場数']}</td>" +
                '<td>' + cell_text(q['常時買い']) + '</td><td>' + cell_text(q['常時売り']) + '</td></tr>')
        width_rows = []
        for q in hold['risks']:
            total = q['全体']
            width_rows.append(f"<tr><th>順10pt／逆{number(q['逆行幅'])}pt</th><td>{cell_text(total)}</td><td>{total['逆先']}</td>" +
                f"<td>{total['窓末未決'] + total['EOF未決']}</td><td>{cell_text(q['常時買い'])}</td><td>{cell_text(q['常時売り'])}</td></tr>")
        example_rows = []
        for example in item['例']:
            label = example['labels'][1]
            result_text = '10pt先着' if label == 1 else '逆5pt先着' if label == -1 else '窓末未決' if label == 0 else 'EOF未決'
            if label == -1 and example['十pt到達秒'] is not None:
                result_text += '・後に10pt到達'
            example_rows.append('<tr><th>' + escape(example['session']) + '</th><td>' + ('買い' if example['方向'] == 1 else '売り') +
                '</td><td>' + at(example['公開秒']) + '</td><td>' + number(example['基準']) + '</td><td>' +
                at(example['十pt到達秒']) + '</td><td>' + result_text + '</td><td>' + number(example['十pt到達前MAE']) + '</td></tr>')
        cards.append('<section class="method" id="method-' + escape(identity) + '"><h2>' + escape(identity + '　' + specs[identity]['name']) +
            '</h2><p class="tag">' + escape(item['status']) + '</p><p>' + escape(item['思想']) + '</p>' +
            '<details><summary>具体的な入口条件</summary><p>' + escape(item['入口条件']) + '</p><p>' + escape(item['共通条件']) + '</p></details>' +
            '<div class="scroll"><table class="period-table"><thead><tr><th>評価期間</th><th>10対5 順先/全候補</th><th>逆先</th><th>未決</th><th>活動場</th><th>固定買い</th><th>固定売り</th></tr></thead><tbody>' +
            ''.join(period_rows) + '</tbody></table></div><details><summary>逆行許容2.5／5／10ptの比較（同じ別枠10場・同じ予兆）</summary><div class="scroll"><table class="width-table"><thead><tr><th>比較幅</th><th>順先/全候補</th><th>逆先</th><th>未決</th><th>固定買い</th><th>固定売り</th></tr></thead><tbody>' +
            ''.join(width_rows) + '</tbody></table></div></details><details><summary>実際の公開時刻と到達時刻</summary><p>別枠10場の時系列順で各区分の最初の例。失敗を後の到達で成功へ変更しません。逆先の時刻自体は未保存です。</p><div class="scroll"><table class="example-table"><thead><tr><th>セッション</th><th>方向</th><th>公開価格時計（日本時間）</th><th>起点Last</th><th>10pt到達時計</th><th>10対5の採点</th><th>到達前の最小signed値幅</th></tr></thead><tbody>' +
            (''.join(example_rows) or '<tr><td colspan="7">該当する公開例なし</td></tr>') + '</tbody></table></div></details></section>')
    all_rows = []
    for spec in public['specifications']:
        identity = spec['id']
        summary = summaries[identity]
        cells = []
        for period in ('学習', '選択', '時系列別枠', '追加別枠', '別枠10'):
            saved = summary['periods'][period]
            cells.append('<td>' + cell_text(saved['主評価']['全体']) + '</td>')
        status = selected[identity]['status'] if identity in selected else '正式表示対象外'
        all_rows.append('<tr><th><button class="method-link" data-id="' + escape(identity) + '">' + escape(identity) + '</button><small>' + escape(spec['family']) +
            '</small></th><td>' + escape(status) + '</td>' + ''.join(cells) + '</tr>')
    options = ''.join('<option value="' + escape(item['id']) + '">' + escape(item['id'] + '　' + item['name']) + '</option>' for item in public['specifications'])
    payload = json.dumps(public, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
    links = '<a href="README.md">読む順</a> · <a href="' + JSON_NAME + '">公開採点JSON</a> · <a href="../../work/topix10pt_20261016/試行計画.json">正式計画</a> · <a href="../../work/topix10pt_20261016/正式固定.json">固定指紋</a> · <a href="../../work/topix10pt_20261016/report.py">生成source</a> · <a href="../../work/direction_review_20261016/research118/十ポイント方向予測の十六仮説と過去試行との差.md">仮説・文献参考</a>'
    return '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TOPIX十ポイントの方向予兆</title><style>
:root{color-scheme:dark;--bg:#0c111b;--panel:#151e2c;--line:#34445c;--text:#e6edf6;--muted:#acb9cc;--accent:#86c7ff}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.7 system-ui,sans-serif}main{max-width:1450px;margin:auto;padding:28px 22px 70px}h1{font-size:27px;line-height:1.4;margin:8px 0 18px}h2{font-size:21px;margin:8px 0}h3{font-size:18px}a{color:var(--accent)}p{margin:9px 0 14px}small{display:block;color:var(--muted);font-size:12px}.lead,.method,.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:20px;margin:22px 0}.lead{border-left:4px solid var(--accent)}.muted,.note{color:var(--muted)}.tag{font-size:13px;color:#c6ddff}.scroll{overflow-x:auto;max-width:100%;margin:14px 0}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:10px 12px;text-align:right;vertical-align:top;white-space:nowrap}th:first-child,td:first-child{text-align:left}thead th{background:#1e2b40;color:#c3d9f5}tbody th{font-weight:500}tfoot td,tfoot th{background:#1c293b;font-weight:700}details{margin:14px 0}summary{cursor:pointer;color:#c3d9f5;padding:7px 0}select,button{font:inherit;background:#1c2c43;color:var(--text);border:1px solid #5c789a;border-radius:5px;padding:8px 12px}select{max-width:100%;margin:7px 10px 7px 0}button{cursor:pointer}.method-link{color:var(--accent);padding:2px 7px}.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.controls label{max-width:100%}.notice{padding:12px 15px;border-left:3px solid #e2bc6a;background:#211f24}.positive{color:#8cdfb5}.negative{color:#ffb4b4}nav{overflow-wrap:anywhere}.disclaimer li{margin-bottom:6px}@media(max-width:600px){main{padding:18px 12px 45px}h1{font-size:23px}.lead,.method,.panel{padding:14px}th,td{padding:9px 10px}select{font-size:13px;width:100%}}
</style></head><body><main><nav>''' + links + '''</nav><h1>TOPIX十ポイントの方向予兆</h1><p class="muted">損益ではなく、公開した方向へ10pt進む前に逆5ptへ触れたかを評価します。</p><div class="lead"><p id="conclusion">''' + escape(conclusion) + '''</p><p>中心に見るのは、候補を決めた後の別枠10場です。過去研究済みの後6場と追加4場も分けて掲載します。</p></div>
<h2>固定候補の別枠10場：順10pt／逆5pt</h2><p class="note">順先率＝順10pt先着数÷全予兆数。未決を分母から除きません。固定買い・固定売りは同じ公開時点の対照です。</p><div class="scroll"><table id="primary-table"><thead><tr><th>手法</th><th>順先/全予兆</th><th>逆先</th><th>未決</th><th>固定買い</th><th>固定売り</th><th>良い方との差</th><th>活動場</th></tr></thead><tbody>''' + (''.join(primary) or '<tr><td colspan="8">選択期に予兆のある比較参照もありません。</td></tr>') + '''</tbody></table></div>
<details id="direction-bias"><summary>別枠10場の昼夜・買売による偏り</summary><div class="scroll"><table id="bias-table"><thead><tr><th>手法</th><th>区分</th><th>順先/全予兆</th><th>逆先</th><th>未決</th></tr></thead><tbody>''' + ''.join(bias_rows) + '''</tbody></table></div><p>買売の各行は、その方向の予兆だけの内訳です。昼夜・買売は同じ予兆を分け直した表であり、別の独立標本ではありません。</p></details>
<p class="notice">この先着率は実取引の勝率ではありません。10ptに後から到達しても、先に逆5ptへ触れていれば逆先です。費用後の平均収支10万円は未評価です。</p>''' + ''.join(cards) + '''
<section class="panel" id="all-sessions"><h2>全37セッションの採点</h2><div class="controls"><label>手法 <select id="method-select">''' + options + '''</select></label><button id="reset" type="button">先頭候補に戻す</button></div><p id="selected-description"></p><p class="note">各行は10対5の先着。同じ幅の判定が終わるまで重複する予兆を除いています。行の率を単純平均した値ではありません。</p><div class="scroll"><table id="sessions-table"><thead><tr><th>セッション</th><th>区分</th><th>順先/全予兆</th><th>逆先</th><th>窓末未決</th><th>EOF未決</th><th>基準不可</th><th>買/売の予兆数</th></tr></thead><tbody id="session-body"></tbody><tfoot id="session-footer"></tfoot></table></div></section>
<details id="all-comparisons"><summary>全44条件の比較と選択用6場の成績</summary><p>元の定義順です。別枠成績の高い順に選び直していません。IDを押すと全37場を表示します。</p><div class="scroll"><table id="comparison-table"><thead><tr><th>ID/系統</th><th>表示区分</th><th>学習内21場</th><th>選択6場</th><th>既知の後6場</th><th>追加4場</th><th>別枠10場</th></tr></thead><tbody>''' + ''.join(all_rows) + '''</tbody></table></div></details>
<details id="limitations"><summary>採点の意味と限界</summary><ul class="disclaimer">''' + ''.join('<li>' + escape(note) + '</li>' for note in public['留保']) + '''</ul><p>仮説・文献参考の16系統は助言資料です。旧中値起点など今回未実装の案も含みます。実際の32規則・学習12条件は正式計画とこの採点JSONを参照してください。</p><p>成功/失敗例の時刻は価格時計です。保存されていない逆行先着時刻や注文時刻は推定していません。</p></details><nav>''' + links + '''</nav>
<script id="report-data" type="application/json">''' + payload + '''</script><script>
const D=JSON.parse(document.getElementById('report-data').textContent);
const selected=D.displayed.length?D.displayed[0].id:D.specifications[0].id;
const select=document.getElementById('method-select');
const rate=v=>v===null?'—':(100*v).toFixed(1)+'%';
const text=c=>c['順先']+'/'+c.n+'（'+rate(c['全候補順先率'])+'）';
const escapeText=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
/**
 * 機能: 保存した一手法の全37場だけを切り替えて表示する。
 * 引数: identity(string) は固定手法ID。
 * 返り値: undefined。率の再採点や候補の選び直しを行わない。
 */
function show(identity){
 const spec=D.specifications.find(v=>v.id===identity);
 const rows=D.rows.filter(v=>v.id===identity);
 const summary=D.summaries.find(v=>v.id===identity).periods['全37'];
 const group=s=>D.splits['学習'].includes(s)?'学習内':D.splits['選択'].includes(s)?'選択':D.splits['時系列別枠'].includes(s)?'既知の後6':'追加4';
 document.getElementById('selected-description').textContent=spec.name+'：'+(spec.condition||spec.description);
 document.getElementById('session-body').innerHTML=rows.map(r=>{const c=r.risks[1];return '<tr data-session="'+escapeText(r.session)+'"><th>'+escapeText(r.session)+'</th><td>'+group(r.session)+'</td><td>'+text(c)+'</td><td>'+c['逆先']+'</td><td>'+c['窓末未決']+'</td><td>'+c['EOF未決']+'</td><td>'+c['基準不可']+'</td><td>'+r['買い数']+'/'+r['売り数']+'</td></tr>'}).join('');
 const c=summary['主評価']['全体'];document.getElementById('session-footer').innerHTML='<tr><th>全37場合計</th><td>参考合算</td><td>'+text(c)+'</td><td>'+c['逆先']+'</td><td>'+c['窓末未決']+'</td><td>'+c['EOF未決']+'</td><td>'+c['基準不可']+'</td><td>'+summary['買い数']+'/'+summary['売り数']+'</td></tr>';
 select.value=identity;document.body.dataset.method=identity;
}
select.addEventListener('change',()=>show(select.value));
document.getElementById('reset').addEventListener('click',()=>show(selected));
document.querySelectorAll('.method-link').forEach(b=>b.addEventListener('click',()=>{show(b.dataset.id);document.getElementById('all-sessions').scrollIntoView({behavior:'smooth'})}));
show(selected);
</script></main></body></html>'''


def readme(public: dict) -> str:
    """
    機能: 最初のHTMLと再現資料の読む順を短いMarkdownへまとめる。
    引数: public(dict) は非金融公開採点。
    返り値: str はREADME本文。別枠を完全未見とは記述しない。
    """
    return f'''# TOPIX十ポイントの予兆

最初に [{HTML_NAME}]({HTML_NAME}) を開いてください。選択6場で固定した候補の別枠10場を先頭に、全37場と全44条件を切り替えられます。これは損益レポートではありません。

読む順：

1. HTMLの固定候補・別枠10場。順10pt／逆5ptの先着、未決、同時点固定方向との比較。
2. 同じHTMLの各候補説明と全37セッション。学習21／選択6／過去既知の後6／追加4を分離。
3. [公開採点JSON]({JSON_NAME})。率の分子分母と保存された選択ID。
4. [正式計画](../../work/topix10pt_20261016/試行計画.json)・[正式固定](../../work/topix10pt_20261016/正式固定.json)・[入力契約](../../work/topix10pt_20261016/入力契約の事前メタデータ.json)。
5. [入力の生成元と留保](../../work/topix10pt_20261016/価格現在値と気配の生成元の確認.md)・[実装と一回実測](../../work/topix10pt_20261016/run.py)・[表示生成](../../work/topix10pt_20261016/report.py)。

[仮説・文献参考](../../work/direction_review_20261016/research118/十ポイント方向予測の十六仮説と過去試行との差.md) は16系統の助言資料です。正式な32規則／学習12条件とは異なり、今回未実装の案も含みます。

観測Lastの先着であり、完全な約定テープ・実注文・手数料後利益ではありません。未決と無信号を成功に数えず、平均1セッション10万円を達成したとの意味もありません。過去既知の後6場、追加4場とも完全未見の証明はありません。

私有の[完成元結果](../../work/topix10pt_20261016/measurement/十ポイント予兆の結果.json)のSHA256：`{public['result']['SHA256']}`。元入力を読み直す再生ではなく、表示sourceへ指定SHAで一目的一読して生成します。正式source10本は変更しません。
'''


def synthetic() -> None:
    """
    機能: 未来成績で表示IDを変えないことと未決の表示だけを純合成で確認する。
    引数: なし。
    返り値: None。実結果・原入力・金融・APIを読まない。
    """
    sample = dict(正式候補=['A'], 比較参照=['B', 'A', 'C'])
    check(display_ids(sample) == ['A', 'B', 'C'], '保存選択IDの補充順')
    check(display_ids(dict(正式候補=[], 比較参照=['C', 'B', 'A'])) == ['C', 'B', 'A'], '資格不足時の保存参照順')
    check(percentage(None) == '—' and percentage(0.) == '0.0%', '率の未知と0')
    check(number(-0.) == '0' and at(None) == '—', '負の0と未保存時刻')
    cell = dict(順先=1, 逆先=2, 窓末未決=3, EOF未決=4, 基準不可=0, n=10, resolved=3,
                全候補順先率=.1, 解決内順先率=1 / 3, 解決率=.3)
    validate_cell(cell, '合成')
    check('1/10' in cell_text(cell), '未決を分母へ残す')
    try:
        validate_cell(dict(cell, 全候補順先率=1 / 3), '未決除外の誤率')
    except AssertionError:
        pass
    else:
        raise AssertionError('未決を分母から除く誤率を拒否しませんでした')
    result = synthetic_result()
    public = build(result, '0' * 64)
    html = render(public)
    check(len(public['rows']) == 44 * 37 and len(public['displayed']) == 3, '全schema合成')
    check(html.count('<option value=') == 44 and html.count('class="method"') == 3, '44切替と固定3章')
    check('別枠デイ' in html and '逆先後に到達' in json.dumps(public, ensure_ascii=False), '昼夜と後の到達を分離')
    changed = json.loads(json.dumps(result, ensure_ascii=False))
    changed['selection']['正式候補'] = []
    changed['selection']['比較参照'] = ['T03', 'T04', 'T05']
    for summary in changed['summaries']:
        if summary['id'] in changed['selection']['比較参照']:
            summary['periods']['選択']['活動場数'] = 3
    check(display_ids(changed['selection']) == ['T03', 'T04', 'T05'], '別枠成績を選定へ使わない')
    destination = HERE / 'report_prepare'
    destination.mkdir(exist_ok=True)
    (destination / '実データではない合成公開例.html').write_text(html, encoding='utf-8')
    proof = dict(全合格=True, 実結果読取=0, 元入力読取=0, 金融=0, API=0,
        report_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        schema=dict(候補=44, 場=37, 場行=44 * 37, 分離期間=8),
        scope='表示helperと全schema・HTML生成の純合成。金融/方向予測の有効性は未測。')
    path = destination / '表示の分母と保存選択及び全schemaの純人工.json'
    check(not path.exists(), '準備人工の上書き禁止')
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False))


def synthetic_result() -> dict:
    """
    機能: 実価格を使わず、44条件・37場・八期間を持つ表示専用schema素材を作る。
    引数: なし。
    返り値: dict は架空の採点結果。実データや実測結果と混ぜない。
    """
    sessions = [f'2026-01-{i // 2 + 1:02d}_' + ('Day' if i % 2 == 0 else 'Night') for i in range(37)]
    split = dict(学習=sessions[:21], 選択=sessions[21:27], 時系列別枠=sessions[27:33], 追加別枠=sessions[33:])
    hold = sessions[27:]
    periods = dict(split, 別枠10=hold, 別枠デイ=[s for s in hold if s.endswith('_Day')],
                   別枠ナイト=[s for s in hold if s.endswith('_Night')], 全37=sessions)
    specs = [dict(id=f'T{i:02d}', name='合成のみ' + str(i), family='合成系統' + str(i % 8), condition='合成専用条件') for i in range(32)]
    specs += [dict(id=f'L{i:02d}', name='合成学習' + str(i), family='学習', description='合成学習だけ', threshold=.45) for i in range(12)]

    def counted(labels: list[int]) -> dict:
        """
        機能: 合成ラベルから五状態の独立した表示素材を作る。
        引数: labels(list[int]) は架空ラベル。
        返り値: dict は件数と率。実観測を読まない。
        """
        result = {name: labels.count(code) for code, name in ((1, '順先'), (-1, '逆先'), (0, '窓末未決'), (2, 'EOF未決'), (-2, '基準不可'))}
        n = len(labels)
        resolved = result['順先'] + result['逆先']
        return dict(**result, n=n, resolved=resolved, 全候補順先率=result['順先'] / n if n else None,
                    解決内順先率=result['順先'] / resolved if resolved else None, 解決率=resolved / n if n else None)

    accounts = []
    for spec in specs:
        for si, session in enumerate(sessions):
            clock = 1767225600. + si * 86400
            records = [dict(bar_row=j, 公開原row=10 + j * 10, 公開秒=clock + j * 120, 確定分末=clock + j * 120 - 1,
                方向=1 if j == 0 else -1, 基準=4000., labels=labels, 終端原row=[11 + j * 10] * 3,
                十pt到達原row=15 + j * 10, 十pt到達秒=clock + j * 120 + 60, MFE=12., MAE=-6., 十pt到達前MAE=-5.5)
                for j, labels in enumerate(([1, 1, 1], [-1, -1, 1]))]
            risks = []
            for ri, risk in enumerate(RISKS):
                labels = [record['labels'][ri] for record in records]
                risks.append(dict(逆行幅=risk, **counted(labels), 買い=counted(labels[:1]), 売り=counted(labels[1:]),
                                  常時買い=counted([1, -1]), 常時売り=counted([-1, 1])))
            accounts.append(dict(id=spec['id'], session=session, family=spec['family'], name=spec['name'],
                公開候補数=2, 採用予兆数=2, 買い数=1, 売り数=1, risks=risks, records=records))
    summaries = []
    for spec in specs:
        aggregate = {}
        for label, included in periods.items():
            rows = [row for row in accounts if row['id'] == spec['id'] and row['session'] in included]
            risks = []
            for ri, risk in enumerate(RISKS):
                groups = {}
                for group in GROUPS:
                    values = [row['risks'][ri] if group == '全体' else row['risks'][ri][group] for row in rows]
                    totals = {key: sum(v[key] for v in values) for key in COUNTS}
                    n = sum(totals.values())
                    resolved = totals['順先'] + totals['逆先']
                    groups[group] = dict(**totals, n=n, resolved=resolved, 全候補順先率=totals['順先'] / n if n else None,
                        解決内順先率=totals['順先'] / resolved if resolved else None, 解決率=resolved / n if n else None)
                risks.append(dict(逆行幅=risk, **groups))
            rate = risks[1]['全体']['全候補順先率']
            aggregate[label] = dict(場数=len(rows), 活動場数=len(rows), 無信号場数=0, 予兆数=2 * len(rows),
                買い数=len(rows), 売り数=len(rows), 主評価=risks[1], risks=risks, 対固定方向改善=rate - .5 if rate is not None else None)
        summaries.append(dict(**spec, periods=aggregate))
    return dict(全合格=True, 金融=False, 試行='合成のみ', counts=dict(旧原NPZ=66, 新JSONL=8, 新金融=0, API=0),
        sessions=sessions, splits=split, periods=periods, specifications=specs, summaries=summaries, accounts=accounts,
        selection=dict(選択期='選択', 正式候補=['T00', 'T01', 'T02'], 比較参照=['T03', 'T04', 'T05'], 合格条件数=44), source_SHA256={})


def main() -> None:
    """
    機能: 許可SHAの結果だけを一回読み、parse前保全後に私有レポートを保存する。
    引数: CLIの--prepare又は--expected-sha(str)、任意--root-publish(bool)。
    返り値: None。未指定SHAや既処理の自動再読を拒否し、原入力・金融を実行しない。
    """
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--expected-sha')
    parser.add_argument('--root-publish', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        check(not args.expected_sha and not args.root_publish, 'prepareの読取禁止')
        synthetic()
        return
    check(isinstance(args.expected_sha, str) and len(args.expected_sha) == 64 and all(c in '0123456789abcdef' for c in args.expected_sha), 'root指定結果SHA必須')
    check(not READY.exists(), '自動再読の禁止')
    READY.mkdir(parents=True)
    evidence = dict(全合格=False, 実結果一目的読取=0, 元入力読取=0, 金融=0, API=0)
    try:
        payload = RESULT.read_bytes()
        evidence['実結果一目的読取'] = 1
        check(len(payload) <= 128 * 1024 * 1024, '指定結果だけの128MB上限')
        sha = hashlib.sha256(payload).hexdigest()
        check(sha == args.expected_sha, 'root指定同bytes')
        copy = READY / '完成元結果の同bytes保全.json'
        copy.write_bytes(payload)
        result = json.loads(payload.decode('utf-8'))
        import plan
        check(result['source_SHA256'] == plan.sources(), '完成元source10の不変')
        public = build(result, sha)
        html = render(public)
        files = {JSON_NAME: json.dumps(public, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                 HTML_NAME: html, 'README.md': readme(public)}
        outputs = {}
        for name, text in files.items():
            data = text.encode('utf-8')
            (READY / name).write_bytes(data)
            outputs[name] = dict(bytes=len(data), SHA256=hashlib.sha256(data).hexdigest())
        if args.root_publish:
            PUBLIC.mkdir(parents=True, exist_ok=True)
            for name in files:
                destination = PUBLIC / name
                check(not destination.exists(), '公開済ファイルの上書き禁止')
                destination.write_bytes((READY / name).read_bytes())
        evidence.update(全合格=True, result_SHA256=sha, source_SHA256=result['source_SHA256'],
            report_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), outputs=outputs,
            shown=[item['id'] for item in public['displayed']], selection=public['selection'],
            比較条件44=True, 場行数=len(public['rows']), 公開=args.root_publish,
            留保='採点の再集計と表示。新たな実測・独立有効性標本・金融ではない。画像QAは別担当。')
        manifest = HERE / '四十四条件と全三十七場の公開射影.json'
        check(not manifest.exists(), '公開射影目録の上書き禁止')
        directory = PUBLIC if args.root_publish else READY
        manifest.write_text(json.dumps(dict(全合格=True, 金融=False, 結果SHA256=sha,
            source_SHA256=result['source_SHA256'], report_SHA256=evidence['report_SHA256'],
            outputs=[dict(path=(directory / name).relative_to(ROOT).as_posix(), SHA256=outputs[name]['SHA256']) for name in files],
            selection=public['selection'], 場行数=len(public['rows']), 実結果一目的読取=1, 原入力=0, API=0),
            ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    except BaseException as error:
        evidence.update(全合格=False, error=repr(error))
        raise
    finally:
        (READY / '公開採点の一読確認と生成の証跡.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 公開=args.root_publish, 表示候補=evidence['shown'], 場行=evidence['場行数'], 実結果読取=1, 金融=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
