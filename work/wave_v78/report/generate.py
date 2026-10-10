"""歴代の前提差と、二市場統合の保存済み会計を簡潔な暗色HTMLへまとめる。"""

import csv
from datetime import date, datetime, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
OUT = ROOT / 'アルゴリズム調査/00074_歴代手法の再評価と二市場統合'
MAIN = '過去の知見を統合した手法と全セッション損益.html'
ALL = '全162条件の比較.html'
SYMBOLS = ('TOPIX', 'NK225')
PERIODS = ('前16', '後14', '全30')
REASONS = {1: '初期損切り', 2: '追跡線・建値保護', 3: '保有期限', 4: '場内返済',
           6: '二市場の反対確認', 10: '共通方向の新規'}


def load(path: Path) -> object:
    """機能: 保存結果を読み取り、売買や通信を実行しない。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 入力又は公開物の内容指紋を求める。

    引数: path(Path)。返り値: SHA256(str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def save(path: Path, value: object) -> None:
    """機能: 担当報告領域へ有限JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE) or path.resolve().is_relative_to(OUT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def accountant() -> object:
    """機能: 固定済み会計関数だけを読み込む。

    引数: なし。返り値: 会計モジュール(object)。
    """
    spec = importlib.util.spec_from_file_location('表示会計78', WORK / 'accounting.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalized(a: dict) -> dict:
    """機能: 既存の指標名を表示用にそろえ、元の数値は保持する。

    引数: a(dict)。返り値: 表示指標(dict)。
    """
    return dict(a, positive_sessions=a.get('winning_sessions', int(a['net'] > 0)),
                negative_sessions=a.get('losing_sessions', int(a['net'] < 0)),
                no_trade_sessions=a.get('no_trade_sessions', int(a['trades'] == 0)))


def steps(c: dict) -> dict:
    """機能: 固定設定の入口・途中・出口を三文へ整理する。

    引数: c(dict)。返り値: 三段階の説明(dict[str,str])。
    """
    entry = '両指数が過去5分で同方向へ各0.03%以上進み、自分の直近15秒の両気配が1呼値進み、相手も逆行しなければ入る。'
    if c['entry'] in ('J1', 'J2'):
        entry += '明確な逆向きの注文増減は見送る。'
    if c['entry'] == 'J2':
        entry += '弱い側の5分進行量も強い側の25%以上を必要とする。'
    middle = '追加・両建てなし。最良価格から当場始値0.4%幅で追跡する。'
    if c['protect_fraction']:
        middle += f"追跡幅の{c['protect_fraction'] * 100:g}%順行後（目安{c['protect_fraction'] * .4:g}%）に手数料込み建値まで保護線を上げる。"
    if c['rest_mode']:
        middle += '2連敗後は30分休止し、共通方向が変わった状態を60秒確認するまで新規を待つ。'
    hold = ('30分', '30分から、利益・共同支持・順行極値更新が続く間は15分ずつ最大90分', '90分')[c['hold_mode']]
    exit_text = f'{hold}で全返済。追跡線に達した時又は場末も返済する。'
    if c['flow_mode']:
        exit_text += ('両市場の注文増減と距離加重板が反対へ15秒そろえば撤退。' if c['flow_mode'] == 1 else
                      '両市場の注文増減・距離加重板・実際の気配進行が反対へ15秒そろえば撤退。')
    return dict(entry=entry, middle=middle, exit=exit_text)


def brief(c: dict) -> str:
    """機能: 全条件一覧の固定設定を一行にする。

    引数: c(dict)。返り値: 設定説明(str)。
    """
    flow = ('反対撤退なし', '板の反対一致で撤退', '板と気配の反対一致で撤退')[c['flow_mode']]
    protection = f"追跡幅の{c['protect_fraction'] * 100:g}%順行で建値保護" if c['protect_fraction'] else '建値保護なし'
    hold = ('30分', '条件付き最大90分', '90分')[c['hold_mode']]
    rest = '2連敗で休止・再準備' if c['rest_mode'] else '連敗休止なし'
    return f"{c['entry']}／{flow}／{protection}／{hold}／{rest}。追跡幅0.4%・新規10枚/20枚。"


def minimal(result: dict) -> dict:
    """機能: 保存済みの場別・期間別会計を表示向けに整理する。

    引数: result(dict)。返り値: 表示条件(dict)。
    """
    return dict(id=result['config']['id'], config=result['config'], configText=brief(result['config']),
                rows=[normalized(a) for a in result['rows']],
                periods={p: {s: normalized(a) for s, a in v.items()} for p, v in result['periods'].items()})


def groups(rows: list, sessions: list, account: object) -> dict:
    """機能: 週・日夜・最大利益日除外を同商品の会計へ分ける。

    引数: rows/sessions(list)、account(object)。返り値: 商品別の表示集計(dict)。
    """
    weeks = {}
    for session in sessions:
        day = date.fromisoformat(session[:10])
        weeks.setdefault(str(day - timedelta(days=day.weekday())), []).append(session)
    output = {}
    for symbol in SYMBOLS:
        scopes = [(monday + '週', names) for monday, names in sorted(weeks.items())]
        scopes += [('デイ合計', [s for s in sessions if s.endswith('_Day')]),
                   ('ナイト合計', [s for s in sessions if s.endswith('_Night')])]
        all_a = account.aggregate(rows, symbol, sessions)
        best = all_a['best_day']
        scopes.append((f'最大利益日 {best} を除外', [s for s in sessions if s[:10] != best]))
        scopes.append(('全30合計', sessions))
        output[symbol] = [dict(normalized(account.aggregate(rows, symbol, names)), label=label) for label, names in scopes]
    return output


def bars(sessions: list) -> dict:
    """機能: 保存五分足を事後の売買図にだけ使用する。

    引数: sessions(list[str])。返り値: 場と商品別のOHLC(dict)。
    """
    output = {}
    for session in sessions:
        for symbol in SYMBOLS:
            path = ROOT / 'candle_5min' / symbol / (session + '.csv')
            with path.open(encoding='utf-8-sig', newline='') as stream:
                output[session + '|' + symbol] = [[datetime.fromisoformat(r['time']).timestamp(),
                    *[float(r[name]) for name in ('open', 'high', 'low', 'close')]] for r in csv.DictReader(stream)]
    return output


def attach(result: dict, ready: dict, sessions: list, account: object) -> dict:
    """機能: 原簿の全注文を時刻・料金・収支付きで添付する。

    引数: result/ready(dict)、sessions(list)、account(object)。返り値: 図と全会計を持つ表示条件(dict)。
    """
    identifier = result['config']['id']
    path = WORK / 'ledgers' / (identifier + '.pkl')
    assert digest(path) == result['ledger_SHA256']
    ledgers = load(path)
    orders = {}
    for key, ledger in ledgers.items():
        time = ready[key]['time_s']
        values = []
        source_orders, trades = ledger['orders'], ledger['trades']
        net = {int(cid): float(trades[trades[:, 0] == cid, 10].sum()) for cid in np.unique(trades[:, 0])}
        for o in source_orders:
            values.append(dict(time=float(time[int(o[0])]), decision=float(time[int(o[1])]),
                campaign=int(o[2]), side=int(o[3]), qty=int(o[4]), price=float(o[5]),
                reason=REASONS[int(o[6])], isNew=bool(o[7]), fee=float(o[8]),
                net=None if o[7] else net[int(o[2])]))
        assert abs(sum(v['net'] for v in values if v['net'] is not None) - float(trades[:, 10].sum())) < 1e-5
        assert all(o['decision'] <= o['time'] for o in values)
        orders['|'.join(key)] = values
    management = {}
    for symbol in SYMBOLS:
        rs = [r for r in result['rows'] if r['symbol'] == symbol]
        management[symbol] = dict(paused_sessions=sum(r['pauses'] > 0 for r in rs),
            pauses=sum(r['pauses'] for r in rs), skipped_entries=sum(r['skipped'] for r in rs),
            extensions=sum(r['extensions'] for r in rs))
    return dict(minimal(result), orders=orders, groups=groups(result['rows'], sessions, account), management=management)


def history_rows() -> list:
    """機能: 歴代十系統の採否と評価前提を簡潔に表示する。

    引数: なし。返り値: 系統別説明(list[dict])。
    """
    descriptions = [
        ('M3逆A00', '不採用', '共通下降を逆張り買いにして損切りを繰り返す。', '13場・費用0・指定価格', '00017_9月28日夜と29日昼の固定候補検証/README.md'),
        ('E01', '対照として保持', '長い波で稼ぐが、短い往復の連敗が増える。', '28場・費用あり・最後値全再運転', '00064_E01への回帰と知見を用いた改修/README.md'),
        ('R01', '入口の思想を採用', '新規時に両市場の方向条件を再確認し、古い判断で入らない。', '28場・費用あり・最後値全再運転', '00064_E01への回帰と知見を用いた改修/README.md'),
        ('R01の連敗休止', '部品を再検証', '連敗を減らす一方、後の回復も逃すため単独対照を残す。', '28場・費用あり・最後値全再運転', '00065_E01とR01の損失低減/README.md'),
        ('C02・即逆張り', '不採用', '最後値の黒字は売買気配差を加えると両市場で赤字。', '23場・費用0・固定注文の気配置換', '00049_価格形成の観測から新手法を構築/README.md'),
        ('C03・価格反転', '不採用', 'TOPIXで強く見えたが、気配置換で残余利益を失う。', '23場・費用0・固定注文の気配置換', '00049_価格形成の観測から新手法を構築/README.md'),
        ('支持抵抗・VWAP等', '共通本命は保留', '確認を待つ間に進み、入った後の値幅が不足した。', '23場・費用0・最後値', '00051_銘柄共通の境界反応とリスク効率/README.md'),
        ('ATRなし帯内復帰', '本命にしない', '平均勝ち幅は大きくても、負け回数と大勝ち依存が残る。', '23場・費用0・次行最後値', '00052_ATRを使わない単純手法/README.md'),
        ('補充監視', '今回の実装は不採用', '表示回復は持続的な吸収の証明にならず、中値でも赤字。', '23場・費用0・中値と気配を確認', '00055_補充監視が赤字になった原因/README.md'),
        ('グリッド・両建て', '利益源にしない', '全在庫損失と往復コストを含めると共通黒字が残らない。', '25場・費用あり・次気配／通過指値', '00058_場内完結の時間軸と積極度の再検証/README.md')]
    return [dict(name=name, status=status, reason=reason, assumption=assumption, url='../' + source)
            for name, status, reason, assumption, source in descriptions]


def render(template: str, data: dict, script: str, filename: str) -> None:
    """機能: 外部依存のない日本語暗色HTMLを生成する。

    引数: template/script/filename(str)、data(dict)。返り値: なし(None)。
    """
    value = (HERE / template).read_text(encoding='utf8')
    assert value.count('__DATA__') == 1
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':')).replace('<', '\\u003c')
    code = (HERE / 'common.js').read_text(encoding='utf8') + '\n' + (HERE / script).read_text(encoding='utf8')
    value = value.replace('__CSS__', (HERE / 'style.css').read_text(encoding='utf8')).replace('__DATA__', payload).replace('__SCRIPT__', code)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / filename).write_text(value, encoding='utf8')


def finding(result: dict) -> str:
    """機能: 後半の収支と大勝ち日依存を誇張せず一文にする。

    引数: result(dict)。返り値: 短い結果説明(str)。
    """
    values = result['periods']['後14']
    net = '／'.join(f"{values[s]['net']:+,.0f}円" for s in SYMBOLS)
    minus = '／'.join(f"{values[s]['without_best_day_net']:+,.0f}円" for s in SYMBOLS)
    return f'後14場の収支はTOPIX／日経の順で{net}。最大利益日を除くと{minus}。'


def parts_overview() -> list:
    """機能: 独立した部品分析からJ2の同条件差額を取り出す。

    引数: なし。返り値: 七部品の差額と短い解釈(list[dict])。
    """
    analysis = load(WORK / 'evidence/統合部品の効果と失敗.json')
    values = analysis['対照全会計']
    baseline = values['J2_F0_B0_H0_R0']['全30']
    descriptions = [
        ('J2_F1_B0_H0_R0', 'F1 板の反対一致で撤退', '変わったのは3組。後半TOPIXと遅延感度に弱く、置換は保留。'),
        ('J2_F2_B0_H0_R0', 'F2 板＋実気配の反対で撤退', '実際の返済変更0。今回の条件では作動せず未判定。'),
        ('J2_F0_B1_H0_R0', 'B1 幅の25%順行で建値保護', '同じトレール幅でも両商品の収支を削った。'),
        ('J2_F0_B2_H0_R0', 'B2 幅の50%順行で建値保護', '保護開始を遅らせても共通の改善にならなかった。'),
        ('J2_F0_B0_H1_R0', 'H1 条件付きで最大90分へ延長', '延長0回。今回の条件では作動せず未判定。'),
        ('J2_F0_B0_H2_R0', 'H2 保有期限を固定90分へ', 'TOPIX改善・日経悪化。最大下落は両方で拡大。'),
        ('J2_F0_B0_H0_R1', 'R1 2連敗後に休止・再準備', 'TOPIX改善・日経悪化で、共通の改善にはならない。')]
    return [dict(id=identifier, label=label, reason=reason,
                 difference={s: values[identifier]['全30'][s]['net'] - baseline[s]['net'] for s in SYMBOLS})
            for identifier, label, reason in descriptions]


def main() -> None:
    """機能: 保存162条件と固定代表だけから主報告・全条件比較を生成する。

    引数: なし。返り値: なし(None)。売買再計算・API取得は行わない。
    """
    fixed = load(WORK / '事前固定.json')
    selection = load(WORK / '前半選定.json')
    results = [load(p) for p in sorted((WORK / 'results').glob('*.json'))]
    assert len(results) == 162
    lookup = {r['config']['id']: r for r in results}
    account = accountant()
    metadata = load(ROOT / 'work/wave_v77/inputs/metadata.json')
    ready = {}
    for source in metadata['input_paths']['ready']:
        ready.update(load(ROOT / source))
    ready.update(load(ROOT / 'work/wave_v77/inputs/extra_inputs.pkl'))
    assert len(ready) == 60 and len(fixed['全30']) == 30
    all_values = {identifier: minimal(r) for identifier, r in lookup.items()}
    choices = {c['id']: c for c in selection['代表']}
    chosen = list(dict.fromkeys([selection['基準'], *choices]))
    methods = []
    for identifier in chosen:
        result = lookup[identifier]
        value = attach(result, ready, fixed['全30'], account)
        value['steps'] = steps(result['config'])
        value['finding'] = finding(result)
        is_primary = identifier == selection['主候補']
        value['title'] = ('従来J2・継続検証の本命' if identifier == selection['基準'] else result['config']['entry'] + 'の統合比較') + ('・前半選定、置換保留' if is_primary else '')
        if identifier == selection['基準']:
            value['finding'] = '新統合版への置換を保留し、継続検証の基準として残します。' + value['finding']
        if identifier in choices and not choices[identifier]['front_payoff_qualified']:
            value['finding'] = '前半の損小利大条件を満たさない比較代表。' + value['finding']
        control_ids = choices.get(identifier, {}).get('controls', [identifier])
        value['controls'] = [all_values[c] for c in control_ids]
        value['sensitivity'] = []
        for delay in (1, 5, 15):
            path = WORK / 'results' / (identifier + '.json') if delay == 5 else WORK / 'sensitivity' / f'delay{delay}' / 'results' / (identifier + '.json')
            current = load(path)
            assert current['config']['delay'] == delay
            for name in ('entry', 'flow_mode', 'protect_fraction', 'hold_mode', 'rest_mode'):
                assert current['config'][name] == result['config'][name]
            value['sensitivity'].append(dict(delay=delay, periods=minimal(current)['periods']))
        methods.append(value)
    # ----------------------------------------
    # 全場と週を同じ会計へ照合し、少数取引や無取引を達成扱いしない。
    checks = []
    for m in methods:
        for symbol in SYMBOLS:
            expected = m['periods']['全30'][symbol]
            rows = [r for r in m['rows'] if r['symbol'] == symbol]
            assert len(rows) == 30
            for field in ('profit', 'loss', 'net', 'fees', 'trades', 'winning_lots', 'losing_lots'):
                assert abs(sum(r[field] for r in rows) - expected[field]) < 1e-5
                assert abs(sum(a[field] for a in m['groups'][symbol][:3]) - expected[field]) < 1e-5
            assert abs(expected['profit'] - expected['loss'] - expected['net']) < 1e-5
            checks.append(dict(id=m['id'], symbol=symbol, 全30=expected, 全場週一致=True))
    counts = dict(両市場全場黒字=sum(all(r['periods']['全30'][s]['all_sessions_profitable'] for s in SYMBOLS) for r in results),
                  両市場金額80=sum(all(r['periods']['全30'][s]['goal80'] for s in SYMBOLS) for r in results))
    primary = lookup[selection['主候補']]
    conclusions = [
        '歴代から残った中核は、二市場の共通方向を選び、幅のあるトレーリングで利益を伸ばす方式です。',
        f"前16場で固定した主候補は {selection['主候補']}。" + finding(primary),
        f"今回の162条件で、全30場が両商品とも黒字の条件は{counts['両市場全場黒字']}、両商品の金額利益割合が80%以上の条件は{counts['両市場金額80']}でした。"]
    override = HERE / '結論文.json'
    if override.exists():
        conclusions = load(override)
        assert isinstance(conclusions, list) and all(isinstance(s, str) for s in conclusions)
    notes = [
        '全30場は過去の調査で既知。前16で代表を固定し後14を確認した時間順再評価であり、完全な未見検証ではありません。後半に合わせた代表の差替えはありません。',
        '日別・週別は保存セッションの開始日で集計し、日付を跨ぐナイトも開始日のデイと同じ日・週へ含めます。',
        '従来J2の後14場TOPIXは最大利益日除外で+1,576円にとどまり、黒字に十分な余裕があるとは言えません。前半で選ばれた統合J2は同指標−73,424円で、全30場合計の小改善だけでは置換を認めません。',
        '入口3×反対撤退3×建値保護3×期限3×休止2の162条件。初回はTOPIXミニ10枚・日経マイクロ20枚、追加・両建て・持越しなし。トレール幅は全条件で当場始値0.4%（最低2呼値、切上げ）に固定しました。',
        '平均勝ち／負けは手数料後の利益取引平均額÷損失取引平均額。全取引が同じ枚数で全返済するため今回は組と建値明細が一致します。黒字場の割合、取引勝率、金額利益割合、平均勝ち負け比は別の尺度です。',
        '判断後の次の有効ラージ気配で買ask・売bid約定。ミニ／マイクロ実板や全数量の実約定を証明しません。片道枚手数料はTOPIX41.8円、日経11円を注文合計で切捨て、両商品円額を合算しません。',
        '5秒判断格子、情報遅延5秒、鮮度30秒。最終約定時刻を代理時計とし、同時刻先頭の厳密過去情報を使用。感度は同じ固定条件の1／5／15秒で、都合の良い遅延へ切り替えていません。',
        '逆向き注文増減は最良気配のOFI。二市場の強反対は15秒OFIと距離加重板を組み合わせて15秒確認し、F2だけ双方の30秒両気配1呼値逆行も要求します。確認中は両市場の参照行更新が必要です。',
        '条件付き延長は期限時点の料金後含み益、共通300秒方向と短期30秒方向の維持、過去5分内の最良価格更新、新鮮な参照格子を要求。15分ずつ最大90分へ伸ばします。未来の高値で延長可否を判断しません。',
        '2連敗休止は30分経過後、共通300秒方向が最後の負け方向以外（有効な中立も含む）を60秒確認して再準備します。再準備後の通常入口でだけ再開。セッションを跨いで連敗は引き継ぎません。',
        '利益保護線は更新の次原本行から有効です。建値保護は保証価格ではなく、次気配が飛べば料金後損失になり得ます。15:34／05:49から場内全返済を判断し、次有効気配で約定するため欠測時は遅れます。',
        '五分足は売買位置を説明する事後図です。旧E01/R01は28場・最後値全再運転と固定注文の気配置換であり、今回の次気配再運転と直接の円順位にはできません。',
        '部品対照は同じ入口・幅・枚数を保つ比較ですが、早い返済や休止により後続の採用入口も変わります。単に同じ注文価格だけを置換した比較ではありません。']
    part_notes = [
        '以下の短い結論はJ2に部品を単独追加した対照。反対板で返すF1は全30場でTOPIX+5万円・日経+8千円改善したが、変更は3組だけ。後14場TOPIXは7.5万円悪化しました。',
        'F1の追加効果は情報遅延1秒でTOPIX+3万円・日経−2千円、15秒で−1.5万円・+8千円。共通の安定改善とは判断しません。',
        '今回、0.4%の追跡幅を保ったまま建値保護だけを比較しても、B1・B2は両商品の全30場収支を削りました。',
        '固定90分H2と2連敗休止R1はいずれもTOPIX改善・日経悪化で、両商品共通の改善にはなりませんでした。',
        '板と実気配の反対を求めるF2はJ2基準からの返済変更0、条件付き延長H1は延長0回。今回の条件では作動せず、能力の評価は未判定です。']
    directions = load(WORK / 'evidence/相場方向別の事後診断.json')
    direction_rows = [dict(label=label, sessions=value['場数'],
                           net={s: value['商品別'][s]['収支'] for s in SYMBOLS})
                      for label, value in directions['群別会計']['全30'].items() if value['場数']]
    assert sum(v['sessions'] for v in direction_rows) == 30
    for symbol in SYMBOLS:
        assert sum(v['net'][symbol] for v in direction_rows) == methods[0]['periods']['全30'][symbol]['net']
    data = dict(title='過去の知見を統合した手法と全セッション損益', sessions=fixed['全30'], periodNames=list(PERIODS),
                benchmark=methods[0], methods=methods[1:], bars=bars(fixed['全30']), history=history_rows(),
                conclusions=conclusions, notes=notes, partNotes=part_notes, partsOverview=parts_overview(),
                directionRows=direction_rows, allUrl=ALL, selection=selection, counts=counts)
    all_data = dict(sessions=fixed['全30'], periodNames=list(PERIODS), methods=list(all_values.values()),
                    selectedIds=list(choices), baselineId=selection['基準'], mainUrl=MAIN)
    render('main_template.html', data, 'main.js', MAIN)
    render('all_template.html', all_data, 'all.js', ALL)
    save(HERE / '主レポートデータ.json', data)
    save(OUT / '公開会計.json', dict(表示集計一致=True, 条件数=162, 場数=30, 代表数=len(choices),
        今回未見場数=0, 選定=selection, 条件数集計=counts, 会計=checks,
        公開SHA256={name: digest(OUT / name) for name in (MAIN, ALL)},
        入力SHA256={str(p.relative_to(ROOT)): digest(p) for p in (WORK / '事前固定.json', WORK / '前半選定.json', WORK / 'evidence/歴代主力の再評価.json', WORK / 'evidence/統合部品の効果と失敗.json', WORK / 'evidence/相場方向別の事後診断.json')},
        API取得=0, 実注文=0))
    print('歴代十系統、固定代表と全162条件の暗色HTMLを生成しました', flush=True)


if __name__ == '__main__':
    main()
