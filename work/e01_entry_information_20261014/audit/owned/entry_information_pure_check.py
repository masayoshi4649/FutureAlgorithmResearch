"""未完成の実源をimportせず、入口情報の境界と系譜の独立純期待を固定する。"""

import hashlib
import itertools
import json
from dataclasses import replace
from pathlib import Path
from entry_information_reference import Price, Volume, admitted, fak_allowance, price_both, volume_allowed


HERE = Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 入口四条件・signed対称性・境界・持越禁止を人工入力だけで検査する。
    引数: なし。
    返り値: None。新所有域へ純期待の合否とsource指紋を保存する。
    """
    observations = []
    checks = 0
    for symbol, side, up, down in itertools.product(('TOPIX', 'NK225'), (-1, 1), range(9), range(9)):
        count = up + down
        signed = side * (up - down) / count if count else None
        volume = Volume(4, 40, 400, 100., True, up, down, count, signed)
        expected25 = count >= 2 and signed >= .25 if count else False
        expected_selected = count >= 2 and signed >= (.5 if symbol == 'TOPIX' else .25) if count else False
        actual25 = volume_allowed(volume, symbol, side, 4, 40, 400, 100.)
        selected = volume_allowed(volume, symbol, side, 4, 40, 400, 100., True)
        assert actual25 == expected25 and selected == expected_selected
        checks += 2
        for price_ok, common_ok in itertools.product((False, True), repeat=2):
            for entry in ('PRICE_BOTH', 'VOL_SELECTED', 'VOL25', 'VOL25_PRICE_BOTH'):
                result = admitted(entry, actual25, selected, price_ok, common_ok)
                expected = {'PRICE_BOTH': price_ok, 'VOL_SELECTED': expected_selected,
                            'VOL25': expected25, 'VOL25_PRICE_BOTH': expected25 and price_ok}[entry] and common_ok
                assert result == expected
                checks += 1
        if count >= 2 and signed in (.25, .5, 1.):
            observations.append(dict(銘柄=symbol,方向=side,上票=up,下票=down,既signed釣合い=signed,
                                     VOL25=actual25,VOL_SELECTED=selected))
    # ----------------------------------------
    for side, k1, k2, n1, n2, b1, b2 in itertools.product(
            (-1, 1), (False, True), (False, True), (0, 1, 2, 4), (0, 1, 2, 4),
            (-1., -.75, -.25, 0., .25, .749999, .75, 1.),
            (-1., -.75, -.25, 0., .25, .749999, .75, 1.)):
        own, peer = Price(k1, n1, b1), Price(k2, n2, b2)
        expected = k1 and k2 and n1 >= 2 and n2 >= 2 and side * b1 >= .25 and side * b2 >= .25
        strong = int(k1 and k2 and side * b1 >= .75 and side * b2 >= .75)
        assert price_both(own, peer, side) == expected
        assert fak_allowance(own, peer, side) == strong
        checks += 2
    # ----------------------------------------
    signed_short = Volume(4, 40, 400, 100., True, 1, 3, 4, .5)
    assert volume_allowed(signed_short, 'TOPIX', -1, 4, 40, 400, 100., True)
    assert admitted('VOL25', True, True, False)
    assert not admitted('VOL25_PRICE_BOTH', True, True, False)
    assert fak_allowance(Price(True, 1, -.75), Price(True, 1, -1.), -1) == 1
    assert not price_both(Price(True, 1, -.75), Price(True, 1, -1.), -1)
    assert fak_allowance(Price(False, 4, -1.), Price(True, 4, -1.), -1) == 0
    assert not volume_allowed(replace(signed_short, known=False, up=None, down=None, count=None, signed_balance=None),
                              'TOPIX', -1, 4, 40, 400, 100.)
    checks += 7
    rejected = []
    mutations = (dict(publication_row=5), dict(raw_row=41), dict(raw_seq=401),
                 dict(price_time=101.), dict(count=3), dict(signed_balance=-.5),
                 dict(signed_balance=float('nan')), dict(up=-1))
    for mutation in mutations:
        try:
            volume_allowed(replace(signed_short, **mutation), 'TOPIX', -1, 4, 40, 400, 100.)
        except AssertionError:
            rejected.append(list(mutation)[0])
        else:
            raise AssertionError(mutation)
    checks += len(rejected)
    source = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
              (HERE / 'entry_information_reference.py', Path(__file__))}
    proof = dict(全合格=True,純確認数=checks,境界事例=observations,系譜不整合拒否=rejected,
                 source_SHA256=source,完成実源接続=False,
                 範囲='人工票schemaと入口採否及び旧FAK許容だけ。実源・正式登録・金融効能は未確認。',
                 読取=dict(金融=0,原入力=0,板=0,台帳=0,API=0,実源import=0),
                 留保='公表出来高正増とLast対直前BBOの代理票は、真の方向別攻撃数量ではない。')
    path = HERE / '原公開signed票と価格票分離の独立純期待.json'
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True,純確認数=checks,証跡=str(path),SHA256=hashlib.sha256(path.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
