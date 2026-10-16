"""正式3レビューだけから安定性と出口差の要旨を再現し、条件を変更しない。"""

from pathlib import Path

import 共通独立読取 as R


def compact_metric(value: dict, rows: list[dict], symbol: str) -> dict:
    """
    機能: 独立照合済みの円損益と安定性を短い項目へまとめる。
    引数: value(dict)は商品期間、rows(list[dict])は全場、symbol(str)は商品。
    返り値: dict。最大利益セッションと開始日単位の最大利益日を混同しない。
    """
    selected = [row for row in rows if row['symbol'] == symbol]
    largest = max(selected,key=lambda row:row['net'])
    return dict(利益円=value['profit'],損失円=value['loss'],収支円=value['net'],
        金額利益割合=value['profit_share'],平均勝負比=value['payoff'],
        黒字場=value['positive_sessions'],赤字場=value['losing_sessions'],
        無取引場=value['no_trade_sessions'],活動場=value['active_sessions'],
        最大利益日除外円=value['without_best_day']['net'],
        除外する最大利益セッション=largest['session'],
        最大利益セッション除外円=value['net']-max(largest['net'],0.),
        買い円=value['directions']['買い']['net'],売り円=value['directions']['売り']['net'])


def main() -> None:
    """
    機能: root許可後の既存正式診断だけを要旨JSONへ結ぶ。
    引数: --根許可後(bool)は全31完了許可後だけ指定する。
    返り値: None。売買・一親反事実・新候補・追加パラメータの再生はしない。
    """
    R.permission()
    fixed, assembled = R.validate()
    paths = [R.HERE/name for name in (
        '全18条件全31の独立親会計と安定性及び一軸経路分解.json',
        '全18の利益床と旧勝ち刈り及び同一実新規の出口差.json',
        '主と事前参考及び旧追従の最悪3場原板と赤字救済及び大勝ち依存の独立反証.json')]
    a,b,c = [R.read(path) for path in paths]
    assert all(v['全合格'] and v['口座']==1116 for v in (a,b,c))
    assert all(v['根集計SHA256']==R.digest(R.WORK/'analysis/比較結果.json') for v in (a,b,c))
    metrics = {}
    for ident,result in assembled['results'].items():
        metrics[ident] = {}
        for symbol in R.SYMBOLS:
            value = compact_metric(result['periods']['全31'][symbol],result['rows'],symbol)
            value.update(平均赤字円=a['独立安定性'][ident]['全31'][symbol]['mean_losing_session_yen'],
                最大赤字円=a['独立安定性'][ident]['全31'][symbol]['worst_session_loss_yen'],
                共通上限全場RMS=a['独立安定性'][ident]['全31'][symbol]['downside_rms_units'],
                前16円=result['periods']['前16'][symbol]['net'],
                後15円=result['periods']['後15'][symbol]['net'])
            metrics[ident][symbol] = value

    # ----------------------------------------
    # 一軸差は管理差と固有親を分けて短く残す。
    requested = (
        'S40_M0_H30→S10_M0_H30','S40_M0_H30→S20_M0_H30',
        'S20_M0_H30→S20_M1_H30','S20_M1_H30→S20_M2_H30',
        'S10_M0_H30→S10_M1_H30','S10_M1_H30→S10_M2_H30',
        'S10_M0_UNL→S10_M1_UNL','S10_M1_UNL→S10_M2_UNL',
        'S10_M1_H30→S10_M1_UNL','S20_M2_H30→S20_M2_UNL')
    fields = ('全経路差円','厳密同一新規親','厳密同一新規管理差円','同一判断符号変化',
        '元固有親','新固有親','逃した元固有利益円','避けた元固有損失円',
        '新固有利益円','新固有損失円','元固有収支円','新固有収支円')
    differences = {pair:{symbol:{name:value for name,value in
        a['一軸比較'][pair]['親会計恒等分解'][symbol]['全源'].items() if name in fields}
        for symbol in R.SYMBOLS} for pair in requested}
    floors = {}
    for ident in (fixed['主'],'S10_M2_UNL','S20_M2_H30'):
        floors[ident] = {symbol:{group:dict(
            親=sum(v['分類'][group]['campaigns'] for v in b['全18利益床'][ident][symbol].values()),
            勝ち親=sum(v['分類'][group]['winning_campaigns'] for v in b['全18利益床'][ident][symbol].values()),
            負け親=sum(v['分類'][group]['losing_campaigns'] for v in b['全18利益床'][ident][symbol].values()),
            純額円=sum(v['分類'][group]['net'] for v in b['全18利益床'][ident][symbol].values()))
            for group in ('保護有効','保護未達','床が最強線','床有効なのに純損失','予定床より悪い約定')}
            for symbol in R.SYMBOLS}

    # 原板の具体例は詳細JSONへ結び、未来の選別材料には戻さない。
    worst = {ident:{symbol:[dict(場=row['場'],収支円=row['収支円'],大損親=[dict(
        新規=p['実新規時計'],返済=p['実返済時計'],方向=p['方向'],純額円=p['純額円'],
        順行最大pt=p['事後清算最大順行pt'],初期S=p['当該実新規の初期S'],
        利益D=p['当該実新規の利益追尾D'],保護有効=p['保存出口証拠']['protection_active'],
        線の所有者=p['停止線の所有者'],原seq=p['実新規原板']['原本seq']) for p in row['大損3親']])
        for row in rows] for symbol,rows in values.items()} for ident,values in c['最悪3場'].items()}
    R.save('3正式レビューの独立原因要旨と次段の未検証仮説.json',dict(
        全合格=True,口座=1116,注文=a['注文'],親=a['親'],商品期間群=a['商品期間群'],
        原本同seq照合=sum(v['同seq照合'] for v in c['原本同seq照合'].values()),
        主=fixed['主'],前16固定参考=assembled['selected'],両商品金額80=a['両商品金額80'],
        全18の短い成績=metrics,一軸の管理差と連鎖差=differences,
        利益床の実損益=floors,最悪3場の短い具体例=worst,
        対象外の元P3例=c['元正常方向でも失敗した08時51分親の適用範囲']['結論の範囲'],
        原因結論=[
          '初期幅を0.4%から0.1%へ下げると旧負けを軽減したが、回復する旧勝ちが初期停止に変わり、その悪化額が両商品で上回った。',
          '主の利益床が発動した後の親は今回両商品とも費用後黒字。日経の赤字は床発動前の親の累積で、床の約定不良が主因ではない。これは発動親を事後で選んだ分類であり新規の勝率ではない。',
          '通常期限を外すとTOPIXで長い勝ちを伸ばせたが、日経では期限内の黒字が後に失われた。場内の時間非依存だけで全銘柄共通に改善しない。',
          '0.1%初期幅で半利益床を追加するとTOPIXの延長勝ちを強く刈り、同じ入口の管理差だけで大幅悪化した。床を強めれば常に安定するわけではない。',
          '中間0.2%と半利益床の30分版は事後に両黒字だが、旧J8よりTOPIXの最大赤字が大きく、両商品の活動黒字頻度は下がる。日経は最大利益日及び最大利益親除外で赤字。全軸の安定改善と認定しない。',
          '事前参考の0.1%/保護なし/30分版は両商品の平均最大赤字とRMSを減らすが、黒字頻度が低下し日経全体が赤字。損失額抑制と安定黒字を混同しない。'],
        次段の未検証仮説='出口をさらに狭める前に、旧勝ちの初期逆行と継続する失敗を当時の新源で区別できるか、返済後の再参加まで含めた別の状態管理として反証する余地がある。未来MFE又は実現勝ちを入口へ返さない。今回その新戦略は実行していない。',
        成果SHA256={str(path.relative_to(R.ROOT)):R.digest(path) for path in paths},
        計算コードSHA256=R.digest(Path(__file__)),**R.provenance()))
    print('3正式レビューの独立原因要旨を保存しました。条件・選定変更なし。',flush=True)


if __name__ == '__main__':
    main()
