"""実行部の四引数会計とC整数半量派生を、正式金融前の私有人工で検査する。"""

from pathlib import Path
import traceback

import numpy as np

import catalog
import common
import derivation
import runner
import selection

ART=common.module('106局所driverの人工素材',common.HERE/'artificial.py')
OLD=ART.INTERFACE.module('106局所driverの旧C_ONLY同bytes写し',common.HERE/'engine/old_regime_core.py')


def old_c_output(prepared: dict, normal: dict, cfg: dict, quantity: int) -> dict:
    """
    機能: 旧regime core同bytesの私有写しへCだけの人工入力を接続する。
    引数: prepared/normal/cfg(dict)、quantity(int)は人工価格と元C源及び実量。
    返り値: dictは旧C経済。旧source/cacheも正式金融も使用しない。
    """
    signal,settings=ART.INTERFACE.connect(prepared,normal,cfg,quantity)
    for name in ('quiet','quiet_start_s','entry_families','target_prices'):signal[name]=normal[name]
    out=OLD.execute(prepared['record'],signal,settings,python=True)
    ART.INTERFACE.assign_sources(prepared['record'],out,signal)
    return out


def main() -> None:
    """
    機能: 新12driver会計、無RのC同値、実料金半量と疎保存、5寄与を意味ある人工で照合する。
    引数: なし。私有人工素材と小sourceだけを読む。
    返り値: None。全33/旧金融台帳/原板/APIを読まない。
    """
    target=common.HERE/'実行部と半量C派生の結合人工検査.json';assert not target.exists();checks=[]
    paths=[Path(__file__),common.HERE/'runner.py',common.HERE/'derivation.py',common.HERE/'alias_proof.py',
        common.HERE/'engine/old_regime_core.py',common.HERE/'engine/accounting.py',common.HERE/'engine/accounting_reference.py']
    before={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in paths}
    try:
        for symbol in ('TOPIX','NK225'):
            q=5 if symbol=='TOPIX' else 10
            for side in (1,-1):
                packet=ART.packet_fixture(side,1);prepared=packet['prepared'][symbol];record=prepared['record']
                c_reference=derivation.c_normal(packet,symbol)
                aliases=[c for c in catalog.catalog() if c['local_policy']=='ALIGNED']
                for cfg in aliases:
                    normal=selection.build(packet,symbol,cfg);checked=derivation.verify_alias(packet,symbol,normal)
                    assert checked['R候補数']==0 and checked['C候補数']==1
                    actual=ART.INTERFACE.play(prepared,normal,cfg,q,python=True)
                    old=old_c_output(prepared,c_reference,cfg,q)
                    for name in ART.ARRAYS:np.testing.assert_array_equal(actual[name],old[name])
                checks.append(f'{symbol}/{side}/ALIGNED全6と旧C_ONLYのC資格根拠及び全経済exact')
                full=old_c_output(prepared,c_reference,cfg,2*q)
                original=runner.stored(full,c_reference,record)
                half=derivation.half_output(original,record,dict(path='私有人工',SHA256='人工参照'))
                expected=old_c_output(prepared,c_reference,cfg,q)
                for name in ART.ARRAYS:np.testing.assert_array_equal(half[name],expected[name])
                row=runner.ACCOUNT.inspect(('私有人工',symbol),record,half,c_reference)
                assert row['fees']==(418 if symbol=='TOPIX' else 220)
                assert row['lots']==q and half['raw_entry_diagnostics'][0]['quantity']==q
                checks.append(f'{symbol}/{side}/C元10/20から5/10へ注文別floorと全curve実派生同値')
                packed=runner.stored(half,c_reference,record)
                for name in ('curve','source_curve','target_trace'):
                    np.testing.assert_array_equal(derivation.expand(packed[name],len(record['seq'])),half[name])
                checks.append(f'{symbol}/{side}/疎変化行を同一原行へ復元して同値')
                mapping=runner.DIFFERENCE.trade_map(half,record);same=runner.DIFFERENCE.contribution(mapping,mapping)
                assert all(same[k]==0 for k in runner.FIELDS)
                checks.append(f'{symbol}/{side}/同量親mapと5寄与自己差0')

                rprepared,rnormal,_=ART.FIXTURE.fixture(symbol,side,2,1)
                rnormal['local_cancel_buy']=np.zeros(1001,bool);rnormal['local_cancel_sell']=np.zeros(1001,bool)
                cfg=next(c for c in catalog.catalog() if c['local_policy']=='OWN_VETO' and c['margin_ticks']==1 and c['range_entry']=='MARKET')
                output,row=runner.physical_case(rprepared,rnormal,cfg,('私有人工',symbol))
                assert len(output['trades'])==1 and row['campaigns']==1 and row['session']=='私有人工'
                assert row['局所方向取消の実fill前検算']==1
                checks.append(f'{symbol}/{side}/新12driverへ実playと最新会計4引数を結合')
                try:runner.physical_case(rprepared,rnormal,aliases[0],('私有人工',symbol))
                except AssertionError:pass
                else:raise AssertionError('ALIGNEDを新実金融へ流せました')
                checks.append(f'{symbol}/{side}/ALIGNED新再生を入口で拒否')
        assert before=={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in paths}
        common.write(target,dict(全合格=True,検査件数=len(checks),検査=checks,source_SHA256=before,
            私有人工のみ=True,正式input読取=0,旧金融台帳読取=0,新金融再生=0,原板読取=0,API取得=0,
            限界='半量同値は固定C出口とこの整数数量/料金だけ。ALIGNED R無発火は全33入力で別に確認する。'))
        print(f'実行部とC半量の結合人工 {len(checks)} 件合格、金融0',flush=True)
    except BaseException as exc:
        common.write(common.HERE/'実行部と半量C派生の人工失敗.json',dict(全合格=False,例外=repr(exc),検査完了=checks,
            source_SHA256=before,traceback=traceback.format_exc(),新金融再生=0))
        raise


if __name__=='__main__':main()
