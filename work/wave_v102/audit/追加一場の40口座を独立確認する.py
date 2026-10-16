"""条件と参考を変えず、追加ナイト一場の保存40口座を独立会計へ照合する。"""

import argparse
from pathlib import Path
import socket
import sys
import traceback

import common
import compare_utils as checks
import full
import support


SESSION = '2026-10-12_Night'
OUT = common.BASE/'holdout_results'
REPRESENTATIVES = ('B1_T0_Q1_X1', 'B1_T1_Q1_X1', 'B2_T1_Q1_X3', 'G0_Q1_X1')


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 監査中のネットワーク接続を禁止する。
    引数: args(tuple[object])、kwargs(dict[str,object])は呼出し引数。
    返り値: None。常にRuntimeErrorを送出する。
    """
    raise RuntimeError('監査では外部接続を行わない')


def modes(argv: list[str] | None = None) -> argparse.Namespace:
    """
    機能: 人工検査と根通知後の追加監査を排他的な明示フラグで分ける。
    引数: argv(list[str] | None)は検査用引数、Noneなら実際のCLI引数。
    返り値: argparse.Namespace。無指定又は両方指定は金融資料を読む前に拒否する。
    """
    parser = argparse.ArgumentParser(description='追加一場の独立監査。明示通知なしの正式実行を拒否する。')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--artificial', action='store_true', help='一条件・両商品の人工台帳だけを検査する')
    mode.add_argument('--root-holdout-complete', action='store_true', help='元31独立監査と根追加再生の終端通知後だけ使う')
    return parser.parse_args(argv)


def signatures() -> dict[str, str]:
    """
    機能: この監査が使う現行金融・独立監査ソースだけを開始終端比較用に指紋化する。
    引数: なし。
    返り値: dict[str,str]。旧全原本及び全31台帳の追加二重走査を行わない。
    """
    paths = [common.BASE/name for name in ('catalog.py', 'strategy.py', 'engine.py',
                                          'research.py', 'accounting.py', 'data.py')]
    paths += [common.HERE/name for name in ('common.py', 'compare_utils.py', 'financial.py',
        'math_oracle.py', 'summaries.py', 'support.py', 'storage.py', 'runtime_oracle.py',
        'watch.py', 'cohort_sources.py', 'full.py', 'artificial.py')]
    paths.append(Path(__file__))
    return common.fingerprints(paths)


def artificial_check(conditions: list[dict]) -> tuple[dict, dict, dict]:
    """
    機能: 一条件の人工二口座を根保存して再読込し、正式と同じ独立検算へ通す。
    引数: conditions(list[dict])は現行の20固定条件。
    返り値: tuple[dict,dict,dict]。独立結果、件数、人工保存資料の指紋。追加場入力は読まない。
    """
    import artificial
    config = next(value for value in conditions if value['id'] == 'B1_T0_Q1_X1')
    strategy = common.module('追加監査の人工だけ102戦略', common.BASE/'strategy.py')
    research = common.module('追加監査の人工だけ102保存', common.BASE/'research.py')
    accounting = common.module('追加監査の人工だけ102根会計', common.BASE/'accounting.py')
    prepared = {('2099-01-01_Day', symbol): artificial.fixture(symbol) for symbol in common.SYMBOLS}
    outputs = {key: strategy.play(config, key, prepared) for key in prepared}
    ledgers = {key: research.ledger(output, prepared[key]) for key, output in outputs.items()}
    destination = common.HERE/'holdout_cli_fixture'/f"{config['id']}.pkl"
    assert not destination.exists(), '追加人工検査を二重起動しない'
    research.save(destination, ledgers)
    loaded = common.read(destination)
    rows = [accounting.account(key, outputs[key]) for key in sorted(outputs)]
    periods = {'追加人工1': ['2099-01-01_Day']}
    expected = dict(config=config, rows=rows,
        periods={'追加人工1': {symbol: accounting.aggregate(rows, symbol, periods['追加人工1'])
                              for symbol in common.SYMBOLS}},
        stability={'追加人工1': research.stability(rows, config, prepared, periods['追加人工1'])})
    result, counts = full.verify_bundle(config, prepared, loaded, periods, expected, True)
    assert counts['口座'] == 2 and counts['商品期間'] == 2 and counts['独立原行再生'] == 2
    return {config['id']: result}, counts, common.fingerprints([destination])


def formal_check(conditions: list[dict], source: dict[str, str]) -> tuple[dict, dict, dict, list[str]]:
    """
    機能: 元31独立監査と追加再生の終端後、不変20条件の保存40口座を独立検算する。
    引数: conditions(list[dict])、source(dict[str,str])は現行条件と開始時ソース指紋。
    返り値: tuple[dict,dict,dict,list[str]]。独立結果、件数、参照指紋、独立原行再生の代表。
    """
    fixed_path = common.BASE/'事前固定.json'
    selected_path = common.BASE/'前16参考代表.json'
    analysis_path = common.BASE/'analysis/比較結果.json'
    original_audit_path = common.HERE/'全20全31の増玉注文と親cohort及び全原板会計の独立検算.json'
    start_path, end_path = OUT/'追加再生前固定.json', OUT/'正式追加再生の終端.json'
    required = [fixed_path, selected_path, analysis_path, original_audit_path, start_path, end_path]
    assert all(path.exists() for path in required), '元31独立監査又は根追加再生が未完了'
    fixed, selected, analysis = (common.read(path) for path in (fixed_path, selected_path, analysis_path))
    original_audit, start, end = (common.read(path) for path in (original_audit_path, start_path, end_path))
    assert original_audit['合格'] is True and original_audit['検査件数']['口座'] == 1240
    assert original_audit['検査件数']['商品期間'] == 320
    assert fixed['条件'] == conditions and len(fixed['全31']) == 31 and SESSION not in fixed['全31']
    assert fixed['固定対象外の新追加場'] == SESSION and fixed['現在の保存場数'] == 32
    assert selected['全合格'] and selected['後15正式損益前選定']
    assert selected['固定SHA256'] == common.sha(fixed_path)
    assert selected['selected'] == 'B05_T1_Q1_X1', '追加確認で前16参考を変更しない'
    assert analysis['全合格'] and analysis['primary'] == fixed['主']
    assert analysis['selected'] == selected['selected']
    assert start['全合格'] and start['条件'] == conditions and start['主'] == fixed['主']
    assert start['前16参考'] == selected['selected'] and start['対象'] == [SESSION]
    assert start['正式追加損益実行'] == start['追加損益による条件又は参考変更'] == 0
    assert start['元31結果確定後']
    assert end['全合格'] and end['条件数'] == 20 and end['口座数'] == 40 and end['対象'] == SESSION
    assert end['条件変更'] == end['参考変更'] == 0 and end['開始終端指紋一致']
    assert end['開始SHA256'] == end['SHA256'] == start['SHA256']
    paths = [common.ROOT/relative for relative in start['SHA256']]
    assert common.fingerprints(paths) == start['SHA256'], '追加再生前後の入力又は元31確定資料が変わった'
    for relative, wanted in source.items():
        if relative in fixed['SHA256']:
            assert wanted == fixed['SHA256'][relative], relative
    assert all(original_audit['SHA256'][relative] == wanted for relative, wanted in source.items()
               if relative in original_audit['SHA256']), '元31監査後に既存の監査又は金融コードが変わった'

    # ----------------------------------------
    loader_path = common.BASE/'holdout_input/data.py'
    compatibility_path = common.BASE/'holdout_input/現102のprepareと旧Day欄及び未来不変の入力互換.json'
    compatibility = common.read(compatibility_path)
    assert compatibility['全合格'] and compatibility['追加確認場'] == SESSION
    assert compatibility['新場損益閲覧'] == compatibility['新場損益計算'] == compatibility['売買実行'] == 0
    loader = common.module('追加独立監査専用の一場入力102', loader_path)
    material = loader.load_inputs()
    strategy = common.module('追加独立監査のprepareだけ102', common.BASE/'strategy.py')
    prepared = strategy.prepare(material, conditions[0])
    assert material['metadata']['sessions'] == [SESSION] and material['metadata']['accounts'] == 2
    assert set(prepared) == {(SESSION, symbol) for symbol in common.SYMBOLS}
    for key, value in prepared.items():
        support.verify_material(key, material, value)
    prepared_before = checks.prepared_sha(prepared)
    representatives = list(dict.fromkeys((*REPRESENTATIVES, selected['selected'])))
    assert len(representatives) == 5
    assert {path.stem for path in (OUT/'results').glob('*.json')} == {value['id'] for value in conditions}
    assert {path.stem for path in (OUT/'ledgers').glob('*.pkl')} == {value['id'] for value in conditions}
    results, counts = {}, {}
    bindings = dict(start['SHA256'])
    bindings.update(common.fingerprints([path for path in required+[loader_path, compatibility_path]
        if str(path.relative_to(common.ROOT)) not in bindings]))
    periods = {'追加ナイト1': [SESSION]}
    for config in conditions:
        result_path = OUT/'results'/f"{config['id']}.json"
        ledger_path = OUT/'ledgers'/f"{config['id']}.pkl"
        saved, ledgers = common.read(result_path), common.read(ledger_path)
        assert saved['config'] == config and len(saved['rows']) == 2
        ledger_digest = common.sha(ledger_path)
        assert saved['ledger_SHA256'] == ledger_digest
        assert set(ledgers) == set(prepared)
        assert set(saved['periods']) == {'追加ナイト1'}
        expected = dict(config=saved['config'], rows=saved['rows'], periods=saved['periods'],
                        stability={'追加ナイト1': saved['stability']})
        result, checked = full.verify_bundle(config, prepared, ledgers, periods, expected,
                                             config['id'] in representatives)
        results[config['id']] = result
        for name, amount in checked.items():
            counts[name] = counts.get(name, 0)+amount
        bindings[str(result_path.relative_to(common.ROOT))] = common.sha(result_path)
        bindings[str(ledger_path.relative_to(common.ROOT))] = ledger_digest
        print(config['id']+': 追加二口座の原板・親cohort・支持・一場会計が独立一致', flush=True)
    assert counts['口座'] == 40 and counts['商品期間'] == 40
    assert counts['独立原行再生'] == len(representatives)*2 == 10
    assert checks.prepared_sha(prepared) == prepared_before, '独立監査で追加共有入力を書き換えた'
    assert common.fingerprints(paths) == start['SHA256'], '監査中に元31確定資料又は追加固定資料が変わった'
    return results, counts, bindings, representatives


def main() -> None:
    """
    機能: 明示モードで追加監査を行い、所有範囲だけに検算終端を保存する。
    引数: CLI --artificial又は--root-holdout-complete。
    返り値: None。不合格を保持して停止。正式モードで根売買を生成又は再選択しない。
    """
    args = modes()
    socket.create_connection = deny
    socket.socket.connect = deny
    catalog = common.module('追加独立監査の不変条件102', common.BASE/'catalog.py')
    conditions = catalog.catalog()
    assert len(conditions) == 20
    source = signatures()
    if args.artificial:
        results, counts, bindings = artificial_check(conditions)
        representatives = ['B1_T0_Q1_X1']
        destination = common.HERE/'追加監査CLIの小人工二口座と根保存再読込.json'
    else:
        results, counts, bindings, representatives = formal_check(conditions, source)
        destination = common.HERE/'追加ナイト全20の40口座と原板及び独立管理の検算.json'
    assert source == signatures(), '追加独立監査中に現行ソースが変わった'
    bindings.update(source)
    assert not destination.exists(), '同じ監査を二重起動しない'
    common.save(destination, dict(合格=True, 人工専用=args.artificial,
        対象='2099-01-01_Dayの人工素材' if args.artificial else SESSION,
        検査件数=counts, 全会計=results, 代表条件=representatives,
        元31不変='人工では未検証。正式は元31独立監査終端及び追加再生前後の固定/前16参考/全31分析のSHAを照合。',
        状態の範囲='全口座は全注文・全原板・cohort25/親物理22/支持source。代表は保有11数理/別19全列/最初入口・追加・返済。旧70補助flags全列の独立再構成とはしない。',
        追加による条件変更=0, 追加による参考再選択=0, 新正式売買生成=0, API取得=0, 実注文=0,
        開始終端ソース一致=True, SHA256=bindings))
    print('追加独立監査の検算終端保存と再読込が合格。', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        serial = 1
        destination = common.HERE/f'追加独立監査不合格_{serial:05d}.json'
        while destination.exists():
            serial += 1
            destination = common.HERE/f'追加独立監査不合格_{serial:05d}.json'
        common.save(destination, dict(合格=False, 原因=str(error), 詳細=traceback.format_exc(),
            新正式売買生成=0, API取得=0, 実注文=0, SHA256=signatures()))
        raise
