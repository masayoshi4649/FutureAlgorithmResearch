"""四入口源の全62純準備を、敵対担当の別式及び独立写像へ接続して照合する。"""

from pathlib import Path
import socket

import numba
import numpy as np

import common


ORACLE_PATH = common.WORK / 'review_pre/正常LP候補と旧板資格の分離を全62入力で反証.py'


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 純準備監査から外部通信を呼べないようにする。
    引数: args(tuple)、kwargs(dict)。接続引数。
    返り値: None。呼出し時は例外。
    """
    raise RuntimeError('純準備監査の通信は禁止')


def mapping(times: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """
    機能: 前原行時計との区間から、新しく到達した最新格子を自己原行へ一度だけ写す。
    引数: times/grid(ndarray[float])。自己保存代理時計と共同格子。
    返り値: ndarray[int32]。各自己原行へ初めて公開された最新格子又は−1。
    正式mappingの格子ループを呼ばず、同時計後続に再公開しない。
    """
    last = np.searchsorted(grid, times, side='right') - 1
    safe = np.maximum(last, 0)
    prior_time = np.r_[-np.inf, times[:-1]]
    accepted = (last >= 0) & (grid[safe] > prior_time) & (times - grid[safe] <= 10.)
    result = np.full(len(times), -1, np.int32)
    result[accepted] = last[accepted]
    return result


def observations(material: dict, key: tuple[str, str]) -> np.ndarray:
    """
    機能: rawLPと旧BBOを別index・原seq・時計で22列へ公開する独立素材を作る。
    引数: material(dict)、key(tuple[str,str])。セッションと商品。
    返り値: ndarray[float,22列]。元loss_observations関数は呼ばない。
    """
    session, own = key
    peer = 'NK225' if own == 'TOPIX' else 'TOPIX'
    grid = material['grids'][session]['grid']
    result = np.full((len(grid), 22), np.nan)
    for position, symbol in enumerate((own, peer)):
        board = material['grids'][session]['markets'][symbol]['current']
        raw = material['prices'][session, symbol]
        source = board['index']
        known = source >= 0
        offset = position * 5
        result[:, offset] = source
        result[:, offset + 1] = -1
        result[known, offset + 1] = raw['seq'][source[known]]
        result[known, offset + 2] = raw['time_s'][source[known]]
        result[:, offset + 3] = board['bid']
        result[:, offset + 4] = board['ask']
        result[:, 18 + position] = (board['valid'] & board.get('q_valid', board['valid'])
                                    & np.isfinite(board['bid']) & np.isfinite(board['ask'])
                                    & (board['bid'] > 0) & (board['ask'] > board['bid']))
        lp = material['trend_prices']['I3'][session]['markets'][symbol]['current']
        offset = 10 + position * 4
        result[:, offset] = lp['index']
        result[:, offset + 1] = lp['raw_seq']
        result[:, offset + 2] = lp['time_s']
        result[:, offset + 3] = lp['value']
        result[:, 20 + position] = lp['valid']
    return result


def verify(material: dict, key: tuple[str, str], config: dict, prepared: dict) -> dict:
    """
    機能: 独立候補・許可を自己原行へ接続し、P0〜P3のeventと22源列を検査する。
    引数: material/config/prepared(dict)、key(tuple[str,str])。
    返り値: dict。候補格子・原行・イベント・四源の件数。
    敵対担当のpermission/candidateは正式strategyの関数を呼ばない別実装として再利用する。
    """
    review = common.module('95入口監査の敵対独立式読取', ORACLE_PATH)
    record, signal = prepared['record'], prepared['signal']
    session, symbol = key
    price = material['trend_prices']['I3'][session]
    execution = material['grids'][session]
    source = config['trend_source']
    allowed = {side: review.permission(price, execution, side) for side in (-1, 1)}
    common.exact(allowed, prepared['trend_lp_allowed'])
    expected_map = mapping(record['time_s'], signal['grid'])
    common.exact(expected_map, signal['mapped'])
    if source in ('P0', 'P1'):
        expected_candidate = material['legacy'][key]
    else:
        expected_candidate = review.candidate(key, material, source, signal)
        positions = price['candidate_positions']
        peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
        expected_candidate.update(own_source=price['markets'][symbol]['current']['index'][positions],
                                  peer_source=price['markets'][peer]['current']['index'][positions])
    common.exact(expected_candidate, prepared['trend_candidate_state'])
    event = np.zeros(len(record['time_s']), np.int8)
    for candidate in expected_candidate['candidates']:
        decision, side = int(candidate[1]), int(candidate[2])
        published = expected_map[decision]
        if published < 0:
            continue
        yes = (material['entries'][session]['entries']['J2']['long_allowed' if side == 1 else 'short_allowed'][published]
               if source == 'P0' else allowed[side][published])
        if yes:
            event[decision] = side
    common.exact(event, signal['event'])
    common.exact(observations(material, key), signal['loss_observations'])
    common.exact(material['execution_lp_index'][key], signal['execution_lp_index'])
    return dict(候補格子=len(expected_candidate['states']), 原行=len(event), 新規event=int(np.count_nonzero(event)),
                四源格子=len(price['grid']))


def main() -> None:
    """
    機能: 四source各62口座を純準備し、旧state不変と38条件への入口共通性を確認する。
    引数: なし。
    返り値: None。新95/auditへ証跡を保存。engine及び正式PLは実行しない。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    data = common.module('入口監査95の保存素材', common.WORK / 'data.py')
    catalog = common.module('入口監査95の固定条件', common.WORK / 'catalog.py')
    strategy = common.module('入口監査95の純準備', common.WORK / 'strategy.py')
    numba.config.CACHE_DIR = str(common.HERE / 'jit')
    material = data.load_inputs()
    configurations = catalog.catalog()
    changing = {'id', 'trend_budget', 'trend_source', 'loss_reentry_kind', 'loss_reentry_trigger'}
    constant = [{key: value for key, value in config.items() if key not in changing} for config in configurations]
    assert all(config == constant[0] for config in constant)
    baseline = common.fingerprint([*material['paths'], common.WORK / 'strategy.py', common.WORK / 'catalog.py',
                                   Path(__file__), Path(common.__file__), ORACLE_PATH])
    old = strategy.LEGACY.prepare(material, configurations[0])
    rows = []
    for source in ('P0', 'P1', 'P2', 'P3'):
        config = next(value for value in configurations if value['id'] == source + '_R0')
        result = strategy.prepare(material, config)
        for key in sorted(result):
            for name, value in old[key]['signal'].items():
                if name != 'event':
                    common.exact(value, result[key]['signal'][name])
            if source == 'P0':
                common.exact(old[key]['signal']['event'], result[key]['signal']['event'])
            checked = verify(material, key, config, result[key])
            rows.append(dict(source=source, 場=key[0], 商品=key[1], 検査=checked))
        del result
        print(f'{source}: 全62候補/許可/原行event/別LP執行22源と旧stateが独立一致', flush=True)
    assert len(rows) == 4 * 62
    common.exact(common.fingerprint([common.ROOT / path for path in baseline]), baseline)
    common.save('4入口源全62の旧state保持と候補許可event及び22別源の独立純準備検算.json',
                dict(合格=True, 全31既知=True, 準備口座=248, 対応条件数=38,
                     全38への共通性='入口source以外の変更はid/数量/反転kind/triggerだけ。数量は同じref幅を使用し反転は執行後だけ作用する。',
                     旧I0全event及び全旧state一致=True, 新source全event及び四源一致=True,
                     検査=rows, SHA256=baseline, 正式95売買実行=0, 正式95損益閲覧=0, API取得=0, 実注文=0,
                     独立式の再利用='敵対担当の別permission/candidateと独立intervalmappingを接続。正式strategyのevent/traceを正答生成に使用しない。'))


if __name__ == '__main__':
    main()
