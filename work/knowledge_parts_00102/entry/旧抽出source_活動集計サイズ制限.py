"""保存済みの入口条件と事後事象を分離し、限定範囲の知見を抽出する。"""

from pathlib import Path
import hashlib
import json


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DOCUMENTS = {}
READS = {}
CHECKS = []
SYMBOLS = ('TOPIX', 'NK225')


def document(path: str) -> object:
    """
    機能: 保存済みの小集計だけを一度読み、内容指紋を保持する。
    引数: path(str)はプロジェクト相対パス。
    返り値: object。JSONの保存内容。金融・原本・NPZを再生しない。
    """
    if path not in DOCUMENTS:
        raw = (ROOT / path).read_bytes()
        assert len(raw) < 1_500_000, path
        READS[path] = hashlib.sha256(raw).hexdigest()
        DOCUMENTS[path] = json.loads(raw.decode('utf-8'))
    return DOCUMENTS[path]


def evidence(path: str, pointer: str = '', function: str | None = None) -> dict:
    """
    機能: JSON pointer又は実装関数を、実在するファイルの指紋に結び付ける。
    引数: path/pointer(str)、function(str|None)は資料の位置と関数名。
    返り値: dict。検証可能な根拠情報。
    """
    if path.endswith('.json'):
        value = document(path)
        for component in pointer.split('/')[1:]:
            key = component.replace('~1', '/').replace('~0', '~')
            value = value[int(key)] if isinstance(value, list) else value[key]
    else:
        raw = (ROOT / path).read_bytes()
        READS.setdefault(path, hashlib.sha256(raw).hexdigest())
        if function:
            assert ('def ' + function + '(') in raw.decode('utf-8')
    result = dict(path=path, pointer=pointer, sha256=READS[path])
    if function:
        result['function'] = function
    return result


def measurement(symbol: str, label: str, kind: str, successes: int, total: int,
                denominator: str, horizon: str, scope: dict, source: dict,
                calculation: str | None = None) -> dict:
    """
    機能: 件数と分母が明示された経験比率を作る。
    引数: symbol/label/kind/denominator/horizon(str)、successes/total(int)、scope/source(dict)、calculation(str|None)。
    返り値: dict。valueは百分率ではなく比率、unitは比率。未到達を勝ちに含めない。
    """
    assert isinstance(successes, int) and isinstance(total, int) and 0 <= successes <= total
    result = dict(symbol=symbol, label=label, kind=kind, successes=successes, total=total,
                  value=successes / total if total else None, unit='比率', denominator=denominator,
                  horizon=horizon, scope=scope, source=source)
    if calculation:
        result['calculation'] = calculation
    return result


def check(label: str, actual: object, expected: object) -> None:
    """
    機能: 保存明細からの再集計を保存集計へ照合する。
    引数: label(str)、actual/expected(object)は実値と期待値。
    返り値: None。不一致では停止し、旧資料を変更しない。
    """
    assert actual == expected, (label, actual, expected)
    CHECKS.append(label)


def common_rule(ident: str, title: str, condition: str, mechanical: str,
                observed: str, use: str, limitations: list[str], values: list, proofs: list) -> dict:
    """
    機能: 入口条件から事象を引ける共通台帳の一項目を作る。
    引数: ident/title/condition/mechanical/observed/use(str)、limitations(list[str])、values/proofs(list)。
    返り値: dict。将来の保証や採用済みアルゴリズムという意味を付けない。
    """
    return dict(id=ident, stage='入口', title=title, condition=condition,
                mechanical_condition=mechanical, observed=observed, use=use,
                limitations=limitations, measurements=values, evidence=proofs)


def extent_rules() -> list[dict]:
    """
    機能: 既存3候補の方向到達と対称先着を全入口の分母で抽出する。
    引数: なし。
    返り値: list[dict]。実決済後も場末まで追った到達率を、実取引勝率と分ける。
    """
    path = 'work/wave_v64/最大順行と入口採点.json'
    packet = document(path)
    quote_path = 'work/wave_v64/限界値の気配感度検査.json'
    quote = document(quote_path)
    micro_path = 'work/wave_v63/microstructure/round3/実行前固定.json'
    micro = document(micro_path)
    mechanical = [
        '256更新連続正常・開始後300秒・16行ごと・直前256更新が120秒以内・spread<=1呼値・執行方向代理の不明割合<=40%。買いは64更新OFI/平均最良数量>=4、256更新OFI比>0、最良数量偏り>=0.6、64更新中値変化>=1呼値、既知代理量が0又は買代理量>=売代理量。売りは反射。16呼値利確/8呼値損切/30分/10秒休止の独立影取引を続け、直近完了10件の6件以上黒字で実入口を許可。',
        '同じ256更新資格。買いは直近64更新以内・reset後の買い補充代理が当時最良数量の0.5倍以上、現在bidがその価格から2呼値以内、64更新の売代理量>=平均最良数量、64更新中値の絶対変化<=2呼値、16更新OFI/平均最良数量>=2。売りは反射。独立影取引の直近完了5件中3件以上黒字で許可。補充代理は同一主体の真の補充ではない。',
        '正常な確定1分足・過去20分の観測割合>=80%。買いは安値が前20分安値-1呼値を割り、終値が同安値+1呼値以上へ戻る陽線。売りは反射。W=max(2呼値,当場観測始値×0.1%の呼値切上げ)。120秒/5000原行以内に、方向付き近接板量偏り>=過去20分の絶対値75分位（現在行を除き60標本以上）、方向付き表示フロー>=0、初期中値から1呼値順行、spread<=0.15Wを確認。半W逆行で候補破棄。実口座は返済後10分休止。'
    ]
    results = []
    for index, method in enumerate(packet['methods']):
        ident = method['id']
        scope = dict(期間='2026-09-21_Day〜2026-10-07_Day', 対象セッション数=25,
                     既知データ=True, 母集団='旧探索で選んだ候補の実新規判断。全候補行ではない。',
                     手法ID=ident, 方向='買い・売りを合計', 除外数=0)
        values = []
        for symbol in SYMBOLS:
            rows = [r for r in packet['rows'] if r['method'] == ident and r['symbol'] == symbol]
            stats = method['summary'][symbol]
            count = len(rows)
            check(ident + symbol + '入口数', count, stats['新規数'])
            source = evidence(path, f'/methods/{index}/summary/{symbol}/到達/0.10')
            for name, field, kind in [('場末までに順行0.1%へ一度到達', '順行到達', '中値の場末までの到達率'),
                                      ('対称0.1%の順行側へ先着', '順行先着', '中値の対称幅先着率'),
                                      ('場末までに逆行0.1%へも到達', '逆行到達', '中値の逆行到達率')]:
                success = sum(r['extent']['到達']['0.10'][field] for r in rows) if field != '順行先着' else sum(r['extent']['到達']['0.10']['先着'] == 1 for r in rows)
                check(ident + symbol + field, success, stats['到達']['0.10'][field])
                values.append(measurement(symbol, name, kind, success, count,
                    '同じ手法・商品で実新規を判断した全入口。先着未到達も分母に含める。',
                    '判断行の次原行から同じ保存通常セッション末まで。実返済後も含む。', scope, source))
            qindex = next(i for i, v in enumerate(quote['summary']) if v['候補'] == index + 1 and v['銘柄'] == symbol)
            q = quote['summary'][qindex]
            values.append(measurement(symbol, '判断時新規気配→将来返済気配でも0.1%へ到達',
                '売買気配差込みの場末までの到達率', q['判断時新規気配から返済気配0_10到達'], count,
                '同じ全入口。判断時買ask/売bidから、将来の買玉bid/売玉askを測る。',
                '同じ場末まで。手数料と実際の次行約定遅れは含めない。', scope,
                evidence(quote_path, f'/summary/{qindex}')))
        proofs = [evidence(path, f'/methods/{index}'), evidence('work/wave_v64/entry_extent.py', function='measure'),
                  evidence('work/wave_v64/限界値採点前固定.json'), evidence('work/wave_v64/限界値の独立検査.json'),
                  evidence('work/wave_v63/report.py')]
        if index < 2:
            ci = next(i for i, v in enumerate(micro['conditions']) if v['id'] == ident)
            proofs.extend([evidence(micro_path, f'/conditions/{ci}'), evidence('work/wave_v63/microstructure/round3/code/core.py', function='candidate_signals')])
        else:
            proofs.extend([evidence('work/wave_v63/directional/round3/code/signals.py', function='candidates'),
                           evidence('work/wave_v63/directional/round3/code/board_round3.py', function='candidates')])
        observed = ('NKは22/23で順行0.1%へ届いたが、逆行0.1%より先だったのは14/23。TOPは15/19到達・7/19先着。' if index == 2 else
                    '板圧力の候補はTOP49/57到達・36/57先着、NK34/46到達・26/46先着。' if index == 0 else
                    '補充候補はTOP60/77到達・40/77先着、NK49/59到達・37/59先着。')
        results.append(common_rule('入口_00' + str(index + 1), method['name'] + '：到達と先着は別',
            ['表示圧力と価格が揃い、当場の影取引が好調なとき入る。',
             '反対側の売買圧力を吸収するような数量回復と方向圧力を待ち、影取引で選別する。',
             '前レンジを破れずに戻ったあと、その方向を支える板と小さな順行を確認して入る。'][index],
            mechanical[index], observed, '到達確率から安全な逆指値幅や利益率を直接決めず、同じ幅の逆行との到達順を必ず参照する。',
            ['既知25場の探索後に選んだ候補。独立未知試験ではない。',
             '281判断は時間的に重なる。独立な標本としての信頼区間や将来保証ではない。',
             '対称先着は判断中値の数学的な障壁であり、IFDの費用後実約定勝率ではない。',
             '最高値は事後専用。到達が高くても、先行逆行・実返済・気配差・料金で利益を逃し得る。',
             '同時刻の買い固定/売り固定対照はこの価格幅版にない。候補間も時刻・母集団が異なる。'], values, proofs))
    return results


def peer_rule() -> dict:
    """
    機能: 同じ実S1入口と実出口を、当時の相手条件だけで分類した観測を抽出する。
    引数: なし。
    返り値: dict。純粋な方向正答率と、費用後の実決済黒字率を混同しない。
    """
    path = 'work/wave_v75/analysis/同じ新規機会での相手確認診断.json'
    packet = document(path)
    fixed = document('work/wave_v75/事前固定.json')
    values = []
    for period in ('前16', '後13', '全29'):
        for symbol in SYMBOLS:
            for group in ('相手確認あり', '相手確認なし'):
                rows = [r for r in packet['明細'] if r['銘柄'] == symbol and r['相手確認'] == group and r['セッション'] in fixed[period]]
                aggregate = packet['比較'][period][symbol][group]
                wins = sum(r['収支'] > 0 for r in rows)
                check(period + symbol + group + '分母', len(rows), aggregate['取引数'])
                check(period + symbol + group + '黒字', wins, aggregate['勝数'])
                values.append(measurement(symbol, period + '・' + group + '・費用後黒字',
                    '固定した実入口・実出口における決済黒字率', wins, len(rows),
                    '元S1の実決済142件を当時のJ1状態で二群化。勝敗や将来値で群を選ばない。',
                    '元の始値0.4%トレール・30分上限・場内返済の実出口まで。',
                    dict(期間='2026-09-21_Day〜2026-10-09_Day', セッション区分=period,
                         対象セッション数=len(fixed[period]), 既知データ=True, 元手法='S1_W300_L0_T40_H30',
                         分類='J1_W300_L0の同方向状態。J1発火の有無ではない。', 枚数='TOPIXmini10/NK225micro20'),
                    evidence(path, f'/比較/{period}/{symbol}/{group}')))
    return common_rule('入口_004', '自市場が進むとき、相手も同方向かを確認する',
        '自市場だけが上がる／下がる場面より、相手も進行している場面の実取引が良かった。',
        '自市場300秒中値変化の方向付き値>=3bp、直前15秒のbid/askが各1呼値順行するS1実判断を母集団にする。同一共通判断で相手の300秒中値変化も同方向>=3bp、相手15秒変化の方向付き値>=0ならJ1確認あり。15秒格子から5秒引いた期限よりstrict過去、同時計先頭、両市場観測鮮度<=30秒・正常を共通要求。',
        '全29ではTOPの確認あり31/49=63.3%・なし14/27=51.9%、NKは24/40=60.0%・なし11/26=42.3%。前半・後半とも確認ありのほうが高かった。',
        '入口の有力な選別仮説。ただし確認なしを外した売買の再生結果ではなく、固定した同じ売買を分類した比較として使う。',
        ['方向到達率ではなく固定出口・料金込みの決済黒字率。', '分類群は時刻や相場が異なり、相手確認の純粋な因果効果ではない。',
         '確認なしを見送ると保有状態・後の受付機会が変わるため、この分類損益をそのまま改良戦略収支にできない。',
         '29場は既知。代理時計の厳密過去であり、実受信順・同時配信を証明しない。'], values,
        [evidence(path, '/比較'), evidence('work/wave_v75/analysis/same_opportunity.py', function='past_label'),
         evidence('work/wave_v75/signals.py', function='conditions'), evidence('work/wave_v75/事前固定.json')])


def settlement_rules() -> list[dict]:
    """
    機能: 定着・反転の全実親から、小順行と支持線の先着を再集計する。
    引数: なし。
    返り値: list[dict]。最終赤字親だけを選ぶ未来選別を行わない入口観測。
    """
    path = 'work/wave_v104/旧自己入口の支持破れと順行の診断.json'
    packet = document(path)
    fixed = document('work/wave_v103/金融事前固定.json')
    common = '当場だけ。完全10段・正常出来高差・resetなしの原行順。買い想定p=初回ask、売り想定p=初回bid、Q0=その初回反対側数量。初期はp±1呼値帯・想定方向と一致する一意の最終価格方向代理・正ΔV・同価格表示減少の区間だけ加算。表示減少>=0.5Q0かつΔV合計>=Q0で準備。方向代理は現在volume_time==price_timeでLast>=直前askなら+、Last<=直前bidなら-、内側は不明。初期・準備・移動・確認は別原行。120価格時計秒/5000原行/価格維持破れ/遠端外の数量不明で破棄。'
    specific = dict(
        C_OWN='Cは買いbid>=pかつask>=初回ask+1呼値（売りは反射）へ移り、新方向支持pの数量>=0.5Q0。移動後のpから順行0〜2呼値帯で実参加方向代理に一致する正ΔV>=Q0を別行で確認。準備行で先に移動を観測した場合も段階を分け、直後崩れで破棄。',
        R_OWN='Rは元方向へ最良気配がpに到達せず、準備後p数量が直前より実増加し>=0.8Q0へ回復。別行で両気配が基準から反対へ各1呼値進む。支持r=旧自身最良で初回その側数量の0.5倍以上、移動後rから反転方向0〜2呼値帯の同方向代理正ΔV>=Q0を確認。回復行で先行反対移動を観測したあと崩れたら破棄。')
    results = []
    for family in ('C_OWN', 'R_OWN'):
        financial_path = f'work/wave_v103/finance/results/{family}.json'
        finance = document(financial_path)
        values = []
        for symbol in SYMBOLS:
            rows = [r for r in packet['rows'] if r['method'] == family and r['symbol'] == symbol]
            n = len(rows)
            totals = packet['totals'][family][symbol]
            check(family + symbol + '全親', n, sum(v['count'] for v in totals.values()))
            reached = sum(r['first_fee_plus2_row'] is not None for r in rows)
            check(family + symbol + '順行', reached, sum(v['fee_plus2_reached'] for v in totals.values()))
            good_first = sum(r['first_fee_plus2_row'] is not None and (r['support_boundaries']['4'] is None or r['first_fee_plus2_row'] < r['support_boundaries']['4']['row']) for r in rows)
            bad_first = sum(r['support_boundaries']['4'] is not None and (r['first_fee_plus2_row'] is None or r['support_boundaries']['4']['row'] < r['first_fee_plus2_row']) for r in rows)
            check(family + symbol + '逆側先着', bad_first, sum(v['boundaries']['4']['crossed_before_fee_plus2'] for v in totals.values()))
            wins = sum(r['outcome'] == '利益' for r in rows)
            fs = finance['periods']['全32'][symbol]
            check(family + symbol + '金融親数', n, fs['campaigns'])
            check(family + symbol + '金融黒字', wins, fs['winning_campaigns'])
            scope = dict(期間='2026-09-21_Day〜2026-10-12_Night', 対象セッション数=len(fixed['sessions']),
                         既知データ=True, 母集団='自己市場だけの当該入口で実際に約定し完結した全親。最終黒字/赤字を問わない。',
                         手法ID=family, 枚数='各商品1枚・追加なし', 方向='買い・売りを合計', 対照='同じ情報資格・旧S/D30分出口。相手条件だけを外したOWN。')
            source = evidence(path, '/rows')
            for label, kind, count, formula in (
                ('手数料幅+2呼値へ一度順行', '実保有中の清算気配到達率', reached, 'method/symbolを限定し、first_fee_plus2_row!=nullを数える。'),
                ('手数料幅+2呼値が支持4呼値破れより先', '非対称の支持境界と利益幅の先着率', good_first, 'first_fee_plus2_row!=null、かつ境界4がnull又はfirst_fee_plus2_row<境界4.row。'),
                ('支持4呼値破れが利益幅より先', '非対称の支持境界と利益幅の逆側先着率', bad_first, '境界4!=null、かつfirst_fee_plus2_rowがnull又は境界4.row<first_fee_plus2_row。')):
                values.append(measurement(symbol, label, kind, count, n,
                    '同じ商品・入口の全実完結親。両側未到達/同原行同着も全親分母に残す。',
                    '実fill行から旧S/D30分又は場内返済の実出口まで。場末まで延長しない。', scope, source, formula))
            values.append(measurement(symbol, '旧固定出口で費用後黒字', '固定出口条件付きの決済黒字率', wins, n,
                '同じ全実完結親。未取引場を成功と数えない。', '元の実出口まで。', scope,
                evidence(financial_path, f'/periods/全32/{symbol}')))
        is_c = family == 'C_OWN'
        results.append(common_rule('入口_005' if is_c else '入口_006',
            '活動を伴う新価格の定着' if is_c else '進行失敗と実際の数量回復から反転',
            '消費されるような表示減少のあと、新価格が支持されるのを待つ。' if is_c else '一方へ進めず元の板が回復したあと、逆側へ実際に進むのを待つ。',
            common + specific[family] + '自己だけのOWNでは相手readyを要求しない。同episode1回・normal同原行・受付は開始300秒後〜終了300秒前、返済後30秒休止。',
            ('全実親で小順行に到達したのはTOP184/274=67.2%・NK104/189=55.0%。支持4呼値破れより先は142/274=51.8%・99/189=52.4%。' if is_c else
             '全実親で小順行に到達したのはTOP59/89=66.3%・NK23/37=62.2%。支持4呼値破れより先は51/89=57.3%・21/37=56.8%。'),
            '初期の小順行を取れる割合と、方向支持が崩れる前に取れる割合を確認する部品として使う。単独で高確度や安定収益を認定しない。',
            ['初期表示減少の門があるため、減らずに完全補充され続ける板は捕捉できない。',
             '累計出来高差と最終価格の方向代理は真の同価格約定量/取消量/同主体補充の識別ではない。',
             '先着2障壁は実建値から等距離ではない。支持価格の離隔でリスク幅が変わる。',
             '手数料幅は実両側料金/(数量×金額倍率)を呼値切上げ。そこへ2呼値を加える。料金後2呼値の小利益に対応するが、その線での約定利益ではない。',
             '先着・順行は旧出口までの事後診断。出口を変えた戦略の反実仮想損益ではない。',
             '当時資格・受付・保有制約を通った実親だけで、全候補の純粋な方向確率ではない。32場は既知。'], values,
            [evidence(path), evidence('work/wave_v104/旧保有中の支持価格の推移を診断する.py', function='run'),
             evidence('work/wave_v103/数値設計草案.json'),
             *[evidence(f'work/wave_v103/数値設計補足{i:02}.json') for i in range(1, 8)],
             evidence('work/wave_v103/engine/states.py'), evidence('work/wave_v103/engine/finance_adapter.py', function='connect'),
             evidence(financial_path, '/config')]))
    return results


def strict_pair_rule() -> dict:
    """
    機能: 同思想の二市場readyへ絞った入口の活動量と黒字件数を抽出する。
    引数: なし。
    返り値: dict。不活動を成功と扱わず、自己のみの入口との母集団差を明示する。
    """
    path = 'work/wave_v103/finance/results/U_C1R1.json'
    packet = document(path)
    activity_path = 'work/wave_v103/activity/全32の状態可用性と発火.json'
    activity = document(activity_path)
    values = []
    for symbol in SYMBOLS:
        rows = [r for r in packet['rows'] if r['symbol'] == symbol]
        fs = packet['periods']['全32'][symbol]
        check(symbol + 'U全親', sum(r['campaigns'] for r in rows), fs['campaigns'])
        check(symbol + 'U黒字', sum(r['winning_campaigns'] for r in rows), fs['winning_campaigns'])
        active = sum(r['campaigns'] > 0 for r in rows)
        scope = dict(期間='2026-09-21_Day〜2026-10-12_Night', 対象セッション数=32, 既知データ=True,
                     手法ID='U_C1R1', 枚数='各商品1枚', 母集団='C1/R1の両市場同思想・同方向確認後の実親。全11件は売り。')
        values.append(measurement(symbol, '旧固定出口で費用後黒字', '固定出口条件付きの決済黒字率', fs['winning_campaigns'], fs['campaigns'],
            '各商品の全11実完結親。不活動25場を成功へ入れない。', '旧S/D30分・場内返済の実出口まで。', scope,
            evidence(path, f'/periods/全32/{symbol}')))
        values.append(measurement(symbol, '取引が発生した場', '活動率・利益確率ではない', active, 32,
            '既知全32場。無取引を利益とは呼ばない。', 'セッション単位。', scope, evidence(path, '/rows'),
            'symbolを限定しcampaigns>0のセッション数を数える。'))
        ag = activity['aggregate']['U_C1R1'][symbol]
        check(symbol + 'U受付内pulse', ag['reception_normal_pulses'], fs['campaigns'])
        check(symbol + 'U活動', ag['受付内normal対応場数'], active)
    return common_rule('入口_007', '両市場に同じ板エピソードを要求すると、活動が消え得る',
        '自己市場の定着又は反転に、相手市場の同じ種類・同方向の準備完了を要求する。',
        '入口005/006のκ=1を使用。相手源は自己価格時計よりstrict過去、相手の各newmax時計の最初原行だけ、age<=15秒、同family・同方向ready。C/Rの全valid-ready（消費済含む）が買売競合なら保留。一方向だけで未消費episodeがあれば1枚参加し同episodeを消費。normal同原行、受付300秒境界、旧S/D30分出口。',
        '両商品とも32場中7場・11親だけ。費用後黒字はTOP3/11=27.3%、NK2/11=18.2%。自己のみのC/Rより入口が少なく、精度向上も確認できなかった。',
        '二市場確認の内容を比較する否定例。相手まで同じ短いepisodeを要求することと、一般的な価格支持を確認することを区別する。',
        ['11件の小母集団で全売り。買いにも同じ性質があるとは言えない。',
         'OWNとUは入口集合・取引経路が異なり、勝率差は相手条件だけの純粋な因果効果ではない。',
         '同時計後半を過去へ戻さずfirst-newmaxを採用しているため、保存上存在しても利用できないreadyがある。',
         '受信順不明の代理時計制約と、同思想readyの非重なりを含む。未知相場での確率を保証しない。'], values,
        [evidence(path, '/periods'), evidence(activity_path, '/aggregate/U_C1R1'),
         evidence('work/wave_v103/catalog.py', function='catalog'), evidence('work/wave_v103/engine/states.py')])


def main() -> None:
    """
    機能: 限定した入口7項目と件数再照合の証跡を新規保存する。
    引数: なし。
    返り値: None。既存資料を変更せず、金融/API/原本/NPZの新読取・再生をしない。
    """
    target = HERE / 'entry_rules.json'
    assert not target.exists(), '保存済み入口知見は上書きしません'
    rules = extent_rules() + [peer_rule()] + settlement_rules() + [strict_pair_rule()]
    check('ルール数', len(rules), 7)
    check('全旧入口採点数', document('work/wave_v64/最大順行と入口採点.json')['新規数'], 281)
    check('同入口分類数', document('work/wave_v75/analysis/同じ新規機会での相手確認診断.json')['全明細数'], 142)
    check('定着反転診断親数', document('work/wave_v104/旧自己入口の支持破れと順行の診断.json')['実完結親数'], 589)
    result = dict(rules=rules, scope=dict(
        公開資料='00060/00061/00062/00071/00099/00100の関連保存集計・当時実装を限定取得。00072〜00074の資料案内も確認。',
        読取実装='wave63/64、75、103/104。保存JSONとsourceだけ。',
        未取得='歴代全入口・全条件・00072〜00074全入口の方向採点・未知将来確率は網羅していない。',
        指標='到達・先着・固定出口決済黒字・活動を別kindにする。母集団を同一視しない。',
        新金融再生=0, 新アルゴリズム再生=0, 原本読取=0, NPZ読取=0, API取得=0, 既存source変更=0),
        件数再照合=dict(全合格=True, 検査数=len(CHECKS), 検査=CHECKS), source_sha256=READS)
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    target.write_text(text, encoding='utf-8')
    print(json.dumps(dict(全合格=True, ルール数=len(rules), 測定数=sum(len(r['measurements']) for r in rules),
                         検査数=len(CHECKS), JSON_SHA256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
                         source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
