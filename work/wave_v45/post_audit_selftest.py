"""売買を再生せず、全返済価格と既知資料の由来を人工値で検査する。"""

from __future__ import annotations

import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
specification = importlib.util.spec_from_file_location('f50_post_audit_selftest',HERE/'post_audit.py')
audit = importlib.util.module_from_spec(specification)
sys.modules[specification.name] = audit
specification.loader.exec_module(audit)


def fixture(symbol: str = 'TOPIX') -> tuple[dict,dict]:
    """機能: 部分減量・復元後の二脚返済と空売り損失を持つ人工台帳を作る。

    引数: symbol(str)。返り値: 台帳と別途計算した場集計(tuple[dict,dict])。
    利益32・損失20ポイント枚を基準とし、損失組と全決済枚数を保持する。
    """
    quantity = 5. if symbol == 'TOPIX' else 10.
    scale = quantity/5.
    factor = 1000. if symbol == 'TOPIX' else 10.
    trades = [[0,0,1,2*scale,100,104,1,3,2,30,8*scale],
        [0,0,1,3*scale,100,106,1,8,2,2,18*scale],
        [0,1,1,2*scale,103,106,5,8,2,2,6*scale],
        [1,2,-1,5*scale,100,104,11,18,2,1,-20*scale]]
    cycles = [[0,1,8,32*scale,quantity*2,2,quantity,quantity,1,2],
              [1,11,18,-20*scale,quantity*2,2,quantity,quantity,-1,1]]
    orders = [[1,0,0,1,quantity,100,20,1],[5,4,0,1,2*scale,103,31,1],
              [11,10,1,-1,quantity,100,20,1]]
    book = dict(session='人工',symbol=symbol,config=dict(point_value=factor,initial_qty=quantity),
        trades=trades,cycles=cycles,orders=orders,shadow_cycles=deepcopy(cycles),
        shadow_orders=[deepcopy(o) for o in orders if o[6] == 20],
        shadow_fingerprints=dict(人工共通影=True))
    row = dict(gross_profit_yen=32*scale*factor,gross_loss_yen=20*scale*factor,net_yen=12*scale*factor,
        profit_units=7*scale,loss_units=5*scale,zero_units=0,cycles=2,cycle_wins=1,cycle_losses=1,
        cycle_profit_yen=32*scale*factor,cycle_loss_yen=20*scale*factor,reductions=1,restorations=1,
        net_r=1.2,maximum_trade_profit=32*scale*factor,two_largest_cycle_profits=[32*scale*factor])
    return book,row


def rejected(function: object) -> bool:
    """機能: 不正な人工資料を経済的な不合格と混同せず拒否する。

    引数: function(Callable)。返り値: 例外を確認した場合True(bool)。
    """
    try:
        function()
    except (AssertionError,KeyError,ValueError,TypeError):
        return True
    return False


def main() -> None:
    """機能: 独立価格式・元組R・集中・全組差・由来の人工反例を保存する。

    引数: なし。返り値: なし(None)。実相場の保存成績も読まない。
    """
    records = []
    rejections = 0

    def check(name: str, condition: bool) -> None:
        """機能: 人工検査名と成功を記録し、不一致で停止する。

        引数: name(str)、condition(bool)。返り値: なし(None)。
        """
        assert condition,name
        records.append(dict(検査=name,一致=True))

    # ----------------------------------------
    # 独立計算の七関数は旧完備後監査と同じ構文であり、採否実装を呼ばない。
    inherited = {'initial','account','cell','distribution','pair','relationship','ratio'}
    trees = []
    for path in (HERE/'post_audit.py',HERE.parent/'wave_v44/post_audit.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        trees.append({n.name:ast.dump(n,include_attributes=False) for n in tree.body
                      if isinstance(n,ast.FunctionDef) and n.name in inherited})
    check('旧独立価格式七関数の構文一致',trees[0] == trees[1] and len(trees[0]) == 7)
    calculated = {}
    for symbol in audit.SYMBOLS:
        book,row = fixture(symbol)
        calculated[symbol] = audit.account(book,row)
        result = calculated[symbol]
        check(symbol+'の全脚価格から集計',result['net_yen'] == row['net_yen'] and
              result['profit_units'] == row['profit_units'] and result['loss_units'] == row['loss_units'])
        check(symbol+'の損失組と初回Rを維持',result['cycles'] == 2 and result['longs'] == result['shorts'] == 1
              and abs(result['net_r']-1.2) <= audit.EPS and result['groups'][1]['r'] == -2.)
        check(symbol+'の減量復元は各一回',result['reductions'] == result['restorations'] == 1)
    check('初回枚数と円倍率をRから分離',calculated['TOPIX']['net_r'] == calculated['NK225']['net_r']
          and calculated['TOPIX']['net_yen'] == 50*calculated['NK225']['net_yen'])
    book,row = fixture()
    for field,value in [('profit_units',5),('gross_profit_yen',31999),('net_r',2),('restorations',0),('cycles',1)]:
        broken = dict(row); broken[field] = value
        check(field+'の保存改竄を拒否',rejected(lambda:audit.account(book,broken))); rejections += 1
    for label,mutator in (
        ('脚損益',lambda b:b['trades'][0].__setitem__(10,99)),
        ('返済価格',lambda b:b['trades'][0].__setitem__(5,105)),
        ('影初回価格',lambda b:b['shadow_orders'][0].__setitem__(5,101)),
        ('元組損益',lambda b:b['cycles'][0].__setitem__(3,30)),
        ('初期R',lambda b:b['cycles'][0].__setitem__(4,9)),
        ('同時発注',lambda b:b['orders'][0].__setitem__(1,1)),
        ('影終了以後',lambda b:b['cycles'][0].__setitem__(2,9))):
        broken = deepcopy(book); mutator(broken)
        check(label+'の不整合を拒否',rejected(lambda:audit.account(broken,row))); rejections += 1
    part = [calculated['TOPIX'] for _ in range(13)]
    fields = ('gross_profit_yen','gross_loss_yen','net_yen','profit_units','loss_units','zero_units','cycles',
        'cycle_wins','cycle_losses','cycle_profit_yen','cycle_loss_yen','reductions','restorations','net_r')
    period = {f:sum(r[f] for r in part) for f in fields}
    period.update(average_cycle_payoff=1.6,drawdown_yen=20000.)
    value = audit.cell(part,period)
    check('全元組比と決済一枚比を分離',abs(value['比率']['元組PF']-1.6)<audit.EPS and
          abs(value['比率']['一枚平均勝敗比']-8/7)<audit.EPS)
    check('最大一勝と上位二勝の同時除外',value['最大勝ち元組除外収支円'] == 124000 and
          value['上位二勝ち元組同時除外収支円'] == 92000)
    check('買売活動を両方保持',value['買い元組数'] == value['売り元組数'] == 13 and value['活動込み基礎候補'])
    lone = dict(calculated['TOPIX']); lone['longs'] = 2; lone['shorts'] = 0
    check('片方向だけでは活動基礎未達',not audit.cell([lone]*13,period)['活動込み基礎候補'])

    # ----------------------------------------
    # 異なる初回や入口を対応させず、既知と新しい反証を明確に区別する。
    names = [f'人工{i:02}' for i in range(13)]
    books,accounts = {},{}
    specifications = {}
    for identifier in (audit.PRIMARY,audit.CONTROL,audit.BASELINE,audit.PREVIOUS_PRIMARY,audit.SAME_FRACTION):
        books[identifier] = {}; accounts[identifier] = {}
        specifications[identifier] = dict(signal_id='H019',entry_scale=1.,min_delay_seconds=0.,observed_fill=False)
        for name in names:
            for symbol in audit.SYMBOLS:
                material,saved = fixture(symbol)
                material['session'] = name
                books[identifier][(name,symbol)] = material
                accounts[identifier][(name,symbol)] = audit.account(material,saved)
    for identifier in (audit.CONTROL,audit.BASELINE,audit.PREVIOUS_PRIMARY,audit.SAME_FRACTION):
        paired = audit.pair(identifier,specifications,books,accounts,names,True)
        check(identifier+'の全組損失も含む対応',paired['全対応元組数'] == 52 and
              any(r['主案収支円']<0 for r in paired['全元組対応']) and
              all(r['差円'] == r['差R'] == 0 for r in paired['全元組対応']))
    for field,value in [('entry_scale',.8),('min_delay_seconds',1.),('observed_fill',True)]:
        broken = deepcopy(specifications); broken[audit.CONTROL][field] = value
        check(field+'が異なる組対応を拒否',rejected(lambda:audit.pair(audit.CONTROL,broken,books,accounts,names,False)))
        rejections += 1
    spec = dict(id=audit.PRIMARY,primary=True,role='reference',threshold=1.5)
    source = dict(spec=dict(spec,primary=False,role='primary_grid'),completed='旧人工完了',
        出力SHA256={str(i):str(i)*64 for i in range(8)},旧探索固定SHA256='0'*64)
    record = dict(id=audit.PRIMARY,全合格=True,全入力数=26,因果入力数=4,
        既知成果引継ぎ=True,新売買再生=False,reuse_source=source)
    check('既知主案の表示メタだけ許可',audit.provenance(spec,record,source))
    fresh = dict(id='G150_F50_N1__A120',全合格=True,全入力数=26,因果入力数=4,
        既知成果引継ぎ=False,新売買再生=True,reuse_source=None)
    check('新反証の由来は明示None',not audit.provenance(dict(id=fresh['id']),fresh,None))
    for label,change in (
        ('既知を新結果扱い',lambda r:r.update(既知成果引継ぎ=False,新売買再生=True)),
        ('既知ソース欠落',lambda r:r.pop('reuse_source')),
        ('既知入力不足',lambda r:r.update(全入力数=25))):
        broken = deepcopy(record); change(broken)
        check(label+'を拒否',rejected(lambda:audit.provenance(spec,broken,source))); rejections += 1
    broken = dict(spec,threshold=2.)
    check('既知の経済条件変更を拒否',rejected(lambda:audit.provenance(broken,record,source))); rejections += 1
    old = dict(id=audit.PRIMARY,spec=source['spec'],探索固定SHA256='0'*64,経済=dict(利益=50,損失=20))
    new = dict(old,spec=spec,探索固定SHA256='1'*64)
    audit.inherited_summary(new,old,spec,source,'1'*64)
    check('要約のメタだけ変更は許可',True)
    broken = deepcopy(new); broken['経済']['利益'] = 51
    check('旧要約の金額変更を拒否',rejected(lambda:audit.inherited_summary(broken,old,spec,source,'1'*64)))
    rejections += 1
    check('分母不足を無限大にしない',audit.ratio(1,0) is None and audit.ratio(None,1) is None)
    for value in (float('nan'),float('inf'),True):
        check('非有限真偽値の金額拒否'+str(value),rejected(lambda:audit.equal(value,1.)))
        rejections += 1
    # ----------------------------------------
    # 修復は新規完了記録のNone一欄だけとし、七成果や一覧の既知記録を変えない。
    old_record = dict(id='G150_F50_N1__A120',全合格=True,既知成果引継ぎ=False,新売買再生=True,
        全入力数=26,因果入力数=4,出力SHA256={str(i):'a'*64 for i in range(7)},経過秒=2.)
    new_record = dict(old_record,reuse_source=None)
    audit.repaired_record(old_record,new_record,old_record['id'])
    check('補完はNone一欄だけ',True)
    for label,change in (
        ('補完後ID変更',lambda r:r.update(id='別ID')),
        ('補完後経過秒変更',lambda r:r.update(経過秒=3.)),
        ('七成果指紋変更',lambda r:r['出力SHA256'].update({'0':'b'*64})),
        ('補完の値が辞書',lambda r:r.update(reuse_source={})),
        ('余分な項目追加',lambda r:r.update(余分=True)),
        ('入力数変更',lambda r:r.update(全入力数=25))):
        broken = deepcopy(new_record); change(broken)
        check(label+'を拒否',rejected(lambda:audit.repaired_record(old_record,broken,old_record['id']))); rejections += 1
    old_header = dict(全合格=True,全条件数=2,records=[record,old_record])
    new_header = dict(全合格=True,全条件数=2,records=[deepcopy(record),new_record])
    ids = {record['id'],old_record['id']}
    audit.repaired_header(old_header,new_header,ids)
    check('一覧は新規行のNoneだけを補完',True)
    for label,change in (
        ('一覧件数変更',lambda h:h.update(全条件数=1)),
        ('一覧順変更',lambda h:h['records'].reverse()),
        ('一覧ID重複',lambda h:h['records'].__setitem__(1,deepcopy(h['records'][0]))),
        ('既知行変更',lambda h:h['records'][0].update(全合格=False))):
        broken = deepcopy(new_header); change(broken)
        check(label+'を拒否',rejected(lambda:audit.repaired_header(old_header,broken,ids))); rejections += 1
    broken = dict(spec,threshold=spec['threshold']+1e-8)
    check('既知仕様は微小な差も拒否',rejected(lambda:audit.provenance(broken,record,source))); rejections += 1
    output = dict(全合格=True,合成検査数=len(records),不正拒否数=rejections,人工返済脚数=8,
        部分返済復元と空売り損失を保持=True,旧七関数構文同一=True,
        四中央対照全組差検査=True,既知と新反証の区分検査=True,由来一欄補完以外の改変拒否=True,
        新実相場損益読取=False,売買再生=False,API取得数=0,検査=records,
        実装SHA256=audit.digest(HERE/'post_audit.py'),検査実装SHA256=audit.digest(Path(__file__)),
        旧実装SHA256=audit.digest(HERE.parent/'wave_v44/post_audit.py'))
    (HERE/'post_audit_selftest.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k!='検査'},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
