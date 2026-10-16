"""十六対照の小会計・方向・寄与・場基準・公開尺度を、金融再生せず独立検算する。"""

from collections import Counter
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
import hashlib
import json
import math
import statistics
import traceback


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ENGINE = ROOT / 'work/e01_cross_market_20261014/engine'
BASELINE = 'E01_ANCHOR_W60_CONFIRM_D0_P1_L2_A1'
SYMBOLS = ('TOPIX', 'NK225')
FIELDS = ('収支変化', '避けた基準損失', '失った基準利益',
          '共通入口の数量/出口差', '新たな入口の収支')
PATHS = (
    ENGINE / 'finance/結果.json', ENGINE / '試行計画.json', ENGINE / '金融事前固定.json',
    HERE / '正式20源八部品と一回1056会計及び登録guardの独立接続.json',
    HERE / '同一E01の両商品差と再利用及び事後選択の敵対監査.json',
    ROOT / 'work/e01_cross_market_20261014/diagnosis/同母二商品43実親の原因射影.json',
)
READS = {}
COUNTS = Counter()


def read_once(path: Path) -> dict:
    """
    機能: 読取計画に列挙した小 JSON を同 bytes で各一読する。
    引数: path(Path) は正式結果・計画・固定・先行監査又は43親小射影。
    返り値: dict は保存内容。入力 packet・実台帳・原板を開かない。
    """
    assert path in PATHS and path not in READS
    saved = path.read_bytes()
    READS[path] = hashlib.sha256(saved).hexdigest()
    return json.loads(saved.decode('utf-8-sig'))


def same(actual: object, expected: object, label: str = '') -> None:
    """
    機能: 真偽・未知・文字列を保ったまま、有限の小会計値を許容誤差内で照合する。
    引数: actual/expected(object) は観測値と独立算術値、label(str) は不一致の識別名。
    返り値: None。不一致は例外とし、比較総数だけを増やす。
    """
    COUNTS['小値照合'] += 1
    if expected is None or isinstance(expected, (bool, str)):
        assert actual == expected, (label, actual, expected)
    elif isinstance(expected, (int, float)):
        assert actual is not None and math.isfinite(actual)
        assert math.isclose(actual, expected, abs_tol=1e-5, rel_tol=1e-11), (label, actual, expected)
    elif isinstance(expected, dict):
        for key, value in expected.items():
            same(actual[key], value, label + '/' + key)
    else:
        assert actual == expected, (label, actual, expected)


def ratio(top: float, bottom: float) -> float | None:
    """
    機能: 分母零を未定義として割合を計算する。
    引数: top/bottom(float) は分子と分母。
    返り値: float | None は比率又は未定義。無取引を成功に置換しない。
    """
    return top / bottom if bottom else None


def metrics(rows: list[dict]) -> dict:
    """
    機能: 完結親 net の正負を保存場から加算し、主金額指標を独立に求める。
    引数: rows(list[dict]) は同商品又は同期間の完結場小会計。
    返り値: dict は利益・損失・net・親数・平均勝負・費用・決済枚数の合計。
    """
    gain = math.fsum(r['利益'] for r in rows)
    loss = math.fsum(r['損失'] for r in rows)
    wins = sum(r['勝ち親'] for r in rows)
    losses = sum(r['負け親'] for r in rows)
    mean_win = ratio(gain, wins)
    mean_loss = ratio(loss, losses)
    base = dict(利益=gain, 損失=loss, 収支=gain-loss,
        親数=sum(r['親数'] for r in rows), 勝ち親=wins, 負け親=losses,
        零親=sum(r['零親'] for r in rows), PF=ratio(gain, loss),
        利益割合=ratio(gain, gain+loss), 平均利益=mean_win, 平均損失=mean_loss,
        平均損益比=ratio(mean_win, mean_loss) if mean_win is not None and mean_loss else None)
    active = [r for r in rows if r['親数'] > 0]
    positives = sorted((r['収支'] for r in rows if r['収支'] > 0), reverse=True)
    base.update(全場=len(rows), 活動場=len(active), 黒字場=len(positives),
        赤字場=sum(r['収支'] < 0 for r in rows), 無取引場=len(rows)-len(active),
        中央値=statistics.median(r['収支'] for r in rows) if rows else float('nan'),
        活動場中央値=statistics.median(r['収支'] for r in active) if active else None,
        上位3利益場除外収支=gain-loss-math.fsum(positives[:3]),
        最大場損失=max([0.] + [-r['収支'] for r in rows if r['収支'] < 0]),
        費用=sum(r['費用'] for r in rows), 新規枚数=sum(r['新規枚数'] for r in rows),
        勝ち枚数=sum(r['勝ち枚数'] for r in rows), 負け枚数=sum(r['負け枚数'] for r in rows),
        零枚数=sum(r['零枚数'] for r in rows), 全33黒字=len(positives) == len(rows))
    return base


def stability(rows: list[dict]) -> dict:
    """
    機能: 全場分母・活動場分母・金額65・赤字20・平均黒字一場で補填の定義を独立計算する。
    引数: rows(list[dict]) は同商品完了場。
    返り値: dict は独立三基準と参照分母。全場の零収支を黒字に数えない。
    """
    net = [r['収支'] for r in rows]
    positive = [n for n in net if n > 0]
    negative = [n for n in net if n < 0]
    gain = math.fsum(r['利益'] for r in rows)
    loss = math.fsum(r['損失'] for r in rows)
    share = ratio(gain, gain+loss)
    active = sum(r['親数'] > 0 for r in rows)
    mean = math.fsum(positive)/len(positive) if positive else None
    worst = max([0.] + [-n for n in negative])
    red = len(negative)/len(rows) if rows else None
    t65 = share is not None and share >= .65
    tr20 = red is not None and red <= .2
    twm = mean is not None and worst <= mean
    return dict(session_count=len(rows), active_sessions=active,
        positive_sessions=len(positive), losing_sessions=len(negative),
        no_trade_sessions=len(rows)-active, flat_active_sessions=active-len(positive)-len(negative),
        red_full_rate=red, red_active_rate=ratio(len(negative), active), profit_share=share,
        mean_positive_session_net_yen=mean, worst_negative_session_abs_yen=worst,
        target65=t65, target_red20=tr20, target_worst_mean=twm,
        all_targets=t65 and tr20 and twm)


def fee(q: int, symbol: str) -> int:
    """
    機能: 公開受理 q の片道注文料を、整数円 floor で独立算術する。
    引数: q(int) は枚数、symbol(str) は商品。
    返り値: int は税込注文料。料金は出口線と清算値で重複徴収しない。
    """
    unit = Decimal('41.8') if symbol == 'TOPIX' else Decimal('11')
    return int((unit * q).to_integral_value(rounding=ROUND_FLOOR))


def lines(boundary: dict, config: dict) -> dict:
    """
    機能: 小境界の初受理 q・公開 ATR・spread から固定円線を独立換算する。
    引数: boundary/config(dict) は小境界と正式条件。
    返り値: dict は利益・損失・始動・追跡・floor の円額。受理なしは全て None。
    """
    symbol = boundary['symbol']
    anchor = boundary['exit_boundary']['anchor']
    result = dict(target_yen=None, hard_loss_yen=None, arm_yen=None,
        drawdown_yen=None, floor_yen=None, quantity_selection_budget_yen=5000 if symbol == 'TOPIX' else 2000)
    if anchor is None:
        return result
    q = anchor['quantity']
    full = 5 if symbol == 'TOPIX' else 10
    value = 1000 if symbol == 'TOPIX' else 10
    tick = .5 if symbol == 'TOPIX' else 10
    assert type(q) is int and 0 < q <= full and anchor['full_quantity'] == full
    risk = q * anchor['published_atr'] * value
    spread_cost = q * anchor['published_spread'] * value + 2 * fee(q, symbol)
    assert anchor['published_atr'] > 0 and anchor['published_spread'] > 0
    same(anchor['atr_yen'], risk, '初受理R')
    same(anchor['spread_fee_yen'], spread_cost, '初受理気配費用')
    same(anchor['roundtrip_fee_yen'], 2*fee(q, symbol), '初受理往復floor料')
    same(anchor['multiplier'], value)
    p1 = q * tick * value
    result['hard_loss_yen'] = result['quantity_selection_budget_yen'] if config['hard_basis'] == 'BUDGET' else config['hard_multiple']*risk + spread_cost
    if config['exit_kind'] == 'fixed':
        basis = config['target_basis']
        result['target_yen'] = config['target_multiple']*risk if basis == 'ATR' else p1 if basis == 'P1' else p1-2*fee(q, symbol)
    else:
        result['arm_yen'] = p1 if config['arm_basis'] == 'P1' else config['arm_multiple']*risk
        result['drawdown_yen'] = config['draw_multiple']*risk
        result['floor_yen'] = config['floor_yen']
    return result


# ----------------------------------------
def main() -> None:
    """
    機能: 根の正式終端0通知後だけ小結果を一読し、1056場と128期間及び尺度を監査する。
    引数: なし。読取対象は冒頭 PATHS に列挙した小 JSON のみ。
    返り値: None。自所有の scope と成功/失敗証跡を保存し共有資料は変更しない。
    """
    scope_path = HERE / '十六対照1056小会計の独立読取計画.json'
    output_path = HERE / '十六対照1056小会計と128期間及び受理円尺度の独立監査.json'
    false_path = HERE / '十六対照1056小会計の独立監査False.json'
    assert not any(p.exists() for p in (scope_path, output_path, false_path))
    scope_path.write_text(json.dumps(dict(根終端0通知後=True,
        小JSON各一読=[p.relative_to(ROOT).as_posix() for p in PATHS],
        予定=dict(小会計=1056,期間商品集計=128,五寄与場=1056,受理境界=1056),
        留保='新実親詳細は保存小結果に無い。親別寄与分類の独立再走査や物理fillの証明はしない。',
        packet=0,ledger=0,原板=0,NPZ=0,金融再実行=0,API=0),
        ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    try:
        result, plan, fixed, preaudit, old, cause = (read_once(p) for p in PATHS)
        assert result['全合格'] and result['source開始終端一致'] and preaudit['全合格'] and old['全合格'] and cause['全合格']
        assert READS[PATHS[5]] == 'e8451fd00380d04199072443f4f6c04e6561de039bad20e6b698a59a8279da73'
        assert len(result['sessions']) == 33 and result['sessions'] == fixed['sessions']
        assert result['configs'] == fixed['configs'] == plan['spec']['entry']['conditions']
        assert READS[PATHS[1]] == fixed['計画SHA256']
        assert len(result['configs']) == 16
        assert result['source_SHA256'] == fixed['source_SHA256'] == plan['spec']['implementation']
        assert result['case_SHA256'] == fixed['case_SHA256']
        for path, expected in result['source_SHA256'].items():
            assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == expected
        assert len(result['source_SHA256']) == 20
        expected_counts = dict(既input一読=33,旧P1台帳一読=66,保存GU再利用=66,
            新GUengine=264,新政策会計=1056,旧基準経済同値確認=66)
        assert result['counts'] == expected_counts
        for key, expected in dict(会計口座数=1056,新GUengine=264,保存GU再利用=66,旧基準経済同値確認=66,
            原板=0,NPZ=0,API=0,現在入力=0,旧金融再生=0).items():
            same(result[key], expected, key)
        baseline = {(s, symbol):r for symbol in SYMBOLS for r in old['保存全場'][symbol] for s in [r['session']]}
        assert len(baseline) == 66 and old['条件'] == BASELINE
        for symbol in SYMBOLS:
            assert len([r for r in baseline.values() if r['symbol'] == symbol]) == 33
        stats = {}
        boundaries_checked = {}
        direction_splits = {}
        contributions = {}
        sessions = result['sessions']
        all_full_pass = {s:[] for s in SYMBOLS}
        robust_pass = {s:[] for s in SYMBOLS}
        both_positive = []
        alias = result['初回受理と費用後目標境界']
        assert alias == result['boundary']
        for config in result['configs']:
            cid = config['id']
            saved = result['results'][cid]
            rows = saved['rows']
            assert len(rows) == len(saved['ledgers']) == 66
            row_map = {(r['session'], r['symbol']):r for r in rows}
            assert set(row_map) == set(baseline)
            assert len({(p['session'], p['symbol']) for p in saved['ledgers']}) == 66
            for row in rows:
                assert row['全会計合格'] is True
                same(row['利益']-row['損失'], row['収支'], cid + '/場net')
                assert row['利益'] >= 0 and row['損失'] >= 0 and row['費用'] >= 0
                same(row['勝ち親']+row['負け親']+row['零親'], row['親数'], '完結親母数')
                same(row['勝ち枚数']+row['負け枚数']+row['零枚数'], row['新規枚数'], '決済枚数保存')
                assert row['最大買枚数'] <= (10 if row['symbol'] == 'TOPIX' else 20)
                assert row['最大売枚数'] <= (10 if row['symbol'] == 'TOPIX' else 20)
                same(row['PF'], ratio(row['利益'], row['損失']), '場PF')
                same(row['利益割合'], ratio(row['利益'], row['利益']+row['損失']), '場金額比')
                same(row['平均利益'], ratio(row['利益'], row['勝ち親']), '場平均利益')
                same(row['平均損失'], ratio(row['損失'], row['負け親']), '場平均損失')
                if row['親数'] == 0:
                    for key in ('利益','損失','収支','費用','新規枚数','注文件数'):
                        same(row[key], 0, '無取引')
                COUNTS['小会計'] += 1
            deltas = result['各場寄与'][cid]
            assert len(deltas) == 66
            assert {(d['session'],d['symbol']) for d in deltas} == set(baseline)
            for d in deltas:
                key = (d['session'],d['symbol'])
                assert d['baseline_id'] == BASELINE
                same(d['収支変化'], row_map[key]['収支']-baseline[key]['収支'], '基準との場差')
                same(d['収支変化'], d['避けた基準損失']-d['失った基準利益']+d['共通入口の数量/出口差']+d['新たな入口の収支'], '五寄与恒等式')
                assert d['避けた基準損失'] >= 0 and d['失った基準利益'] >= 0
                for p in d['元勝ち親が赤字化']:
                    assert p['old_net'] > 0 and p['new_net'] < 0
                COUNTS['五寄与場'] += 1
            stats[cid] = {}
            contributions[cid] = {}
            direction_splits[cid] = {}
            for symbol in SYMBOLS:
                own = [r for r in rows if r['symbol'] == symbol]
                assert [r['session'] for r in own] == sessions
                full = metrics(own)
                same(saved['symbols'][symbol], full, cid + '/' + symbol + '/全33集計')
                top = sorted((r for r in own if r['収支']>0),key=lambda r:(-r['収支'],r['session']))[:3]
                excluded = {r['session'] for r in top}
                scopes = {'全33':sessions,'前16':sessions[:16],'後17':sessions[16:],
                    '上位3正収支場除外':[s for s in sessions if s not in excluded]}
                periods = {}
                for name, selected in scopes.items():
                    subset = [r for r in own if r['session'] in selected]
                    agg = metrics(subset)
                    goal = stability(subset)
                    current = saved['periods'][symbol][name]
                    assert current['sessions'] == selected
                    same(current['aggregate'], agg, cid+'/'+symbol+'/'+name+'/集計')
                    same(current['stability'], goal, cid+'/'+symbol+'/'+name+'/基準')
                    periods[name] = dict(金額=agg,基準=goal)
                    COUNTS['期間商品集計'] += 1
                assert saved['periods'][symbol]['除外場'] == [r['session'] for r in top]
                same(saved['stability'][symbol], periods['全33']['基準'])
                stats[cid][symbol] = dict(期間=periods,除外場=[r['session'] for r in top])
                if periods['全33']['基準']['all_targets']:
                    all_full_pass[symbol].append(cid)
                if periods['上位3正収支場除外']['基準']['all_targets']:
                    robust_pass[symbol].append(cid)
                direction = saved['directional_symbols'][symbol]
                for side in ('long','short'):
                    m = direction[side]
                    same(m['利益']-m['損失'],m['収支'],'方向net')
                    same(m['勝ち親']+m['負け親']+m['零親'],m['親数'],'方向親母数')
                    same(m['PF'],ratio(m['利益'],m['損失']),'方向PF')
                    same(m['利益割合'],ratio(m['利益'],m['利益']+m['損失']),'方向比')
                    same(m['平均利益'],ratio(m['利益'],m['勝ち親']),'方向平均勝')
                    same(m['平均損失'],ratio(m['損失'],m['負け親']),'方向平均敗')
                for key in ('利益','損失','収支','親数','勝ち親','負け親','零親'):
                    same(direction['long'][key]+direction['short'][key],full[key],'方向小計と全親')
                same(direction['long']['枚数']+direction['short']['枚数'], full['新規枚数'], '方向新規枚数')
                leg = saved['actual_leg_symbols'][symbol]
                same(leg['利益']-leg['損失'],full['収支'],'実玉netと親net')
                same(leg['勝ち親']+leg['負け親']+leg['零親'],leg['親数'],'実玉母数')
                direction_splits[cid][symbol] = direction
                summed = {f:math.fsum(d[f] for d in deltas if d['symbol']==symbol) for f in FIELDS}
                same(result['diagnosis'][cid][symbol],summed,'商品別五寄与')
                same(result['diagnosis'][cid][symbol]['元勝ち親が赤字化'],
                    sum(len(d['元勝ち親が赤字化']) for d in deltas if d['symbol']==symbol),'赤字化数')
                contributions[cid][symbol] = summed
            if all(stats[cid][s]['期間']['全33']['金額']['収支']>0 for s in SYMBOLS):
                both_positive.append(cid)
            boundaries = result['boundary'][cid]
            assert len(boundaries) == 66 and {(b['session'],b['symbol']) for b in boundaries} == set(baseline)
            by_status = Counter()
            for b in boundaries:
                key = (b['session'], b['symbol'])
                row = row_map[key]
                anchor = b['anchor']
                source_anchor = b['exit_boundary']['anchor']
                calculated = lines(b,config)
                same(b['exit_boundary'],calculated,cid+'/円線')
                same(b['目標円'],calculated['target_yen'])
                same(b['損失予算円'],calculated['hard_loss_yen'])
                same(b['新規数量選択予算円'],calculated['quantity_selection_budget_yen'])
                same(anchor['成立'], source_anchor is not None)
                if source_anchor is None:
                    for name in ('数量','受理行','受理原seq','受理価格時計','紙上親','利益目標円'):
                        same(anchor[name],None,'未受理')
                    assert row['親数']==0 and not b['停止判断']['発動']
                    by_status['未受理'] += 1
                else:
                    for field, sourcefield in (('数量','quantity'),('受理行','row'),('受理原seq','raw_seq'),
                        ('受理価格時計','price_time_s'),('紙上親','parent'),('通常全量','full_quantity')):
                        same(anchor[field],source_anchor[sourcefield],'初回受理境界')
                    by_status['受理'] += 1
                    control = b['停止判断']
                    if control['発動']:
                        assert control['判断行'] >= anchor['受理行']
                        assert control['判断原seq'] >= anchor['受理原seq']
                        assert control['判断価格時計'] >= anchor['受理価格時計']
                        assert control['返済行'] >= control['判断行']
                        assert control['返済原seq'] >= control['判断原seq']
                        assert control['返済価格時計'] >= control['判断価格時計']
                        same(control['実返済後収支'],row['収支'],'返済後net')
                        same(control['判断から返済の悪化'], row['収支']-control['判断時清算利益'],'判断fill差')
                        assert control['以後新規なし'] is True and control['未来返済テンプレート参照'] is False
                        by_status[control['種別']] += 1
                    else:
                        by_status['受理後通常完了'] += 1
                COUNTS['受理境界'] += 1
            boundaries_checked[cid] = dict(by_status)
        assert COUNTS['小会計'] == COUNTS['五寄与場'] == COUNTS['受理境界'] == 1056
        assert COUNTS['期間商品集計'] == 128
        both_full = sorted(set(all_full_pass['TOPIX']) & set(all_full_pass['NK225']))
        both_robust = sorted(set(robust_pass['TOPIX']) & set(robust_pass['NK225']))
        output = dict(全合格=True,評価='小会計と固定条件の監査合格。有用性や未知成功とは別。',
            正式結果SHA256=READS[PATHS[0]],
            小JSON一読SHA256={p.relative_to(ROOT).as_posix():h for p,h in READS.items()},
            検査=dict(COUNTS),正式実行数=expected_counts,
            商品別全33合格=all_full_pass,商品別上位3除外合格=robust_pass,
            両商品全33三基準合格=both_full,両商品上位3除外三基準合格=both_robust,
            両商品合計黒字=both_positive,商品と期間=stats,方向副表=direction_splits,
            五寄与=contributions,受理と停止件数=boundaries_checked,
            定義='主利益/損失は完結実親net正負。赤字は全33分母、最大赤字は平均黒字場netと比較。無取引は黒字又は勝ちに含めない。',
            留保=['個別新親が小結果に無いため五寄与の親別分類を独立再走査していない。恒等式・商品小計・基準との差を確認した。',
                '方向副表は実親の開始方向別。日自体の上昇/下落状態や方向の未知精度を証明していない。',
                '実玉net正負と完結親net正負は異なる母数。利益8割又は65%の主評価を玉で置換していない。',
                '初受理q/ATR/気配線の算術と小保存時計を確認。normal nextfillや全親uidを新実台帳で独立再トレースしていない。',
                '16係数は同じ既知33の43親原因を見た後の対照。未知日成功や独立16回の再現とは呼ばない。',
                '現在の API の再取得、原板、NPZ、packet、台帳、金融再実行は全て0。'],
            独立source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            原板=0,NPZ=0,packet=0,ledger=0,金融再実行=0,API=0,共有docs又は金融源変更=0)
        output_path.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,検査=dict(COUNTS),両商品合計黒字=both_positive,
            両商品全33三基準合格=both_full,商品別全33合格=all_full_pass,
            SHA256=hashlib.sha256(output_path.read_bytes()).hexdigest()),ensure_ascii=False))
    except Exception:
        false_path.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),
            小JSON読取SHA256={p.relative_to(ROOT).as_posix():h for p,h in READS.items()},
            検査=dict(COUNTS),金融再実行=0,自動再実行=False),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__ == '__main__':
    main()
