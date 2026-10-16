"""検査済み既存入力の実接頭部で、新待機と自己相手未来の不変を確認する。"""

from copy import deepcopy
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
sys.path.insert(0, str(WORK / 'audit'))
sys.path.insert(0, str(WORK))
import common
import catalog
import strategy
import data


def save(path: Path, value: dict) -> None:
    """
    機能: 根の接頭検査資料だけを所有領域へ保存して再読込する。
    引数: path(Path)はroot_preflight内、value(dict)は検査証跡。
    返り値: None。別所有のaudit保存関数の範囲を変更しない。
    """
    assert path.resolve().is_relative_to(HERE.resolve())
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    assert json.loads(path.read_text(encoding='utf-8')) == value


def shorten(value: dict, cut: int) -> dict:
    """
    機能: 既知運用末を保ち、原行の因果入力だけを切断する。
    引数: value(dict)はprepared、cut(int)は原行数。
    返り値: dict。既存格子を保持し、端点返済は追加しない。
    """
    n = len(value['record']['time_s'])
    result = dict(value)
    result['record'] = {k: v[:cut].copy() if isinstance(v, np.ndarray) and len(v) == n else deepcopy(v)
                        for k, v in value['record'].items()}
    raw = {'event', 'mapped', 'quality', 'reset', 'execution_lp_index'}
    result['signal'] = {k: v[:cut].copy() if k in raw else deepcopy(v)
                       for k, v in value['signal'].items()}
    return result


def compare(short: dict, longer: dict, cut: int) -> None:
    """
    機能: 接頭部で既知の約定・予約・待機と途中の清算時価を比較する。
    引数: short/longer(dict)は再生結果、cut(int)は原行境界。
    返り値: None。未完親の将来更新列を過去へ遡って比較しない。
    """
    for name, column in (('orders', 0), ('trades', 3), ('events', 0),
                         ('entry_wait_events', 0), ('trend_parent_diagnostics', 2)):
        common.exact(short[name], longer[name][longer[name][:, column] < cut], name)
    for name in ('curve', 'source_curve', 'target_trace', 'trend_exit_state_trace', 'watch_state_trace'):
        common.exact(short[name], longer[name][:cut], name)
    a, b = short['entry_parent_diagnostics'], longer['entry_parent_diagnostics']
    b = b[b[:, 28] < cut]
    common.exact(a[:, :37], b[:, :37], '実予約までの入口親')
    common.exact(a[:, 44], b[:, 44], '予約時点の正常pair')
    filled = np.isfinite(a[:, 37]) & (a[:, 37] >= 0) & (a[:, 37] < cut)
    common.exact(a[filled, 37:41], b[filled, 37:41], '接頭部で実約定した新規')


def main() -> None:
    """
    機能: 五入口・四商品場・三時点で既存因果入力と新待機の接頭不変を検査する。
    引数: なし。
    返り値: None。全場損益を計算せず、既存入力の全raw再生成は別補足とする。
    """
    material = data.load_inputs()
    configs = {c['id']: c for c in catalog.catalog()}
    prepared = strategy.prepare(material, configs['A0_X3'])
    sessions = material['metadata']['sessions']
    def available(session: str) -> bool:
        """
        機能: 損益を使わず、両市場に検査可能な元候補がある場を選ぶ。
        引数: session(str)は保存場ID。
        返り値: bool。運用受付窓の候補が両市場にある場合True。
        """
        for symbol in catalog.SYMBOLS:
            item = prepared[session, symbol]; record = item['record']
            rows = np.flatnonzero(item['signal']['event'])
            rows = rows[(record['time_s'][rows] >= record['start']+300.)
                        & (record['time_s'][rows] < record['limit']-600.)]
            if not len(rows):
                return False
        return True
    chosen = [next(s for s in sessions[:16] if s.endswith('_Day') and available(s)),
              next(s for s in reversed(sessions[16:]) if s.endswith('_Night') and available(s))]
    counts = dict(代表=5, 商品場=0, 接頭=0, 自己未来=0, 相手未来=0, 待機を含む接頭=0, 実親を含む接頭=0)
    samples = []
    for ident in ('A0_X3', 'A1_X3', 'A2_X3', 'A5_X3', 'A7_X3'):
        config = configs[ident]
        for session in chosen:
            for symbol in catalog.SYMBOLS:
                key = session, symbol; value = prepared[key]; record = value['record']
                rows = np.flatnonzero(value['signal']['event'])
                rows = rows[(record['time_s'][rows] >= record['start'] + 300.)
                            & (record['time_s'][rows] < record['limit'] - 600.)]
                assert len(rows), key
                first = int(rows[0]); n = len(record['time_s']); t = float(record['time_s'][first])
                cuts = sorted(set([first+1] + [int(np.searchsorted(record['time_s'], t+s, side='right')) for s in (90., 300.)]))
                counts['商品場'] += 1
                for cut in cuts:
                    assert 0 < cut < n-50
                    piece = shorten(value, cut)
                    short = strategy.play(config, key, {key: piece}, finish=False)
                    longer_value = shorten(value, cut+50)
                    longer = strategy.play(config, key, {key: longer_value}, finish=False)
                    compare(short, longer, cut); counts['接頭'] += 1
                    counts['待機を含む接頭'] += int(np.any(short['watch_state_trace'][:, 0] != 0))
                    counts['実親を含む接頭'] += int(len(short['orders']) > 0)
                    own = deepcopy(longer_value)
                    for field in ('bid', 'ask', 'price'):
                        own['record'][field][cut:] += 100.*record['tick']
                    own['record']['quote_valid'][cut:] = False
                    own['signal']['event'][cut:] *= -1
                    compare(short, strategy.play(config, key, {key: own}, finish=False), cut)
                    counts['自己未来'] += 1
                    peer = deepcopy(longer_value)
                    future = peer['signal']['grid'] > piece['record']['time_s'][-1]
                    for field in ('entry_j2_long', 'entry_j2_short', 'wait_opposite_long', 'wait_opposite_short'):
                        peer['signal'][field][future] = ~peer['signal'][field][future]
                    peer['signal']['entry_peer_bbo'][future] = np.nan
                    compare(short, strategy.play(config, key, {key: peer}, finish=False), cut)
                    counts['相手未来'] += 1
                    samples.append(dict(method=ident, session=session, symbol=symbol, cut=cut,
                                        known_time=float(piece['record']['time_s'][-1])))
                print(ident+'/'+session+'/'+symbol+': 実接頭と未来不変一致', flush=True)
    assert counts['接頭'] == counts['自己未来'] == counts['相手未来'] == 60
    assert counts['待機を含む接頭'] > 0 and counts['実親を含む接頭'] > 0
    paths = [Path(__file__), WORK / 'engine.py', WORK / 'strategy.py', WORK / 'catalog.py', WORK / 'data.py',
             WORK / 'audit/common.py', WORK / 'engine_preflight/人工待機36と旧即時15台帳及びPythonJITの自己検査.json']
    save(HERE / '五代表の実接頭と新待機及び自己相手未来の不変.json', dict(
        合格=True, 検査件数=counts, 例=samples,
        範囲='旧95/96で検査済みの因果素材を直接使用し、新watchと新5入力の接頭不変を検査。原JSONLから全旧特徴を再生成する検査は別補足。',
        未来表現='原行境界で自己未来を、時計が境界後の公表格子で相手未来を変更。同clockの別受信順を保証しない。',
        旧入力依存=str((WORK.parent / 'wave_v96/事前固定.json').relative_to(common.ROOT)),
        完結した新条件口座=0, 正式97損益=0, API取得=0, 実注文=0,
        SHA256=common.fingerprint(paths)))


if __name__ == '__main__':
    main()
