"""全原行から得た板の変化を、判断時点までの履歴だけで接続する。"""

from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent


def past_mean(times, values, sequence, seconds):
    """
    機能: 各判断原行までに観測した値の過去窓平均を計算する。同時計の後続行は使わない。
    引数: times/values/sequence(ndarray)は全原行時計・値・判断原seq、seconds(float)は価格時計上の窓。
    返り値: ndarrayは各判断行の平均。受信時計がないため、実受信秒数とは呼ばない。
    """
    finite = np.flatnonzero(np.isfinite(times))
    if not len(finite):
        return np.full(len(sequence), np.nan)
    ts = times[finite]
    assert np.all(np.diff(ts) >= 0.), '原時計逆行は個別監査が必要'
    value = values[finite]
    good = np.isfinite(value)
    count = np.r_[0, np.cumsum(good)]
    total = np.r_[0., np.cumsum(np.where(good, value, 0.))]
    right = np.searchsorted(finite, sequence, side='right')
    left = np.searchsorted(ts, times[sequence]-seconds, side='left')
    denominator = count[right]-count[left]
    return np.divide(total[right]-total[left], denominator, out=np.full(len(sequence), np.nan), where=denominator>0)


def attach(packet, prepared):
    """
    機能: 30秒の自己板変化と厳密過去の他市場板変化を原行特徴へ付加する。
    引数: packet/prepared(dict)は保存原行と公開価格特徴。
    返り値: dictは24列へOFI平均・距離加重厚さ平均を自己/相手の順に4列追加したデータ。
    """
    for symbol, data in prepared.items():
        path = HERE/'raw_features'/f'{symbol}_{packet["session"]}.npz'
        with np.load(path) as book:
            ts, seq = book['time_s'], data['ready']['seq'].astype(int)
            values = []
            for name in ('ofi_normalized', 'distance_imbalance'):
                value = book[name].copy()
                value[~book['in_session']] = np.nan
                values.append(past_mean(ts, value, seq, 30.))
        a = np.column_stack((data['features'], *values, np.full((len(seq),2),np.nan)))
        data['features'] = a
    for symbol, data in prepared.items():
        peer = prepared['TOPIX' if symbol=='NK225' else 'NK225']
        t, pt = data['ready']['time_s'], peer['ready']['time_s']
        selected = np.searchsorted(pt,t,side='left')-1
        safe = np.maximum(0,selected)
        valid = (selected>=0)&(t-pt[safe]<=15.)
        data['features'][valid,26:28] = peer['features'][safe[valid],24:26]
    return prepared


def configurations():
    """
    機能: 観測した失敗原因別の変更と統合を金融結果の参照前に固定する。
    引数: なし。
    返り値: list[dict]は12条件。昼夜の採否は別集計で判断する。
    """
    items = [
        ('40分逆方向の単純禁止',dict(entry_guard=1)),
        ('安値切上げ・高値切下げの再進行',dict(entry_guard=2)),
        ('二市場の板変化の支持',dict(flow_guard=1)),
        ('追撃の損失予算を初回実額以内',dict(add_guard=1)),
        ('利益保護前の追撃禁止',dict(add_guard=2)),
        ('二市場の逆行15秒で退出',dict(exit_guard=1)),
        ('二市場の逆行と板変化で退出',dict(exit_guard=2)),
        ('再進行確認と初回実額以内の追撃',dict(entry_guard=2,add_guard=1)),
        ('再進行確認と利益保護後の追撃',dict(entry_guard=2,add_guard=2)),
        ('再進行・追撃保護・二市場退出',dict(entry_guard=2,add_guard=2,exit_guard=1)),
        ('再進行・追撃保護・板で退出',dict(entry_guard=2,add_guard=2,exit_guard=2)),
        ('板支持・追撃保護・板で退出',dict(flow_guard=1,add_guard=2,exit_guard=2)),
    ]
    return [dict(id=f'G{i+1:02d}',name=name,changes=changes) for i,(name,changes) in enumerate(items)]
