"""凍結監査の2商品依存定数を補足し、同じmainと純会計を全範囲実行する。"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

SUPPORT = Path(__file__).resolve().parent
AUDIT = SUPPORT.parent / 'audit'
sys.path.insert(0, str(AUDIT))
sys.dont_write_bytecode = True

import common
import full


def save(path: Path, value: dict) -> None:
    """
    機能: 外部補足だけを新support領域へ保存して再読込する。
    引数: path(Path)はsupport内、value(dict)は補足証跡。
    返り値: None。原資料又は保存不一致は例外。
    """
    assert path.resolve().is_relative_to(SUPPORT.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    assert common.read(path) == value


def frozen() -> dict:
    """
    機能: 全固定依存が現在も同じ原本であることを照合する。
    引数: なし。
    返り値: dict。固定資料と照合件数。
    """
    path = common.BASE / '事前固定.json'
    value = common.read(path)
    for relative, expected in value['SHA256'].items():
        assert common.sha(common.ROOT / relative) == expected, relative
    return dict(資料SHA256=common.sha(path), 依存件数=len(value['SHA256']))


def artificial_periods(proof: dict) -> dict:
    """
    機能: 同mainの人工36口座を8期間へ集計し、未実行だったstability依存まで通す。
    引数: proof(dict)はsupport内へ保存した人工main出力。
    返り値: dict。期間・安定性の照合件数と全再算定値。
    """
    import artificial
    catalog = common.module('96正式独立条件', common.BASE / 'catalog.py')
    accounts = common.module('96補足人工根会計', common.BASE / 'accounting.py')
    research = common.module('96補足人工根集計', common.BASE / 'research.py')
    session = '2099-01-01_Day'
    periods = ('全31', '前16', '後15', '旧30', '後14', '追加1', 'デイ', 'ナイト')
    rebuilt, count = {}, 0
    for config in catalog.catalog():
        rows = proof['全会計'][config['id']]
        prices, prepared = {}, {}
        for symbol in catalog.SYMBOLS:
            record, signal, reference = artificial.fixture(symbol, 1, '費用床と次気配gap', config)
            record['session'] = session
            prices[session, symbol] = record
            prepared[session, symbol] = dict(record=record)
        rebuilt[config['id']] = {}
        for name in periods:
            independent = {symbol: full.MATH.aggregate(rows, symbol, [session]) for symbol in catalog.SYMBOLS}
            root = {symbol: accounts.aggregate(rows, symbol, [session]) for symbol in catalog.SYMBOLS}
            common.same(independent, root, name + '/期間会計')
            stable = full.MATH.stability(rows, config, prices, [session])
            root_stable = research.stability(rows, config, prepared, [session])
            common.same(stable, root_stable, name + '/期間安定性')
            rebuilt[config['id']][name] = dict(period=independent, stability=stable)
            count += 2
    return dict(商品期間=count, 安定性商品期間=count, 全期間再算定=rebuilt)


def main() -> None:
    """
    機能: 定数接続を明示固定して、原mainの人工終端と正式全範囲を同じ関数で実行する。
    引数: CLI --artificial又は--formal。追加再実行は根の明示許可済み。
    返り値: None。原監査又は原会計の不一致はそのまま例外。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--artificial', action='store_true')
    group.add_argument('--formal', action='store_true')
    args = parser.parse_args()
    fixed = frozen()
    catalog = common.module('96補足依存条件', common.BASE / 'catalog.py')
    assert catalog.SYMBOLS == ('TOPIX', 'NK225')
    assert not hasattr(common, 'SYMBOLS')
    common.SYMBOLS = catalog.SYMBOLS
    fingerprints = common.fingerprint([AUDIT / name for name in ('common.py', 'independent.py', 'full.py')])
    fingerprints.update(common.fingerprint([common.BASE / 'catalog.py', Path(__file__),
        common.ROOT / 'work/wave_v94/audit/full.py',
        AUDIT / '正式監査初回の純会計定数未接続と未完範囲.json']))
    if args.artificial:
        stage = SUPPORT / 'artificial_run'
        stage.mkdir(parents=True, exist_ok=True)
        for name in ('common.py', 'independent.py', 'full.py'):
            source, target = AUDIT / name, stage / name
            target.write_bytes(source.read_bytes())
            assert common.sha(source) == common.sha(target)
        old_here, old_argv = common.HERE, sys.argv
        try:
            common.HERE = stage
            sys.argv = [str(AUDIT / 'full.py'), '--artificial']
            full.main()
        finally:
            common.HERE, sys.argv = old_here, old_argv
        path = stage / '人工1場36口座の独立本番CLIと根台帳及び会計の保存終端.json'
        proof = common.read(path)
        assert proof['合格'] and proof['人工専用'] and proof['検査件数']['口座'] == 36
        periods = artificial_periods(proof)
        assert periods['商品期間'] == periods['安定性商品期間'] == 288
        fingerprints.update(common.fingerprint([path]))
        destination = SUPPORT / '同一依存定数補足と通常人工CLI36口座及び全8期間の終端検査.json'
        result = dict(合格=True, 人工36口座=proof['検査件数'], 全8期間=periods,
            人工場集合='全8期間は同じ明示人工1場。時間帯分類や未見性能の証明ではない。',
            原コード実行='凍結full.main及び旧純会計原本を実行。3バイト同一コピーは指紋用だけで実行しない。',
            既存証跡保護='人工時だけHEREをsupport/artificial_runへ向け、全人工保存先を分離。正式は原HERE。',
            正式全31実行=0)
    else:
        required = SUPPORT / '同一依存定数補足と通常人工CLI36口座及び全8期間の終端検査.json'
        artificial = common.read(required)
        assert artificial['合格'] and artificial['全8期間']['商品期間'] == 288
        for relative, expected in artificial['SHA256'].items():
            assert common.sha(common.ROOT / relative) == expected, relative
        old_argv = sys.argv
        try:
            sys.argv = [str(AUDIT / 'full.py'), '--formal']
            full.main()
        finally:
            sys.argv = old_argv
        path = AUDIT / '全18全31の全台帳会計と3代表の独立出口及び全原板の検算.json'
        proof = common.read(path)
        counts = proof['検査件数']
        assert proof['合格'] and not proof['人工専用']
        assert counts['口座'] == 1116 and counts['商品期間'] == 288
        assert counts['独立最初出口と23状態及び27親'] == 186
        fingerprints.update(common.fingerprint([path, required]))
        destination = SUPPORT / '同一依存定数補足による正式全1116口座及び288期間の最終受入.json'
        result = dict(合格=True, 正式証跡SHA256=common.sha(path), 検査件数=counts,
            原コード実行='凍結full.mainの正式分岐と全検算関数を全数実行。中断62口座の計算結果流用0。',
            人工終端及び全8期間の事前成功=True)
    assert frozen() == fixed
    for relative, expected in fingerprints.items():
        assert common.sha(common.ROOT / relative) == expected, relative
    result.update(依存補足='common.SYMBOLS=catalog.SYMBOLS。凍結catalogの同じ2商品tupleだけ。',
        初回不足='通常人工CLIが期間stability呼出しを覆わず、依存定数接続漏れを検出できなかった。',
        初回正式終了コード=1, 初回完了部分='第一条件62会計のみ。正式最終合格への流用0。',
        固定コード変更=0, 数学検算条件変更=0, 正答値変更=0, 実売買コード変更=0,
        固定依存= fixed, API取得=0, 実注文=0, SHA256=fingerprints)
    save(destination, result)
    print('依存補足driverの全要求と終端保存/再読込: 合格', flush=True)


if __name__ == '__main__':
    main()
