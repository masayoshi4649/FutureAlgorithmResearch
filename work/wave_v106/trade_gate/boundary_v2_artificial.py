"""票と不明検査の窓境界を揃えた局所訂正だけを確認し、旧19/45人工は委譲する。"""

from copy import deepcopy
import json
from pathlib import Path

import numpy as np

import common
import votes


ARCHIVE=common.HERE/'archive/初版_窓外基準尾部の資格検査'


def main() -> None:
    """
    機能: 独立反例の窓外resetを除外し、窓内resetと同clock接頭拒否を確認する。
    引数: なし。
    返り値: None。旧証跡を同SHAのarchiveへ委譲し、新金融/入力再読は行わない。
    """
    prior=common.module('取引更新v1の保持済み境界',ARCHIVE/'votes.py')
    old_art=common.module('取引更新v1の人工fixtureのみ',ARCHIVE/'artificial.py')
    raw=old_art.fixture()
    raw['price_time_s']=np.array([0.,10.,10.,10.,20.,20.,21.,40.])
    raw['volume_reset_reason'][2]=32;raw['volume_delta_usable'][2]=False
    old=prior.measure(raw,prior.context(raw),6,10,1)
    new=votes.measure(raw,votes.context(raw),6,10,1)
    assert not old['known'] and old['reason']&8 and new['known'] and new['accepted'] and new['direction_votes']==2
    within=deepcopy(raw);within['volume_reset_reason'][4]=32;within['volume_delta_usable'][4]=False
    result=votes.measure(within,votes.context(within),6,10,1)
    assert not result['known'] and result['reason']&8
    known=deepcopy(raw);known['volume_reset_reason'][2]=0;known['volume_delta_usable'][2]=True
    assert prior.measure(known,prior.context(known),6,10,1)==votes.measure(known,votes.context(known),6,10,1)
    prefix={k:v[:7] for k,v in raw.items()}
    assert new==votes.measure(prefix,votes.context(prefix),6,10,1)
    current=votes.measure(raw,votes.context(raw),4,10,1)
    assert not current['accepted'] and current['direction_votes']==1
    import prepare
    archived={}
    for path in ARCHIVE.rglob('*'):
        if path.is_file():archived[path.relative_to(common.ROOT).as_posix()]=common.digest(path)
    delegate=dict(前人工19SHA256=common.digest(ARCHIVE/'取引更新方向票とscope及び接頭の人工検査.json'),
        前結合45SHA256=common.digest(ARCHIVE/'取引更新maskと単一執行及び料金の結合人工.json'),
        旧証跡不変=True,再実行件数=0)
    proof=dict(全合格=True,検査数=5,
        検査=['窓外同clock尾部resetの独立反例でv1Unknown→v2既知2買票',
            '窓内resetはv2でもUnknown', '既知対照の数値/採否はv1と同じ',
            '未来除去prefixで同値','同clock後半の未来2票目を前候補へ戻さない'],
        source_SHA256=prepare.sources(),archive_SHA256=archived,委譲=delegate,
        訂正='bad_prefixの開始だけをbaseline+1から票firstへ揃える。票/閾値/窓/出口不変更。',
        金融再生=0,大型入力読取=0,原book読取=0,API取得=0)
    common.write(common.HERE/'窓内資格境界訂正と旧人工委譲_v2.json',proof)
    print(json.dumps(dict(全合格=True,局所検査数=5,旧19_45再実行=0),ensure_ascii=False))


if __name__=='__main__':main()
