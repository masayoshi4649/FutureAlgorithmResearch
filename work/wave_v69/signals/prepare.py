"""保存済み全56口座の入口を生成し、実原本の途中切断と未来改変を照合する。"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

from core import candidate_signals, arguments_from, SIGNAL_META
from check import shorter


HERE = Path(__file__).resolve().parent
PREPARED = HERE.parent / 'prepared'


def digest(path: Path) -> str:
    """機能: 保存済み入力または実装のSHA256を求める。

    引数: path(Path)。返り値: 16進SHA256(str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def reflected(arguments: tuple) -> tuple:
    """機能: 気配と数量とOFIと補充側を上下の鏡像にする。

    引数: arguments(tuple)。返り値: 鏡像の入口引数(tuple)。時計と品質を保つ。
    """
    axis = arguments[0][0] + arguments[1][0]
    result = list(arguments)
    result[0], result[1] = axis - arguments[1], axis - arguments[0]
    result[2], result[3] = arguments[3].copy(), arguments[2].copy()
    result[4] = -arguments[4]
    result[9] = -arguments[9]
    result[12] = axis - arguments[12]
    return tuple(result)


def local_segment(arguments: tuple, left: int, right: int) -> tuple:
    """機能: 連続した短い原本区間を独立の状態初期化から再生できる形にする。

    引数: arguments(tuple)、left/right(int)。返り値: 区間引数(tuple)。
    """
    event_mask = (arguments[8] >= left) & (arguments[8] < right)
    result = list(tuple(v[left:right] if k < 8 else v[event_mask] if k < 13 else v
                        for k, v in enumerate(arguments)))
    result[6] = result[6].copy()
    result[6][0] = True
    result[8] = result[8] - left
    return tuple(result)


def main() -> None:
    """機能: 入口仕様を固定して全56口座を生成し、因果性の証拠を保存する。

    引数: なし。返り値: なし(None)。取引損益は参照せずAPIアクセスもしない。
    """
    target = HERE / 'signals.pkl'
    assert not target.exists(), '入口の生成は完了済みです'
    specification = dict(固定時刻=datetime.now(timezone.utc).isoformat(), 入口仕様=SIGNAL_META,
        最小開始経過秒=300, 最大気配差呼値=2, 状態最大経過秒=120,
        ティック定義='同銘柄の最良気配中値が変わった価格イベント。原本行数と同義ではない。',
        機械判定='同秒でも原本順に処理。同行までの表示量と気配だけで候補を出す。約定・退出条件・将来収益は使わない。',
        不連続='reset、無効板、2呼値超の気配差、時計逆行、120秒超の時計空白で全状態を破棄。',
        往復='4/8呼値の進行を2/4呼値戻したとき反転。両気配の反対向き変更も必要。元legは120秒以内。',
        再開='4/8呼値の進行後2/4呼値押し、局所極値から2/4呼値反発し旧極値から2/4呼値以内。両気配も反発。新高安ができるまで同じ極値を使い回さない。',
        補充反転='最良から2呼値以内の価格の表示回復0.5/1倍。直近8中値イベントでその側へ2/4呼値接近。補充後はその側へ1呼値超え進む前に2/4呼値反転し両気配も戻る。',
        補充突破='近傍2呼値の価格の表示回復0.5/1倍。その価格を2/4呼値越え、補充時比で両気配も2/4呼値前進、直近16中値イベント区間の最良OFI符号が同方向。',
        補充代理='元の価格別表示減少の80%以上と開始時最良表示量25%以上の表示回復完了。真の吸収、取消、成行、個別アルゴ注文を識別していない。',
        補充保持='最初の適格完了を固定。後続で時刻を延長しない。発火/120秒/T3は前進1呼値超/T4は逆方向へ価格帯から8呼値離脱で失効。上下候補が同時なら見送り。',
        ATR使用=False, EMA使用=False, 損益参照=False, 現在API取得=0,
        core_SHA256=digest(HERE / 'core.py'),人工監査_SHA256=digest(HERE / '入口人工経路の照合.json'),
        入力照合_SHA256=digest(PREPARED / '入力と特徴の照合.json'))
    (HERE / '入口仕様.json').write_text(json.dumps(specification, ensure_ascii=False, indent=2), encoding='utf-8')
    inputs = pickle.loads((PREPARED / 'inputs.pkl').read_bytes())
    features = pickle.loads((PREPARED / 'features.pkl').read_bytes())
    events = pickle.loads((PREPARED / 'events.pkl').read_bytes())
    assert len(inputs) == len(features) == len(events) == 56
    output = {}
    audits = []
    for key in sorted(inputs):
        ready, feature, completed = inputs[key], features[key], events[key]
        np.testing.assert_array_equal(ready['seq'], feature['seq'])
        np.testing.assert_array_equal(ready['time_s'], feature['time_s'])
        assert np.all(np.diff(ready['seq']) > 0)
        if len(completed):
            assert np.all(np.diff(completed['i']) >= 0)
            np.testing.assert_array_equal(feature['seq'][completed['i']], completed['seq'])
        args = arguments_from(feature, completed, ready['tick'], ready['start'])
        full = candidate_signals(*args)
        cut = len(ready['seq']) // 2
        np.testing.assert_array_equal(candidate_signals(*shorter(args, cut)), full[:, :cut])
        future = list(args)
        for column in (0, 1):
            future[column] = args[column].copy()
            future[column][cut:] += 20. * ready['tick']
        future[4] = args[4].copy()
        future[4][cut:] *= -7.
        future[6] = args[6].copy()
        future[6][cut:] = True
        future[12] = args[12].copy()
        future[12][args[8] >= cut] += 20. * ready['tick']
        np.testing.assert_array_equal(candidate_signals(*future)[:, :cut], full[:, :cut])
        # 真ん中の最大20,000原本行で反射を確認する。元区間も状態を初期化する。
        right = min(len(ready['seq']), cut + 20000)
        local = local_segment(args, cut, right)
        local_signal = candidate_signals(*local)
        np.testing.assert_array_equal(candidate_signals(*reflected(local)), -local_signal)
        output[key] = full
        audits.append(dict(セッション=key[0],銘柄=key[1],原本行数=len(ready['seq']),
            中値価格イベント数=int(np.count_nonzero(np.diff(feature['mid']))),
            同秒連続原本行数=int(np.count_nonzero(np.diff(feature['time_s']) == 0.)),
            中値価格イベント数の注記='不正板/リセット前後を除外する前の参考件数。候補状態はこれらを除外する。',
            途中切断一致=True,未来変更で過去一致=True,短区間上下反射一致=True,
            短区間信号数=[int(np.count_nonzero(x)) for x in local_signal],
            候補数=[int(np.count_nonzero(x)) for x in full],
            買い候補数=[int(np.count_nonzero(x == 1)) for x in full],
            売り候補数=[int(np.count_nonzero(x == -1)) for x in full]))
        print(f'{key}: 8入口生成・実原本prefix/未来改変/上下反射一致', flush=True)
    target.write_bytes(pickle.dumps(output, protocol=pickle.HIGHEST_PROTOCOL))
    record = dict(合格=True,口座数=len(output),実原本途中切断=56,未来改変=56,短区間上下反射=56,
        ATR使用=False,EMA使用=False,損益参照=False,現在API取得=0,
        signals_SHA256=digest(target),core_SHA256=digest(HERE / 'core.py'),
        全口座候補数=[sum(a['候補数'][k] for a in audits) for k in range(8)],口座別=audits)
    (HERE / '入口の実原本因果照合.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(合格=True,口座数=56,全候補=record['全口座候補数']), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
