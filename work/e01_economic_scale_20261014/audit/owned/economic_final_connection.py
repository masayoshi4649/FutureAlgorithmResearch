"""十四条件の最終署名と登録JSON及び全場平均の分母を独立検査する。"""

import argparse
import ast
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import traceback

sys.dont_write_bytecode = True
OWN = Path(__file__).resolve().parent
ROOT = OWN.parents[3]
ENGINE = ROOT / 'work/e01_economic_scale_20261014/engine'
READS = {}
CHECKS = []


def read(path: Path) -> dict:
    """
    機能: 指定小JSONをこの目的で一読し、同じbytesの指紋を保存する。
    引数: path(Path) は許可済み署名・登録又は独立人工証跡。
    返り値: dict はJSON辞書。金融結果・入力・台帳本文を読まない。
    """
    key = path.relative_to(ROOT).as_posix()
    assert key not in READS, key
    raw = path.read_bytes()
    READS[key] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode('utf-8-sig'))


def check(value: bool, label: str) -> None:
    """
    機能: 独立期待値と実値の一致を、日本語の論点へ保存する。
    引数: value(bool)、label(str) は成立可否と論点。
    返り値: None。不成立を黙って除外しない。
    """
    assert value, label
    CHECKS.append(label)


def function_tree(path: Path, name: str) -> str:
    """
    機能: コメントを除いた指定関数の構文を比較可能にする。
    引数: path(Path)、name(str) は許可されたsourceと関数。
    返り値: str は構文木。関数を実行しない。
    """
    module = ast.parse(path.read_text(encoding='utf-8-sig'))
    node = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.dump(node, include_attributes=False)


def synthetic(values: list[float], symbol: str) -> tuple[list, list, list, list]:
    """
    機能: 負場と無取引を含む純人工の小会計を組み立てる。
    引数: values(list[float]) は各場net、symbol(str) は商品。
    返り値: tuple は行・親・射影・場順。実価格経路を生成しない。
    """
    rows, parents, profiles = [], [], []
    sessions = ['純算術' + str(i).zfill(2) for i in range(len(values))]
    for session, net in zip(sessions, values):
        count = int(net != 0)
        rows.append(dict(session=session, symbol=symbol, 収支=net, 利益=max(0., net), 損失=max(0., -net),
                         親数=count, 最大買枚数=count, 最大売枚数=0, 費用=0, 新規枚数=count,
                         勝ち枚数=int(net > 0), 負け枚数=int(net < 0), 零枚数=0))
        if count:
            parents.append(dict(session=session, symbol=symbol, 収支=net))
            profiles.append(dict(session=session, symbol=symbol, net_yen=net, entry_quantity=1,
                                 worst_parent_liquidation_yen=min(0., net)))
    return rows, parents, profiles, sessions


def arithmetic(stats: object) -> None:
    """
    機能: 損失/無取引込み全33場と上位除外後の残場分母を独立算術へ照合する。
    引数: stats(object) は完成した純集計module。
    返り値: None。親平均と未指定NK床を主場目標に代用しない。
    """
    patterns = [([100000.] * 33, True), ([100000.] * 32 + [99999.], False),
                ([100000.] + [0.] * 32, False), ([1100000.] * 3 + [0.] * 30, True),
                ([0.] * 33, False), ([200000.] * 17 + [-20000.] * 5 + [0.] * 11, True),
                ([200000.] * 16 + [-20000.] * 6 + [0.] * 11, False)]
    for number, (values, expected) in enumerate(patterns):
        for symbol in ('TOPIX', 'NK225'):
            rows, parents, profiles, sessions = synthetic(values, symbol)
            result = stats.periods(rows, parents, profiles, sessions, symbol)
            full = result['全33']['economic']
            check(math.isclose(full['mean_session_net_yen'], sum(values) / 33), f'純{number}/{symbol}:損失零場込み33分母')
            check(full['mean_parent_net_yen'] == (sum(values) / len(parents) if parents else None), f'純{number}/{symbol}:親平均は別分母')
            check(full['target_mean_success'] == (expected if symbol == 'TOPIX' else None), f'純{number}/{symbol}:TOP床とNK未指定')
            trim = result['上位3正収支場除外']
            removed = set(result['除外場'])
            residual = [v for s, v in zip(sessions, values) if s not in removed]
            check(trim['economic']['session_count'] == len(residual) and math.isclose(trim['economic']['mean_session_net_yen'], sum(residual) / len(residual)),
                  f'純{number}/{symbol}:trimの残場分母')
            check(full['parent_count'] == len(parents), f'純{number}/{symbol}:零無取引を親へ補完しない')
    rows, parents, profiles, sessions = synthetic([200000.] * 17 + [-20000.] * 5 + [0.] * 11, 'TOPIX')
    p = stats.periods(rows, parents, profiles, sessions, 'TOPIX')
    trim = p['上位3正収支場除外']
    check(p['全33']['stability']['all_economic_targets'], '全33平均10万円と主三基準は同時成立')
    check(trim['stability']['target65'] and trim['stability']['target_worst_mean'] and not trim['economic']['target_mean_success'],
          '従来trim頑健性とtrim経済床は独立:全場10万円/trim9万円')
    rows, _, profiles, _ = synthetic([0.] * 33, 'TOPIX')
    e = stats.economic(rows, profiles, 'TOPIX'); s = stats.stability(rows, e)
    check(e['mean_session_net_yen'] == 0 and e['mean_parent_net_yen'] is None and s['profit_share'] is None and not s['all_economic_targets'],
          '全無取引は場平均0/親平均未定義/非勝利')
    check(s['no_trade_sessions'] == 33 and s['active_sessions'] == 0 and s['red_full_rate'] == 0,
          '赤字率0と活動0を混同しない')


def main() -> None:
    """
    機能: 最終17源・八部品・登録境界と既独立経済人工の委譲範囲を保存する。
    引数: CLI --formal(bool) は根freeze後、--registration(Path) は根の小登録証跡。
    返り値: None。source実行は純集計/guardだけで、正式金融と経済coreを再実行しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--formal', action='store_true')
    parser.add_argument('--registration', type=Path)
    args = parser.parse_args()
    name = '十四最終17源と八部品及び全場平均の独立接続' + ('_正式' if args.formal else '_準備') + '.json'
    target = OWN / name
    assert not target.exists()
    source = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ENGINE.glob('*.py'))}
    try:
        check(len(source) == 17, '最終sourceは17部品')
        for path in source:
            ast.parse((ROOT / path).read_text(encoding='utf-8-sig'))
        sys.path.insert(0, str(ENGINE))
        if 'statistics' in sys.modules:
            del sys.modules['statistics']
        import common, catalog, runner, plan, statistics
        proof = read(ENGINE / '十四容量と実親分離及び登録接口の人工検査_v4.json')
        proposal_path = ENGINE / ('試行計画.json' if args.formal else '試行計画草案.json')
        fixed_path = ENGINE / ('金融事前固定.json' if args.formal else '準備固定.json')
        proposal, fixed = read(proposal_path), read(fixed_path)
        archived = read(ROOT / proof['経済人工委譲']['path'])
        meta = read(ENGINE / '旧選択小会計と三十三入力の目録.json')
        independent = read(OWN / '規模核心9源と全実親分母及び純v3の独立人工.json')
        check(proof['全合格'] and archived['全合格'] and independent['全合格'], '所有v4と保存v3及び独立経済人工はいずれも合格')
        check(proof['source_SHA256'] == source == fixed['source_SHA256'] == proposal['spec']['implementation'] == common.sources(), '最終17指紋をv4/計画/固定/実moduleへ束縛')
        check(READS[proposal_path.relative_to(ROOT).as_posix()] == fixed['計画SHA256'], '計画byte指紋は正式固定と同値')
        check(READS[proof['経済人工委譲']['path']] == proof['経済人工委譲']['SHA256'], '委譲v3は元保存bytesと一致')
        changed = [p for p in source if source[p] != archived['source_SHA256'][p]]
        check({Path(p).name for p in changed} == {'artificial.py', 'catalog.py', 'plan.py'}, 'null形式訂正は3sourceだけ、経済14source不変')
        for path, sha in proof['経済人工委譲']['source不変'].items():
            check(source[path] == sha == archived['source_SHA256'][path], '委譲不変:' + Path(path).name)
        for path, sha in independent['source_SHA256'].items():
            if Path(path).name not in ('catalog.py', 'interface.py'):
                check(source[path] == sha, '独立2400人工から経済源不変:' + Path(path).name)
        check(function_tree(ENGINE / 'interface.py', 'play') == function_tree(OWN / 'private_economic_core/interface.py', 'play'),
              '当時interface.playの売買構文は独立2400人工と同値')
        configs = catalog.configs()
        check(len(configs) == 14 and len({c['id'] for c in configs}) == 14, '14独立条件/重複ID無し')
        check(configs == fixed['configs'] == proposal['spec']['entry']['conditions'] == json.loads(json.dumps(configs, ensure_ascii=False, allow_nan=False)),
              '全条件をJSON保存再読してもtuple/list差を生じない')
        for c in configs:
            check(c['target_session_mean_net_yen'] == {'TOPIX': 100000, 'NK225': '円額目標の対象外（未指定）'} and
                  c['session_profit_stop_yen'] == '不使用（利益後も候補継続）', c['id'] + ':未指定/不使用を明示')
            check(c['cap'] == {'TOPIX': 10, 'NK225': 20}, c['id'] + ':容量10/20')
        expected = copy.deepcopy(read(ENGINE / 'archive/根照合でnull不完全と判定した正式初版/金融事前固定.json')['configs'])
        for c in expected:
            c['target_session_mean_net_yen']['NK225'] = '円額目標の対象外（未指定）'
            c['session_profit_stop_yen'] = '不使用（利益後も候補継続）'
        check(configs == expected, '14売買係数と条件IDはnull形式訂正前後で不変')
        check(runner.case_hashes(configs) == fixed['case_SHA256'], '14条件の全項目caseSHA同値')
        roundtrip = lambda value: json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
        found = roundtrip([dict(id=catalog.TRIAL_ID, spec=proposal['spec'])])
        runner.registry_guard(found, roundtrip(fixed), roundtrip(proposal)); runner.source_scope_guard()
        check(True, '保存JSON型の登録/全17moduleの新所有域とJIT隔離')
        for kind in ('未登録', '別ID', '別spec', '別config', '別case', '別source'):
            f, x, p = copy.deepcopy(found), copy.deepcopy(fixed), copy.deepcopy(proposal)
            if kind == '未登録': f = []
            elif kind == '別ID': f[0]['id'] = '別試行'
            elif kind == '別spec': f[0]['spec']['management']['別項目'] = True
            elif kind == '別config': x['configs'][0]['parent_stop_fraction'] *= 2
            elif kind == '別case': x['case_SHA256'][configs[0]['id']] = '0' * 64
            else: x['source_SHA256'][next(iter(source))] = '0' * 64
            rejected = False
            try: runner.registry_guard(f, x, p)
            except AssertionError: rejected = True
            check(rejected, '登録guard拒否:' + kind)
        checker_path = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/duplicate_check.py'
        ms = importlib.util.spec_from_file_location('独立経済形式チェック', checker_path)
        checker = importlib.util.module_from_spec(ms); ms.loader.exec_module(checker)
        check(set(proposal['spec']) == set(checker.PARTS) and checker.analyze(proposal, [])['proposal_complete'], '最終八部品specはnull無しで完全')
        for key in ('target_session_mean_net_yen', 'session_profit_stop_yen'):
            broken = copy.deepcopy(proposal)
            if key == 'target_session_mean_net_yen': broken['spec']['entry']['conditions'][0][key]['NK225'] = None
            else: broken['spec']['entry']['conditions'][0][key] = None
            check(not checker.analyze(broken, [])['proposal_complete'], '元null不完全境界:' + key)
        check(plan.clones() == proposal['同bytesコピー'], '料金/旧対照/公開票等9cloneは旧source同bytes')
        check(len(fixed['sessions']) == len(fixed['input_cache']) == 33 and fixed['input_cache'] == meta['input_cache'], '既33場の入力指紋目録を新固定へ接続')
        check(fixed['reused_results'] == meta['reused_results'] and len(fixed['reused_results']) == 2, '旧2条件は小会計引用だけ')
        check(proposal['予定'] == dict(新条件=14, 既input一読=33, 新account金融=924, 旧GU再利用=0, 旧台帳本文=0, 旧保存引用条件=2), '33×2×14=924を全実状態運転、旧GU再利用0')
        tree = ast.parse((ENGINE / 'runner.py').read_text(encoding='utf-8-sig'))
        run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
        calls = [(n.lineno, ast.unparse(n.func)) for n in ast.walk(run) if isinstance(n, ast.Call)]
        loadline = next(line for line, name in calls if name == 'data.load')
        check(sum(name == 'data.load' for _, name in calls) == 1 and all(next(line for line, name in calls if name == gate) < loadline for gate in ('registry_guard', 'source_scope_guard')),
              'registry/sourceguardが唯一inputload文より前')
        check(sum(name == 'interface.play' for _, name in calls) == 1 and runner.EXPECTED == dict(既input一読=33, 新account金融=924), '各場商品14ループで新実親運転、924counter拘束')
        check('future' not in function_tree(ENGINE / 'interface.py', 'play') and 'argmax' not in function_tree(ENGINE / 'core.py', 'simulate'),
              '事後極値は経済simulateとplayへ渡さない')
        check(fixed['正式freeze'] == proposal['正式freeze'] == args.formal, '準備と正式固定の状態を混同しない')
        arithmetic(statistics)
        if args.registration:
            record = read(args.registration.resolve())
            check(record['全合格'], '根の実照合/登録は合格')
            check(record['登録ID'] == catalog.TRIAL_ID and record['状態'] == '未実行' and
                  record['計画SHA256'] == fixed['計画SHA256'] and record['金融'] == record['入力'] == record['API'] == 0,
                  '登録証跡は現計画/未実行/金融前へ束縛')
            registered_path = args.registration.resolve().parent / '登録の全出力_v2.json'
            checked_path = args.registration.resolve().parent / '重複照合の全出力_v2.json'
            registered, checked = read(registered_path), read(checked_path)
            check(READS[registered_path.relative_to(ROOT).as_posix()] == record['登録SHA256'] and
                  READS[checked_path.relative_to(ROOT).as_posix()] == record['照合SHA256'], '保存した照合/登録全出力byte指紋一致')
            runner.registry_guard([registered], fixed, proposal)
            check(registered['status'] == '未実行' and registered['preflight']['proposal_complete'] and checked['proposal_complete'],
                  '実登録spec/config/sourceをguardへ通し未実行状態確認')
            check(not any(v['kind'] == '完全同一' for v in checked['matches']) and
                  record['未照合過去あり'] == bool(checked['incomplete_history']), '比較可能完全同一無しと未照合過去留保を分離')
        check(common.sources() == source, '検査開始終端の最終17source不変')
        output = dict(全合格=True,正式固定監査=args.formal,source_SHA256=source,読取小資料SHA256=READS,
                      独立確認数=len(CHECKS),確認観点=CHECKS,変更source=changed,
                      経済人工再試験=0,既独立人工口座=2400,所有経済人工委譲=archived['人工口座'],
                      主評価='TOP損失/無取引込み全33場net/33>=100000。NK円床未指定。親平均は参考。',
                      留保=['平均10万円は全場各10万円の保証ではない。', '17源の純接続は金融有効性を証明しない。',
                            'GUは共通親/場stop付きの新対照。旧GUの経済同値ではない。',
                            '未指定と不使用の形式記述は計算NKNone/利益停止なしを変更しない。',
                            '旧13源時のtuple指摘と登録前null未確定は区別し、金融の失敗とは呼ばない。'],
                      金融=0,実入力=0,台帳本文=0,原板=0,NPZ=0,API=0)
    except BaseException:
        output = dict(全合格=False,source_SHA256=source,読取小資料SHA256=READS,確認観点=CHECKS,
                      原因=traceback.format_exc(),金融=0,実入力=0,台帳本文=0,原板=0,NPZ=0,API=0)
        target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        raise
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('最終17源独立接続合格 ' + str(len(CHECKS)) + '確認 ' + hashlib.sha256(target.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
