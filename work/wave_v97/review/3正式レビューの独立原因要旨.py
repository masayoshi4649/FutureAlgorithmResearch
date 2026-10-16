"""正式三証跡から原因を要約し、待機取消の時計間隔を受信断と混同しない。"""

from pathlib import Path

import numpy as np

import 共通独立読取 as R
import 元候補対応と独立会計分解 as P


def counts(values: dict, symbol: str) -> dict:
    """
    機能: 各口座の待機・消費・取消件数を商品ごとに合計する。
    引数: values(dict)は一条件の口座別計数、symbol(str)。
    返り値: dict。成立親の勝負と取消理由を別に保持する。
    """
    selected = [value for key, value in values.items() if key.endswith('|' + symbol)]
    return {field: {name: sum(value[field][name] for value in selected) for name in selected[0][field]}
        for field in ('イベント', '取消理由', '候補消費理由')}


def primary_gaps(ledger: dict, material: dict, wanted: dict) -> dict:
    """
    機能: 主の自己間隔取消を原seq差・代理時計差・候補からの時間に分ける。
    引数: ledger/material/wanted(dict)。
    返り値: dict。観測時計が開いた事実から真ネットワーク中断を断定しない。
    """
    answer = {}
    for symbol in R.SYMBOLS:
        items = []
        for key, value in ledger.items():
            if key[1] != symbol:
                continue
            record = material['prices'][key]
            for row in value['entry_wait_events']:
                event = P.named(row, value['entry_wait_event_columns'])
                if event['code'] != 3 or event['reason'] != 3:
                    continue
                current = int(event['row'])
                assert current > 0
                previous = current - 1
                gap = float(record['time_s'][current] - record['time_s'][previous])
                assert gap > 10. + 1e-8
                items.append(dict(場=key[0], 取消行=current, 元候補行=int(event['state_candidate_row']),
                    取消時計=R.clock(record['time_s'][current]),
                    直前原板時計=R.clock(record['time_s'][previous]),
                    代理時計間隔秒=gap, 直前保持行からの原seq差=int(record['seq'][current] - record['seq'][previous]),
                    候補から取消秒=float(record['time_s'][current] - event['state_candidate_time']),
                    受理同行の即時取消=current == int(event['state_candidate_row']),
                    自己気配有効=bool(record['quote_valid'][current])))
        examples = sorted(items, key=lambda value: (-value['代理時計間隔秒'], value['場'], value['取消行']))[:3]
        for value in examples:
            key = value['場'], symbol
            record = material['prices'][key]
            value['直前保持原板'] = R.raw_point(key, record, value['取消行'] - 1, wanted)
            value['取消時保持原板'] = R.raw_point(key, record, value['取消行'], wanted)
            value['候補原板'] = R.raw_point(key, record, value['元候補行'], wanted)
        gaps = [value['代理時計間隔秒'] for value in items]
        life = [value['候補から取消秒'] for value in items]
        answer[symbol] = dict(自己間隔取消=len(items), 原本連続seq取消=sum(value['直前保持行からの原seq差'] == 1 for value in items),
            原本の途中行が保持対象から除外された取消=sum(value['直前保持行からの原seq差'] > 1 for value in items),
            受理同行の即時取消=sum(value['受理同行の即時取消'] for value in items),
            間隔秒中央値=float(np.median(gaps)) if gaps else None,
            候補から取消秒中央値=float(np.median(life)) if life else None,
            最大間隔3例=examples, 全取消一覧=items,
            推定限界='CurrentPriceTimeは最終価格公表の代理時計。真受信時計が無いため市場静穏と収集停止は区別できない。原seq連続か欠番かは区別する。')
    return answer


def compact_parent(value: dict) -> dict:
    """
    機能: 具体原板例を説明に必要な候補・発注・約定・停止の要点へ絞る。
    引数: value(dict)は原本照合済み親診断。
    返り値: dict。時計が同一でも原seq順の次行執行を保持する。
    """
    return dict(方向=value['方向'], 純額円=value['純額円'],
        元候補時計=value['元候補原板']['時刻'], 元候補seq=value['元候補原板']['原本seq'],
        発注時計=value['発注判断原板']['時刻'], 発注seq=value['発注判断原板']['原本seq'],
        実新規時計=value['実新規原板']['時刻'], 実新規seq=value['実新規原板']['原本seq'],
        実返済時計=value['実返済原板']['時刻'], 実返済seq=value['実返済原板']['原本seq'],
        新規価格=value['新規価格'], 返済価格=value['返済価格'],
        清算最良変位pt=value['事後保有中の最良清算変位pt'],
        清算最悪変位pt=value['事後保有中の最悪清算変位pt'], 停止線所有者=value['停止線所有者'])


def main() -> None:
    """
    機能: 正式三レビューを指紋で結び、活動不足・建値悪化・旧勝ち逸失を簡潔に保存する。
    引数: --根許可後(bool)は全31正式完了通知後の実行だけに必須。
    返り値: None。候補の再探索、取消解除又は別策略の損益計算を行わない。
    """
    R.permission()
    fixed, assembled = R.validate()
    names = ['全36条件全31の独立親会計と安定性及び即時旧対照一致.json',
        '全36待機の同候補建値差と勝ち刈り及び固有経路の独立分解.json',
        '主と事前参考及び同出口即時の最悪3場原板と待機救済及び勝ち刈りの独立反証.json']
    proof, cause, raw = [R.read(R.HERE / name) for name in names]
    assert all(value['全合格'] and value['口座'] == 2232 for value in (proof, cause, raw))
    assert all(value['根集計SHA256'] == R.digest(R.WORK / 'analysis/比較結果.json') for value in (proof, cause, raw))
    summary = {}
    for ident in assembled['results']:
        result = assembled['results'][ident]
        summary[ident] = {}
        for symbol in R.SYMBOLS:
            metric, stable = result['periods']['全31'][symbol], result['stability']['全31'][symbol]
            summary[ident][symbol] = dict(利益円=metric['profit'], 損失円=metric['loss'], 収支円=metric['net'],
                金額利益割合=metric['profit_share'], 親数=metric['campaigns'], 活動場=metric['active_sessions'],
                黒字場=metric['positive_sessions'], 赤字場=metric['losing_sessions'], 無取引場=metric['no_trade_sessions'],
                平均赤字円=stable['mean_losing_session_yen'], 最大赤字円=stable['worst_session_loss_yen'],
                下方偏差=stable['downside_rms_units'], 待機=counts(cause['各口座待機取消消費成立'][ident], symbol))
    wanted = {}
    material = R.material()
    gaps = primary_gaps(R.load_ledgers(fixed['主']), material, wanted)
    source = R.attach_raw(wanted)
    primary = cause['比較']['A0_X3→' + fixed['主']]['期間別元候補対応']['全31']
    assert proof['注文'] == 1868 and proof['親'] == 934 and proof['商品期間群'] == 576
    assert fixed['主'] == 'A7_X3' and assembled['selected'] == 'A0_X1'
    assert summary['A7_X3']['TOPIX']['親数'] == 0 and summary['A7_X3']['NK225']['親数'] == 2
    assert summary['A7_X3']['NK225']['収支円'] == -23104.
    assert primary['NK225']['建値改善円'] == -64000. and primary['NK225']['返済差円'] == 11200.
    assert gaps['TOPIX']['自己間隔取消'] == gaps['TOPIX']['原本連続seq取消'] == 68
    assert gaps['NK225']['自己間隔取消'] == gaps['NK225']['原本連続seq取消'] == 71
    primary_compact = {symbol: {name: value for name, value in primary[symbol].items() if name not in (
        '同候補一覧', '元固有一覧', '新固有一覧', '改善上位例', '悪化上位例')} for symbol in R.SYMBOLS}
    worst = {ident: {symbol: [dict(場=case['場'], 収支円=case['収支円'],
        大損3親=[compact_parent(parent) for parent in case['大損3親']]) for case in values]
        for symbol, values in markets.items()} for ident, markets in raw['最悪3場'].items()}
    conclusion = [
        '全36条件の2232口座、1868注文、934親、576商品期間群を独立検算し、A0四出口は旧96全31の会計及び注文と完全一致した。',
        '主A7_X3はTOPIX94候補を全取消して0親、日経80候補から2親で両負け。主の赤字縮小はほぼ参加減少であり全日安定した入口改善ではない。',
        '主の自己間隔10秒超取消はTOPIX68件、日経71件。reset取消は21件、4件。候補後の順行・押し回復が有効かという仮説を十分試す前に多くが失効した。',
        '日経の主に残った2同候補は旧即時より両方不利な建値。建値差−64000円と返済差＋11200円で同候補差−52800円。既存の負け回避と勝ち逸失を別に加えて全差が一致した。',
        '両商品80%のA4四設定は各商品で一親だけ。20親8活動場を満たす両80%は0で、安定収益の成功と認定できない。',
        '前16で固定した参考A0_X1は全31でTOPIX＋265216円、日経−43456円。細い初期停止は最大/平均赤字を抑える一方、回復して勝つ親も刈る旧96の問題が残る。',
        '今回確かめたのは旧J8候補から5分までの厳密な待機と旧4出口の組合せ。押し回復全般、原本LPで候補を再構成した追従、真受信時計を使用する待機まで否定する結果ではない。']
    R.save('3正式レビューの独立原因要旨と代理時計による活動不足の反証.json', dict(
        全合格=True, 主=fixed['主'], 前16固定参考=assembled['selected'], 結論=conclusion,
        条件別安定性及び待機取消=summary, 主と同出口即時の会計差=primary_compact,
        主自己間隔取消の原seqと時計=gaps, 追加同seq原本照合=source,
        主参考即時の最悪3場要点=worst,
        両商品金額80=proof['両商品金額80'], 活動充足両80=proof['活動充足両80'],
        次段への提言='利益率や取消幅を後から選ぶ前に、真受信時計の無い価格更新間隔と本当の観測断裂を区別する入力/待機資格の一軸対照を損益前に定義する。成功すると仮定せず新規連鎖込みで確認する。',
        主変更=False, 参考事後差替え=False,
        根拠SHA256={str((R.HERE / name).relative_to(R.ROOT)): R.digest(R.HERE / name) for name in names},
        計算コードSHA256=R.digest(Path(__file__)), **R.provenance()))
    print('正式三レビューの原因要旨と自己間隔取消の原seq分類を保存しました。新策略損益は計算していません。', flush=True)


if __name__ == '__main__':
    main()
