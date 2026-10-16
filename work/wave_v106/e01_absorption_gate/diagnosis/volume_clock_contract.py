"""旧出来高資格が反復を数学的に禁止するか、静的sourceの小人工だけで調べる。"""

from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
ROOT = HERE.parents[3]


def digest(path: Path) -> str:
    """
    機能: 小sourceの指紋を求める。
    引数: path(Path)は対象位置。
    返り値: strはSHA256。派生NPZ・原板は読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module(name: str, path: Path) -> object:
    """
    機能: 純抽出又は純票数学のsourceを固有名で読み込む。
    引数: name(str)、path(Path)はモジュール名と位置。
    返り値: objectは純関数を持つ部品。金融・データloadは呼ばない。
    """
    specification = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(specification)
    sys.modules[name] = value
    specification.loader.exec_module(value)
    return value


def rows(extra: bool = False) -> tuple:
    """
    機能: 同価格同板で累積出来高が増える人工原行と別時計を作る。
    引数: extra(bool)は価格時計停滞と出来高時計先行の枝を追加するか。
    返り値: tuple[list,float,float]は人工原行・場開始・終了。実データではない。
    """
    start = datetime(2000, 1, 3, 17, tzinfo=timezone(timedelta(hours=9))).timestamp()
    price = [0, 40, 41, 60, 80, 100, 100]
    volume_clock = list(price)
    volumes = [100, 100, 100, 106, 112, 118, 124]
    if extra:
        price.extend([100, 100, 103, 104])
        volume_clock.extend([101, 102, 103, 104])
        volumes.extend([130, 136, 142, 148])
    output = []
    for i, (pt, vt, volume) in enumerate(zip(price, volume_clock, volumes)):
        value = dict(Symbol='時計契約人工', SymbolName='時計契約人工専用', Exchange=2,
                     CurrentPrice=100.5,
                     CurrentPriceTime=datetime.fromtimestamp(start+pt, timezone(timedelta(hours=9))).isoformat(),
                     TradingVolume=volume,
                     TradingVolumeTime=datetime.fromtimestamp(start+vt, timezone(timedelta(hours=9))).isoformat())
        for depth in range(1, 11):
            value[f'Buy{depth}'] = dict(Price=100-(depth-1)*.5, Qty=10)
            value[f'Sell{depth}'] = dict(Price=100.5+(depth-1)*.5, Qty=10)
        output.append((i, value))
    return output, start, start+1000


def run() -> None:
    """
    機能: 反復2回以上が可能な人工と、別時計だけでusableが落ちる人工を確認する。
    引数: なし。
    返り値: None。診断所有域へ契約証跡を新規保存し、固定8sourceを変更しない。
    """
    paths = [ROOT/'work/wave_v103/input/core.py', ROOT/'work/wave_v103/input_v2/correction.py',
             SOURCE/'votes.py', SOURCE/'feature.py', SOURCE/'catalog.py']
    source_sha = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    core = module('出来高時計契約の純抽出', paths[0])
    votes = module('出来高時計契約の旧票', paths[2])
    catalog = module('catalog', paths[4])
    feature = module('出来高時計契約の固定述語', paths[3])
    artificial, start, end = rows(False)
    raw, _ = core.extract_rows(artificial, start, end)
    context = votes.context(raw)
    base = votes.measure(raw, context, 6, 60, 1)
    value = feature.measure(raw, context, 6, 1, base)
    assert base['known'] and base['direction_votes'] == 4
    assert value['known'] and value['hit'] and value['touch_count'] == 4
    assert value['touch_rows'] == [3, 4, 5, 6] and value['touch_activity_volume'] == 24
    assert raw['price_time_s'][5] == raw['price_time_s'][6]
    assert raw['volume_delta_usable'][5] and raw['volume_delta_usable'][6]
    # ----------------------------------------
    # 同じ原行で既に観測した出来高時計が古い現在値時計より先になると、knownとusableが分かれる。
    artificial, start, end = rows(True)
    raw, _ = core.extract_rows(artificial, start, end)
    for j in (7, 8, 9):
        assert raw['volume_delta_known'][j]
        assert raw['volume_delta_observed'][j] == 6
        assert not raw['volume_delta_usable'][j] and math.isnan(raw['volume_delta'][j])
    assert raw['volume_time_s'][7] > raw['price_time_s'][7]
    assert raw['volume_time_s'][8] > raw['price_time_s'][8]
    assert raw['volume_time_s'][9] == raw['price_time_s'][9]
    assert raw['volume_delta_usable'][10]
    context = votes.context(raw)
    stopped = votes.measure(raw, context, 8, 60, 1)
    assert not stopped['known'] and stopped['reason'] & 8
    assert not any(int(x) & 8 for x in raw['price_reset_reason'])
    # ----------------------------------------
    # v2は前価格時計逆行のみ追加除外するので、この逆行のない人工ではv1の資格を変えない。
    for p in paths:
        assert digest(p) == source_sha[p.relative_to(ROOT).as_posix()]
    witness = [dict(raw_seq=int(raw['raw_seq'][j]), price_time_s=float(raw['price_time_s'][j]),
                    volume_time_s=float(raw['volume_time_s'][j]),
                    volume_delta_known=bool(raw['volume_delta_known'][j]),
                    volume_delta_observed=float(raw['volume_delta_observed'][j]),
                    volume_delta_usable=bool(raw['volume_delta_usable'][j]),
                    volume_reset_reason=int(raw['volume_reset_reason'][j]),
                    price_reset_reason=int(raw['price_reset_reason'][j])) for j in range(5, 11)]
    target = HERE/'反復接触と出来高別時計の純source契約.json'
    assert not target.exists()
    target.write_text(json.dumps(dict(
        全合格=True, source_SHA256=source_sha, consumer_SHA256=digest(Path(__file__)),
        数学的な接触上限一回=False,
        同価格反復人工=dict(元W60票=base, 固定述語=value, 出来高差資格='4接触中最後2行はpriceclock同値でもusable=True'),
        時計先行人工=dict(原行=witness, 元窓の判断=stopped,
                          原因='現在又は直前volume_time>price_timeで、knownの正増差がusableから落ちる'),
        解釈='同原行に既に記録された出来高時計の先行を、自動的に未来データとは断定しない。Last方向も自動復活しない。',
        未測定='実素材でこの資格が反復接触をどれだけ落としたか。全原行の現象数。新しい資格の金融差。',
        原板=0, NPZ=0, 準備cache=0, 金融=0, API=0), ensure_ascii=False, indent=2, allow_nan=False)+'\n',
        encoding='utf-8', newline='\n')
    print('純source時計契約合格。同価格4接触は可能、別時計先行でknownとusableが分離。NPZ0。', flush=True)


if __name__ == '__main__':
    run()
