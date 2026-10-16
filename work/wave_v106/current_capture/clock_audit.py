"""一回取得した現在板の価格時計逆行を非金融で測り、保存順を変更せず証跡を残す。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def measure(path: Path) -> dict:
    """
    機能: 保存順と価格時計の逆行を同じ一読取で数え、最初の具体行を残す。
    引数: path(Path)は今回一回取得した銘柄別NDJSONの固定保存先。
    返り値: dictは件数、逆行例、最大逆行幅及び原本指紋。損益は計算しない。
    """
    assert path.parent.resolve() == (HERE / 'snapshot').resolve()
    digest = hashlib.sha256()
    previous = None
    high_water = None
    previous_point = None
    first = last = None
    reversal = below_max = missing = count = 0
    examples = []
    maximum = 0.0
    before = path.stat()
    with path.open('rb') as stream:
        for sequence, line in enumerate(stream):
            digest.update(line)
            value = json.loads(line)
            count += 1
            text = value.get('CurrentPriceTime')
            if not text:
                missing += 1
                continue
            stamp = datetime.fromisoformat(text)
            assert stamp.tzinfo is not None
            seconds = stamp.timestamp()
            point = dict(原連番0起点=sequence, 価格時刻=text,
                         現在値=value.get('CurrentPrice'),
                         買気配=value.get('Buy1'), 売気配=value.get('Sell1'))
            if first is None:
                first = point
            last = point
            if previous is not None and seconds < previous:
                reversal += 1
                difference = previous - seconds
                maximum = max(maximum, difference)
                if len(examples) < 12:
                    examples.append(dict(直前=previous_point, 逆行行=point, 逆行秒=difference))
            if high_water is not None and seconds < high_water:
                below_max += 1
            high_water = seconds if high_water is None else max(high_water, seconds)
            previous, previous_point = seconds, point
    after = path.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    return dict(全行数=count, 時計欠測=missing, 直前行からの価格時計逆行=reversal,
                過去最大価格時計より古い行=below_max, 最大直前逆行秒=maximum,
                最初=first, 最後=last, 最初12逆行例=examples,
                bytes=before.st_size, SHA256=digest.hexdigest(), 診断目的本文読取=1)


def main() -> None:
    """
    機能: 取得済み二銘柄を各一回診断し、入力停止の具体的な理由を保存する。
    引数: なし。取得manifestに記録した今回の固定板だけを読む。
    返り値: None。API、金融再生、時刻の並べ替え又は値の補完を行わない。
    """
    target = HERE / '価格時計逆行による入力停止の非金融診断.json'
    assert not target.exists()
    capture = json.loads((HERE / '取得完了.json').read_text(encoding='utf8'))
    values = {}
    for symbol in ('TOPIX', 'NK225'):
        path = Path(capture['symbols'][symbol]['原本位置'])
        values[symbol] = measure(path)
        assert values[symbol]['全行数'] == int(capture['symbols'][symbol]['snapshot']['sequence'])
        assert values[symbol]['bytes'] == capture['symbols'][symbol]['bytes']
    result = dict(診断完了=True, session=capture['session'], 商品別=values,
                  API取得=0, 新金融再生=0, 原本改変=0,
                  時刻並べ替え=0, 時計補完=0,
                  限界='価格時計は板受信時計ではない。逆行は原板の虚偽を示すものではなく、今回固定した単調価格時計consumerの前提不成立。')
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')
    for symbol, value in values.items():
        print(symbol, value['全行数'], '行、価格時計逆行', value['直前行からの価格時計逆行'], '回', flush=True)


if __name__ == '__main__':
    main()
