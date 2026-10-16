"""検算済み三証跡の要点を、未検証の改修案と混ぜずに短く保存する。"""

from pathlib import Path

import 共通独立読取 as R


def main() -> None:
    """
    機能: 独立検算の原因要旨と具体的板反例及び未検証の次段仮説を保存する。
    引数: --根許可後(bool)は必須。全31正式完了後だけ実行する。
    返り値: None。新候補の損益又は事後除外戦略を計算しない。
    """
    R.permission()
    names = ('全38条件全31の独立親会計と安定性及び一軸経路分解.json',
             '全38の直前完了親と四源再参加及び候補時刻移動の独立原因分解.json',
             '主と事前参考及び旧追従の最悪3場原板と赤字救済及び大勝ち依存の独立反証.json')
    proof, cause, raw = [R.read(R.HERE / name) for name in names]
    assert all(value['全合格'] and value['口座'] == 2356 for value in (proof, cause, raw))
    current = R.provenance()
    assert all(value['固定SHA256'] == current['固定SHA256']
        and value['根集計SHA256'] == current['根集計SHA256'] for value in (proof, cause, raw))
    independent = proof['一軸比較']
    selected = proof['前16固定参考']['selected']
    examples = {}
    for symbol in R.SYMBOLS:
        value = raw['最悪3場'][proof['主']][symbol][0]
        t = value['大損3親'][0]
        examples[symbol] = dict(場=value['場'], 場収支円=value['収支円'],
            判断時計=t['新規判断時計'], 実新規時計=t['実新規時計'], 実返済時計=t['実返済時計'],
            新規原seq=t['実新規原板']['原本seq'], 返済原seq=t['実返済原板']['原本seq'],
            方向=t['方向'], 純額円=t['純額円'], 最大順行pt=t['事後清算最大順行pt'],
            最大逆行pt=t['事後清算最大逆行pt'], 幅pt=t['旧停止追尾幅pt'],
            判断時両市場=t['新規判断原板']['両市場'])
    cohorts = {}
    for ident in ('P0_R0', selected, 'P3_R0', proof['主']):
        cohorts[ident] = {}
        for symbol in R.SYMBOLS:
            cohorts[ident][symbol] = {}
            for period in ('前16', '後15', '全31'):
                parts = cause['前親損益方向停止別'][ident][symbol][period]
                cohorts[ident][symbol][period] = {direction: {field: sum(value[field]
                    for tag, value in parts.items() if tag.startswith('前親損失_' + direction + '_'))
                    for field in ('campaigns', 'profit', 'loss', 'net')} for direction in ('同方向', '反対方向')}
    result = dict(全合格=True, 条件数=38, 口座=2356, 主=proof['主'], 前16固定参考=selected,
        検算規模=dict(注文=proof['注文'], 親=proof['親'], 商品期間群=proof['商品期間群'],
            原本同seq=sum(value['同seq照合'] for value in raw['原本同seq照合'].values())),
        両商品金額80=proof['両商品金額80'], 活動充足両80=proof['活動充足両80'],
        入口源一軸の会計分解={name: independent[name] for name in
            ('P0_R0→P1_R0', 'P1_R0→P2_R0', 'P2_R0→P3_R0')},
        参考の旧追従比較=independent['P0_R0→P0_R1_S'],
        独立確認済み具体板反例=examples,
        損失後同方向と反対方向の群が政策で変わる=cohorts,
        原因の結論=[
            'P3の価格正常化自体は因果的に正当。しかし発火・消費・保有中見送りまで変わり、P2旧親との共通はTOP12/87、NK10/71だけ。正常な観測を増やしたことを旧の利益入口へ単純な追加と扱えない。',
            '厳密同一新規は出口不変で純管理差0。大幅赤字は同じ入口の約定を変えたためでなく、消えた旧利益入口と新経路の負の親会計から説明できる。',
            '主R3の反対判定で時計/源更新不足は0。TOPは66中42、NK73中46を四源確認後に受理したが、その親群はTOP−448056円、NK−281792円。更新確認は方向の継続利益を保証しない。',
            'TOP09/24 09:11:45ではLPは両市場とも下落、自己両気配も下落だったが、相手両気配は15秒0tick。LPの同方向と相手の実気配進行は別物。',
            'NK10/09 08:51は両LP・両気配・十分な同方向OFIが揃っても、最大順行10ptに対し幅280ptで逆行270ptまで許し−43552円。相手板確認だけでも全ての反転は防げない。',
            '主の最悪3場の大損親は、多くが小さな順行しかせず広い固定幅又は30分期限まで逆行した。入口根拠消失時の途中判断は今回変えていないので、その改修の成績まで否定していない。',
            '旧損失後同方向の黒字は政策変更後に不変でない。直前親と次親の群自体が変わるため、旧の親群会計を反対禁止後の成績へ移せない。',
            '前16参考P0_R1_Sは両黒字、最大利益日を除いても両黒字だが、TOPの赤字平均/最大/RMSは旧より悪化、黒字場数は双方17/29のまま。共通の毎場安定改善ではない。'],
        次段の未検証仮説=[
            '価格を未知へ戻すのでなく、旧資格がどの観測失敗・流動性状態を除いていたかを原因別に分離する。正常LPの復旧と売買条件の期待値を別に評価する。',
            '15秒候補が最初原行へ届くまでに支持が消えた入口と、実判断時にも両市場支持があるのに反転した入口を分け、前者の再確認と後者の保有中失敗判定を別対照にする。',
            '入口を固定したまま、四源の共通方向・両気配の前提消失を保有中の縮小/返済へ使う出口単独対照を事前固定する。今回の結果から利益を得るとは認定しない。'],
        注意=['上記の未検証案は正式候補に追加していない。', '全31は既知。新しい未見データでの成功ではない。',
            '小数量の半額損益はリスク縮小であり方向予測改善ではない。'],
        三証跡SHA256={name: R.digest(R.HERE / name) for name in names},
        計算コードSHA256=R.digest(Path(__file__)), **current)
    R.save('3正式レビューの独立原因要旨と次段の未検証仮説.json', result)
    print('3正式レビューの原因要旨を保存。追加策略損益0。', flush=True)


if __name__ == '__main__':
    main()
