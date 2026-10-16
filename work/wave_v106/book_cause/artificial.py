"""数量診断の価格対応と自己原行の未来不変を小さな人工列で確かめる。"""

from pathlib import Path

import numpy as np

from diagnose import digest, highs, past, quantity_path, save


def fixture() -> dict:
    """
    機能: 同価格数量変化を明確に追える人工十段列を作る。
    引数: なし。
    返り値: dictは実原本を参照しない6行の人工板。
    """
    n = 6; t = np.array([50.,70.,100.,100.,101.,110.])
    a = {key: np.ones(n, bool) for key in ('price_time_valid','in_session','price_row_valid',
        'depth_valid','depth_transition_valid','price_transition_valid','volume_delta_usable')}
    a.update(price_time_s=t, volume_time_s=t.copy(), raw_seq=np.arange(n), price_reset_reason=np.zeros(n,np.int64),
        bid=np.full(n,100.), ask=np.full(n,101.), bid_qty=np.full(n,20.), ask_qty=np.full(n,20.),
        bid_prices=np.tile(np.arange(100.,90.,-1),(n,1)), ask_prices=np.tile(np.arange(101.,111.),(n,1)),
        bid_quantities=np.full((n,10),20.), ask_quantities=np.full((n,10),20.),
        last=np.full(n,101.),volume_delta=np.array([0.,0.,5.,100.,500.,1000.]))
    a['_highs'] = highs(a)
    return a


def main() -> None:
    """
    機能: 同価格・十段外・自己原seq後の非参照を独立した既知値で確認する。
    引数: なし。人工データのみ使用。
    返り値: Noneは検査件数とsource指紋を私有領域へ保存する。
    """
    checks = []; a = fixture()
    a['bid_quantities'][1,0] = 5.; q = quantity_path(a,np.arange(3),1.,1)
    expected = 15./1.5
    assert q['買板']['減少_距離重み量'] == expected and q['買板']['減少後回復_距離重み量'] == expected
    checks.append('同価格100で20→5→20は減少15・後回復15を一度ずつ計上')
    a = fixture(); a['bid_prices'][1] += 1.; a['ask_prices'][1] += 1.
    a['bid_quantities'][2,-1] = 999.
    q = quantity_path(a,np.arange(3),1.,1)
    assert q['買板']['追加_距離重み量'] == 0. and q['買板']['減少_距離重み量'] == 0.
    checks.append('十段外へ消え戻った91の999枚を補充と計上しない')
    a = fixture(); peer = fixture(); old = past(a,peer,2,1,1.,1.)
    for key in ('bid','ask','bid_qty','ask_qty','last','volume_delta','bid_quantities','ask_quantities'):
        a[key][3:] = 99999.
    assert past(a,peer,2,1,1.,1.) == old
    checks.append('自己判断後の同時計原行3を含む全未来値変更でも直前統計不変')
    assert old['相手']['相手終端原seq'] == 1 and peer['price_time_s'][1] < a['price_time_s'][2]
    checks.append('相手の同時刻100を使わず厳密過去70を使用')
    a = fixture(); a['bid'][3] = 900.; a['ask'][3] = 901.
    assert highs(a).tolist() == [0,1,2,4,5]
    checks.append('同時計の後半板へ新最大公表行を差し替えない')
    save('数量診断の同価格と当時原行の人工確認.json', {'全合格':True, '検査数':len(checks), '検査':checks,
        '金融再生':0,'原本NPZAPI':0,'source':{'diagnose.py':digest(Path(__file__).with_name('diagnose.py')),
            'artificial.py':digest(Path(__file__))}})
    print('人工',len(checks),'終端合格',flush=True)


if __name__ == '__main__':
    main()
