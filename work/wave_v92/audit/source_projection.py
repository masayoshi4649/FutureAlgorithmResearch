"""正式固定後、配分で源の売買自体が変化していないことを保存注文から独立確認する。"""

from pathlib import Path

import numpy as np

import common
import full


def read_orders(ident):
    """
    機能: 凍結後に保存した前16と後15の全注文を読む。
    引数: ident(str、条件ID)。
    返り値: dict[tuple,ndarray]の31場・2銘柄注文。再生や利益による条件選択はしない。
    """
    output = {}
    for part in ('front','back'):
        path = common.WORK/part/'ledgers'/f'{ident}.pkl'
        ledgers = full.read(path)
        assert not set(output)&set(ledgers)
        output.update({key:np.asarray(value['orders'],float) for key,value in ledgers.items()})
    return output


def main():
    """
    機能: 追従源の同数量完全一致と、反発源の数量以外の同経路を全31場で確認する。
    引数: なし。
    返り値: None。既存の固定・注文・公開成果は変更せず新しい監査証跡だけ保存する。
    """
    fixed = full.read(common.WORK/'事前固定.json')
    for relative,digest in fixed['SHA256'].items():
        assert common.sha(common.ROOT/relative)==digest,relative
    checks = []
    fingerprints = {}
    pairs = (('M_RB25_C','J8',0,False),('M_KS25','J8',0,False),
             ('M_RB25_C','R_B25_C',1,True),('M_KS25','KS25',1,True),
             ('R0_C','R0',1,False))
    for actual,baseline,source,ignore_quantity in pairs:
        current,previous = read_orders(actual),read_orders(baseline)
        assert set(current)==set(previous)
        count = 0
        for key in sorted(current):
            first = current[key][current[key][:,3]==source]
            second = previous[key][previous[key][:,3]==source]
            columns = [column for column in range(17) if column not in (2,16)]
            if ignore_quantity:
                columns = [column for column in columns if column not in (5,9)]
                common.same(first[:,5]*5,second[:,5])
            common.same(first[:,columns],second[:,columns])
            count += len(first)
        checks.append(dict(配分又は確認なし=actual,同経路対照=baseline,源=source,
                           口座数=len(current),注文数=count,枚数以外の完全一致=ignore_quantity,
                           費用端数は数量正規化しない=True,独立した売買改善と数えない=True))
        for ident in (actual,baseline):
            fingerprints.update(common.fingerprint([common.WORK/part/'ledgers'/f'{ident}.pkl' for part in ('front','back')]))
    common.save('固定配分の源別経路と確認なし対照の全31注文照合.json',dict(
        全合格=True,全31既知=True,検査=checks,再生=0,固定変更=0,実注文=0,現在API取得=0,
        SHA256=dict(common.fingerprint([Path(__file__),common.WORK/'事前固定.json']),**fingerprints)))
    print('配分2条件の追従・反発源と確認なし同執行の全31経路を独立照合',flush=True)


if __name__=='__main__':
    main()
