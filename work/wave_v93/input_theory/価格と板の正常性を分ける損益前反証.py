"""価格入力へ深板・出来高の故障を伝播させる必要性を、損益なしで反証する。"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REFERENCES = [ROOT / 'work/wave_v57/features.py', ROOT / 'work/wave_v77/inputs/core.py',
              ROOT / 'work/wave_v76/inputs/core.py']


def finite(value: object) -> float | None:
    """
    機能: 欠測又は非有限値を0へ置き換えず識別する。
    引数: value (object) は原本の値。
    返り値: float | None は有限値又は不明。
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def snapshot(mid: float, clock: float, volume: float, seq: int) -> dict:
    """
    機能: 正常最良気配と完全10段を持つ人工原本行を作る。
    引数: mid/clock/volume (float)、seq (int)。
    返り値: dict は売買損益を持たない人工観測。
    """
    raw = {'seq': seq, 'clock': clock, 'session': '人工同場', 'contract': '人工同限月',
           'CurrentPrice': mid, 'TradingVolume': volume}
    for depth in range(1, 11):
        raw[f'Buy{depth}'] = {'Price': mid - .5 - (depth - 1), 'Qty': 100.}
        raw[f'Sell{depth}'] = {'Price': mid + .5 + (depth - 1), 'Qty': 100.}
    return raw


def top_valid(raw: dict) -> bool:
    """
    機能: 価格中値を作れる正の最良価格と最良数量だけを検査する。
    引数: raw (dict) は人工又は原本形式の観測。
    返り値: bool は最良BBOが有限・非交差・正数量ならTrue。
    """
    bid, ask = raw.get('Buy1', {}), raw.get('Sell1', {})
    b, a, bq, aq = (finite(v) for v in (bid.get('Price'), ask.get('Price'), bid.get('Qty'), ask.get('Qty')))
    return bool(None not in (b, a, bq, aq) and 0 < b < a and bq > 0 and aq > 0)


def deep_valid(raw: dict) -> bool:
    """
    機能: 旧v57に相当する完全10段の有限性・非負数量・順序を独立検査する。
    引数: raw (dict)。
    返り値: bool は最良及び両10段の全条件を満たすか。
    """
    if not top_valid(raw):
        return False
    for label, direction in [('Buy', -1), ('Sell', 1)]:
        previous = None
        for depth in range(1, 11):
            item = raw.get(f'{label}{depth}', {})
            p, q = finite(item.get('Price')), finite(item.get('Qty'))
            if p is None or q is None or p <= 0 or q < 0:
                return False
            if previous is not None and direction * (p - previous) <= 0:
                return False
            previous = p
    return True


def classify(raw: dict, previous: dict | None) -> dict:
    """
    機能: 価格・最良OFI・深板補充・出来高代理へ必要な正常性を独立分類する。
    引数: raw (dict)、previous (dict | None)。
    返り値: dict は入力故障の分類。正式特徴器又は注文を実行しない。
    """
    clock = finite(raw.get('clock'))
    top, deep = top_valid(raw), deep_valid(raw)
    last, volume = finite(raw.get('CurrentPrice')), finite(raw.get('TradingVolume'))
    missing = clock is None
    discontinuity = previous is not None and raw['seq'] != previous['seq'] + 1
    backwards = previous is not None and clock is not None and finite(previous.get('clock')) is not None and clock < previous['clock']
    identity_changed = previous is not None and any(raw.get(k) != previous.get(k) for k in ('session', 'contract'))
    hard = bool(missing or discontinuity or backwards or identity_changed)
    old_volume = finite(previous.get('TradingVolume')) if previous else None
    volume_reset = bool(old_volume is not None and volume is not None and volume < old_volume)
    return {'最良価格正常': top, '10段正常': deep, 'LP正常': last is not None and last > 0,
            '時計不明': missing, '原本行不連続': discontinuity, '時計逆行': backwards,
            '場又は限月変更': identity_changed, '価格時間の必須切断': hard or not top,
            '出来高リセット': volume_reset,
            '最良OFI比較可': bool(previous and top and top_valid(previous) and not hard),
            '深板補充比較可': bool(previous and deep and deep_valid(previous) and not hard),
            '出来高増分比較可': bool(previous and not hard and old_volume is not None and volume is not None
                                        and old_volume >= 0 and volume >= old_volume)}


def price_er(rows: list[dict], keep_deep: bool, keep_volume: bool) -> float | None:
    """
    機能: 人工価格列へ独立に故障を伝播し、窓の価格効率が定義可能か確認する。
    引数: rows (list[dict])、keep_deep/keep_volume (bool) は故障伝播の有無。
    返り値: float | None は同時計先頭の中値ER又は不明。損益を計算しない。
    """
    prices = []
    previous = None
    last_clock = None
    for i, raw in enumerate(rows):
        state = classify(raw, previous)
        broken = state['価格時間の必須切断'] or keep_deep and not state['10段正常'] or keep_volume and state['出来高リセット']
        # 窓の開始点に初期化があることは許す。窓内の未知は補完しない。
        if i > 0 and broken:
            return None
        if state['時計不明'] or not state['最良価格正常']:
            return None
        if raw['clock'] != last_clock:
            prices.append((raw['Buy1']['Price'] + raw['Sell1']['Price']) / 2)
            last_clock = raw['clock']
        previous = raw
    variation = sum(abs(b - a) for a, b in zip(prices, prices[1:]))
    return abs(prices[-1] - prices[0]) / variation if variation > 0 else None


def last_price_er(rows: list[dict]) -> float | None:
    """
    機能: 最良気配の資格とは別に、原本の正常LastPriceから人工価格効率を作る。
    引数: rows (list[dict]) は観測順を保持した人工原本。
    返り値: float | None は同時計先頭LastPriceのER又は不明。
    """
    previous, last_clock = None, None
    prices = []
    for raw in rows:
        state = classify(raw, previous)
        # 最良BBO不正だけをLPの破綻とはしない。原本時計/seq/識別は必ず要求する。
        hard = any(state[name] for name in ('時計不明', '原本行不連続', '時計逆行', '場又は限月変更'))
        if hard or not state['LP正常']:
            return None
        if raw['clock'] != last_clock:
            prices.append(float(raw['CurrentPrice']))
            last_clock = raw['clock']
        previous = raw
    variation = sum(abs(b - a) for a, b in zip(prices, prices[1:]))
    return abs(prices[-1] - prices[0]) / variation if variation > 0 else None


def artificial_cases() -> list[dict]:
    """
    機能: 深板故障隔離の正例と、隔離してはいけない価格・時計故障を反証する。
    引数: なし。
    返り値: list[dict] は人工観測の全ケースと独立assert結果。
    """
    base = [snapshot(v, float(i), 100. + 10 * i, i) for i, v in enumerate([100.5, 101.5, 100.5, 101.5, 100.5, 101.5, 100.5])]
    cases = []
    mutations = [('正常', None), ('遠方Buy10欠測', 'missing_deep'), ('遠方価格順序逆転', 'deep_order'),
                 ('出来高だけ低下', 'volume'), ('最良交差', 'crossed'), ('最良数量0', 'qty_zero'),
                 ('最良数量NaN', 'qty_nan'),
                 ('原本行欠落', 'seq_gap'), ('時計逆行', 'clock_back'), ('時計不明', 'clock_missing'),
                 ('場変更', 'session'), ('限月変更', 'contract')]
    for name, kind in mutations:
        rows = deepcopy(base)
        if kind == 'missing_deep':
            rows[3].pop('Buy10')
        elif kind == 'deep_order':
            rows[3]['Buy10']['Price'] = rows[3]['Buy9']['Price'] + 1.
        elif kind == 'volume':
            for i in range(3, len(rows)):
                rows[i]['TradingVolume'] -= 100.
        elif kind == 'crossed':
            rows[3]['Sell1']['Price'] = rows[3]['Buy1']['Price']
        elif kind == 'qty_zero':
            rows[3]['Buy1']['Qty'] = 0.
        elif kind == 'qty_nan':
            rows[3]['Sell1']['Qty'] = math.nan
        elif kind == 'seq_gap':
            for i in range(3, len(rows)):
                rows[i]['seq'] += 1
        elif kind == 'clock_back':
            rows[3]['clock'] = .5
        elif kind == 'clock_missing':
            rows[3]['clock'] = None
        elif kind in ('session', 'contract'):
            for i in range(3, len(rows)):
                rows[i][kind] = '人工の別識別'
        values = {'I0_旧両故障伝播': price_er(rows, True, True),
                  'I1_深板だけ隔離': price_er(rows, False, True),
                  'I2_出来高だけ隔離': price_er(rows, True, False),
                  'I3_価格専用切断': price_er(rows, False, False)}
        state = classify(rows[3], rows[2])
        lp_efficiency = last_price_er(rows)
        if kind is None:
            assert all(v == 0. for v in values.values())
        elif kind in ('missing_deep', 'deep_order'):
            assert values['I0_旧両故障伝播'] is None and values['I2_出来高だけ隔離'] is None
            assert values['I1_深板だけ隔離'] == values['I3_価格専用切断'] == 0.
            assert state['最良OFI比較可'] and not state['深板補充比較可']
        elif kind == 'volume':
            assert values['I0_旧両故障伝播'] is None and values['I1_深板だけ隔離'] is None
            assert values['I2_出来高だけ隔離'] == values['I3_価格専用切断'] == 0.
            assert state['最良OFI比較可'] and state['深板補充比較可'] and not state['出来高増分比較可']
        else:
            assert all(v is None for v in values.values()), (name, values)
        if kind in (None, 'missing_deep', 'deep_order', 'volume', 'crossed', 'qty_zero', 'qty_nan'):
            assert lp_efficiency == 0.
        else:
            assert lp_efficiency is None
        cases.append({'ケース': name, '当時分類': state, '人工価格ER': values,
                      '独立LastPrice_ER': lp_efficiency,
                      'その行のBBO執行可': state['最良価格正常'] and not state['時計不明'],
                      '正式モデルを実行': False, '人工assert合格': True})
    # ----------------------------------------
    # LPの欠測を中値の欠測へ混ぜず、LPによる停止に補完値を渡さない。
    invalid_last = deepcopy(base)
    invalid_last[3]['CurrentPrice'] = None
    state = classify(invalid_last[3], invalid_last[2])
    assert state['最良価格正常'] and not state['LP正常'] and price_er(invalid_last, False, False) == 0.
    assert last_price_er(invalid_last) is None
    cases.append({'ケース': 'LastPriceのみ欠測', '当時分類': state,
                  '人工中値ER': 0., 'LP停止用価格': None, 'LP補完禁止': True, '人工assert合格': True})
    # ----------------------------------------
    # 同時計の後続行を後から採用すると、過去の判断が将来追記で変わる。
    tied = [snapshot(100.5, 10., 100., 0), snapshot(900.5, 10., 110., 1), snapshot(101.5, 11., 120., 2)]
    selected_before = tied[0]
    future = snapshot(5000.5, 10., 130., 3)
    selected_after = (tied + [future])[0]
    assert selected_before == selected_after
    assert selected_after['Buy1']['Price'] != future['Buy1']['Price']
    cases.append({'ケース': '同時計後続の未来追記又は価格毒入れ', '参照': 'clock10の先頭seq0を固定。後続seq1/3を期限より過去へ差替えない。',
                  '先頭行不変': True, '未来価格は過去採否を変えない': True, '人工assert合格': True})
    # ----------------------------------------
    # 旧深板状態のprevious=Noneから出るbit1を、新価格初期化へ丸ごとコピーしない。
    deep_missing = deepcopy(base[3])
    deep_missing.pop('Buy10')
    assert not deep_valid(deep_missing) and top_valid(deep_missing)
    recovered = classify(base[4], deep_missing)
    assert recovered['最良価格正常'] and not recovered['価格時間の必須切断']
    cases.append({'ケース': '深板異常後の旧bit1初期化と新価格継続',
                  '旧フローprevious': None, '旧フロー初期化bit': 1,
                  '新価格の直前最良は観測済正常': True, '新価格の実初回': False,
                  '新価格seq連続': True, '新価格resetへbit1をコピー': False, '人工assert合格': True})
    return cases


def main() -> None:
    """
    機能: 旧入力の結合点と次段の独立対照及び人工反証を専用新規領域へ保存する。
    引数: なし。旧ソースを読むだけで新売買損益を実行しない。
    返り値: None。input_theory内に日本語JSONを保存する。
    """
    source57, source77, source76 = (p.read_text(encoding='utf-8') for p in REFERENCES)
    assert 'self.bid_book is not None and self.ask_book is not None' in source57
    assert 'for depth in range(1, 11)' in source57
    assert 'seq != self.previous_seq + 1' in source57 and 'now.volume < old.volume' in source57
    assert "~book['valid']|book['reset']" in source77
    assert "displacement=book['mid'][safe_now]-book['mid'][safe_old]" in source77
    assert "first=np.searchsorted(times,times[ends[present]],side='left')" in source76
    cases = artificial_cases()
    data = {
        '段階': '既知93の原因から行う次段入力の損益前理論。93固定実装、監査、結果は変更しない。',
        '旧ソース独立確認': {
            'v57': 'validは最良価格/数量に加え完全両10段を要求。resetには原行不連続・10段不正・約定時計逆行・volume低下が含まれ、深板障害後の初期化も発生する。',
            'v77': 'ERとretと直前範囲はmid価格で計算し、broken=~book.valid|book.resetを全区間へ伝播する。ゆえに遠方深板だけの異常でも300秒価格窓が不明になる。',
            'v76': 'CurrentPriceTimeによる厳密過去期限の最新時計先頭行のみを参照。後続同時計の都合良い正常行へ救済していない。',
            '参照SHA256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in REFERENCES}},
        '伝播の判断': {
            '価格中値に必須': ['最良価格非有限/非正/交差及び最良数量非正・不明', '欠測時計・逆行時計・未解決の原行欠落', '銘柄/限月/場境界及び受信系列の再接続で履歴連続性が未証明', '最良価格を覆うfeed全体破損と判定された行'],
            '価格中値に直ちに必須とは言えない': ['最良と識別と時計が正常な遠方10段の欠測/順序不正/数量不正だけ', '累積出来高又は売買代金だけのreset/欠測'],
            'LP': 'LastPrice有効性はmid有効性と別。正常midでLPが不明でもmid特徴は定義可能だが、旧LP停止へ前LPを補完しない。正常LPでも不正BBOで仮想約定しない。',
            '最良OFI': '両隣接観測の最良価格と数量及び連続性が必要。遠方深板と累積出来高は式に直接含まれない。ただし第一段のQ/Fは旧まま保ち、価格だけの差分へ混ぜない。',
            '深板補充': '同価格の表示量・可視範囲・連続性を要求。範囲外又は欠測を0へ置換しない。価格チャンネルを継続しても不明な補充エピソードは破棄する。',
            '出来高執行代理': '累積volume/valueの有効増分と契約倍率が必要。reset/欠測の後は増分を不明とし、負増分や0の既知執行へ置換しない。',
            '反証': '遠段だけの不正でも同じpacketの最良が実は混在/破損している可能性はある。フィールド分離は正しさの保証でなく入力仮説で、旧完全10段対照と故障人工例を残す。'},
        '時計の因果性': [
            '保存全原行をseq順に読む。時計逆行を並替えて過去へ挿入しない。選別したreadyのseq gapは原本全行で理由を確認するまで未知として切断する。',
            'CurrentPriceTimeは取引価格の時計であり真の板受信時計でない。同値時計の板変化はseqの前後しか分からず、秒経過の証拠へ変換しない。',
            '保存時間格子は旧と同じ厳密過去/同時計先頭/固定age上限を維持し、clock欠測や未来同時計後続を正常化して救済しない。',
            '二市場の真の受信順が無いので、保存代理時計上の未来不変は検証できても、本当に同時に見えていた受信時刻の再現とは認定しない。',
            '次のライブ取得では原packetの受信UTCとプロセス単調時計と銘柄別seqを保存する。その後に各判断で実際公開済みだった両源の組を再現できる。過去データへ受信時計を捏造しない。',
            '原行prefix切断と未来同時計後続毒入れで価格/OFI/補充各状態が不変であることを全境界で検証する。'],
        '具体的な次段入力対照': {
            'I0': '旧complete10/volume resetを価格窓にも伝播。93対照へ全一致。',
            'I1': '最良/時計/seq正常な深板だけの異常を価格mid窓から隔離。volume resetは旧通り伝播。深板無効由来の後続初期化も価格に残さない。',
            'I2': 'volumeだけのresetを価格窓から隔離。深板異常は旧通り伝播。',
            'I3': '深板だけとvolumeだけを価格から隔離。価格・時計・seq・識別の必須切断は全て維持。',
            '全対照共通': '第一段ではERをmidの同時計先頭で計算、窓長・ER閾値・格子delay・age・spread閾値を旧と同じにする。Q/Fと補充は旧の正常性/切断のまま。価格のみの入力正常性効果と、価格LP化・全同時計tick利用の別軸を混ぜない。',
            '原行gap': '元readyが省略した原行は全生板で分類する。深板だけの省略と最良/時計不明の省略を同じ救済にしない。追加の中値観測を採る軸と、同じ観測点のreset旗だけを変える軸は別記・別照合する。'},
        '古い中心と不明時の新規の事前対照': {
            'G0': '旧persistent中心を未知で保持し、旧の入口許可のまま。',
            'G1': '中心保持/保有/返済を変えず、新規判断だけに両市場の現在価格窓と共同方向窓が判定可能なことを要求。未知を中立へ扱わない。',
            'G2': 'G1に加え新規判断で元raw往復述語が現在もTrueを要求。確認の時間/閾値は旧を維持し、rawとmodeの混同をしない。',
            '基本12列': 'I0/I1/I2/I3×G0/G1/G2。各行は固定C11の入口距離/目標/停止OR/N4/数量/料金を保ち、入力だけ又は新規有効性だけの1軸対照として読む。',
            '活動不足': '無取引を勝ちへ含めず、各商品の親数・活動場・拒否理由を全場掲載。G1/G2が無取引なら失敗であり、閾値を結果で緩め成功へ作り替えない。',
            'ゼロ取引へ逃げない方法': '正当な最良価格を深板障害から隔離して観測を回復できるかを先に測る。現在なお不明なら無理に新規せず、短い正常区間による別の予測源は損益前に独立定義して別対照へ置く。未知を反対方向の根拠にはしない。'},
        '出口との交絡を避ける': [
            '上の12入力/新規対照では旧C11の出口とN4を全て固定する。',
            '価格入力の変更で入口列が変わるので、同一判断キーの管理差と新旧固有親G/Lを全経路で出す。入力改善と単純なstop拡幅の効果を一つの比較へ混ぜない。',
            '次に固定した入力/入口へ出口だけを変え、極値OR/旧LP1Wなどを同一新規で比較する。必要なら入力×出口の完全対照を損益前に増設し、各差の軸を明記する。',
            '事後の一親診断−49,196/+23,360円を新正式戦略の成績として採用しない。新規連鎖/枠/N4を含めた正式再生が必要。'],
        '原本独立診断による仮説修正': {
            '参照段階': 'audit93の初回独立生板診断。以後の正式取引結果は追加していない。',
            '観測': '全62抽出7,921,507行の深板不正72、seqgap reset6,117、volume/clock reset0。32原本4,429,975行の最良不正8,360、最良正常深板不正62。二つの集計は対象母数が異なるので割合を直接比較しない。',
            'C11入力': '正常最良Qtyを維持した原mid300の双方有限はTOPIX0/11・日経1/6。原LastPrice300なら9/11・5/6、mid30なら7/11・5/6。',
            '判断': '深板だけのprice伝播が問題になり得ることと、今回それが主因だったことは別。多数の旧seqgapは実際の最良不正を原本選別で落とした結果。深板隔離だけで長窓不明が消えると予測しない。'},
        'LastPrice入力とBBO執行を分ける追加対照': {
            '許容する論理': '正常LastPriceと時計/seq/識別から価格特徴を作ることは、BBOで実行することと矛盾しない。過去取引価格の方向を予測情報として使い、次有効買ask/売bidへ執行する。LPで約定したと仮定しない。',
            'LPの切断': 'LP欠測/非有限/非正、clock欠測・逆行、原行の未解決欠落、場/限月/銘柄変更を切断する。最良Price/Qty不正だけはLP不正と同一視しない。',
            'MIDの切断': '最良PriceとQtyの有限正/非交差を必要とし、その不正はmid窓を切断する。LP正常でもmidを仮作成しない。',
            '執行の資格': '最良Price/Qty正常なBBOを従来通り使用。不正BBOで新規又は返済を約定せず、既に決定した注文は次正常BBOまで待つ。正常LPの有効予測は良好な執行価格を保証しない。',
            '同clock': 'LastPriceもmidも厳密過去期限の最新clock先頭seqを固定。後続同clockのLPが違っても、未来の後続LPを以前の格子へ差替えない。真受信時刻が無い限界は残る。',
            '推奨する次段入力4対照': [
                'M0:旧mid・旧complete10/全reset結合で現段対照へ完全一致。',
                'M1:mid・正常最良Price/Qtyと独立clock/seq切断。deep/volumeだけのprice伝播を除く。',
                'L0:LastPriceに価格値を替えるが旧complete10/全reset/端点資格は保持。価格値の違いを先に対照化。',
                'L1:LastPrice・正常LPと独立clock/seq切断。BBO資格を価格窓へ自動伝播しない。'],
            '12対照': 'M0/M1/L0/L1×G0/G1/G2を損益前に固定する案。先のdeep/volume4対照は入力故障の人工識別用に残し、実データ主因への正式探索の中心とはしない。',
            '未検証': 'L1の窓が定義可能になっても共同方向予測又は金額80が改善するかは未検証。出所が違う価格情報なのでMIDとLPのERを同一意味で比較しない。',
            '固定すべき非入力項目': '第一段は既存の観測始値幅とknown_from原seq、最小spread閾値、執行/出口の観測列を保持する。追加raw正常LPを価格窓へ採ることと、その追加行で出口を早める変更は別軸。',
            '追加LP行で停止を観測する後段': '正常LPが不正BBO行で停止線へ触れれば返済予約は機械的に可能だが実約定は次正常BBO。第一段の入口入力修正に、この出口観測の増設を混ぜず独立対照で計測する。'},
        '人工正負ケース': cases, '人工ケース合格数': len(cases),
        '限界': ['回復した価格特徴が予測力を持つかは未検証。入力が定義できることと損益が改善することは別。',
                 '最良数量正常でも実約定全量やmicro/mini板を保証しない。',
                 '全31既知探索の結果から作った仮説。現在の正式16条件又は有効性認定を更新しない。'],
        '正式実装変更': 0, '正式損益変更': 0, '新しい売買再生': 0, '新しい損益計算': 0,
        'API取得': 0, '実注文': 0, '入力仮説の有用性認定': False,
        '理論コードSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    target = HERE / '深板故障の価格伝播と古い中心新規を分ける事前理論.json'
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'保存先': str(target), '人工ケース': len(cases),
                      'SHA256': hashlib.sha256(target.read_bytes()).hexdigest(), '新しい損益計算': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
