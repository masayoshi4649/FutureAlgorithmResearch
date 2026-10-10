"""人工元組と影台帳だけで163条件の採否境界・改竄拒否を検査する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('profit_gate_assessment_check_v44', HERE/'assessment.py')
audit = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = audit
_spec.loader.exec_module(audit)


def refresh(data: tuple, identifier: str | None = None) -> None:
    """機能: 人工元組と約定調整から場・期間の集計を作り直す。

    引数: data(tuple)、identifier(str|None)。返り値: なし(None)。
    実相場や注文器を使わず、採否の会計単位だけを検査する材料である。
    """
    index, sessions, names, ledgers = data
    for key in ([identifier] if identifier else index):
        for row, book in zip(sessions[key], ledgers[key]):
            factor = book['config']['point_value']
            quantity = book['config']['initial_qty']
            profits = [c[3]*factor for c in book['cycles']]
            gains = [p for p in profits if p > 0]
            losses = [-p for p in profits if p < 0]
            row.update(net_yen=sum(profits), gross_profit_yen=sum(gains), gross_loss_yen=sum(losses),
                profit_units=len(gains)*quantity, loss_units=len(losses)*quantity,
                zero_units=sum(p == 0 for p in profits)*quantity, cycles=len(profits),
                cycle_wins=len(gains), cycle_losses=len(losses), cycle_profit_yen=sum(gains),
                cycle_loss_yen=sum(losses),
                reductions=sum(e[2] == 2 and e[3] == -1 for e in book['adjustment_events']),
                restorations=sum(e[2] == 2 and e[3] == 1 for e in book['adjustment_events']),
                maximum_trade_profit=max([0.] + gains), drawdown_yen=2*factor,
                net_r=sum(c[3]/c[4] for c in book['cycles']),
                two_largest_cycle_profits=sorted(gains,reverse=True)[:2])
        for period in audit.PERIODS:
            chosen = audit.names_for(period,names)
            for symbol in audit.SYMBOLS:
                part = [r for r in sessions[key] if r['session'] in chosen and r['symbol'] == symbol]
                value = {field:sum(r[field] for r in part) for field in audit.SUM_FIELDS}
                value.update(net_r=sum(r['net_r'] for r in part),
                    drawdown_yen=max(r['drawdown_yen'] for r in part))
                value['average_cycle_payoff'] = ((value['cycle_profit_yen']/value['cycle_wins']) /
                    (value['cycle_loss_yen']/value['cycle_losses'])) if value['cycle_wins'] and value['cycle_losses'] else None
                index[key][period][symbol] = value


def fixture() -> tuple:
    """機能: 全163条件・4238口座に共通影を持つ人工集計を作る。

    引数: なし。返り値: index、場集計、13場名、台帳(tuple)。初回ID0を含む。
    """
    names = [f'人工{i:02d}' for i in range(13)]
    index, sessions, ledgers = {}, {}, {}
    for spec in audit.all_specs():
        identifier = spec['id']
        index[identifier] = dict(id=identifier,spec=spec,all_symbols={s:{} for s in audit.SYMBOLS},
                                symbols={s:{} for s in audit.SYMBOLS},wave_passes=8)
        sessions[identifier], ledgers[identifier] = [], []
        strong = spec['primary'] or spec['role'] in ('sensitivity','execution')
        profits = [5.,4.,-1.,-1.] if strong else [3.,2.,-1.,-1.]
        for name in names:
            for symbol in audit.SYMBOLS:
                quantity = 5. if symbol == 'TOPIX' else 10.
                cycles = [[i,i*10+1,i*10+8,p,quantity*2,2.,quantity,quantity,1 if i%2 == 0 else -1,2.]
                          for i,p in enumerate(profits)]
                shadow_cycles = deepcopy(cycles)
                for cycle,p in zip(shadow_cycles,[3.,2.,-1.,-1.]):
                    cycle[3] = p
                orders = [[c[1],c[1]-1,c[0],c[8],quantity,100.,20.,1.] for c in cycles]
                material = json.dumps([name,symbol,audit.pair_context(spec)],ensure_ascii=False)
                signature = hashlib.sha256(material.encode()).hexdigest()
                fields = ('trades','cycles','curve','orders','stats','atr_curve','plans',
                          'execution_plans','prepare_events','entry_preparations')
                fingerprints = {field:dict(shape=[4,10],dtype='<f8',SHA256=signature) for field in fields}
                events = [] if spec['baseline_policy'] == 'A0' else [
                    [3.,0.,2.,-1.,2.,2.,1.,30.,1.,1.,2.],
                    [5.,0.,2.,1.,4.,4.,1.,31.,1.,1.,4.]]
                sessions[identifier].append(dict(id=identifier,session=name,symbol=symbol))
                ledgers[identifier].append(dict(session=name,symbol=symbol,
                    config=dict(initial_qty=quantity,point_value=1000. if symbol == 'TOPIX' else 10.),
                    cycles=cycles,orders=orders,shadow_cycles=shadow_cycles,shadow_orders=deepcopy(orders),
                    shadow_fingerprints=fingerprints,adjustment_events=events))
    data = index,sessions,names,ledgers
    refresh(data)
    return data


def set_profits(data: tuple, identifier: str, values: list[float], chosen: list[str] | None = None) -> None:
    """機能: 初回の母集団を保ち、指定した場の人工最終収支だけを変更する。

    引数: data(tuple)、identifier(str)、values(list[float])、chosen(list[str]|None)。返り値: なし(None)。
    """
    assert len(values) == 4
    for book in data[3][identifier]:
        if chosen is None or book['session'] in chosen:
            for cycle,profit in zip(book['cycles'],values):
                cycle[3] = profit
    refresh(data,identifier)


def rejected(function: object) -> bool:
    """機能: 不正材料で採否を返さず例外になることを確認する。

    引数: function(Callable)。返り値: 拒否された場合True(bool)。
    """
    try:
        function()
    except (AssertionError,KeyError,TypeError,ValueError):
        return True
    return False


def main() -> None:
    """機能: 主案固定、全組差、集中・感度・情報価値の境界を人工検査する。

    引数: なし。返り値: なし(None)。損益再生や旧保存収支の読取は行わない。
    """
    original = fixture()
    records, rejection_count = [], 0
    primary, control, baseline = audit.PRIMARY,audit.CONTROL,audit.BASELINE

    def check(name: str, passed: bool) -> None:
        """機能: 検査名と成功を保存し、不一致なら直ちに停止する。

        引数: name(str)、passed(bool)。返り値: なし(None)。
        """
        assert passed,name
        records.append(dict(検査=name,一致=True))

    value = audit.assess(*original)
    check('全163条件4238入力を保持',value['全条件数'] == 163 and value['全入力数'] == 4238)
    check('初回ID0と全組の損失も対応',value['同じ影の元組差'][control]['全対応元組数'] == 104 and
          any(r['主案収支円'] < 0 for r in value['同じ影の元組差'][control]['全元組対応']))
    check('中央黒字改善実調整が正常',value['経済目安合格'] and value['中央の基礎候補'])
    check('結果監査前に研究候補へしない',not value['既知比較の研究候補'])
    verified = audit.assess(*original,verification=True)
    check('監査後にだけ研究候補',verified['既知比較の研究候補'])
    restored = deepcopy(verified)
    restored['監査完了'] = False
    for field in ('既知比較の研究候補','耐性付き研究候補','情報対照を通過した研究候補'):
        restored[field] = False
    check('監査flagで経済式を変えない',restored == value)
    check('十二感度と八波は別ラベル',verified['十二感度の後七基礎'] and verified['指定八波'])
    check('悪化回復を別系統で支持',value['悪化情報の利益付加価値支持'] and value['回復情報の構造保存対照超過'])
    check('全対照64の中央値と順位',all(len(c['全64']) == 64 for g in value['乱数対照'].values()
          for cells in g['期間別'].values() for c in cells.values()))
    check('既知改善を未知保証へしない',not verified['未知での有効性確認'] and not verified['全体目標達成'])

    data = deepcopy(original)
    for period in audit.PERIODS:
        for symbol in audit.SYMBOLS:
            data[0][primary][period][symbol]['drawdown_yen'] += 1
    result = audit.assess(*data,verification=True)
    check('微小DD増と経済候補を分離',result['既知比較の研究候補'] and
          result['中央比較'][control]['収益DD関係']['関係'] == '交換又は混在')
    data = deepcopy(original)
    set_profits(data,primary,[3.,2.,-1.,-1.])
    result = audit.assess(*data)
    check('C01同値を改善にしないが黒字は維持',not result['中央の収益追加改善'] and result['中央の基礎候補'])
    data = deepcopy(original)
    set_profits(data,primary,[-5.,-5.,-1.,-1.],data[2][:6])
    set_profits(data,primary,[3.1,2.,-1.,-1.],data[2][6:])
    check('後七微増でも全十三減益を改善へしない',not audit.assess(*data)['中央の収益追加改善'])
    data = deepcopy(original)
    for book in data[3][primary]:
        book['adjustment_events'] = []
    refresh(data,primary)
    result = audit.assess(*data,verification=True)
    check('黒字でも実減量復元0を機構成功にしない',result['中央の基礎候補'] and not result['全期間両銘柄で減量復元実約定']
          and not result['既知比較の研究候補'] and not result['悪化情報の利益付加価値支持'])
    data = deepcopy(original)
    data[0][primary]['wave_passes'] = 7
    result = audit.assess(*data,verification=True)
    check('八波不足を隠さず経済と分離',not result['指定八波'] and result['既知比較の研究候補'])

    data = deepcopy(original)
    for identifier in data[0]:
        for book in data[3][identifier]:
            for field in ('cycles','orders','shadow_cycles','shadow_orders','adjustment_events'):
                book[field] = []
    refresh(data)
    result = audit.assess(*data)
    check('全無活動でも完全資料として評価し不合格',not result['中央の基礎候補'] and not result['経済目安合格'])
    data = deepcopy(original)
    set_profits(data,primary,[4.,3.,1.,1.])
    result = audit.assess(*data)
    check('無損失の未定義比を無限大へしない',not result['中央の基礎候補'] and
          result['全条件'][primary]['期間別']['symbols']['TOPIX']['比率']['元組PF'] is None)
    data = deepcopy(original)
    set_profits(data,primary,[1.,1.,-1.,-1.])
    check('収支0とPF1は基礎不合格',not audit.assess(*data)['中央の基礎候補'])
    data = deepcopy(original)
    set_profits(data,primary,[1.,1.,1.,-1.])
    result = audit.assess(*data)['全条件'][primary]['期間別']['symbols']['TOPIX']
    check('PFが良くても平均元組比1は不合格',result['基礎検査']['元組PF1超'] and not result['基礎検査']['平均元組勝敗比1超'])
    data = deepcopy(original)
    set_profits(data,primary,[-1.,-1.,-1.,-1.])
    set_profits(data,primary,[100.,-1.,-1.,-1.],[data[2][-1]])
    result = audit.assess(*data)['全条件'][primary]['期間別']['symbols']['TOPIX']
    check('一勝依存の黒字を合格にしない',result['基礎検査']['収支正'] and not result['最大勝ち除外検査']['最大勝ち元組除外非負'])
    data = deepcopy(original)
    set_profits(data,primary,[-1.,-1.,-1.,-1.])
    set_profits(data,primary,[60.,60.,-1.,-1.],[data[2][-1]])
    result = audit.assess(*data)['全条件'][primary]['期間別']['all_symbols']['TOPIX']
    check('一勝除外と一場除外は別検査',result['最大勝ち除外検査']['最大勝ち元組除外非負'] and not result['最大勝ち除外検査']['最大黒字場除外非負'])
    data = deepcopy(original)
    set_profits(data,primary,[1.,1.,-1.,-1.])
    set_profits(data,primary,[30.,30.,-1.,-1.],[data[2][-1]])
    result = audit.assess(*data)['全条件'][primary]
    check('上位二勝除外負は表示し基礎へ後付けしない',result['基礎候補'] and
          result['期間別']['symbols']['TOPIX']['上位二勝ち元組同時除外収支円'] < 0)
    check('最大黒字場除外0は非負',result['期間別']['symbols']['TOPIX']['最大黒字場除外収支円'] == 0)

    data = deepcopy(original)
    last = audit.main_variant('L015')
    set_profits(data,last,[-1.,-1.,-1.,-1.])
    result = audit.assess(*data,verification=True)
    check('感度失敗を中央候補へ混同しない',result['既知比較の研究候補'] and not result['十二感度の後七基礎']
          and not result['耐性付き研究候補'])
    data = deepcopy(original)
    neighbor = audit.main_variant('E080')
    set_profits(data,neighbor,[-1.,-1.,-1.,-1.])
    set_profits(data,neighbor,[100.,-1.,-1.,-1.],[data[2][-1]])
    result = audit.assess(*data)
    check('時計で基礎黒字でも集中依存が残る',result['十二感度']['入口時計']['全変形の後七基礎'] and
          not result['入口三時計の集中活動耐性'] and result['中央の基礎候補'])
    data = deepcopy(original)
    set_profits(data,'G200_F50_N3__V000',[1000.,900.,-1.,-1.])
    check('別配分の大勝ちへ主案差替なし',audit.assess(*data)['主案ID'] == primary)

    data = deepcopy(original)
    set_profits(data,audit.main_variant('INV'),[5.,4.,-1.,-1.])
    result = audit.assess(*data)
    check('逆方向同値なら悪化情報未支持',not result['悪化情報の利益付加価値支持'] and result['回復情報の構造保存対照超過'])
    data = deepcopy(original)
    set_profits(data,audit.main_variant('AV_ALL'),[5.,4.,-1.,-1.])
    result = audit.assess(*data)
    check('方向除去同値なら悪化情報未支持',not result['悪化情報の利益付加価値支持'])
    data = deepcopy(original)
    for seed in range(33):
        set_profits(data,audit.main_variant(f'UB{seed:03d}'),[5.,4.,-1.,-1.])
    result = audit.assess(*data,verification=True)
    check('悪化乱数中央値同値を厳密超過にしない',not result['悪化情報の利益付加価値支持'] and
          result['回復情報の構造保存対照超過'] and result['既知比較の研究候補'])
    data = deepcopy(original)
    for seed in range(33):
        set_profits(data,audit.main_variant(f'UG{seed:03d}'),[5.,4.,-1.,-1.])
    result = audit.assess(*data)
    check('回復情報だけの失敗を独立に保持',result['悪化情報の利益付加価値支持'] and not result['回復情報の構造保存対照超過'])
    data = deepcopy(original)
    set_profits(data,audit.main_variant('UB000'),[1000.,900.,-1.,-1.])
    result = audit.assess(*data)
    check('乱数最良は採用せず64中央値を見る',result['悪化情報の利益付加価値支持'] and
          result['乱数対照']['bad_seed']['期間別']['symbols']['TOPIX']['主以上元組Rの本数'] == 1)
    pair = value['同じ影の元組差'][control]['期間別']['all_symbols']
    check('小口倍率差でも共通Rはq0差を保持',pair['TOPIX']['差R']['合計'] == 2*pair['NK225']['差R']['合計'])
    check('円差をR差へ誤換算しない',pair['TOPIX']['差円']['合計'] == 100*pair['NK225']['差円']['合計'])

    # ----------------------------------------
    # 論理不合格と資料不備を分け、欠落や異なる初回の対応を拒否する。
    changes = [
        ('条件欠落',lambda d:d[0].pop(primary)),
        ('条件追加',lambda d:d[0].update(未知条件=deepcopy(d[0][primary]))),
        ('仕様差替え',lambda d:d[0][primary]['spec'].update(gate_threshold_atr=2.)),
        ('保存ID差替え',lambda d:d[0][primary].update(id=control)),
        ('補助seed重複',lambda d:d[0][audit.main_variant('UB001')]['spec'].update(bad_seed=0)),
        ('場行欠落',lambda d:d[1][primary].pop()),
        ('場行重複',lambda d:d[1][primary].__setitem__(0,deepcopy(d[1][primary][1]))),
        ('場ID誤り',lambda d:d[1][primary][0].update(id=control)),
        ('台帳欠落',lambda d:d[3][primary].pop()),
        ('台帳重複',lambda d:d[3][primary].__setitem__(0,deepcopy(d[3][primary][1]))),
        ('負の元組ID',lambda d:d[3][primary][0]['cycles'][0].__setitem__(0,-1)),
        ('重複元組ID',lambda d:d[3][primary][0]['cycles'][1].__setitem__(0,0)),
        ('無効方向',lambda d:d[3][primary][0]['cycles'][0].__setitem__(8,0)),
        ('初期Rゼロ',lambda d:d[3][primary][0]['cycles'][0].__setitem__(4,0)),
        ('元組収支改竄',lambda d:d[3][primary][0]['cycles'][0].__setitem__(3,99)),
        ('小口倍率改竄',lambda d:d[3][primary][0]['config'].update(point_value=999)),
        ('非有限',lambda d:d[0][primary]['symbols']['TOPIX'].update(net_yen=float('nan'))),
        ('無限DD',lambda d:d[0][primary]['symbols']['TOPIX'].update(drawdown_yen=float('inf'))),
        ('真偽値を数値',lambda d:d[0][primary]['symbols']['TOPIX'].update(net_yen=True)),
        ('最大勝ち欠落',lambda d:d[1][primary][0].pop('maximum_trade_profit')),
        ('上位二勝改竄',lambda d:d[1][primary][0].update(two_largest_cycle_profits=[])),
        ('期間総R改竄',lambda d:d[0][primary]['symbols']['TOPIX'].update(net_r=999)),
        ('平均元組比改竄',lambda d:d[0][primary]['symbols']['TOPIX'].update(average_cycle_payoff=999)),
        ('非整数枚数',lambda d:d[1][primary][0].update(profit_units=1.5)),
        ('指定波範囲外',lambda d:d[0][primary].update(wave_passes=9)),
        ('場名重複',lambda d:d[2].__setitem__(0,d[2][1])),
        ('場順逆転',lambda d:d[2].reverse()),
        ('影台帳欠落',lambda d:d[3][primary][0].pop('shadow_cycles')),
        ('影の初回数量差',lambda d:d[3][primary][0]['shadow_orders'][0].__setitem__(4,4)),
        ('実の初回価格差',lambda d:d[3][primary][0]['orders'][0].__setitem__(5,101)),
        ('共通影指紋差',lambda d:d[3][primary][0]['shadow_fingerprints']['curve'].update(SHA256='a'*64)),
        ('影指紋欠落',lambda d:d[3][primary][0]['shadow_fingerprints'].pop('curve')),
        ('初回ATR非整合',lambda d:d[3][primary][0]['cycles'][0].__setitem__(5,3)),
        ('初回同一行発注',lambda d:d[3][primary][0]['orders'][0].__setitem__(1,1)),
        ('影終了後返済',lambda d:d[3][primary][0]['cycles'][0].__setitem__(2,99)),
        ('減量実約定数改竄',lambda d:d[3][primary][0]['adjustment_events'][0].__setitem__(2,1)),
        ('調整予約の組欠落',lambda d:d[3][primary][0]['adjustment_events'][0].__setitem__(1,99))]
    for name,change in changes:
        data = deepcopy(original)
        change(data)
        check(name+'を拒否',rejected(lambda:audit.assess(*data)))
        rejection_count += 1
    specs = {s['id']:s for s in audit.all_specs()}
    for variant in ('E080','L001','O000'):
        check(variant+'を同じ元組として対応しない',rejected(lambda:audit.paired_comparison(
            primary,audit.main_variant(variant),specs,{}, {},{},original[2])))
        rejection_count += 1
    check('元の人工材料を不変保持',audit.assess(*original) == value)

    paths = [HERE/'assessment.py',Path(__file__),HERE/'design.py',audit.SOURCE,HERE/'反証設計案.md',HERE/'反証計画.md',
             HERE.parent/'wave_v38/探索条件の固定.json',HERE.parent/'wave_v37/partial_design_fixed.json']
    refs = {p.relative_to(audit.ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    output = dict(全合格=True,合成検査数=len(records),不正資料拒否数=rejection_count,
        全条件数=163,全人工入力数=4238,検査=records,新実相場損益=False,現在API取得数=0,
        採否実装SHA256=refs[(HERE/'assessment.py').relative_to(audit.ROOT).as_posix()],参照資料SHA256=refs)
    (HERE/'check_assessment.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k not in ('検査','参照資料SHA256')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
