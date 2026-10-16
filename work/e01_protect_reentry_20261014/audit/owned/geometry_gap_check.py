"""一般価格欠測によるgeometry保持とresetイベントの未知化を独立に区別する。"""

import hashlib
import json
from pathlib import Path
import math
from price_vote_reference import Geometry


def main() -> None:
    """
    機能: 欠測挿入で押し/回復を消す反例を、所有実装未読の純期待へ保存する。
    引数: なし。両側対称の正常/欠測Lastだけを使う。
    返り値: None。金融/入力/台帳/APIの読取無しで証跡を作る。
    """
    here = Path(__file__).resolve().parent
    path = here / '通常欠測保持と取消後未知化の独立形状境界.json'
    assert not path.exists()
    observations = []
    for side in (1, -1):
        price = lambda shift: 4000 + side * shift
        g = Geometry(side, 4000, 0, price(0))
        g.observe(1, price(2), True, 'PULL', False)
        g.observe(2, price(1), True, 'PULL', False)
        before = dict(vars(g))
        result = g.observe(3, price(100), False, 'PULL', False)
        assert not result['entry'] and vars(g) == before
        result = g.observe(4, price(1.5), True, 'PULL', False)
        assert result['entry'] and g.anchor == price(0)
        observations.append(dict(side=side,通常欠測で保持=True,欠測後回復で参加=True))
        g = Geometry(side, 4000, 2, math.nan)
        result = g.observe(3, price(100), False, 'BREAK', True)
        assert not result['entry'] and math.isnan(g.anchor)
        result = g.observe(4, price(1.5), True, 'BREAK', True)
        assert not result['entry'] and g.anchor == price(1.5) and g.row == 4
        observations.append(dict(side=side,reset未知を保持=True,次正常初期化のみ=True))
    result = dict(全合格=True,人工境界=len(observations),観測=observations,
                  純参照SHA256=hashlib.sha256((here / 'price_vote_reference.py').read_bytes()).hexdigest(),
                  独立検査源SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  限界='owner source未import。完成source接続は別途。一般価格欠測とイベントresetの仕様差だけ。',
                  金融=0,入力=0,台帳=0,API=0)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('欠測挿入の純境界合格 ' + hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
