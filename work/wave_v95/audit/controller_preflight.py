"""隔離した人工素材だけでrootcontrollerと独立fullの通常CLIを終端保存まで通す。"""

import hashlib
from datetime import date, timedelta
import json
from pathlib import Path
import pickle
import socket
import subprocess
import sys

import numba
import numpy as np

import common
import artificial_loss


BASE = common.HERE / 'controller_fixture_final_31_sparse'


def write(path: Path, value: object) -> None:
    """
    機能: 人工専用fixture領域だけへ保存する。
    引数: path(Path)、value(object)。JSON又はpickleの内容。
    返り値: None。rootの正式front/back/事前固定は変更しない。
    """
    assert path.resolve().is_relative_to(BASE.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.pkl':
        with path.open('wb') as stream:
            pickle.dump(value, stream, protocol=5)
    else:
        path.write_text(json.dumps(common.clean(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def prepared(config: dict, session: str, symbol: str) -> dict:
    """
    機能: 合法人工執行へ旧22源と別LP四源を明示し、controller台帳用入力を作る。
    引数: config(dict)、session/symbol(str)。人工条件・場・商品。
    返り値: dict。record/signalと人工候補診断。source候補の本検査は別の全62純準備証跡。
    """
    record, signal = artificial_loss.fixture(symbol, '正常な四源反転', session.endswith('_Night'), config)
    record['session'] = session
    observed = signal['loss_observations']
    size = len(signal['grid'])
    signal.update(peer_source=observed[:, 5].astype(np.int64), peer_valid=observed[:, 19] == 1,
                  peer_mid=(observed[:, 8] + observed[:, 9]) / 2., peer_bid=observed[:, 8], peer_ask=observed[:, 9],
                  peer_width=8. * signal['peer_tick'], own_source=observed[:, 0].astype(np.int64),
                  own_source_time=observed[:, 2], peer_source_time=observed[:, 7],
                  price_own_index=observed[:, 0].astype(np.int64), price_peer_index=observed[:, 5].astype(np.int64),
                  price_own_raw_seq=observed[:, 1].astype(np.int64), price_peer_raw_seq=observed[:, 6].astype(np.int64),
                  price_own_time=observed[:, 2], price_peer_time=observed[:, 7],
                  price_own_valid=observed[:, 18] == 1, price_peer_valid=observed[:, 19] == 1,
                  price_observable=np.zeros(size, bool), price_mode=np.zeros(size, np.int8),
                  raw_range_valid=np.zeros(size, bool), raw_range_eligible=np.zeros(size, bool),
                  raw_oldest_time=np.full(size, np.nan), raw_mode=np.zeros(size, np.int8), valid=np.ones(size, bool))
    return dict(record=record, signal=signal,
                trend_candidate_state=dict(人工直接event=True, candidates=np.flatnonzero(signal['event']).copy()),
                trend_lp_allowed={side: np.ones(size, bool) for side in (-1, 1)})


def controller_main(controller: object, option: str) -> None:
    """
    機能: 隔離素材を持つrootcontrollerのmainを、通常CLIと同じ引数処理で通す。
    引数: controller(object)。rootresearchモジュール。option(str)。実行段階。
    返り値: None。引数は終了後に元へ復元する。
    """
    previous = sys.argv
    try:
        sys.argv = ['research.py', option, '--workers', '1']
        controller.main()
    finally:
        sys.argv = previous


def main() -> None:
    """
    機能: 前38→参考選定→後38→分析値保存→独立full.main通常CLIの終端を検査する。
    引数: なし。
    返り値: None。人工専用包括証跡を95auditへ保存。正式95損益は0。
    loaderとprepareの境界だけを明示人工へ接続し、controller/main/ledger/会計/保存/独立監査の式を変えない。
    """
    socket.socket.connect = artificial_loss.deny
    socket.create_connection = artificial_loss.deny
    assert not (BASE / 'front/results').exists() and not (BASE / 'back/results').exists(), '人工fixtureを黙って再利用しません'
    sys.path.insert(0, str(common.WORK))
    try:
        controller = common.module('95人工controller通常main', common.WORK / 'research.py')
    finally:
        sys.path.pop(0)
    numba.config.CACHE_DIR = str(common.HERE / 'jit')
    configs = controller.catalog.catalog()
    sessions = [str(date(2001, 1, 1) + timedelta(days=index // 2)) + ('_Day' if index % 2 == 0 else '_Night')
                for index in range(31)]
    all_prepared = {config['id']: {(session, symbol): prepared(config, session, symbol)
                    for session in sessions for symbol in common.SYMBOLS} for config in configs}
    first = all_prepared[configs[0]['id']]
    material = dict(prices={key: value['record'] for key, value in first.items()})
    paths = [common.WORK / name for name in ('catalog.py', 'data.py', 'strategy.py', 'engine.py', 'accounting.py', 'research.py')]
    paths += [Path(__file__), Path(common.__file__), Path(artificial_loss.__file__), common.HERE / 'full.py']
    fingerprints = common.fingerprint(paths)
    fixed = dict(人工専用=True, 全31既知=True, 条件=configs, 主=controller.catalog.PRIMARY,
                 全31=sessions, 前16=sessions[:16], 後15=sessions[16:], 旧30=sessions[:-1], 後14=sessions[16:-1], 追加1=sessions[-1:],
                 SHA256=fingerprints)
    write(BASE / '事前固定.json', fixed)
    controller.HERE = BASE
    controller.data.load_inputs = lambda verify=True: material
    controller.strategy.prepare = lambda supplied, config: all_prepared[config['id']]
    for option in ('--run-front', '--select', '--run-back'):
        controller_main(controller, option)
    # ----------------------------------------
    # 根の独立fullとは別の会計で作られるanalysis値を人工だけで保存する。
    results = {}
    period_map = {name: fixed[name] for name in ('全31', '前16', '後15', '旧30', '後14', '追加1')}
    period_map.update(デイ=[session for session in sessions if session.endswith('_Day')],
                      ナイト=[session for session in sessions if session.endswith('_Night')])
    for config in configs:
        front = json.loads((BASE / 'front/results' / (config['id'] + '.json')).read_text(encoding='utf-8'))
        back = json.loads((BASE / 'back/results' / (config['id'] + '.json')).read_text(encoding='utf-8'))
        rows = sorted(front['rows'] + back['rows'], key=lambda row: (row['session'], row['symbol']))
        periods = {name: {symbol: controller.accounting.aggregate(rows, symbol, selected)
                         for symbol in common.SYMBOLS} for name, selected in period_map.items()}
        stable = {name: controller.stability(rows, config, all_prepared[config['id']], selected)
                  for name, selected in period_map.items()}
        results[config['id']] = dict(config=config, rows=rows, periods=periods, stability=stable)
    write(BASE / 'analysis/比較結果.json', dict(人工専用=True, results=results))
    write(BASE / 'fixture.pkl', dict(material=material, prepared=all_prepared))
    child = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(common.HERE / 'full.py'), '--artificial', str(BASE)],
                           cwd=common.ROOT, check=False)
    assert child.returncode == 0, ('独立full.main通常CLI終端不合格', child.returncode)
    proof_path = common.HERE / '人工専用_全38監査main終端保存と全源及び期間会計.json'
    terminal = json.loads(proof_path.read_text(encoding='utf-8'))
    assert terminal['合格'] and terminal['人工専用'] and terminal['検査件数']['口座'] == 2356
    assert terminal['検査件数']['商品期間集計'] == 608
    common.exact(common.fingerprint(paths), fingerprints)
    print('rootcontrollerの前後/選定/ledger保存と独立full.mainの全終端が通常CLIで合格しました。', flush=True)
    binding = common.fingerprint([proof_path,
                                 common.HERE / '全38の実親料金負と四源反転及び最新親解除の独立人工検算.json',
                                 common.HERE / '100万人工原行の公開変化と元全原行による同一loss66及び性能検査.json',
                                 BASE / '事前固定.json', BASE / '前16参考代表.json', BASE / 'analysis/比較結果.json'])
    fingerprints.update(binding)
    artificial = json.loads((common.HERE / '全38の実親料金負と四源反転及び最新親解除の独立人工検算.json').read_text(encoding='utf-8'))
    assert artificial['合格'] and artificial['検査']['人工台帳'] == 2432
    for relative, digest in artificial['SHA256'].items():
        assert common.sha(common.ROOT / relative) == digest, relative
    fingerprints.update(artificial['SHA256'])
    benchmark = json.loads((common.HERE / '100万人工原行の公開変化と元全原行による同一loss66及び性能検査.json').read_text(encoding='utf-8'))
    assert benchmark['合格'] and artificial['全2432で公開変化行と元全原行Pythonの66列完全一致']
    for relative, digest in benchmark['SHA256'].items():
        assert common.sha(common.ROOT / relative) == digest, relative
    fingerprints.update(benchmark['SHA256'])
    common.save('全38独立人工台帳とrootledger及び監査main終端の包括検算.json',
                dict(合格=True, 人工台帳=2432, root保存人工口座=2356, 人工商品期間=608,
                     rootcontroller通常main終端=True, rootledger全新項目復元=True,
                     独立full通常CLI終端保存及び再読込=True, 末尾依存を明示import=True,
                     全人工明示境界合格=True, 保存及び再読込=terminal['検査件数'], SHA256=fingerprints,
                     全2432で元全原行Pythonと公開変化行の66列完全一致=True,
                     追加長人工400万原行の66列完全一致=True, 会計の全原板間引き=0,
                     正式95損益実行=0, 正式95損益閲覧=0, API取得=0, 実注文=0,
                     人工接続='loader/prepareのみ人工providerへ接続。rootcontroller main/ledger/会計/保存及び独立full会計/期間/指紋/終端保存の式は変更0。入力分類は別の全62独立純準備証跡で検証。',
                     正式監査の件数='2356口座/608商品期間。人工2356小口座の一致を正式合格へ流用しない。'))


if __name__ == '__main__':
    main()
