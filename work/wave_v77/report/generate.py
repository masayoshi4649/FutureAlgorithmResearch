"""金額利益割合と組勝率を分け、固定した三代表・配分対照・未見一場を報告する。"""

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
OUT = ROOT / 'アルゴリズム調査/00073_二市場判断と金額利益8割への改善'
MAIN = '金額利益8割を目指す改善と全セッション損益.html'
ALL = '全492条件の比較.html'
SYMBOLS = ('TOPIX', 'NK225')
PERIODS = ('前16', '後13', '全29', '追加1', '全30')
TITLES = {'J': '共同方向を確認して入る', 'Q': '最良板の偏りを確認して入る', 'P': '共同方向の小反落後に入る'}
REASONS = {1: '初期損切り', 2: '利益保護・トレーリング', 3: '保有時間上限', 4: '場内全返済',
           6: '二市場の反対合意', 8: '構造幅・追加後の損失枠超過', 9: '進展不足と支持不足',
           10: '最初の新規', 11: '順行後の追加'}


def load(path: Path) -> object:
    """機能: 結果・台帳・固定資料を読み取る。

    引数: path(Path)。返り値: 保存内容(object)。読取元は変更しない。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 公開物又は会計証拠の内容指紋を求める。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def save(path: Path, value: object) -> None:
    """機能: 担当する報告領域だけへ日本語JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE) or path.resolve().is_relative_to(OUT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def account_module() -> object:
    """機能: 凍結済み会計関数をキャッシュ書込なしで読み込む。

    引数: なし。返り値: 会計モジュール(object)。再生器は呼び出さない。
    """
    spec = importlib.util.spec_from_file_location('報告会計77', WORK / 'accounting.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def manager(c: dict) -> str:
    """機能: 損切りと利益保護の方式を短く説明する。

    引数: c(dict)。返り値: 方式名(str)。
    """
    return ('P0 従来トレール', 'P1 損切りと追従を分離', 'P2 早めの費用込み建値保護',
            'P3 順行後に利益固定・幅半減', 'P4 直前高安で初期損切り', 'P5 進展不足で撤退')[c['policy']]


def brief(c: dict) -> str:
    """機能: 固定した入口・保護・幅・期限・配分を一行へ整理する。

    引数: c(dict)。返り値: 設定説明(str)。
    """
    allocation = 'A0 全量新規' if c['allocation'] == 0 else 'A1 2→5→10枚／4→10→20枚'
    return f"{c['entry']}／{manager(c)}／初期{c['stop_bp']/100:g}%・追従{c['trail_bp']/100:g}%／{c['hold_minutes']}分／{allocation}"


def steps(c: dict) -> dict:
    """機能: 入口・途中・出口を実装に沿って短い三文へ整理する。

    引数: c(dict)。返り値: 三段階の説明(dict[str,str])。
    """
    entries = {
        'J0': '両指数が300秒で同方向へ0.03%以上進み、自分の15秒両気配が1呼値進み、相手も逆行していなければ入る。',
        'J1': '従来J1入口を使い、どちらかの15秒注文増減に明確な逆行があれば入らない。',
        'J2': '従来J1入口に加え、二市場の300秒進行量が同方向かつ弱い側も強い側の25%以上、明確な逆15秒注文増減なしを確認して入る。',
        'J3': 'J2の足並みに加え、両市場の300秒純移動が総変動の20%以上なら入る。',
        'Q0': '両指数の最良一段買売数量の偏りが同方向へ25%以上の状態を、双方の更新を伴って10秒確認して入る。',
        'Q1': '両指数の最良一段買売数量が同方向へ25%以上偏る状態を10秒確認し、明確な逆15秒注文増減がなければ入る。',
        'Q2': '最良一段数量の同方向25%以上・10秒確認に加え、両市場の180秒価格進行が同方向へ各0.01%以上なら入る。',
        'Q3': 'Q2の180秒価格支持に加え、どちらにも明確な逆15秒注文増減がなければ入る。',
        'P0': '両市場の300秒共同方向を保った30秒の小反落後、両市場の再進行と両気配1呼値進行を10秒確認して入る。',
        'P1': '両市場の300秒共同方向を保った30秒の小反落後、両気配の再進行を10秒確認し、明確な逆15秒注文増減がなければ入る。',
        'P2': '両市場の300秒共同方向を保った60秒の小反落後、両市場の再進行と両気配1呼値進行を10秒確認して入る。',
        'P3': '両市場の300秒共同方向を保った60秒の小反落後、再進行を10秒確認し、明確な逆15秒注文増減がなければ入る。'
    }
    entry = entries[c['entry']]
    protection = ('実建値から即時に全量トレールを追従させる。',
                  '初期損切りを維持し、1R順行後に別幅のトレールを追従させる。',
                  '0.5R順行後に費用込み建値を保護し、同幅のトレールを追従させる。',
                  '1R順行後に追従し、2R順行後は幅半減と最低1Rの利益保護を行う。',
                  '観測済み180秒高安で初期損切りを決め、1R順行後に別幅で追従する。',
                  '1R順行後の追従に加え、5分経過しても0.5R未達で共同支持不足が30秒続けば撤退する。')[c['policy']]
    allocation = ('最初から上限10枚／20枚を持つ。' if c['allocation'] == 0 else
                  '2枚／4枚から始め、0.5R・1R順行と共同支持を確認し、全玉の損失枠を守れる時だけ計10枚／20枚まで追加する。')
    middle = allocation + protection
    exit_ = f"初期損切り・利益保護又は{c['hold_minutes']}分期限で全返済。"
    if c['policy']:
        exit_ += '二市場の30秒進行と15秒OFIが反対に30秒揃った時も全返済。'
    exit_ += '場末は全返済を判断し、判断後の次有効気配で約定する。'
    return dict(entry=entry, middle=middle, exit=exit_)


def minimal(result: dict) -> dict:
    """機能: 金額会計と組会計の両方を表示用に保持する。

    引数: result(dict)。返り値: 一条件の表示資料(dict)。
    """
    c = result['config']
    return dict(id=c['id'], config=c, configText=brief(c), rows=result['rows'], periods=result['periods'])


def combined(result: dict, fixed: dict, accounting: object) -> dict:
    """機能: 固定対象だけの未見一場を既往29場へ接続する。

    引数: result/fixed(dict)、accounting(object)。返り値: 結合結果(dict)。未実施は補完しない。
    """
    extra_path = WORK / 'unseen/results' / (result['config']['id'] + '.json')
    r = dict(result, rows=list(result['rows']), periods=dict(result['periods']))
    if extra_path.exists():
        extra = load(extra_path)
        for k in ('entry', 'policy', 'stop_bp', 'trail_bp', 'hold_minutes', 'allocation', 'cooldown', 'delay'):
            assert result['config'][k] == extra['config'][k]
        r['rows'] += extra['rows']
        r['periods'].update(extra['periods'])
        r['periods']['全30'] = {s: accounting.aggregate(r['rows'], s, fixed['全30']) for s in SYMBOLS}
        r['extraLedgerSHA'] = extra['ledger_SHA256']
    return r


def weeks(rows: list[dict], sessions: list[str], accounting: object) -> dict:
    """機能: 同じ商品だけを保存場日付の週へ集計する。

    引数: rows(list[dict])、sessions(list[str])、accounting(object)。返り値: 商品別週合計(dict)。
    """
    groups = {}
    for session in sessions:
        d = date.fromisoformat(session[:10])
        groups.setdefault(d - timedelta(days=d.weekday()), []).append(session)
    return {s: [dict(accounting.aggregate(rows, s, scope), label=f'{monday:%m/%d}週（{len(scope)}場）')
                for monday, scope in sorted(groups.items())] for s in SYMBOLS}


def bars(sessions: list[str]) -> dict:
    """機能: 保存五分足を図解専用の五列へ変換する。

    引数: sessions(list[str])。返り値: 場・商品別の足(dict)。売買判断には使用しない。
    """
    output = {}
    for session in sessions:
        for symbol in SYMBOLS:
            path = ROOT / 'candle_5min' / symbol / (session + '.csv')
            if not path.exists():
                output[session + '|' + symbol] = []
                continue
            with path.open(encoding='utf-8-sig', newline='') as stream:
                output[session + '|' + symbol] = [[datetime.fromisoformat(r['time']).timestamp(),
                    *[float(r[n]) for n in ('open', 'high', 'low', 'close')]] for r in csv.DictReader(stream)]
    return output


def attach(result: dict, ready: dict, fixed: dict, accounting: object) -> dict:
    """機能: 全注文・全追加玉・料金・時刻を台帳から添付する。

    引数: result/ready/fixed(dict)、accounting(object)。返り値: 売買図付き一条件(dict)。
    """
    ident = result['config']['id']
    path = WORK / 'ledgers' / (ident + '.pkl')
    assert digest(path) == result['ledger_SHA256']
    archive = load(path)
    extra = WORK / 'unseen/ledgers' / (ident + '.pkl')
    if '追加1' in result['periods']:
        assert digest(extra) == result['extraLedgerSHA']
        archive.update(load(extra))
    orders, decisions, nets, parts, exits = {}, {}, {}, {}, {}
    for key, item in archive.items():
        name = '|'.join(key)
        times = ready[key]['time_s']
        o, t = item['orders'], item['trades']
        orders[name] = [list(row) + [0, float(times[int(row[0])])] for row in o]
        decisions[name] = [float(times[int(row[1])]) for row in o]
        net_by_campaign = {int(cid): float(t[t[:, 0] == cid, 10].sum()) for cid in np.unique(t[:, 0])}
        nets[name] = [None if row[7] else net_by_campaign[int(row[2])] for row in o]
        assert len(o[o[:, 7] == 1]) == len(t)
        assert abs(sum(v for v in nets[name] if v is not None) - float(t[:, 10].sum())) < 1e-5
    # ----------------------------------------
    # 同じ一組の追加玉でも建値別損益を相殺せず、表と理由別集計に残す。
    for period in PERIODS:
        if period not in result['periods']:
            continue
        parts[period], exits[period] = {}, {}
        for symbol in SYMBOLS:
            chunks = [v['trades'] for k, v in archive.items() if k[1] == symbol and k[0] in fixed[period]]
            trades = np.concatenate(chunks) if chunks else np.empty((0, 12))
            groups = []
            for stage in range(3):
                subset = trades[trades[:, 11] == stage]
                net = subset[:, 10]
                groups.append(dict(stage=stage, legs=len(subset), profit=float(net[net > 0].sum()),
                    loss=float(-net[net < 0].sum()), net=float(net.sum()), lots=int(subset[:, 4].sum())))
            parts[period][symbol] = groups
            reasons = {str(code): dict(profit=0., loss=0., net=0., trades=0) for code in REASONS if code < 10}
            for key, item in archive.items():
                if key[1] != symbol or key[0] not in fixed[period]:
                    continue
                t = item['trades']
                for close in item['orders'][item['orders'][:, 7] == 0]:
                    a = reasons[str(int(close[6]))]
                    net = t[t[:, 0] == close[2], 10]
                    a['profit'] += float(net[net > 0].sum())
                    a['loss'] += float(-net[net < 0].sum())
                    a['net'] += float(net.sum())
                    a['trades'] += 1
            exits[period][symbol] = reasons
            expected = result['periods'][period][symbol]
            for field in ('profit', 'loss', 'net'):
                assert abs(sum(v[field] for v in groups) - expected[field]) < 1e-5
                assert abs(sum(v[field] for v in reasons.values()) - expected[field]) < 1e-5
    return dict(minimal(result), weeks=weeks(result['rows'], fixed['全30'], accounting), orders=orders,
        decisionTimes=decisions, orderNet=nets, parts=parts, exitReasons=exits)


def render(template: str, data: dict, filename: str) -> None:
    """機能: 一箇所の固定JSONを暗色HTMLへ埋め込む。

    引数: template/filename(str)、data(dict)。返り値: なし(None)。
    """
    text = (HERE / template).read_text(encoding='utf8')
    assert text.count('__DATA__') == 1
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
    script = HERE / ('main.js' if template == 'main_template.html' else 'all.js')
    text = text.replace('__CSS__', (HERE / 'style.css').read_text(encoding='utf8'))
    text = text.replace('__SCRIPT__', script.read_text(encoding='utf8'))
    (OUT / filename).write_text(text.replace('__DATA__', payload), encoding='utf8')


def conclusions(analysis: dict, methods: list[dict], benchmark: dict) -> list[str]:
    """機能: 前半固定の三代表から目標の達否を短く説明する。

    引数: analysis/benchmark(dict)、methods(list[dict])。返り値: 結論文列(list[str])。
    """
    count = analysis['金額80条件数']['全29']['全492内両商品80達成']
    text = [f'金額利益80%の目標は未達です。既往全29場では492条件中、両商品とも80%以上となる条件は{count}件でした。']
    j = next(m for m in methods if m['config']['family'] == 'J')
    a, b = j['periods']['全30'], benchmark['periods']['全30']
    text.append(f"検証継続候補は{j['config']['entry']}。全30はTOPIX{a['TOPIX']['net']:+,.0f}円・金額利益割合{a['TOPIX']['profit_share']*100:.2f}%／日経{a['NK225']['net']:+,.0f}円・{a['NK225']['profit_share']*100:.2f}%。同じ従来出口のまま入口を絞ると、基準比はTOPIX{a['TOPIX']['net']-b['TOPIX']['net']:+,.0f}円／日経{a['NK225']['net']-b['NK225']['net']:+,.0f}円でした。")
    text.append('最良板Q代表は両商品で赤字、小反落後P代表は取引数不足です。今回の三代表では追加条件の成立は0回で、段階追加による成功を確認できていません。')
    new = j['periods']['追加1']
    text.append(f"固定後の追加ナイトは{j['config']['entry']}のTOPIX1組{new['TOPIX']['net']:+,.0f}円、日経は無取引。前29場は既知資料で、新しい一場だけでは安定性を認定できません。")
    return text


def main() -> None:
    """機能: 全結果・固定感度・未見確認・分析の完成後に報告を生成する。

    引数: なし。返り値: なし(None)。結果を見て代表又は条件を変更しない。
    """
    fixed = load(WORK / '事前固定.json')
    selection = load(WORK / '前半選定.json')
    assert selection['前16だけで選択']
    assert load(WORK / '未見確認完了.json')['合格']
    assert load(WORK / '旧J1の完全一致.json')['合格']
    analysis_path = WORK / 'analysis/改善と反証の整理.json'
    analysis = load(analysis_path)
    diagnostic_path = WORK / 'diagnostics/改善機構の対照分析.json'
    diagnostic = load(diagnostic_path)
    assert not diagnostic['前半代表選定を変更'] and not diagnostic['新条件追加']
    accounting = account_module()
    raw = [load(p) for p in sorted((WORK / 'results').glob('*.json'))]
    assert len(raw) == 492
    lookup = {r['config']['id']: combined(r, fixed, accounting) for r in raw}
    metadata = load(WORK / 'inputs/metadata.json')
    ready = {}
    for path in metadata['input_paths']['ready']:
        ready.update(load(ROOT / path))
    ready.update(load(WORK / 'inputs/extra_inputs.pkl'))
    attached = {}

    def get(ident: str) -> dict:
        """機能: 台帳添付を同じIDで重複させず再利用する。

        引数: ident(str)。返り値: 台帳付き表示条件(dict)。
        """
        if ident not in attached:
            attached[ident] = attach(lookup[ident], ready, fixed, accounting)
        return attached[ident]

    def sensitivity(ident: str) -> list[dict]:
        """機能: 同じ固定条件の情報遅延三水準を接続する。

        引数: ident(str)。返り値: 感度会計列(list[dict])。追加未見場を混ぜない。
        """
        values = []
        for delay in (1, 5, 15):
            base = WORK if delay == 5 else WORK / 'sensitivity' / f'delay{delay}'
            r = load(base / 'results' / (ident + '.json'))
            assert r['config']['delay'] == delay
            for field in ('entry', 'policy', 'stop_bp', 'trail_bp', 'hold_minutes', 'allocation', 'cooldown'):
                assert r['config'][field] == lookup[ident]['config'][field]
            values.append(dict(delay=delay, periods=r['periods']))
        return values

    benchmark = dict(get(selection['基準']), title='従来J1・全量トレール', sensitivity=sensitivity(selection['基準']))
    analyzed = {r['id']: r for r in analysis['代表']}
    methods = []
    for choice in selection['代表']:
        ident = choice['id']
        c, a = lookup[ident]['config'], analyzed[ident]
        method = dict(get(ident), title=TITLES[c['family']], steps=steps(c), eligible=choice['eligible'],
            recognition=a['認定'], controls=[get(cid) for cid in choice['controls']], sensitivity=sensitivity(ident),
            finding='', analysis=a)
        method['finding'] = ('前16の必要活動条件を満たした比較代表です。' if choice['eligible'] else '前16の活動件数不足で有望認定しません。') + f"後13の判定：{a['認定']}。"
        if c['allocation'] == 1:
            assert all(method['periods']['全30'][s]['adds'] == 0 for s in SYMBOLS)
            method['finding'] += '実際は初回TOPIX2枚／日経4枚のみで、追加条件は成立しませんでした。'
        if c['entry'] == 'J2':
            method['finding'] += '出口は改修案ではなく従来の0.4%トレール・30分期限です。日経は改善しましたが、TOPIXの金額利益割合はほぼ不変で収支は減りました。'
        methods.append(method)
    # ----------------------------------------
    # 公開する全場・週・建値明細は同じ期間合計へ一致させる。
    checks = []
    for value in attached.values():
        assert '全30' in value['periods']
        for symbol in SYMBOLS:
            a = value['periods']['全30'][symbol]
            for field in ('profit', 'loss', 'net', 'fees', 'trades', 'winning_lots', 'losing_lots'):
                assert abs(sum(r[field] for r in value['rows'] if r['symbol'] == symbol) - a[field]) < 1e-5
                assert abs(sum(r[field] for r in value['weeks'][symbol]) - a[field]) < 1e-5
            assert abs(a['profit'] - a['loss'] - a['net']) < 1e-5
            checks.append(dict(id=value['id'], symbol=symbol, 全30=a, 全場週建値別理由一致=True))
    notes = [
        '金額利益割合＝手数料後の建値明細利益÷（建値明細利益＋損失）。80%以上は利益:損失4:1以上。組勝率は初回から全返済までの一組で別計算します。追加玉の損失も省きません。',
        '492条件を事前固定。前16だけで入口三群から各一代表を選択し、後13で変更しません。前29は既知資料です。追加2026-10-09ナイトは固定された代表・対照・基準だけを一度確認しました。',
        '前16は両商品20組・8活動場以上、後13は10組・5活動場以上が必要です。無取引は利益80%達成に数えません。追加一場の勝敗だけで安定性を認定しません。',
        'P0基準は返済後30秒、P1〜5は300秒の再入場待機を持ちます。基準との差には入口・幅・再入場機会も含み、利益保護だけの因果効果ではありません。同じ入口・初期幅・期限のP1〜5×A0/A1を別表で比較します。',
        '共通5秒判断格子、主の情報遅延5秒、鮮度30秒。最終約定代理時計で厳密過去の同時計先頭だけを参照します。真の共通受信時計がなく、実受信順や心理の直接証明はできません。感度1/15秒は同じ固定条件を既往29場だけで再生します。',
        'Rは初期損切り幅。幅は場開始時に既知の始値に対する0.1/0.2%、基準は0.4%、最低2呼値へ切上げ。P4のみ観測済み180秒高安から実建値までをRにし、上限超過は返済判断します。ATRは使いません。',
        '従来J1入口は両指数の300秒進行が同方向へ各0.03%以上、自分の15秒両気配は1呼値以上進み、相手15秒価格は逆行しない条件。J2は現在の300秒進行量比25%以上と逆OFI除外を追加します。逆OFIは有効な15秒窓・非ゼロ3イベント以上・入口方向の符号比−10%以下で、少数・未知は逆行と決めつけません。P4の構造線は過去180秒安値の1呼値下／高値の1呼値上です。',
        'A0はTOPIXミニ10枚／日経225マイクロ20枚で新規。A1は2→追加3→追加5枚／4→追加6→追加10枚です。順行・共同支持・共通保護線での全玉損失枠を確認して追加し、損玉へ追加しません。次観測の飛びによる約定後損失枠超過は隠さず次行全返済します。',
        '判断後の次有効ラージ気配へ約定。買ask／売bid。ミニ・マイクロの実板や滑り・市場影響を直接再現しません。新規・追加・返済ごとの注文料金を合計し1円未満を切捨てます。TOPIX41.8円/枚・倍率1000円、日経11円/枚・倍率10円。両商品円は合算しません。',
        '新規は場開始5分後から撤収目安5分前まで。保有上限30/60分、15:34／05:49から全返済判断、次有効気配で約定するため欠測時は遅れます。保存末尾の架空清算はしません。図は事後の五分足であり入口判断用の未来情報ではありません。'
    ]
    data = dict(title='金額利益8割を目指す改善と全セッション損益', sessions=fixed['全30'], periodNames=list(PERIODS),
        methods=methods, benchmark=benchmark, bars=bars(fixed['全30']), selection=selection, notes=notes,
        conclusions=conclusions(analysis, methods, benchmark), allUrl=ALL,
        research=load(WORK / 'theory/金額8対2を目指す改善の事前仮説.json')['一次研究'],
        distribution=analysis['金額80条件数'], mechanismNotes=[
            'Q/P代表のA1は追加0回で初回2枚／4枚のまま。全量A0より利益も損失もほぼ5分の1となり、金額利益割合を改善した結果ではありません。',
            'Q1の早期建値保護P2は、P1に比べ損失以上に利益も削り、両商品の収支を悪化させました。P2では追従幅も半分なので、建値保護だけの効果とは分解できません。',
            '今回残ったJ2は入口選別の案で、出口は従来型です。この検証から一般に全てのトレーリングが無効とは言えません。'
        ])
    all_data = dict(title='全492条件の比較', sessions=fixed['全30'], periodNames=list(PERIODS),
        methods=[minimal(lookup[r['config']['id']]) for r in raw], selectedIds=[m['id'] for m in methods],
        baselineId=benchmark['id'], mainUrl=MAIN, notes=notes[:4], unseenIds=selection['未見対象'])
    OUT.mkdir(parents=True, exist_ok=True)
    render('main_template.html', data, MAIN)
    render('all_template.html', all_data, ALL)
    save(HERE / '主レポートデータ.json', data)
    save(OUT / '公開会計.json', dict(全合格=True, 条件数=492, 主代表数=3, 場数=30, 口座数=60,
        未見対象数=len(selection['未見対象']), 選定=selection, 会計=checks,
        公開SHA256={name: digest(OUT / name) for name in (MAIN, ALL)},
        固定SHA256=digest(WORK / '事前固定.json'), 分析SHA256=digest(analysis_path),
        改善機構分析SHA256=digest(diagnostic_path), API取得=0, 実注文=0))
    print('金額8割・全492条件・固定対象の追加一場を生成しました', flush=True)


if __name__ == '__main__':
    main()
