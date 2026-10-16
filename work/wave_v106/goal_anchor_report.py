"""初回受理数量に合わせた利確四対照を、完成小会計から短く報告する。"""

import argparse
import hashlib
import html
import json
from pathlib import Path
import statistics

import e01_trade_report
import range_report
import risk_sizing_report
import trade_report

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = range_report.PUBLIC
TITLE = '枚数に合わせた利確修正と全セッション損益'
ACCOUNTING_TITLE = '枚数に合わせた利確修正4比較の公開会計.json'
SOURCE = HERE/'e01_size_goal_anchor/finance/結果.json'
FIXED = HERE/'e01_size_goal_anchor/金融事前固定.json'
PLAN = HERE/'e01_size_goal_anchor/試行計画.json'
OLD_SOURCE = HERE/'e01_risk_sizing/finance/結果.json'
SYMBOLS = ('TOPIX', 'NK225')
LABELS = risk_sizing_report.LABELS
TESTS = risk_sizing_report.TESTS
FIVE = ('収支変化', '避けた基準損失', '失った基準利益', '共通入口の数量/出口差', '新たな入口の収支')


def read(path: Path) -> tuple:
    """
    機能: 完成小JSONを同bytesで読み、その指紋を返す。
    引数: path(Path)は新結果、正式計画・固定又は直近比較結果。
    返り値: tuple[dict,str]は保存内容とSHA256。台帳・packet・金融は読まない。
    """
    saved = path.read_bytes()
    return json.loads(saved.decode('utf-8-sig')), hashlib.sha256(saved).hexdigest()


def case_hashes(configs: list) -> dict:
    """
    機能: 条件全体の正規JSON指紋を、正式runnerと同じ定義で求める。
    引数: configs(list[dict])は四固定条件。
    返り値: dict[str,str]はIDとSHA256。金融moduleをimportしない。
    """
    result = {}
    for c in configs:
        assert c['id'] not in result
        saved = json.dumps(c, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
        result[c['id']] = hashlib.sha256(saved).hexdigest()
    return result


def summaries(rows: list) -> tuple:
    """
    機能: 主金額・三基準と、利益上位三場を除外した同商品指標を計算する。
    引数: rows(list[dict])は66保存口座を対応した共通schema。
    返り値: tuple[dict,dict]は全33と除外後。無取引を勝ちへ数えない。
    """
    full, trimmed = {}, {}
    for s in SYMBOLS:
        own = [r for r in rows if r['symbol'] == s]
        assert len(own) == 33
        full[s] = risk_sizing_report.statistics_for(rows, s)
        control = variable_summary(own, s)
        for field in ('profit', 'loss', 'net', 'profit_share', 'positive', 'negative', 'active', 'no_trade',
                      'mean_positive_session_net', 'worst_session_loss', 'red_all', 'red_active'):
            a, b = full[s][field], control[field]
            assert (a is b) if a is None or b is None else abs(a-b) < 1e-5
        assert full[s]['tests'] == control['tests']
        removed = sorted((r for r in own if r['net'] > 0), key=lambda r: (-r['net'], r['session']))[:3]
        removed_sessions = {r['session'] for r in removed}
        tail = [r for r in own if r['session'] not in removed_sessions]
        assert len(tail) == 33-len(removed)
        value = variable_summary(tail, s)
        assert abs(value['net']-full[s]['top3_excluded']) < 1e-5
        value.update(sessions=len(tail), removed_sessions=[r['session'] for r in removed])
        trimmed[s] = value
    return full, trimmed


def variable_summary(rows: list, symbol: str) -> dict:
    """
    機能: 上位三場除外後の任意場数について、最新三基準と金額を純集計する。
    引数: rows(list[dict])、symbol(str)は保存小会計と対象商品。
    返り値: dictは除外後指標。33場固定の旧関数を変更しない。
    """
    own = [r for r in rows if r['symbol'] == symbol]
    assert own
    nets = [r['net'] for r in own]
    profits, losses = sum(r['profit'] for r in own), sum(r['loss'] for r in own)
    green = [v for v in nets if v > 0]
    red = sum(v < -1e-5 for v in nets)
    active = sum(r['campaigns'] > 0 for r in own)
    mean = statistics.mean(green) if green else None
    worst = max([0.]+[-v for v in nets if v < 0])
    share = profits/(profits+losses) if profits+losses else None
    tests = {TESTS[0]: share is not None and share >= .65,
             TESTS[1]: red/len(own) <= .2,
             TESTS[2]: mean is not None and worst <= mean}
    assert abs(profits-losses-sum(nets)) < 1e-4
    return dict(profit=profits, loss=losses, net=profits-losses, profit_share=share,
        positive=sum(v > 1e-5 for v in nets), negative=red, active=active, no_trade=len(own)-active,
        median=statistics.median(nets), mean_positive_session_net=mean, worst_session_loss=worst,
        red_all=red/len(own), red_active=red/active if active else None, tests=tests, pass_all=all(tests.values()),
        winning_lots=sum(r['winning_lots'] for r in own), losing_lots=sum(r['losing_lots'] for r in own))


def saved_check(value: dict, saved: dict) -> None:
    """
    機能: 表示用再集計を金融保存の同商品合計へ照合する。
    引数: value/saved(dict)は表示指標と保存symbols。
    返り値: None。異なる枚数・金額定義を混ぜない。
    """
    for a, b in (('profit', '利益'), ('loss', '損失'), ('net', '収支'), ('winning_lots', '勝ち枚数'), ('losing_lots', '負け枚数')):
        assert abs(value[a]-saved[b]) < 1e-5, (a, value[a], saved[b])
    assert value['positive'] == saved['黒字場'] and value['negative'] == saved['赤字場'] and value['no_trade'] == saved['無取引場']
    assert abs(value['top3_excluded']-saved['上位3利益場除外収支']) < 1e-5


def anchors(rows: list, config: dict) -> dict:
    """
    機能: 当時受理した数量・一回固定目標・実新規無しを、保存66境界から検算する。
    引数: rows(list[dict])、config(dict)は当該条件の境界小保存と固定条件。
    返り値: dictは商品別分布。取消後の実fill数量をアンカーへ置換しない。
    """
    assert len(rows) == len({(r['session'], r['symbol']) for r in rows}) == 66
    result = {}
    for s in SYMBOLS:
        own = [r for r in rows if r['symbol'] == s]
        assert len(own) == 33
        accepted, goals, quantities = [], [], []
        for r in own:
            a = r['anchor']; original = config['profit_goal_yen'][s]; full = config['quantity'][s]
            assert a['通常全量'] == full and a['元利益目標円'] == original and r['損失予算円'] == config['loss_budget_yen'][s]
            assert r['停止判断']['目標'] == r['目標円'] and r['停止判断']['損失予算'] == r['損失予算円']
            if not a['成立']:
                assert all(a[k] is None for k in ('数量', '利益目標円', '受理行', '受理原seq', '受理価格時計', '紙上親'))
                assert r['実政策初回新規'] is None and r['目標円'] is None and r['受理行の費用後清算円'] is None
                continue
            q = a['数量']; assert isinstance(q, int) and 0 < q <= full
            assert a['利益目標円'] == original*q/full == r['目標円']
            assert isinstance(a['受理行'], int) and a['受理行'] >= 0
            if r['停止判断']['発動']:
                assert r['停止判断']['判断行'] >= a['受理行']
            if r['実政策初回新規'] is not None:
                first = r['実政策初回新規']
                assert first['source_row'] >= a['受理行'] and first['row'] > first['source_row']
            accepted.append(r); quantities.append(q); goals.append(a['利益目標円'])
        result[s] = dict(受理あり=len(accepted), 受理なし=33-len(accepted),
            受理あり実新規なし=sum(r['実政策初回新規'] is None for r in accepted),
            初回受理q最小=min(quantities) if quantities else None, 初回受理q最大=max(quantities) if quantities else None,
            固定目標最小=min(goals) if goals else None, 固定目標最大=max(goals) if goals else None,
            元固定円目標=config['profit_goal_yen'][s], 損失枠=config['loss_budget_yen'][s])
    return result


def build(finance: dict, fixed: dict, plan: dict, previous: dict, sources: dict) -> dict:
    """
    機能: 完成四会計を正式固定・source・同母旧数量版へ束縛し、表示用値を作る。
    引数: finance/fixed/plan/previous/sources(dict)は新結果、正式固定計画、旧結果と直接指紋。
    返り値: dictは公開小会計。結果不足時に仮金額や達成数を作らない。
    """
    assert finance['全合格'] and fixed['全合格'] and previous['全合格'] and plan['正式freeze']
    assert finance['source開始終端一致'] and previous['source開始終端一致']
    assert finance['source_SHA256'] == fixed['source_SHA256'] == plan['spec']['implementation']
    assert sources[PLAN.relative_to(ROOT).as_posix()] == fixed['計画SHA256']
    assert finance['configs'] == fixed['configs'] == plan['spec']['entry']['conditions']
    assert case_hashes(finance['configs']) == finance['case_SHA256'] == fixed['case_SHA256']
    assert finance['新GUengine'] == 132 and finance['新政策会計'] == finance['会計口座数'] == 264
    assert finance['counts'] == dict(既input一読=33, 新GUengine=132, 新政策会計=264, 旧数量台帳一読=264)
    assert finance['元paper再計算'] == finance['旧金融再生'] == finance['原板読取'] == finance['NPZ読取'] == finance['現在入力読取'] == finance['API'] == 0
    assert finance['保存旧代表'] == fixed['旧fullP1L8参考rows']
    sessions = finance['sessions']; assert sessions == fixed['sessions'] and len(sessions) == len(set(sessions)) == 33
    configs = {c['id']: c for c in finance['configs']}; assert len(configs) == 4 and set(configs) == set(finance['results'])
    cases = {}
    for ident, raw in finance['results'].items():
        config = configs[ident]; reference = fixed['comparisons'][ident]
        baseline_id = config['baseline_id']; before = previous['results'][baseline_id]
        assert reference['id'] == baseline_id and reference['rows'] == before['rows'] and reference['symbols'] == before['symbols']
        assert reference['source'] == OLD_SOURCE.relative_to(ROOT).as_posix() and reference['SHA256'] == sources[reference['source']]
        old_config = next(c for c in previous['configs'] if c['id'] == baseline_id)
        assert all(config[k] == old_config[k] for k in ('mode', 'window_seconds', 'execution', 'offset_atr', 'profit_ticks', 'loss_ticks', 'risk_atr_multiple', 'quantity', 'cap', 'profit_goal_yen', 'loss_budget_yen'))
        rows = [e01_trade_report.mapped(r) for r in raw['rows']]
        old_rows = [e01_trade_report.mapped(r) for r in before['rows']]
        assert len(rows) == len({(r['session'], r['symbol']) for r in rows}) == 66 and {r['session'] for r in rows} == set(sessions)
        summary, top3 = summaries(rows); old_summary, old_top3 = summaries(old_rows)
        changes = finance['各場寄与'][ident]
        assert len(changes) == len({(r['session'], r['symbol']) for r in changes}) == 66
        for s in SYMBOLS:
            saved_check(summary[s], raw['symbols'][s]); saved_check(old_summary[s], before['symbols'][s])
            assert abs(raw['actual_leg_symbols'][s]['収支']-summary[s]['net']) < 1e-5
            own = [r for r in changes if r['symbol'] == s]; assert len(own) == 33
            expected = finance['diagnosis'][ident][s]
            for f in FIVE:
                assert abs(sum(r[f] for r in own)-expected[f]) < 1e-5
            assert expected['元勝ち親が赤字化'] == sum(len(r['元勝ち親が赤字化']) for r in own)
            assert abs(expected['収支変化']-(summary[s]['net']-old_summary[s]['net'])) < 1e-5
            assert abs(expected['収支変化']-(expected['避けた基準損失']-expected['失った基準利益']+expected['共通入口の数量/出口差']+expected['新たな入口の収支'])) < 1e-5
            assert all(r['baseline_id'] == baseline_id for r in own)
        boundary = finance['初回受理と費用後目標境界'][ident]
        cases[ident] = dict(config=config, rows=rows, summary=summary, top3=top3,
            comparison=dict(id=baseline_id, rows=old_rows, summary=old_summary, top3=old_top3),
            diagnosis=finance['diagnosis'][ident], actual_legs=raw['actual_leg_symbols'],
            anchor_rows=boundary, anchor_summary=anchors(boundary, config))
    return dict(全合格=True, title=TITLE, sessions=sessions, cases=cases, sources=sources,
        both_net_positive=sum(all(c['summary'][s]['net'] > 0 for s in SYMBOLS) for c in cases.values()),
        both_goal_pass=sum(all(c['summary'][s]['pass_all'] for s in SYMBOLS) for c in cases.values()),
        both_test_counts={k: sum(all(c['summary'][s]['tests'][k] for s in SYMBOLS) for c in cases.values()) for k in TESTS},
        criterion=dict(金額利益割合=.65, 赤字全場割合=.2, 一場損失='最大赤字場net絶対額<=平均黒字場net'),
        金融source_SHA256=finance['source_SHA256'], case_SHA256=finance['case_SHA256'],
        定義=dict(金額='完結実親netの利益・損失', 枚数='実決済玉の勝ち・負け枚数', 無取引='勝ちに含めない',
            アンカー='最初の受理公開qで一度固定。約定取消でも保持、後の実qに交換しない。'),
        新金融再生=0, API取得=0, packet読取=0, ledger読取=0, 原板読取=0, NPZ読取=0)


# ----------------------------------------
def overview(data: dict) -> str:
    """
    機能: 四条件二商品の利益・損失・収支と最新三基準を八行へ表示する。
    引数: data(dict)は検算済み公開会計。
    返り値: strは概要HTML。全商品金額を合算して評価しない。
    """
    rows = []
    for ident, case in data['cases'].items():
        for s in SYMBOLS:
            v = case['summary'][s]
            status = ' / '.join('達成' if v['tests'][k] else '未達' for k in TESTS)
            rows.append('<tr data-case-id="'+html.escape(ident, quote=True)+'" data-symbol="'+s+'"><td>'+risk_sizing_report.label(case['config'])+'<small>'+html.escape(ident)+'</small></td><td>'+LABELS[s]+'</td>'+range_report.cell(v['profit'])+range_report.cell(v['loss'], True)+range_report.cell(v['net'])+'<td>'+risk_sizing_report.percent(v['profit_share'])+'</td><td>'+str(v['negative'])+'/33 ('+risk_sizing_report.percent(v['red_all'])+')</td><td>'+range_report.number(v['mean_positive_session_net'], 1)+'</td>'+range_report.cell(v['worst_session_loss'], True)+'<td>'+status+'</td><td>'+str(v['positive'])+'/'+str(v['negative'])+'/'+str(v['no_trade'])+'</td></tr>')
    return '<div class="scroll"><table id="overview"><thead><tr><th>条件</th><th>商品</th><th>利益（円）</th><th>損失（円）</th><th>収支（円）</th><th>金額利益割合</th><th>赤字/全33場</th><th>平均黒字net（円）</th><th>最大赤字（円）</th><th>割合 / 赤字率 / 一場損失</th><th>黒字/赤字/無取引</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'


def explanation(config: dict) -> str:
    """
    機能: 元入口、当時受理アンカー、利確とL2不変を三行で説明する。
    引数: config(dict)は正式固定条件。
    返り値: strは短い説明HTML。未来ピークを判断条件へ使わない。
    """
    gate = '同方向を確認' if config['mode'] == 'CONFIRM' else '強い逆票を回避'
    return '<p><b>入口：</b><a href="../00044_新候補2手法と基準の説明と損益/新候補2手法の説明と損益.html">元E01</a>の候補で直近60代理秒の更新票により'+gate+'。ATR・気配差・料と残予算から実qを決め、次正常気配で新規。</p><p><b>途中：</b>最初に新規注文を受理した公開q÷通常5枚/10枚で、その場のP'+str(config['profit_ticks'])+'利益目標を一度だけ比例固定。未約定で取り消されても保持し、後のqへ交換しない。</p><p><b>出口：</b>固定した利益目標又は不変L2（TOPIX5,000円・日経2,000円）へ先に達したら次正常気配で残玉返済し場停止。元の影・途中返済・数量計算・費用・場内返済は維持する。</p>'


def details(case: dict) -> str:
    """
    機能: 同母固定円版との比較、上位三場除外、五寄与及び目標固定分布を折り畳む。
    引数: case(dict)は検算済み一条件。
    返り値: strは補足HTML。事後利益ピークや仮想救済PLを載せない。
    """
    compare, trim, change, anchor = [], [], [], []
    for s in SYMBOLS:
        v, old = case['summary'][s], case['comparison']['summary'][s]
        compare.append('<tr><td>'+LABELS[s]+'</td>'+range_report.cell(v['net'])+range_report.cell(old['net'])+range_report.cell(v['net']-old['net'])+'<td>'+str(v['positive'])+'/'+str(old['positive'])+'</td><td>'+str(v['negative'])+'/'+str(old['negative'])+'</td><td>'+risk_sizing_report.percent(v['profit_share'])+' / '+risk_sizing_report.percent(old['profit_share'])+'</td></tr>')
        for label, source in (('利確修正', case), ('固定円版', case['comparison'])):
            full, tail = source['summary'][s], source['top3'][s]
            trim.append('<tr><td>'+label+'</td><td>'+LABELS[s]+'</td>'+range_report.cell(full['median'])+range_report.cell(tail['net'])+'<td>'+risk_sizing_report.percent(tail['profit_share'])+'</td><td>'+str(tail['negative'])+'/'+str(tail['sessions'])+'</td><td>'+range_report.number(tail['mean_positive_session_net'], 1)+'</td>'+range_report.cell(tail['worst_session_loss'], True)+'</tr>')
        d = case['diagnosis'][s]
        change.append('<tr><td>'+LABELS[s]+'</td>'+''.join(range_report.cell(d[f], f == '失った基準利益') for f in FIVE)+'<td>'+str(d['元勝ち親が赤字化'])+'</td></tr>')
        a = case['anchor_summary'][s]
        anchor.append('<tr><td>'+LABELS[s]+'</td><td>'+str(a['受理あり'])+'/33</td><td>'+str(a['受理あり実新規なし'])+'</td><td>'+range_report.number(a['初回受理q最小'])+'〜'+range_report.number(a['初回受理q最大'])+'</td><td>'+range_report.number(a['固定目標最小'])+'〜'+range_report.number(a['固定目標最大'])+'</td><td>'+range_report.number(a['元固定円目標'])+'</td><td>'+range_report.number(a['損失枠'])+'</td></tr>')
    return '<details><summary>直前の固定円サイズ版との比較</summary><small>'+html.escape(case['comparison']['id'])+'。母条件・P1/P2・L2が同じ。</small><div class="scroll"><table class="fixed-comparison"><thead><tr><th>商品</th><th>新収支</th><th>旧収支</th><th>差額</th><th>黒字場 新/旧</th><th>赤字場 新/旧</th><th>金額利益割合 新/旧</th></tr></thead><tbody>'+''.join(compare)+'</tbody></table></div></details><details><summary>上位3利益場を除いても成り立つか</summary><div class="scroll"><table class="top3"><thead><tr><th>比較</th><th>商品</th><th>全33中央値</th><th>利益上位3場除外収支</th><th>除外後金額割合</th><th>除外後赤字場</th><th>除外後平均黒字net</th><th>除外後最大赤字</th></tr></thead><tbody>'+''.join(trim)+'</tbody></table></div></details><details><summary>入口入替と共通親の寄与（円）</summary><div class="scroll"><table><thead><tr><th>商品</th><th>収支差</th><th>避けた損失</th><th>失った利益</th><th>共通親の数量/出口差</th><th>新後続収支</th><th>旧勝ち親の赤字化</th></tr></thead><tbody>'+''.join(change)+'</tbody></table></div></details><details><summary>最初の受理qと固定目標</summary><p class="note">受理と約定は別。受理無しは目標未定義、無取引を勝ちに含めない。</p><div class="scroll"><table class="anchors"><thead><tr><th>商品</th><th>受理あり</th><th>受理あり実新規なし</th><th>初回受理q範囲</th><th>比例目標範囲（円）</th><th>元固定目標（円）</th><th>不変L2（円）</th></tr></thead><tbody>'+''.join(anchor)+'</tbody></table></div></details>'


def render(data: dict) -> str:
    """
    機能: 動的な達成数、四切替と両商品全33場を暗色自己完結HTMLへ描画する。
    引数: data(dict)は完成小会計から検算した表示内容。
    返り値: strはHTML。未完の結果を仮置きしない。
    """
    options, sections = [], []
    for ident, case in data['cases'].items():
        options.append('<option value="'+html.escape(ident, quote=True)+'">'+html.escape(risk_sizing_report.label(case['config'])+' — '+ident)+'</option>')
        table = trade_report.session_table(case, data['sessions']).replace('TOPIXミニ：5枚・上限10枚', 'TOPIXミニ：新規1〜5枚・上限10枚').replace('日経マイクロ：10枚・上限20枚', '日経マイクロ：新規1〜10枚・上限20枚')
        sections.append('<section data-case="'+html.escape(ident, quote=True)+'" hidden><h2>'+html.escape(risk_sizing_report.label(case['config']))+'<small>'+html.escape(ident)+'</small></h2>'+explanation(case['config'])+details(case)+table+'</section>')
    counts = data['both_test_counts']
    status = '両商品での達成数：利益割合 '+str(counts[TESTS[0]])+'/4、赤字率 '+str(counts[TESTS[1]])+'/4、一場損失 '+str(counts[TESTS[2]])+'/4。各条件の未達部分は概要表に示す。'
    css = '*{box-sizing:border-box}body{background:#0b1120;color:#dce4f2;font:16px/1.65 system-ui;margin:0}main{max-width:1450px;margin:auto;padding:24px 20px}h1{font-size:26px}h2{font-size:21px}p{margin:10px 0}small{display:block;color:#aebed4;font-size:12px;overflow-wrap:anywhere}a{color:#91c2ff}.note{color:#b0bed1}.scroll{overflow:auto;max-width:100%;margin:16px 0}table{border-collapse:collapse;min-width:1150px;width:100%;font-size:14px}th,td{padding:10px 12px;border-bottom:1px solid #35445c;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{background:#1d2c43}tbody tr:nth-child(even){background:#152135}.positive{color:#57ddb1}.negative{color:#ff9196}.total{font-weight:bold;background:#1d2c43!important}select{width:100%;min-width:0;background:#18263b;color:#dce4f2;border:1px solid #74839b;padding:12px;font-size:15px}section{border:1px solid #35445c;border-radius:10px;padding:20px;margin:20px 0}section[hidden]{display:none}details{margin:12px 0}summary{cursor:pointer;color:#bad1ef}@media(max-width:600px){main{padding:16px 12px}h1{font-size:23px}section{padding:12px}}'
    first = next(iter(data['cases']))
    script = '''/**
 * 機能: 固定四条件から説明と全セッション会計を一つ表示する。
 * @param {string} id - 保存条件ID。
 * @returns {undefined} 表示だけ更新し、通信・取引を行わない。
 */
function showCase(id){for(const node of document.querySelectorAll('[data-case]'))node.hidden=node.dataset.case!==id;document.getElementById('case').value=id;}
document.getElementById('case').addEventListener('change',event=>showCase(event.target.value));showCase('''+json.dumps(first)+''');'''
    return '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+TITLE+'</title><style>'+css+'</style></head><body><main><h1>'+TITLE+'</h1><p><b>最新3基準を両商品で満たす条件は'+str(data['both_goal_pass'])+'/4件。収支が両方黒字の条件は'+str(data['both_net_positive'])+'/4件。</b></p><p>'+status+'</p><p class="note">金額利益割合65%以上 / 赤字セッション20%以下 / 最大赤字≦平均黒字1場。平均黒字はセッションnet、金額は手数料後。無取引は勝ちではない。</p>'+overview(data)+'<select id="case" aria-label="初回受理枚数に合わせた利確の四条件">'+''.join(options)+'</select>'+''.join(sections)+'<p class="note">今回変えたのは利確目標だけ。L2と公開q計算・元paper・途中返済・料は据え置いた。利確額が小さくなるため、黒字場の増加だけで成功とせず金額割合と最大赤字も評価する。</p><p class="note">利益・損失は完結実親net、枚数は実決済玉の勝ち/負け枚数。価格時計の代理秒とラージ気配を使用。実ミニ/マイクロ板・待ち順位、未見相場の成功は未確認。</p><p><a href="README.md">調査状況</a> · <a href="予定リスクで枚数を変える4比較と全セッション損益.html">直前の固定円サイズ版</a> · <a href="'+ACCOUNTING_TITLE+'">表示会計と資料指紋</a></p></main><script>'+script+'</script></body></html>'


# ----------------------------------------
def load_and_build() -> dict:
    """
    機能: 完成結果及び正式固定が揃った時だけ小会計を読み、表示値を検算する。
    引数: なし。
    返り値: dictは検算済み内容。金融sourceは読取指紋だけでimportしない。
    """
    assert not (SOURCE.parent/'False.json').exists(), '未完又は失敗の金融から公開しない'
    values, sources = {}, {}
    for p in (SOURCE, FIXED, PLAN, OLD_SOURCE):
        values[p], sources[p.relative_to(ROOT).as_posix()] = read(p)
    for financial in (values[SOURCE], values[OLD_SOURCE]):
        for relative, expected in financial['source_SHA256'].items():
            assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() == expected, relative
    data = build(values[SOURCE], values[FIXED], values[PLAN], values[OLD_SOURCE], sources)
    data['表示source_SHA256'] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__), HERE/'risk_sizing_report.py', HERE/'e01_trade_report.py', HERE/'trade_report.py', HERE/'range_report.py')}
    return data


def run(destination: Path | None = None) -> dict:
    """
    機能: root公開実行又は公開しない小会計検査を行う。
    引数: destination(Path|None)はrootの公開先。Noneなら出力ファイルを作らない。
    返り値: dictは動的達成数と表示件数。金融・API・packet・ledger読取は0。
    """
    data = load_and_build(); document = render(data)
    assert document.count('data-case="') == 4 and document.count('class="sessions"') == 4
    assert not any(t in document for t in ('NaN', 'Infinity'))
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=True)
        (destination/ACCOUNTING_TITLE).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
        (destination/(TITLE+'.html')).write_text(document, encoding='utf-8', newline='\n')
    proof = dict(全合格=True, 表示条件=4, 全セッション口座=264, 両商品黒字=data['both_net_positive'], 両商品三基準達成=data['both_goal_pass'], 各基準達成=data['both_test_counts'], 公開実行=destination is not None, 新金融=0, API=0, packet=0, ledger=0)
    print(json.dumps(proof, ensure_ascii=False), flush=True)
    return proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check-only', action='store_true')
    action.add_argument('--root-publish', action='store_true')
    parser.add_argument('--output-dir', type=Path, default=PUBLIC)
    args = parser.parse_args()
    run(None if args.check_only else args.output_dir)
