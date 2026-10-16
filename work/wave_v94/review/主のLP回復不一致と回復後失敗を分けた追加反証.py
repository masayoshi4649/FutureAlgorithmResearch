"""既存親の分類だけで、LP方向不一致と同方向回復後の失敗を分ける。"""

from pathlib import Path

import 共通独立読取 as R


def category(parent: dict) -> str:
    """
    機能: 両LP回復、同方向だが小回復、不変、逆向き、不明を別に分類する。
    引数: parent(dict)は第2レビューの親診断。
    返り値: strは因果断定をしない観測分類。
    """
    labels = [parent['自己LP分類'],parent['相手LP分類']]
    if 'LP不明' in labels:
        return '一方以上LP不明'
    if 'LP逆方向' in labels:
        return '一方以上LP逆方向'
    if 'LP不変' in labels:
        return '板は回復したが一方以上LP不変'
    if labels == ['LP所定幅回復','LP所定幅回復']:
        return '両LPも0.25幅以上回復'
    return '両LP同方向だが所定幅未満を含む'


def totals(parents: list[dict]) -> dict:
    """
    機能: 既存の親群の利益・損失と方向を相殺せず集計する。
    引数: parents(list[dict])は固定した正式策略の親。
    返り値: dictは親群だけの会計。フィルタを実施した策略成績とは異なる。
    """
    gains = sum(max(parent['収支円'],0.) for parent in parents)
    losses = -sum(min(parent['収支円'],0.) for parent in parents)
    return dict(親=len(parents),利益円=gains,損失円=losses,収支円=gains-losses,
                利益親=sum(parent['収支円']>0 for parent in parents),損失親=sum(parent['収支円']<0 for parent in parents),
                金額利益割合=gains/(gains+losses) if gains+losses else None,
                買い収支円=sum(parent['収支円'] for parent in parents if parent['方向']==1),
                売り収支円=sum(parent['収支円'] for parent in parents if parent['方向']==-1),
                幅停止損失円=-sum(min(parent['収支円'],0.) for parent in parents if parent['返済理由']=='指値の損切り幅到達'),
                中心理由損失円=-sum(min(parent['収支円'],0.) for parent in parents if parent['返済理由']=='準備時中心の利益目標で返済'))


def main() -> None:
    """
    機能: 根の許可後、完成済み親診断を細分し誤った単一原因説明を反証する。
    引数: --根許可後(bool)。
    返り値: None。新規注文、フィルタ再生、正式会計変更は行わない。
    """
    R.permission()
    fixed,assembled = R.validate()
    cause_path = R.HERE/'全53入口の現在価格資格と回復停止中心の独立診断.json'
    cause = R.read(cause_path)
    assert cause['全合格'] and cause['主']==fixed['主'] and cause['根集計SHA256']==R.digest(R.WORK/'analysis/比較結果.json')
    output = {}
    for symbol,parents in cause['主の全受理親'].items():
        all_groups,unique_groups = {},{}
        for parent in parents:
            label = category(parent)
            all_groups.setdefault(label,[]).append(parent)
            if not parent['旧源LP対照の同判断あり']:
                unique_groups.setdefault(label,[]).append(parent)
        all_totals = totals(parents)
        assert all_totals['収支円']==assembled['results'][fixed['主']]['periods']['全31'][symbol]['net']
        output[symbol] = dict(全親会計=all_totals,全親のLP方向及び回復量分類={label:totals(values) for label,values in all_groups.items()},
                              I2から原本LPへ変更した新固有親の分類={label:totals(values) for label,values in unique_groups.items()},
                              現在観測可能だが持続往復未確認=totals([parent for parent in parents if parent['価格源状態']['price_mode']!=2]),
                              現在持続往復も確認=totals([parent for parent in parents if parent['価格源状態']['price_mode']==2]),
                              現在往復原条件なし=totals([parent for parent in parents if not parent['入口当時資格']['現在往復原条件']]),
                              中心理由で負netかつ実新規時点でも利益側中心=totals([parent for parent in parents if parent['返済理由']=='準備時中心の利益目標で返済'
                                                                  and parent['収支円']<0 and parent['実新規後の固定中心が利益側']]))
    R.save('主のLP回復の不一致と同方向回復後失敗及び現在往復確認の追加反証.json',dict(
        全合格=True,主=fixed['主'],商品別分類=output,
        親群の位置づけ='固定した正式主の既存親の事後分類。群を入口フィルタにして再生した新策略の利益ではない。',
        結論=['板中値の回復だけでLPにも同じ強さの回復があるとは限らない。不明・逆向き・不変・小回復を分ける。',
              '両LPが0.25幅以上回復した親でもその後1幅停止又は中心理由の負netがある。方向の確認だけでは利益幅と継続を保証しない。',
              '現在窓が観測可能である条件G1と、持続往復を確認したG2は別の条件。観測修正自体を誤りと扱わない。',
              '中心が実新規の利益側でも、次返済気配と料金で負netになる可能性がある。利益目標という表示を黒字と混同しない。',
              'TOPは買い損失が大きく、日経は売り損失が大きい。この資料から単一の買売反転で両銘柄を解決すると結論しない。'],
        根拠SHA256={str(cause_path.relative_to(R.ROOT)):R.digest(cause_path)},
        計算コードSHA256=R.digest(Path(__file__)),**R.provenance()))


if __name__=='__main__':
    main()
