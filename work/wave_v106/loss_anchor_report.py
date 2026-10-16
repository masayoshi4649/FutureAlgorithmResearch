"""初回受理数量に合わせた損失停止四対照を、完成小会計から報告する。"""

import argparse
import hashlib
import html
import json
from pathlib import Path

import goal_anchor_report as base

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = base.PUBLIC
TITLE = '枚数に合わせた損失停止の修正と全セッション損益'
ACCOUNTING_TITLE = '枚数に合わせた損失停止4比較の公開会計.json'
SOURCE = HERE/'e01_size_loss_anchor/finance/結果.json'
FIXED = HERE/'e01_size_loss_anchor/金融事前固定.json'
PLAN = HERE/'e01_size_loss_anchor/試行計画.json'
OLD_SOURCE = HERE/'e01_size_goal_anchor/finance/結果.json'
SYMBOLS, LABELS, TESTS, FIVE = base.SYMBOLS, base.LABELS, base.TESTS, base.FIVE


def anchors(rows: list, config: dict) -> dict:
    """
    機能: 受理qに比例した利益・損失停止線と、不変の数量選択Bを別々に検算する。
    引数: rows(list[dict])、config(dict)は当該条件の66保存境界と固定条件。
    返り値: dictは商品別固定線分布。無受理の両停止線を0へ補完しない。
    """
    assert len(rows) == len({(r['session'], r['symbol']) for r in rows}) == 66
    result = {}
    for s in SYMBOLS:
        own = [r for r in rows if r['symbol'] == s]; assert len(own) == 33
        accepted, quantities, goals, stops = [], [], [], []
        for r in own:
            a, loss = r['anchor'], r['損失アンカー']
            full, original, budget = config['quantity'][s], config['profit_goal_yen'][s], config['quantity_selection_budget_yen'][s]
            assert a['通常全量'] == loss['通常全量'] == full and a['元利益目標円'] == original
            assert r['新規数量選択予算円'] == loss['新規数量選択予算円'] == budget
            assert r['停止判断']['目標'] == r['目標円'] and r['停止判断']['損失予算'] == r['損失停止線円']
            if not a['成立']:
                assert all(a[k] is None for k in ('数量', '利益目標円', '受理行', '受理原seq', '受理価格時計', '紙上親'))
                assert r['実政策初回新規'] is None and r['受理行の費用後清算円'] is None
                assert r['目標円'] is r['損失停止線円'] is loss['比例損失停止線円'] is loss['初回受理数量'] is None
                continue
            q = a['数量']; assert isinstance(q, int) and 0 < q <= full and loss['初回受理数量'] == q
            assert a['利益目標円'] == original*q/full == r['目標円']
            stop = config['loss_stop_base_yen'][s]*q/full
            assert r['損失停止線円'] == loss['比例損失停止線円'] == stop
            assert isinstance(a['受理行'], int) and a['受理行'] >= 0
            if r['停止判断']['発動']:
                assert r['停止判断']['判断行'] >= a['受理行']
            if r['実政策初回新規'] is not None:
                first = r['実政策初回新規']; assert first['source_row'] >= a['受理行'] and first['row'] > first['source_row']
            accepted.append(r); quantities.append(q); goals.append(a['利益目標円']); stops.append(stop)
        result[s] = dict(受理あり=len(accepted), 受理なし=33-len(accepted),
            受理あり実新規なし=sum(r['実政策初回新規'] is None for r in accepted),
            初回受理q最小=min(quantities) if quantities else None, 初回受理q最大=max(quantities) if quantities else None,
            固定目標最小=min(goals) if goals else None, 固定目標最大=max(goals) if goals else None,
            固定損失線最小=min(stops) if stops else None, 固定損失線最大=max(stops) if stops else None,
            新規数量選択予算円=config['quantity_selection_budget_yen'][s], 元損失停止額=config['loss_stop_base_yen'][s])
    return result


def build(finance: dict, fixed: dict, plan: dict, previous: dict, sources: dict) -> dict:
    """
    機能: 完成四政策を正式固定・保存GU・同母旧goal版へ束縛し、表示小会計を作る。
    引数: finance/fixed/plan/previous/sources(dict)は新結果、正式固定計画、直前結果と指紋。
    返り値: dictは検算済み表示値。未完結果や金融再生を代用しない。
    """
    assert finance['全合格'] and fixed['全合格'] and previous['全合格'] and plan['正式freeze']
    assert finance['source開始終端一致'] and previous['source開始終端一致']
    assert finance['source_SHA256'] == fixed['source_SHA256'] == plan['spec']['implementation']
    assert sources[PLAN.relative_to(ROOT).as_posix()] == fixed['計画SHA256']
    assert finance['configs'] == fixed['configs'] == plan['spec']['entry']['conditions']
    assert base.case_hashes(finance['configs']) == finance['case_SHA256'] == fixed['case_SHA256']
    assert finance['新GUengine'] == 0 and finance['保存GU再利用'] == 132 and finance['新政策会計'] == finance['会計口座数'] == 264
    assert finance['counts'] == dict(新GUengine=0, 既input一読=33, 保存GU再利用=132, 新政策会計=264, 旧利確アンカー台帳一読=264)
    assert finance['元paper再計算'] == finance['旧金融再生'] == finance['原板読取'] == finance['NPZ読取'] == finance['現在入力読取'] == finance['API'] == 0
    assert finance['保存旧代表'] == fixed['旧fullP1L8参考rows']
    sessions = finance['sessions']; assert sessions == fixed['sessions'] and len(sessions) == len(set(sessions)) == 33
    configs = {c['id']: c for c in finance['configs']}; assert len(configs) == 4 and set(configs) == set(finance['results'])
    cases = {}
    for ident, raw in finance['results'].items():
        config, reference = configs[ident], fixed['comparisons'][ident]
        baseline_id = config['baseline_id']; before = previous['results'][baseline_id]
        assert reference['id'] == baseline_id and reference['rows'] == before['rows'] and reference['symbols'] == before['symbols']
        assert reference['source'] == OLD_SOURCE.relative_to(ROOT).as_posix() and reference['SHA256'] == sources[reference['source']]
        old_config = next(c for c in previous['configs'] if c['id'] == baseline_id)
        assert 'loss_budget_yen' not in config
        assert config['quantity_selection_budget_yen'] == config['loss_stop_base_yen'] == old_config['loss_budget_yen']
        assert all(config[k] == old_config[k] for k in ('mode', 'window_seconds', 'execution', 'offset_atr', 'profit_ticks', 'loss_ticks', 'risk_atr_multiple', 'quantity', 'cap', 'profit_goal_yen', 'goal_anchor'))
        rows = [base.e01_trade_report.mapped(r) for r in raw['rows']]
        old_rows = [base.e01_trade_report.mapped(r) for r in before['rows']]
        assert len(rows) == len({(r['session'], r['symbol']) for r in rows}) == 66 and {r['session'] for r in rows} == set(sessions)
        summary, top3 = base.summaries(rows); old_summary, old_top3 = base.summaries(old_rows)
        changes = finance['各場寄与'][ident]
        assert len(changes) == len({(r['session'], r['symbol']) for r in changes}) == 66
        examples = {}
        for s in SYMBOLS:
            base.saved_check(summary[s], raw['symbols'][s]); base.saved_check(old_summary[s], before['symbols'][s])
            assert abs(raw['actual_leg_symbols'][s]['収支']-summary[s]['net']) < 1e-5
            own = [r for r in changes if r['symbol'] == s]; assert len(own) == 33
            expected = finance['diagnosis'][ident][s]
            for f in FIVE:
                assert abs(sum(r[f] for r in own)-expected[f]) < 1e-5
            assert expected['元勝ち親が赤字化'] == sum(len(r['元勝ち親が赤字化']) for r in own)
            assert abs(expected['収支変化']-(summary[s]['net']-old_summary[s]['net'])) < 1e-5
            assert abs(expected['収支変化']-(expected['避けた基準損失']-expected['失った基準利益']+expected['共通入口の数量/出口差']+expected['新たな入口の収支'])) < 1e-5
            assert all(r['baseline_id'] == baseline_id for r in own)
            turned = [dict(session=r['session'], symbol=s, **p) for r in own for p in r['元勝ち親が赤字化']]
            assert all(p['old_net'] > 0 and p['new_net'] < 0 for p in turned)
            examples[s] = sorted(turned, key=lambda p: (p['new_net']-p['old_net'], p['session'], p['parent']))[:2]
        boundary = finance['初回受理と費用後目標境界'][ident]
        cases[ident] = dict(config=config, rows=rows, summary=summary, top3=top3,
            comparison=dict(id=baseline_id, rows=old_rows, summary=old_summary, top3=old_top3),
            diagnosis=finance['diagnosis'][ident], actual_legs=raw['actual_leg_symbols'],
            anchor_rows=boundary, anchor_summary=anchors(boundary, config), recovery_examples=examples)
    return dict(全合格=True, title=TITLE, sessions=sessions, cases=cases, sources=sources,
        both_net_positive=sum(all(c['summary'][s]['net'] > 0 for s in SYMBOLS) for c in cases.values()),
        both_goal_pass=sum(all(c['summary'][s]['pass_all'] for s in SYMBOLS) for c in cases.values()),
        both_test_counts={k: sum(all(c['summary'][s]['tests'][k] for s in SYMBOLS) for c in cases.values()) for k in TESTS},
        criterion=dict(金額利益割合=.65, 赤字全場割合=.2, 一場損失='最大赤字場net絶対額<=平均黒字場net'),
        金融source_SHA256=finance['source_SHA256'], case_SHA256=finance['case_SHA256'], 保存GU再利用=132,
        定義=dict(金額='完結実親netの利益・損失', 枚数='実決済玉の勝ち・負け枚数', 無取引='勝ちに含めない',
            数量予算='TOP5000/NK2000で不変。縮小停止線を新規q選択へ戻さない。',
            両停止線='最初の受理q/fullで一度固定。取消でも保持、無受理は両線None。'),
        新金融再生=0, API取得=0, packet読取=0, ledger読取=0, 原板読取=0, NPZ読取=0)


# ----------------------------------------
def table(headers: list, rows: list, css_class: str) -> str:
    """
    機能: 表示済み文字列の補足表を安全に描画する。
    引数: headers(list[str])、rows(list[list[str]])、css_class(str)は列名・内容・同定class。
    返り値: strはHTML表。数値の再判断はしない。
    """
    assert all(len(r) == len(headers) for r in rows)
    return '<div class="scroll"><table class="'+html.escape(css_class, quote=True)+'"><thead><tr>'+''.join('<th>'+html.escape(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in r)+'</tr>' for r in rows)+'</tbody></table></div>'


def explanation(config: dict) -> str:
    """
    機能: 不変入口・q選択B・比例した両停止線を三行へ要約する。
    引数: config(dict)は正式固定条件。
    返り値: strは短い説明HTML。停止線を約定損失保証と呼ばない。
    """
    gate = '同方向を確認' if config['mode'] == 'CONFIRM' else '強い逆票を回避'
    return '<p><b>入口：</b><a href="../00044_新候補2手法と基準の説明と損益/新候補2手法の説明と損益.html">元E01</a>の候補を60代理秒の票で'+gate+'。新規q選択の予算BはTOPIX5,000円・日経2,000円のまま、ATR・気配差・料でqを決める。</p><p><b>途中：</b>最初に受理した公開q÷通常5枚/10枚で、P'+str(config['profit_ticks'])+'利益目標とL2損失停止線を一度だけ固定。未約定取消でも保持し、後の実qに合わせ直さない。影・部分返済・料は不変。</p><p><b>出口：</b>比例固定した利益又は損失線へ先に達したら、次正常気配で残玉を返済し場停止。無受理は両線未定義。損失線を狭めても新規数量予算Bは縮めない。</p>'


def details(case: dict) -> str:
    """
    機能: 旧goal版比較、上位三除外、五寄与、固定線と失った旧勝ちを短く表示する。
    引数: case(dict)は検算済み一条件。
    返り値: strは折り畳みHTML。未来回復を新出口判断へ使わない。
    """
    number, percent = base.range_report.number, base.risk_sizing_report.percent
    comparison, trim, change, fixed_lines, recovery = [], [], [], [], []
    for s in SYMBOLS:
        new, old = case['summary'][s], case['comparison']['summary'][s]
        comparison.append([LABELS[s], number(new['net']), number(old['net']), number(new['net']-old['net']),
            str(new['positive'])+'/'+str(old['positive']), str(new['negative'])+'/'+str(old['negative']), percent(new['profit_share'])+' / '+percent(old['profit_share'])])
        for label, origin in (('損失線修正', case), ('旧goal版', case['comparison'])):
            v, t = origin['summary'][s], origin['top3'][s]
            trim.append([label, LABELS[s], number(v['median']), number(t['net']), percent(t['profit_share']),
                         str(t['negative'])+'/'+str(t['sessions']), number(t['mean_positive_session_net'], 1), number(t['worst_session_loss'])])
        d = case['diagnosis'][s]
        change.append([LABELS[s]]+[number(d[f]) for f in FIVE]+[str(d['元勝ち親が赤字化'])])
        a = case['anchor_summary'][s]
        fixed_lines.append([LABELS[s], str(a['受理あり'])+'/33', str(a['受理あり実新規なし']),
            number(a['初回受理q最小'])+'〜'+number(a['初回受理q最大']), number(a['固定目標最小'])+'〜'+number(a['固定目標最大']),
            number(a['固定損失線最小'])+'〜'+number(a['固定損失線最大']), number(a['新規数量選択予算円'])])
        recovery.extend([LABELS[s], p['session'].replace('_Day', ' デイ').replace('_Night', ' ナイト'), str(p['parent']), number(p['old_net']), number(p['new_net'])] for p in case['recovery_examples'][s])
    return '<details><summary>直前の利確だけ比例版との比較</summary><small>'+html.escape(case['comparison']['id'])+'。同母・同P1/P2、損失停止線だけの変更。</small>'+table(['商品', '新収支', '旧収支', '差額', '黒字場 新/旧', '赤字場 新/旧', '金額利益割合 新/旧'], comparison, 'fixed-comparison')+'</details><details><summary>上位3利益場を除いた結果</summary>'+table(['比較', '商品', '全33中央値', '除外後収支', '除外後金額割合', '除外後赤字場', '除外後平均黒字net', '除外後最大赤字'], trim, 'top3')+'</details><details><summary>入口入替・共通親の寄与と失った回復勝ち</summary>'+table(['商品', '収支差', '避けた損失', '失った利益', '共通親の数量/出口差', '新後続収支', '旧勝ち親の赤字化'], change, 'contributions')+'<p class="note">旧条件では勝ち、新条件では負けになった同じpaper親を数える。将来の回復を当時の判断に使ったものではない。以下は商品別最大悪化の2例まで。</p>'+table(['商品', 'セッション', '同じ親ID', '旧親収支', '新親収支'], recovery, 'recovery-examples')+'</details><details><summary>受理q・比例した両停止線・不変B</summary><p class="note">新規数量選択の予算と、実損失を止める線は別。無受理の両停止線は未定義。</p>'+table(['商品', '受理あり', '受理あり実新規なし', '初回q範囲', '利益目標範囲', '損失停止線範囲', '不変q選択B'], fixed_lines, 'anchors')+'</details>'


def render(data: dict) -> str:
    """
    機能: 達成数を動的計算した概要と四切替の全33場会計を暗色HTMLへ描画する。
    引数: data(dict)は完成小会計から検算した内容。
    返り値: strは自己完結HTML。仮結果や未来ピークによる救済は載せない。
    """
    options, sections = [], []
    for ident, case in data['cases'].items():
        label = base.risk_sizing_report.label(case['config'])
        options.append('<option value="'+html.escape(ident, quote=True)+'">'+html.escape(label+' — '+ident)+'</option>')
        sessions = base.trade_report.session_table(case, data['sessions']).replace('TOPIXミニ：5枚・上限10枚', 'TOPIXミニ：新規1〜5枚・上限10枚').replace('日経マイクロ：10枚・上限20枚', '日経マイクロ：新規1〜10枚・上限20枚')
        sections.append('<section data-case="'+html.escape(ident, quote=True)+'" hidden><h2>'+html.escape(label)+'<small>'+html.escape(ident)+'</small></h2>'+explanation(case['config'])+details(case)+sessions+'</section>')
    counts = data['both_test_counts']
    status = '両商品での達成数：利益割合 '+str(counts[TESTS[0]])+'/4、赤字率 '+str(counts[TESTS[1]])+'/4、一場損失 '+str(counts[TESTS[2]])+'/4。各条件の未達部分は概要表に示す。'
    css = '*{box-sizing:border-box}body{background:#0b1120;color:#dce4f2;font:16px/1.65 system-ui;margin:0}main{max-width:1450px;margin:auto;padding:24px 20px}h1{font-size:26px}h2{font-size:21px}p{margin:10px 0}small{display:block;color:#aebed4;font-size:12px;overflow-wrap:anywhere}a{color:#91c2ff}.note{color:#b0bed1}.scroll{overflow:auto;max-width:100%;margin:16px 0}table{border-collapse:collapse;min-width:1150px;width:100%;font-size:14px}th,td{padding:10px 12px;border-bottom:1px solid #35445c;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{background:#1d2c43}tbody tr:nth-child(even){background:#152135}.positive{color:#57ddb1}.negative{color:#ff9196}.total{font-weight:bold;background:#1d2c43!important}select{width:100%;min-width:0;background:#18263b;color:#dce4f2;border:1px solid #74839b;padding:12px;font-size:15px}section{border:1px solid #35445c;border-radius:10px;padding:20px;margin:20px 0}section[hidden]{display:none}details{margin:12px 0}summary{cursor:pointer;color:#bad1ef}@media(max-width:600px){main{padding:16px 12px}h1{font-size:23px}section{padding:12px}}'
    first = next(iter(data['cases']))
    script = '''/**
 * 機能: 四条件から説明と全セッション会計を一つ表示する。
 * @param {string} id - 保存条件ID。
 * @returns {undefined} 表示だけ更新し、通信・取引を行わない。
 */
function showCase(id){for(const node of document.querySelectorAll('[data-case]'))node.hidden=node.dataset.case!==id;document.getElementById('case').value=id;}
document.getElementById('case').addEventListener('change',event=>showCase(event.target.value));showCase('''+json.dumps(first)+''');'''
    return '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+TITLE+'</title><style>'+css+'</style></head><body><main><h1>'+TITLE+'</h1><p><b>最新3基準を両商品で満たす条件は'+str(data['both_goal_pass'])+'/4件。収支が両方黒字の条件は'+str(data['both_net_positive'])+'/4件。</b></p><p>'+status+'</p><p class="note">金額利益割合65%以上 / 赤字セッション20%以下 / 最大赤字≦平均黒字1場。金額は手数料後の完結親、平均黒字はセッションnet。無取引は勝ちではない。</p>'+base.overview(data)+'<select id="case" aria-label="初回受理枚数に合わせた損失停止の四条件">'+''.join(options)+'</select>'+''.join(sections)+'<p class="note">今回変えたのは実損失停止線だけ。新規q選択BはTOPIX5,000円・日経2,000円を維持し、利益線・影・料・部分返済は直前版と同じ。保存GU132を共有した政策対照で、新たな独立標本ではない。</p><p class="note">初期気配差と往復料だけで停止し得る。次正常気配で損失線を超過し得るため上限保証ではない。回復して勝った旧親を早く切る副作用も表示した。</p><p class="note">価格時計の代理秒とラージ気配を使用。実ミニ/マイクロ板・待ち順位、未見相場の成功は未確認。</p><p><a href="README.md">調査状況</a> · <a href="枚数に合わせた利確修正と全セッション損益.html">直前の利確だけ比例版</a> · <a href="'+ACCOUNTING_TITLE+'">表示会計と資料指紋</a></p></main><script>'+script+'</script></body></html>'


# ----------------------------------------
def load_and_build() -> dict:
    """
    機能: 完成結果と正式固定が揃った時だけ小会計を読み、源指紋と表示値を確認する。
    引数: なし。
    返り値: dictは表示小会計。金融sourceは指紋だけでimportしない。
    """
    assert not (SOURCE.parent/'False.json').exists(), '未完又は失敗の金融から公開しない'
    values, sources = {}, {}
    for p in (SOURCE, FIXED, PLAN, OLD_SOURCE):
        values[p], sources[p.relative_to(ROOT).as_posix()] = base.read(p)
    for financial in (values[SOURCE], values[OLD_SOURCE]):
        for relative, expected in financial['source_SHA256'].items():
            assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() == expected, relative
    data = build(values[SOURCE], values[FIXED], values[PLAN], values[OLD_SOURCE], sources)
    data['表示source_SHA256'] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__), HERE/'goal_anchor_report.py', HERE/'risk_sizing_report.py', HERE/'e01_trade_report.py', HERE/'trade_report.py', HERE/'range_report.py')}
    return data


def run(destination: Path | None = None) -> dict:
    """
    機能: root公開実行又は公開しない純小会計検査を行う。
    引数: destination(Path|None)はroot公開先。Noneなら出力ファイルを作らない。
    返り値: dictは動的達成数と表示件数。金融・API・packet・ledger読取は0。
    """
    data = load_and_build(); document = render(data)
    assert document.count('data-case="') == 4 and document.count('class="sessions"') == 4
    assert not any(t in document for t in ('NaN', 'Infinity'))
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=True)
        (destination/ACCOUNTING_TITLE).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
        (destination/(TITLE+'.html')).write_text(document, encoding='utf-8', newline='\n')
    proof = dict(全合格=True, 表示条件=4, 全セッション口座=264, 両商品黒字=data['both_net_positive'],
        両商品三基準達成=data['both_goal_pass'], 各基準達成=data['both_test_counts'], 公開実行=destination is not None,
        新金融=0, API=0, packet=0, ledger=0)
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
