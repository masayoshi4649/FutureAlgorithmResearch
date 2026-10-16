"""既署名の私有核心で将来価格を実際に変え、公開maskと過去注文を保全する。"""

from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import sys

import fak_reference as oracle
from fak_core_check_v2 import material


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
PRIVATE=HERE/'private_core_source_v2'
os.environ['NUMBA_CACHE_DIR']=str(HERE/'private_core_jit_v2')
sys.dont_write_bytecode=True
sys.path.insert(0,str(PRIVATE))
import numpy as np
import numba
numba.config.CACHE_DIR=str(HERE/'private_core_jit_v2')
import sizing_engine
import entry_policy
import catalog


def execute(account: dict, mode: str) -> tuple:
    """
    機能: 既署名の私有FAK核心で小人工だけを実行する。
    引数: account(dict)、mode(str) は純人工口座とFAK0/1。
    返り値: tuple は私有核心12配列。新金融又は原入力を使わない。
    """
    r=account['record'];q=account['quotes'];s=account['symbol'];f=catalog.FEE_RATIO[s]
    return sizing_engine.simulate(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],account['feed'],
        account['quiet'],account['quiet_force'],r['limit'],catalog.CAP[s],r['tick'],0.,True,
        account['entry_filter'],True,catalog.BUDGET[s],1.,catalog.VALUE[s],f[0],f[1],True,int(mode=='FAK1'))


def compare(left: tuple,right: tuple,cut: int) -> int:
    """
    機能: 時刻ではなくraw対応の人工行までの注文・イベント・清算接頭を照合する。
    引数: left/right(tuple)、cut(int) は新核心の二未来経路と過去終端。
    返り値: int は比較した配列数。未来の完結tradeを過去実現へ混ぜない。
    """
    for slot in (2,7,10):
        np.testing.assert_array_equal(left[slot][:cut+1],right[slot][:cut+1])
    for slot in (0,6,8,9,11):
        a=left[slot][left[slot][:,0]<=cut];b=right[slot][right[slot][:,0]<=cut]
        np.testing.assert_array_equal(a,b)
    np.testing.assert_array_equal(left[5][left[0][:,0]<=cut],right[5][right[0][:,0]<=cut])
    return 9


def main() -> None:
    """
    機能: 実際に異なる第一正常価格と未来suffixでも、公開状態が変わらない独立反例を検査する。
    引数: なし。直前の自所有11源人工を指紋として使う。
    返り値: None。小proofだけを新規保存する。
    """
    target=HERE/'FAK第一気配未来変更と公開mask保全の独立人工.json'
    assert not target.exists()
    p=HERE/'署名済みFAK核心11源と純小feed及び旧市場の独立人工_v2.json'
    saved=p.read_bytes();proof=json.loads(saved.decode('utf-8-sig'));assert proof['全合格']
    for path,sha in proof['source_SHA256'].items():
        assert hashlib.sha256((PRIVATE/Path(path).name).read_bytes()).hexdigest()==sha
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha
    comparisons=0;cases=0;gate_comparisons=0
    for symbol in ('TOPIX','NK225'):
        for side in (1,-1):
            source=oracle.fixture(symbol,side,'通常同値')
            changed=deepcopy(source)
            row=changed['rows'][2];tick=source['tick']
            if side>0:
                row['ask']=source['rows'][1]['ask']+100*tick;row['bid']=row['ask']-tick
            else:
                row['bid']=source['rows'][1]['bid']-100*tick;row['ask']=row['bid']+tick
            original=material(source);bad=material(changed)
            for gate in catalog.GATES:
                a=entry_policy.mask(original,gate);b=entry_policy.mask(bad,gate)
                np.testing.assert_array_equal(a['accepted'],b['accepted'])
                np.testing.assert_array_equal(a['reasons'],b['reasons'])
                gate_comparisons+=2
            for mode in ('FAK0','FAK1'):
                a=execute(original,mode);b=execute(bad,mode)
                comparisons+=compare(a,b,1)
                assert np.any((a[0][:,2]==0)&(a[0][:,7]==1))
                assert not np.any((b[0][:,2]==0)&(b[0][:,7]==1))
                assert a[9][0,15]==b[9][0,15]==1
                # 行2で失効した元予約を、行3以降の価格回復で復活させない。
                assert len(b[11][(b[11][:,1]==2)&(b[11][:,2]==0)])==1
                suffix=deepcopy(source)
                for row in suffix['rows']:
                    if row['row']>5:
                        row['bid']+=50*tick;row['ask']+=50*tick
                c=execute(material(suffix),mode)
                comparisons+=compare(a,c,5)
                cases+=1
    assert cases==8 and comparisons==144 and gate_comparisons==32
    output=dict(全合格=True,参照11源人工SHA256=hashlib.sha256(saved).hexdigest(),
        新核心source_SHA256=proof['source_SHA256'],経路反例=cases,過去配列照合=comparisons,公開gate配列照合=gate_comparisons,
        確認=['第一正常価格を実際に100T不利へ変えても、それを観測する前の公開mask/選択q/アンカー予約/料/注文は同じ。',
            '第一正常を観測した行から成立/失効が変わる。公開maskを後から拒否へ書き換えない。',
            '失効予約は後の有利気配で復活せず、新紙上親への参加を別に処理する。',
            '未来行6以後の気配を50T動かしても、行5までの影・実残玉・実注文/UID・fee/清算・FAK診断は同じ。'],
        未完了='interface/driver/全source固定は別監査。真のFAK到達と実商品板の物理fillは証明しない。',
        独立source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        金融=0,入力=0,台帳=0,原板=0,NPZ=0,API=0,共有又は旧source変更=0)
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,経路反例=cases,過去配列=comparisons,SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
