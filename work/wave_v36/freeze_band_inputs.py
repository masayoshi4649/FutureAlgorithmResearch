"""損益を使わず、入力素材・方向実体・相互独立の監査を同じ指紋へ束ねる。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import band_runner as runner

HERE, ROOT = runner.HERE, runner.ROOT


def main() -> None:
    """機能: 全入力監査の合格と全参照SHAを確認し、入力固定を保存する。

    引数: なし。返り値: なし (None)。方向の売買成績を計算・読取しない。
    """
    hashes = {}
    def check(path: Path, expected: str | None = None) -> str:
        """機能: 固定する資料の実体を一度読み、監査時指紋との一致を要求する。

        引数: path (Path)、expected (str|None)。返り値: SHA256 (str)。
        """
        relative = path.resolve().relative_to(ROOT).as_posix()
        if relative not in hashes:
            hashes[relative] = runner.digest(path)
        if expected is not None:
            assert hashes[relative] == expected, relative
        return hashes[relative]
    def load(name: str) -> dict:
        """機能: 指定したJSON本体も固定資料へ含める。

        引数: name (str)。返り値: JSON資料 (dict)。
        """
        check(HERE / name)
        return runner.read(HERE / name)
    artifact = load('input_artifacts.json')
    assert artifact['方向ファイル数'] == 273 and artifact['新信号方向ファイル数'] == 270
    assert artifact['旧比較方向ファイル数'] == 3
    assert artifact['新規根拠ファイル数'] == artifact['新規区間明細数'] == 270
    assert artifact['全26入力'] is True and artifact['新損益再生'] is False
    for relative, sha in artifact['SHA256'].items():
        check(ROOT / relative, sha)
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    assert len(inputs) == 26 and len({key[0] for key in inputs}) == 13
    audits = {}
    for name in ('volume_quote_audit.json', 'band_signal_audit.json', 'band_signal_independent_audit.json',
                 'band_subset_audit.json'):
        value = load(name)
        assert value['全監査合格'] is True
        assert value['新損益読取'] is False and value['売買再生'] is False
        assert value['API取得数'] == 0 and value['現在保存物使用'] is False
        for relative, sha in value['参照SHA256'].items():
            check(ROOT / relative, sha)
        audits[name] = value
    volume = audits['volume_quote_audit.json']
    assert volume['全入力数'] == 26 and volume['原本前後不変'] is True
    assert volume['接頭部検査数'] == volume['未来改変検査数'] == 52
    check(HERE / 'events.pkl', volume['出力SHA256'])
    volume_fixed = load('volume_quote_fixed.json')
    assert check(HERE / 'volume_quote_fixed.json') == volume['固定SHA256']
    assert volume['原本26SHA256'] == volume_fixed['原本26SHA256']
    volume_test = load('volume_quote_selftest.json')
    assert volume['人工検査'] == volume_test and volume_test['全合格'] is True and volume_test['検査数'] == 15
    for relative, sha in volume_fixed['参照SHA256'].items():
        check(ROOT / relative, sha)
    original_path = HERE.parent / 'wave_v35/input_causality_before_pnl.json'
    check(original_path)
    original = runner.read(original_path)['原本78SHA256']
    assert len(original) == 78
    for relative, sha in original.items():
        check(ROOT / relative, sha)
    assert all(original[name] == sha for name, sha in volume['原本26SHA256'].items())
    implementation = audits['band_signal_audit.json']
    assert implementation['全入力数'] == 26 and implementation['全条件時計入力数'] == 7020
    assert implementation['共通価格母集団数'] == 156
    assert implementation['接頭部列比較数'] == implementation['未来改変列比較数'] == 2808
    assert implementation['売買反射列比較数'] == 1404
    independent = audits['band_signal_independent_audit.json']
    assert independent['条件時計数'] == 270 and independent['条件入力組数'] == 1080
    assert independent['prefix入力比較数'] == 2160 and independent['未来改変入力比較数'] == 1080
    assert independent['上下反射入力比較数'] == 1080 and len(independent['検査行']) == 1080
    assert all(row['全一致'] is True for row in independent['検査行'])
    subset = audits['band_subset_audit.json']
    assert subset['対応集合数'] == len(subset['検査行']) == 2808 and subset['全入力数'] == 26
    assert all(row['採用episode部分集合一致'] is True for row in subset['検査行'])
    for audit in (implementation, independent, subset):
        assert audit['入力ソース前後不変'] is True
    synthetic = load('band_signal_selftest.json')
    assert synthetic['人工検査'] == implementation['人工検査']
    assert synthetic['人工検査']['全合格'] is True and synthetic['人工検査']['検査数'] == 13
    for relative, sha in synthetic['参照SHA256'].items():
        check(ROOT / relative, sha)
    revision = load('代理スコアの数値境界改訂.json')
    assert revision['仕様閾値変更'] is False and revision['新損益読取'] is False and revision['売買再生'] is False
    for label, name in (('旧信号', 'band_signals_cumsum_before_audit.py.txt'), ('新信号', 'band_signals.py'),
                       ('旧監査', 'band_signal_audit_before_fsum.py.txt'), ('新監査', 'band_signal_audit.py')):
        check(HERE / name, revision[label + 'SHA256'])
    check(Path(__file__))
    assert all(runner.digest(ROOT / relative) == sha for relative, sha in hashes.items()), '固定処理中の変更'
    value = dict(全入力監査合格=True, 方向ファイル数=273, 新規根拠ファイル数=270, 新規区間明細数=270,
        全入力数=26, 新信号時計条件数=270, 全条件時計入力数=7020, 共通価格母集団数=156,
        独立代表期間入力数=1080, 採用episode部分集合数=2808, 全出来高イベント数=volume['全イベント数'],
        原本数=78, 全条件方向SHA256=implementation['全条件方向SHA256'],
        全26因果検査ではない='全270は2代表期間×2銘柄。別途18代表条件は全26、全270×26は公開参照・共通母集団・部分集合を検査。',
        新損益読取=False, 売買再生=False, API取得数=0, 現在保存物使用=False,
        SHA256=dict(sorted(hashes.items())), 固定日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat())
    path = HERE / '入力固定.json'
    if path.exists():
        prior = runner.read(path)
        assert {k: v for k, v in prior.items() if k != '固定日時'} == {k: v for k, v in value.items() if k != '固定日時'}
    else:
        runner.save(path, value)
    print('全273方向・270根拠・270区間を監査済み入力へ固定。売買再生なし。', flush=True)


if __name__ == '__main__':
    main()
