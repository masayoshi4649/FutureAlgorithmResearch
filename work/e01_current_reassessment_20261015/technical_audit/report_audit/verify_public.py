"""公開十比較だけから期間算術とHTML全セルを独立検算する。"""

from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import traceback
from urllib.parse import unquote

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CAPTURE = HERE / '公開同bytes保全'
ACCOUNT = '現在の活動と再進行の公開会計.json'
HTML = '現在の活動と再進行から参加する手法と全セッション損益.html'
PUBLIC = ROOT / 'アルゴリズム調査/00113_現在の注文活動と再進行から波の中間に参加'
PROOF = HERE / '公開十比較と全三十三場及び期間の独立算術と静的DOM.json'
SYMBOLS = ('TOPIX', 'NK225')
checks = 0


def check(condition: bool, detail: object) -> None:
    """
    機能: 独立条件の成立数を記録し、不成立なら根拠を保持して止める。
    引数: condition(bool)は検査結果、detail(object)は失敗時の根拠。
    返り値: None。
    """
    global checks
    checks += 1
    assert condition, detail


def same(actual: object, expected: object, detail: object) -> None:
    """
    機能: 未定義と零を区別して保存値を独立期待値へ照合する。
    引数: actual(object)、expected(object)、detail(object)は値と根拠。
    返り値: None。
    """
    if isinstance(actual, (int, float)) and not isinstance(actual, bool) and isinstance(expected, (int, float)) and not isinstance(expected, bool):
        check(math.isfinite(actual) and math.isfinite(expected) and math.isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-6), (detail, actual, expected))
    else:
        check(actual == expected and (actual is None) == (expected is None), (detail, actual, expected))


def total(rows: list[dict], key: str) -> float:
    """
    機能: 公開小会計の円額を十進数として合計する。
    引数: rows(list[dict])は各場、key(str)は対象欄。
    返り値: floatは独立合計。
    """
    return float(sum((Decimal(str(row[key])) for row in rows), Decimal(0)))


def metric(rows: list[dict], symbol: str) -> dict:
    """
    機能: 完結親の損益合計と全場分母から期間の主三基準と経済床を計算する。
    引数: rows(list[dict])は商品別場群、symbol(str)は商品。
    返り値: dictは保存値と独立に作った指標。
    """
    profit, loss, net = (total(rows, key) for key in ('profit', 'loss', 'net'))
    positive = [row['net'] for row in rows if row['net'] > 0]
    negative = [row['net'] for row in rows if row['net'] < 0]
    count = len(rows)
    ratio = profit / (profit + loss) if profit + loss else None
    black_mean = sum(positive) / len(positive) if positive else None
    worst = max((-value for value in negative), default=0)
    tests = dict(share65=ratio is not None and ratio >= .65,
                 red20=bool(count) and len(negative) / count <= .2,
                 coverage=black_mean is not None and worst <= black_mean)
    old_pass = all(tests.values())
    mean = net / count if count else None
    floor = 100000 if symbol == 'TOPIX' else None
    economic = mean is not None and mean >= floor if floor is not None else True
    campaigns = sum(row['campaigns'] for row in rows)
    value = dict(profit=profit, loss=loss, net=net, profit_share=ratio, sessions=count,
                 positive=len(positive), negative=len(negative), active=sum(row['campaigns'] > 0 for row in rows),
                 no_trade=sum(row['campaigns'] == 0 for row in rows), mean_session_net=mean,
                 mean_positive_session_net=black_mean, worst_session_loss=worst, pass_all=old_pass,
                 primary_pass=old_pass and economic, tests=tests, campaigns=campaigns,
                 winning_lots=sum(row['winning_lots'] for row in rows), losing_lots=sum(row['losing_lots'] for row in rows),
                 fees=total(rows, 'fees'), red_all=len(negative) / count if count else None,
                 mean_parent_net=net / campaigns if campaigns else None, economic_floor=floor, economic_pass=economic)
    multiplier = 10000 if symbol == 'TOPIX' else 200
    value.update(capacity_net_points=net / multiplier,
                 mean_parent_capacity_net_points=net / campaigns / multiplier if campaigns else None,
                 mean_session_capacity_net_points=mean / multiplier if mean is not None else None)
    for key in ('winning_campaigns', 'losing_campaigns'):
        if all(key in row for row in rows):
            value[key] = sum(row[key] for row in rows)
    return value


def money(value: float | None, signed: bool = True) -> str:
    """
    機能: HTMLの円額規則と同じ桁数で期待表示文字を作る。
    引数: value(float|None)は円額、signed(bool)は符号有無。
    返り値: strは期待文字。保存値の負の零も金額として零と同じに扱う。
    """
    return '未定義' if value is None else format(value, '+,.0f' if signed else ',.0f')


def percent(value: float | None) -> str:
    """
    機能: 金額利益割合の期待文字を作る。
    引数: value(float|None)は比率。
    返り値: strは百分率又は未定義。
    """
    return '未定義' if value is None else f'{value * 100:.1f}%'


def run() -> dict:
    """
    機能: 同bytes保全二資料だけを算術検査し、ブラウザへ渡す期待値を作る。
    引数: なし。
    返り値: dictは独立検算証跡。
    """
    manifest = json.loads((HERE / '公開一読と同bytes保全の目録.json').read_text(encoding='utf-8'))
    blobs = {name: (CAPTURE / name).read_bytes() for name in (ACCOUNT, HTML)}
    for name, raw in blobs.items():
        same(hashlib.sha256(raw).hexdigest(), manifest['成果物'][name]['SHA256'], ('保全同bytes', name))
    account = json.loads(blobs[ACCOUNT])
    source = blobs[HTML].decode('utf-8')
    soup = BeautifulSoup(source, 'html.parser')
    sessions, cases = account['sessions'], account['cases']
    same(len(sessions), 33, '全場分母')
    same(len(set(sessions)), 33, '唯一場')
    same(sum(value.endswith('_Day') for value in sessions), 17, 'デイ場数')
    same(sum(value.endswith('_Night') for value in sessions), 16, 'ナイト場数')
    same(set(account['未読追加場']), {'2026-10-13_Night', '2026-10-14_Day'}, '追加二場')
    check(not set(sessions) & set(account['未読追加場']), '追加場を零円で混ぜない')
    same(len(cases), 10, '十比較')
    same(sum(case['new_financial'] for case in cases.values()), 9, '新九')
    same(account['新金融口座'], 9 * 2 * 33, '新金融594')
    same(account['保存基準会計'], 66, '保存66')
    same(account['保存基準再金融'], 0, '保存再生なし')
    main = account['表示主候補']
    same(main, 'E01_CURRENT_VOL_PRICE_RESPONSE_WIDE_TRAIL', '結果前主候補')
    ids = [main] + [cid for cid in cases if cid != main]
    expected = dict(ids=ids, sections={}, overview=[], required=[], initial='c0')
    audit_summary = {}
    for cid, case in cases.items():
        rows = case['rows']
        same(len(rows), 66, (cid, '66会計'))
        same(len({(row['session'], row['symbol']) for row in rows}), 66, (cid, '唯一会計'))
        same(set(row['symbol'] for row in rows), set(SYMBOLS), (cid, '両商品'))
        for row in rows:
            identity = cid, row['session'], row['symbol']
            check(row['profit'] >= 0 and row['loss'] >= 0, (identity, '損失絶対値'))
            same(row['profit'] - row['loss'], row['net'], (identity, '損益恒等式'))
            for key in ('campaigns', 'winning_lots', 'losing_lots', 'fees'):
                check(row[key] >= 0 and int(row[key]) == row[key], (identity, key))
            if row['campaigns'] == 0:
                for key in ('profit', 'loss', 'net', 'fees', 'winning_lots', 'losing_lots'):
                    same(row[key], 0, (identity, '無取引', key))
            if case['new_financial']:
                cap, round_fee = (10, 836) if row['symbol'] == 'TOPIX' else (20, 440)
                same(row['fees'], row['campaigns'] * round_fee, (identity, '全量往復料の表示整合'))
                same(row['winning_lots'] + row['losing_lots'], cap * row['campaigns'], (identity, '全量完結親枚数'))
        audit_summary[cid] = {}
        for symbol in SYMBOLS:
            own = [row for row in rows if row['symbol'] == symbol]
            same({row['session'] for row in own}, set(sessions), (cid, symbol, '全場集合'))
            indexed = {row['session']: row for row in own}
            ordered = [indexed[session] for session in sessions]
            removed = sorted((row for row in own if row['net'] > 0), key=lambda row: (-row['net'], row['session']))[:3]
            removed_set = {row['session'] for row in removed}
            groups = dict(full=ordered, top3=[row for row in ordered if row['session'] not in removed_set],
                          day=[row for row in ordered if row['session'].endswith('_Day')],
                          night=[row for row in ordered if row['session'].endswith('_Night')],
                          first=ordered[:16], last=ordered[16:])
            for label, group in groups.items():
                reference = metric(group, symbol)
                saved = case['metrics'][symbol][label]
                for key, value in saved.items():
                    if key == 'removed_sessions':
                        same(value, [row['session'] for row in removed], (cid, symbol, label, key))
                    elif key == 'tests':
                        same(value, reference[key], (cid, symbol, label, key))
                    elif key in reference:
                        same(value, reference[key], (cid, symbol, label, key))
                    else:
                        raise AssertionError(('未検査の保存期間項目', cid, symbol, label, key))
            whole = metric(ordered, symbol)
            audit_summary[cid][symbol] = dict(net=whole['net'], mean=whole['mean_session_net'],
                positive=whole['positive'], negative=whole['negative'], no_trade=whole['no_trade'],
                profit_share=whole['profit_share'], primary_pass=whole['primary_pass'],
                経済床=100000 if symbol == 'TOPIX' else '未指定',
                除外場=[row['session'] for row in removed], 除外後分母=len(groups['top3']))
            directions = case['metrics'][symbol].get('directions')
            if directions is not None:
                for key, row_key in (('利益', 'profit'), ('損失', 'loss'), ('収支', 'net'), ('親数', 'campaigns')):
                    same(sum(value[key] for value in directions.values()), whole[row_key], (cid, symbol, '買売合計', key))
                for side, value in directions.items():
                    same(value['利益'] - value['損失'], value['収支'], (cid, symbol, side, '純損益'))
                    same(value['勝ち親'] + value['負け親'] + value['零親'], value['親数'], (cid, symbol, side, '親数'))
                    same(value['利益割合'], value['利益'] / (value['利益'] + value['損失']) if value['利益'] + value['損失'] else None, (cid, symbol, side, '金額割合'))
                    same(value['PF'], value['利益'] / value['損失'] if value['損失'] else None, (cid, symbol, side, 'PF'))
                    same(value['平均利益'], value['利益'] / value['勝ち親'] if value['勝ち親'] else None, (cid, symbol, side, '平均勝ち'))
                    same(value['平均損失'], value['損失'] / value['負け親'] if value['負け親'] else None, (cid, symbol, side, '平均負け'))
            if case['new_financial']:
                check(whole['net'] < 0, (cid, symbol, '新九は商品ごと合計赤字'))
                same(case['config']['target_session_mean_net_yen'][symbol], 100000 if symbol == 'TOPIX' else '円額目標の対象外（未指定）', (cid, symbol, '円額目標対象'))
    # ----------------------------------------
    same([option.get('value') for option in soup.select('#method option')], [f'c{index}' for index in range(10)], '全十selector')
    sections = soup.select('section.method')
    same(len(sections), 10, '十章')
    for index, cid in enumerate(ids):
        case, section = cases[cid], sections[index]
        sid = f'c{index}'
        same(section.get('id'), sid, (cid, '章ID'))
        same(section.has_attr('hidden'), index != 0, (cid, '初期hidden'))
        same(section.h2.get_text(), case['name'], (cid, '章名'))
        check(cid in section.get_text(), (cid, '表示ID'))
        lookup = {(row['session'], row['symbol']): row for row in case['rows']}
        body, footer = [], ['合計']
        for session in sessions:
            cells = [session.replace('_Day', ' デイ').replace('_Night', ' ナイト')]
            for symbol in SYMBOLS:
                row = lookup[session, symbol]
                cells.extend((money(row['profit'], False), money(row['loss'], False),
                    money(row['net']) + f"{row['campaigns']}親・利益{row['winning_lots']}枚／損失{row['losing_lots']}枚"))
            body.append(cells)
        for symbol in SYMBOLS:
            footer.extend(money(case['metrics'][symbol]['full'][key]) for key in ('profit', 'loss', 'net'))
        saved_body = [[cell.get_text() for cell in row.select('td')] for row in section.select('tbody tr')]
        same(len(saved_body), 33, (cid, '33行'))
        for actual, reference in zip(saved_body, body):
            for a, b in zip(actual, reference):
                same(a, b, (cid, '全場セル'))
            same(len(actual), 7, (cid, '全場列数'))
        same([cell.get_text() for cell in section.select('tfoot th')], footer, (cid, '合計セル'))
        trim = ' / '.join(label + ' ' + money(case['metrics'][symbol]['top3']['mean_session_net']) + '円/場・金額利益' + percent(case['metrics'][symbol]['top3']['profit_share']) for symbol, label in (('TOPIX', 'TOPIX'), ('NK225', '日経')))
        check(trim in section.get_text(), (cid, '除外後表示'))
        expected['sections'][sid] = dict(cid=cid, name=case['name'], body=body, footer=footer, trim=trim)
        for symbol, label in (('TOPIX', 'TOPIXミニ10枚'), ('NK225', '日経マイクロ20枚')):
            value = case['metrics'][symbol]['full']
            expected['overview'].append([case['name'], label, money(value['mean_session_net']) + '円', percent(value['profit_share']),
                f"{value['negative']}/{value['sessions']}", str(value['no_trade']), money(-value['worst_session_loss']) + '円',
                money(value['mean_positive_session_net']) + '円', '数式合格' if value['primary_pass'] else '未達'])
    overview = soup.select('details')[0]
    actual = [[cell.get_text() for cell in row.select('td')] for row in overview.select('tbody tr')]
    same(actual, expected['overview'], '20商品比較行')
    all_text = soup.get_text()
    for phrase in ('0/9新条件', '損失・無取引込み平均＋10万円/場', '金額利益65%以上', '赤字20%以下',
                   '最大赤字を平均黒字1場で補う', '追加2場は未測定', '損失欄は絶対値', '価格時計', 'ラージ気配', '事後診断'):
        check(phrase in all_text, ('必要留保', phrase))
        expected['required'].append(phrase)
    check('未見' not in all_text and 'holdout' not in all_text, '追加二場を正式未見と呼ばない')
    for link in soup.select('a[href]'):
        path = link['href']
        check(not path.startswith(('http:', 'https:')), ('外部通信リンクなし', path))
        check((PUBLIC / unquote(path.split('#')[0])).exists(), ('相対リンク存在', path))
    check(not soup.select('script[src],link[href],img[src]'), '外部依存なし')
    (HERE / '独立DOM期待値.json').write_text(json.dumps(expected, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return dict(全合格=True, 検査数=checks, 会計件数=660, 比較数=10, 新金融会計の表示=594, 保存会計の表示=66,
                公開SHA={name: hashlib.sha256(raw).hexdigest() for name, raw in blobs.items()}, 算術要約=audit_summary,
                表示範囲=dict(HTML=['全33場', '全場主基準一覧', '上位3黒字場除外の平均と割合'],
                    公開JSON追加=['前半16', '後半17', 'デイ17', 'ナイト16', '新9の方向別'],
                    留保='前半・後半・昼夜をHTML表示済みとは主張しない。日経円額床はconfigで未指定と明記、HTMLはTOPIXだけ円額目標を記す。'),
                未検査=['元金融会計と親経路の正否', 'HTML損失事例の価格時刻と実台帳の照合', '新追加2場の損益', '物理受信順・実商品の板待ち順位'],
                読取=dict(公開会計=1, 公開HTML=1, 元金融結果=0, 元入力=0, 実台帳=0, 新金融=0, API=0), 根目視=False)


def main() -> None:
    """
    機能: 初版の失敗も上書きせず、公開表示の独立監査を一回保存する。
    引数: なし。
    返り値: None。
    """
    assert not PROOF.exists()
    try:
        result = run()
    except Exception as error:
        result = dict(全合格=False, 検査数=checks, 理由=str(error), traceback=traceback.format_exc(),
                      元金融=0, 入力cache=0, 実台帳=0, 新金融=0, API=0)
        PROOF.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise
    result['監査source_SHA256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    PROOF.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査数=checks, 証跡=str(PROOF), SHA256=hashlib.sha256(PROOF.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
