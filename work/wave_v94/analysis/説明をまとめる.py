"""独立検証済みの正式損益へ、セッション安定性を優先した短い説明を添える。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def read(path: Path) -> dict:
    """
    機能: 保存済みの日本語資料を読み込む。
    引数: path(Path)は資料の位置。
    返り値: dictは資料の内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    """
    機能: 根拠となる資料が変更されていないことを内容で確認する。
    引数: path(Path)は対象の位置。
    返り値: strはSHA256指紋。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def main() -> None:
    """
    機能: 全会計・配分・原因の独立合格後、会計を変えずに説明だけを保存する。
    引数: なし。
    返り値: None。売買判断、参考選定及び正式損益は変更しない。
    """
    account_path = HERE / '比較結果.json'
    account = read(account_path)
    fixed_path = WORK / '事前固定.json'
    fixed = read(fixed_path)
    assert sha(fixed_path) == '94969a99b2e7373cb2c34a8f8c7cc23ea234ce26d1b32904e175f1e440efbc6b'
    assert len(fixed['SHA256']) == 181
    for relative, expected in fixed['SHA256'].items():
        assert sha(ROOT / relative) == expected, relative
    evidence = [
        WORK / 'audit_parallel/並列実行_全53条件全31場の価格入口と別執行源及び全原板会計と安定性の独立検算.json',
        WORK / 'audit/独立配分の同数量単独と全31源別注文及び全原板時価の完全一致.json',
        WORK / 'audit/全3286口座の運用区切りと連続立会末及び立会内約定の独立補足.json',
        WORK / 'audit/後15正式損益未参照の前16参考代表の注文会計による独立再選定.json',
        WORK / 'review/全53条件全31の独立親会計と安定性及び一軸経路分解.json',
        WORK / 'review/全53入口の現在価格資格と回復停止中心の独立診断.json',
        WORK / 'review/主とJ8及びM82の最悪3場原板と配分及び依存の独立反証.json',
        WORK / 'review/主のLP回復の不一致と同方向回復後失敗及び現在往復確認の追加反証.json',
        WORK / 'review/J8旧イベントの前決済と連続損失及び既知市場開始の前後分類.json',
        WORK / 'audit_parallel/凍結監査の全手順同一と実行並列化及び依存名補足.json',
        WORK / 'audit/元full単純起動の中断と依存名補足.json',
    ]
    for path in evidence[:-1]:
        assert read(path)['全合格'], path
    interrupted = read(evidence[-1])
    assert interrupted['正式最終合格'] is False
    assert interrupted['数学検算基準変更'] == interrupted['正式PL変更'] == 0
    assert interrupted['固定full原本変更'] == interrupted['凍結181依存変更'] == 0
    assert interrupted['潜在例外が実際に発生したとの主張'] is False
    assert account['全合格'] and account['条件数'] == 53 and account['selected'] == 'J8'
    assert not account['both80'] and not account['両商品で全場黒字']
    totals = account['results']
    j8 = totals['J8']['periods']['全31']
    stable = totals['J8']['stability']['全31']
    main_values = totals[account['primary']]['periods']['全31']
    review = read(evidence[4])
    assert review['口座'] == 3286 and review['注文'] == 11320 and review['親'] == 5660
    target_change = review['一軸及び別源比較']['I3_G2_S0_T0→I3_G2_S0_T1']
    assert target_change['TOPIX']['全源']['厳密同一新規管理差円'] == -480000
    assert target_change['NK225']['全源']['厳密同一新規管理差円'] == -100000
    # ----------------------------------------
    # 最大収益の順位ではなく、赤字場の損失と活動黒字数から説明する。
    conclusion = [
        '毎セッション安定して稼げる解は、今回も未達です。53条件を比較しましたが、両銘柄で金額利益80%を達成した条件は0でした。',
        f'比較参考はJ8（追従8枚／日経16枚）。両銘柄とも29活動場中17黒字。平均赤字はTOPIX {stable["TOPIX"]["mean_losing_session_yen"]:,.0f}円・日経 {stable["NK225"]["mean_losing_session_yen"]:,.0f}円、最大赤字は{stable["TOPIX"]["worst_session_loss_yen"]:,.0f}円・{stable["NK225"]["worst_session_loss_yen"]:,.0f}円でした。',
        '反発の追加はTOPIXの赤字をわずかに軽減しましたが、日経の平均赤字・最大赤字を増やしました。両銘柄共通の安定化としては採用できません。',
        f'事前主{account["primary"]}はTOPIX {main_values["TOPIX"]["net"]:+,.0f}円・日経 {main_values["NK225"]["net"]:+,.0f}円で不採用。観測可能な価格を増やしても、回復後に利益方向へ続く確率や利幅は改善しませんでした。',
        f'J8の全31収支はTOPIX {j8["TOPIX"]["net"]:+,.0f}円・日経 {j8["NK225"]["net"]:+,.0f}円。最大利益日を除いても{j8["TOPIX"]["without_best_day"]["net"]:+,.0f}円・{j8["NK225"]["without_best_day"]["net"]:+,.0f}円ですが、平均勝ち額／平均負け額は{j8["TOPIX"]["payoff"]:.2f}・{j8["NK225"]["payoff"]:.2f}に留まります。安定した損小利大の完成形とは呼びません。',
        '利確を中心へ縮めた比較では、厳密に同じ新規の管理差だけでTOPIX−480,000円・日経−100,000円。助かった損失より、削った利益の方が大きくなりました。返済が早くなって増えた再参加の損益は別に分けています。',
    ]
    notes = dict(account['cause_notes'])
    notes.update({
        '入力': '深い板の不正と価格の不正を分離。原本の正常約定価格を使うことで計算可能な場面は増えました。しかし、同じ入口での管理改善ではなく、増えた新固有取引が主の赤字を増やしました。価格が観測できることと、回復後の継続に正の期待値があることは別です。',
        '検証していない部分': '今回の新価格系列で変えたのは市場分類と反発入口の現在資格です。追従J8の新規イベントは旧素材を保持しました。正常約定価格から追従の入口全体を作り直す手法や、セッション損失予算による停止は、今回の53条件には含めていません。反発の失敗から追従の新入力まで無効とは推論しません。',
        '次の改善の根拠': 'J8の損失後の同方向再参加は既存親診断で両銘柄とも前16・後15が黒字。反対方向は日経で前後とも赤字でした。負け後の一律停止はTOPIXの利益を削る可能性があり、時間帯回避も両商品には共通しません。次は追従入口の独立価格化と、損失後の反転判断の根拠を調べます。これは未検証の提案で、親群だけを抜いた新手法成績とは扱いません。',
        '利確': '旧中心は新規時点で既知ですが、将来そこへ戻る保証はありません。現在往復確認・固定幅停止を揃えたT0→T1では、同一新規管理差TOP−480,000円・日経−100,000円。中心返済による負け軽減はありましたが、利益縮小と利益→損失を補えませんでした。',
        '配分': 'M82は追従8/16と反発2/4の独立枠。J8へ反発を加えると全収支−70,956円・−48,328円。TOPIXの平均赤字は約1,168円減りましたが、日経では約1,259円増加、最大赤字も7,544円増加しました。J10より損失が小さいことは、追従枚数を減らした効果と区別します。',
        '安定性': '赤字場の平均・最大、活動黒字率、共通上限での下方偏差を優先します。J8とJ10は同じ売買の枚数違いです。J8の実円リスクが小さいことは認めますが、方向判断の精度が上がったとは扱いません。R2も少枚数のため損失額が小さいだけなら成功に数えません。',
        '場内返済': '全11,320注文は連続立会終了前に約定。データ間隔の影響で保守的な運用区切りを越えた返済は23件ありました。これは場跨ぎではありませんが、運用区切り内の返済を保証する結果でもありません。代理時計とラージ気配による検証です。',
        account['primary']: '現在の両価格が観測可能な時だけ、旧中心からの逸脱と両市場midの回復で反発参加。それでもTOPIXは15活動場中6黒字、日経26活動場中10黒字でした。約定価格の欠測を救済して増えた入口は収益の優位を示しません。',
        'J8': '両市場共通の方向に追従する参考。29活動場中17黒字ずつで、残り12場は赤字、2場は無取引。平均親の利益と損失はほぼ同額です。全31は既知であり、今後も同じ安定性を示すという証明ではありません。',
        'J10': 'J8と同じ売買を10/20枚で行う数量対照。収益も赤字もほぼ25%大きく、黒字場数は同じです。収益が大きいことだけでは安定性の改善にしません。',
        'R2': '事前主を2/4枚へ縮小した単独対照。全31では両銘柄で赤字です。損失の円額を減らす数量管理にはなっても、利益が出る手法への改善ではありません。',
        'M82': '全31収支TOP+369,600円・日経+137,880円。TOPIX平均赤字63,780円・最大190,004円、日経31,947円・最大80,952円。日経の活動黒字は18/30へ増えましたが、10/07ナイトの赤字救済1場に対し09/25デイは黒字→赤字1場、10/09ナイトは新しい黒字活動でした。最大利益日を除くと日経−3,536円。赤字額の安定化は両商品に共通しません。',
        'I3_G2_S0_T0': '現在の両市場が往復と確認された時だけ入って3幅の利益を待つ対照。TOPIX+333,264円・日経−21,040円。片方の黒字を両市場共通の安定化へ代用しません。中心へ利確を縮めると両商品で収支が悪化しました。',
        '具体的な損失': '主のTOPIX最悪は10/07デイ−137,508円。09:01:43売り、09:08:39売り、09:12:32買いの判断から各−45,836円。日経最悪は09/29デイ−54,400円で、09:00:28売りは09:00:33、09:02:46買いは09:03:05に返済して各−16,440円。同じ場で買売の双方が失敗しており、一定方向の禁止や全反転だけでは説明できません。',
        '損失の値段': '09/29の日経09:00:28ショート20枚は、新規売り65,860→09:00:33返済買い65,940。80pt×20枚×10円で−16,000円、往復料金440円を加えて−16,440円。停止はLastPrice65,930で判断しており、停止線と次の返済askは同じ価格ではありません。09:02:46ロングも65,780→65,700で同額を失いました。',
        '板と約定価格の回復': '主に増えた新固有赤字のうち、両市場の約定価格も0.25幅以上回復していたのに1幅停止となった例はTOPIX9親−417,524円・日経16親−265,040円。LPも所定回復した既存親群の合計もTOPIX−227,572円・日経−124,640円でした。最新の往復確認済み親群も両赤字で、板だけの錯覚や観測不明の除外だけでは説明できません。いずれも事後親診断であり、新フィルタの実績ではありません。',
    })
    value = dict(全合格=True, 根集計SHA256=sha(account_path), 売買及び会計の変更=0,
                 conclusion=conclusion, cause_notes=notes,
                 根拠SHA256={str(path.relative_to(ROOT)): sha(path) for path in evidence},
                 API取得=0, 実注文=0)
    (HERE / '説明補足.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 根集計SHA256=value['根集計SHA256'], 根拠数=len(evidence)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
