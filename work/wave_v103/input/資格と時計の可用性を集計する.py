"""完成した新npzだけから資格率と同clock率を数え、生原本を再走査しない。"""

import json
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import data


def rate(count: int, denominator: int) -> float | None:
    """
    機能: 観測可能な分母だけで割合を計算する。
    引数: count/denominator(int)は件数と分母。
    返り値: float|Noneは割合又は分母0の不明。
    """
    return count/denominator if denominator else None


def account(item: dict) -> dict:
    """
    機能: 完成した一口座の新npzから時計・出来高・表示板の可用件数だけを数える。
    引数: item(dict)は完成metadataの一口座診断。
    返り値: dictは件数と割合。金融再生、将来収益及び原本読取は行わない。
    """
    with np.load(ROOT/item['出力位置'], allow_pickle=False) as saved:
        pt, vt = saved['price_time_s'], saved['volume_time_s']
        inside, price_good = saved['in_session'], saved['price_row_valid']
        depth_good, depth_transition = saved['depth_valid'], saved['depth_transition_valid']
        known, usable, delta = saved['volume_delta_known'], saved['volume_delta_usable'], saved['volume_delta']
        bid, ask, last_valid = saved['bid'], saved['ask'], saved['last_valid']
    finite = np.isfinite(pt)
    pairs = finite[1:] & finite[:-1]
    same = pairs & (pt[1:] == pt[:-1])
    inside_pairs = inside[1:] & inside[:-1] & pairs
    same_inside = same & inside_pairs
    same_price = same_inside & price_good[1:] & price_good[:-1]
    changes_inside_clock = same_price & ((bid[1:] != bid[:-1]) | (ask[1:] != ask[:-1]))
    volume_match = inside & np.isfinite(vt) & (pt == vt)
    n = len(pt)
    result = dict(session=item['session'], symbol=item['symbol'], raw_rows=n,
        normal_execution_rows=item['normal_execution_rows'], inside_rows=int(inside.sum()),
        price_good_rows=int(price_good.sum()), depth_good_inside_rows=int((depth_good & inside).sum()),
        volume_known_rows=int(known.sum()), volume_usable_rows=int(usable.sum()),
        volume_positive_usable_rows=int((usable & (delta > 0)).sum()),
        volume_zero_usable_rows=int((usable & (delta == 0)).sum()),
        depth_and_volume_observable_rows=int((depth_transition & usable & last_valid & inside).sum()),
        finite_price_adjacent_pairs=int(pairs.sum()), same_price_clock_pairs=int(same.sum()),
        finite_inside_adjacent_pairs=int(inside_pairs.sum()), same_inside_price_clock_pairs=int(same_inside.sum()),
        same_inside_clock_bbo_changed_pairs=int(changes_inside_clock.sum()),
        matching_volume_price_clock_inside_rows=int(volume_match.sum()),
        received_at_present_rows=item['qualifications']['received_at_present'])
    result['rates'] = dict(price_good_of_raw=rate(result['price_good_rows'], n),
        depth_good_of_inside=rate(result['depth_good_inside_rows'], result['inside_rows']),
        volume_known_of_raw=rate(result['volume_known_rows'], n),
        volume_usable_of_raw=rate(result['volume_usable_rows'], n),
        volume_usable_of_inside=rate(result['volume_usable_rows'], result['inside_rows']),
        same_clock_of_finite_adjacent=rate(result['same_price_clock_pairs'], result['finite_price_adjacent_pairs']),
        same_clock_of_inside_adjacent=rate(result['same_inside_price_clock_pairs'], result['finite_inside_adjacent_pairs']),
        matching_volume_price_clock_of_inside=rate(result['matching_volume_price_clock_inside_rows'], result['inside_rows']))
    return result


def summary(rows: list[dict]) -> dict:
    """
    機能: 商品別又は全体の可用件数を足し、観測分母で割合を計算し直す。
    引数: rows(list[dict])は口座の件数。
    返り値: dictは合計件数と割合。各場割合の単純平均にはしない。
    """
    fields = [name for name, value in rows[0].items() if isinstance(value, int)]
    result = {name: sum(row[name] for row in rows) for name in fields}
    result['account_count'] = len(rows)
    result['rates'] = dict(price_good_of_raw=rate(result['price_good_rows'], result['raw_rows']),
        depth_good_of_inside=rate(result['depth_good_inside_rows'], result['inside_rows']),
        volume_known_of_raw=rate(result['volume_known_rows'], result['raw_rows']),
        volume_usable_of_raw=rate(result['volume_usable_rows'], result['raw_rows']),
        volume_usable_of_inside=rate(result['volume_usable_rows'], result['inside_rows']),
        same_clock_of_finite_adjacent=rate(result['same_price_clock_pairs'], result['finite_price_adjacent_pairs']),
        same_clock_of_inside_adjacent=rate(result['same_inside_price_clock_pairs'], result['finite_inside_adjacent_pairs']),
        matching_volume_price_clock_of_inside=rate(result['matching_volume_price_clock_inside_rows'], result['inside_rows']))
    return result


def main() -> None:
    """
    機能: 全64正式入力の終端後だけ、資格と価格代理時計の重複を別集計する。
    引数: なし。
    返り値: None。生原本再読取、金融再生及びAPIは0。
    """
    metadata_path = HERE/'metadata.json'
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    assert metadata['全合格'] and metadata['口座数'] == metadata['正式全64原本抽出'] == 64
    output = HERE/'全64の資格と時計及び出来高可用性.json'
    assert not output.exists()
    before = data.digest(metadata_path)
    rows = [account(item) for item in metadata['accounts'].values()]
    assert len(rows) == 64
    result = dict(全合格=True, 対象場数=32, 口座数=64, rows=rows,
        totals=summary(rows), by_symbol={symbol: summary([row for row in rows if row['symbol'] == symbol])
                                      for symbol in ('TOPIX', 'NK225')},
        定義='同clock率は隣接原行の両価格代理時計が有限なペアを分母にする。場内ペアの率も別掲。出来高usableは既知0も含む。',
        限界='同価格代理時計内でも板は変わる。ここで数える同clock率は真の同受信時刻や注文速度ではない。方向性や収益性の証明ではない。',
        SHA256={str(metadata_path.relative_to(ROOT)): before,
                str(Path(__file__).relative_to(ROOT)): data.digest(Path(__file__))},
        生原本の追加読取=0, 金融再生=0, 現在API取得=0, 実注文=0)
    assert data.digest(metadata_path) == before
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 商品別=result['by_symbol']), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
