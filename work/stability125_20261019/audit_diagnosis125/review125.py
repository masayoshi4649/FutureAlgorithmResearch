"""全保存groupの分類から、損失の原因と未測定の一部品対策を整理する。"""

import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def main() -> None:
    """
    機能: 所有済み分類JSONだけを使って、敵対的所見と次の固定対照2案を保存する。
    引数: なし。
    返り値: None。保存台帳の再読、原市場、金融再生、登録を行わない。
    """
    path=HERE/'全十二条件の入口出口と順行返し及び実撤回距離.json'
    raw=path.read_bytes();d=json.loads(raw);assert d['passed']
    g=d['aggregates'];case_rows=[]
    for case in d['details']:
        parts=case['trades']
        case_rows.append(dict(symbol=case['symbol'],session=case['session'],session_net=case['net'],
            forced_net=case['forced_net'],signal_net=case['signal_net'],loss_groups=case['loss_groups'],
            positive_then_loss_groups=case['mfe_positive_loss_groups'],never_positive_loss_groups=case['never_positive_loss_groups'],
            sampled_loss_groups=[dict(group_id=t['group_id'],entry_time=t['entry_time'],side=t['side'],
                first_price=t['geometry']['first_price'],exit_time=t['exit_time'],exit_price=t['exit_price'],net=t['net'],
                mfe=t['mfe'],initial_w=t['initial_w'],entry_reason=t['entry_reason'],exit_reason=t['exit_reason'],
                fill_Last_directional_gross=t['last_directional_gross'],entry_drag=t['entry_drag'],exit_drag=t['exit_drag'],
                fees=t['fees']) for t in parts]))
    findings=[
        dict(subject='手数料を除いても、価格方向の優位が売買価格差を上回っていない',
            evidence={s:dict(net=g['C00'][s]['all']['net'],
                decision_Last_directional_gross=g['C00'][s]['all']['decision_last_directional_gross'],
                entry_to_decision_Last_drag=g['C00'][s]['all']['entry_vs_decision_last_drag'],
                exit_to_decision_Last_drag=g['C00'][s]['all']['exit_vs_decision_last_drag']) for s in ('TOPIX','NK225')},
            interpretation='C00の判断Last起点の方向寄与は全316/352群で−47500/−7000円。実約定へ移す差額を引くと−1497500/−730000円。手数料は全0。この標本では、直前ERが高いことは将来の利益値幅の優位につながっていない。',
            limitation='この全群分解は判断時Lastとの恒等式で、真のspreadだけではなく判断後の価格移動も含む。Lastで約定できたという戦略成績ではない。'),
        dict(subject='一度の順行を、1w追尾起動まで伸びると見込んで返している',
            evidence={s:g['C00'][s]['all'] for s in ('TOPIX','NK225')},
            interpretation='C00の負群はTOP187中120、NK203中129で途中黒字。うち119/120・128/129は1w追尾の起動前だった。黒字化したことと、その後1wまで順行することは別。',
            limitation='同じ群で狭くすれば全て取れたという反実仮想ではない。C02の一律狭幅化はTOP−2010000/NK−995000円へ悪化。起動・停止・幅をまとめた政策差であり純粋な追尾幅だけの効果でもない。'),
        dict(subject='出口で救える利益自体がなかった群もある',
            evidence={s:dict(losses=g['C00'][s]['all']['losses'],never_positive=g['C00'][s]['all']['never_positive_losses'],
                net=g['C00'][s]['all']['never_positive_loss_net']) for s in ('TOPIX','NK225')},
            interpretation='TOP67/187負群・NK74/203負群は全保持区間で清算利益が正にならず、−1487500/−712000円。利確の早期化だけではこの群を利益化できない。',
            limitation='負群を後から抜いた率。全入口の予測正答率ではなく、入口を見送れた利益でもない。'),
        dict(subject='期限強制参加だけを消しても残る信号損失',
            evidence={m:{s:dict(forced=g[m][s]['entry'].get('5'),signal={k:v for k,v in g[m][s]['entry'].items() if k!='5'})
                for s in ('TOPIX','NK225')} for m in ('A00','B00','C00')},
            interpretation='C00通常信号はTOP−1210000/NK−478000円。強制参加の少ないB00も通常信号−3165000/−701000円。最低参加が唯一の赤字原因ではない。',
            limitation='強制群のPLを算術で引くことを、強制参加OFFの再生収支とはしない。busyと後続参加が変わり得る。'),
        dict(subject='追加は全6対照で悪化し、平均建値と撤回条件の悪化を再現した',
            evidence=d['addition_pairs'],
            interpretation='00→01の初回実entry keyは全6対照で100%一致。追加許可の差はA TOP−157500/NK−61000、B−1082500/−362000、C−27500/−161000円。追加後の平均建値・保険線・最終PLの問題であり、初回候補の選び違いではない。',
            limitation='追加で利益が増えた個別群もあり、全ての増玉が無意味とはしない。純追加数量と、それに連動するstop再計算の効果は分離していない。源を同じ初回で再実行していない。'),
        dict(subject='事前に疑った狭い実撤回幅・費用占有は、C00の主因ではなかった',
            evidence={s:dict(groups=g['C00'][s]['all']['groups'],spread_gt_half_actual_stop=g['C00'][s]['all']['decision_spread_gt_half_actual_stop'],
                median_spread_to_stop=g['C00'][s]['all']['stop_cost_ratio_median']) for s in ('TOPIX','NK225')},
            interpretation='C00の該当0/316・0/352、判断spread/実初期撤回幅の中央値は両方12.5%。この原因を理由に新しいgateを足す提案は採らない。A00の7/225・9/204とは分ける。',
            limitation='判断spreadと実fill後stopの別時点比。全エントリー経路の因果として完結していない。'),
        dict(subject='両建てを解除したことだけで集中損失を説明しない',
            evidence='C00は初回だけのTOP5枚/NK10枚、追加なし。上位6赤字場は反復する純方向のstop損失。',
            interpretation='同枚数両建ての不利な建値差固定は解消したが、期待値のない方向判断を繰返すと片方向でも損失が増える。',
            limitation='旧120〜124と今回では入口・保有・費用・対象も違い、両建てOFFだけの対照ではない。両建てを戻せば直るという結論は出せない。')
    ]
    proposals=[
        dict(id='D125_R1',name='両市場の継続状態が往復へ変わったときだけ、既存小益を保全する',
            mechanism='入口理由3の追従群を保有中、現在の新公開特徴で自己ER<=.2かつ相手ER<=.2・鮮度適格になり、返済側BBOによる純益>0なら、初回だけ利益保全モードへ遷移。',
            exact_candidate='初回数量と入口は維持。条件成立時の返済側BBOでpositiveな場合だけ、以後の停止線を既建値の有利側1観測tickと最高返済側価格から0.5w戻りの有利な方へ一方向更新。次正常raw返済、gap損は計上。条件未成立ではC00の1w起動/0.75w追尾を保持。',
            why='現在C00は入口でだけERを使い、保有後の「進行が終わり往復へ変わった」ことでは保全しない。1w未達の一度黒字負群が多数ある。',
            sources=['00072_二市場の即時板判断と保有管理','00108_利益保護と二市場の再参加検証','00125の日次参加十二条件（公開フォルダ名は根担当で確定）'],
            difference='旧弱支持消失の一律退出や、今回C02の全場一律狭幅化と異なり、既存の金額黒字と両市場ERの往復化が同時に観測された場合だけ停止線を切り替える。単なる狭幅再試行として既測定扱いしない。',
            unknown='保全条件が過去の大勝ち途中にも出て利益を削る可能性がある。今回の小JSONだけでは時点ごとのER遷移を測定していない。効いたとは一切主張しない。',
            test='C00の入口/数量/全後続を固定した保全OFF/ON。避けた損失・失った勝ち・後続参加の寄与を分ける。独立人工・新試行登録の後にのみ金融。'),
        dict(id='D125_R2',name='損切り後は、失敗後に生じた新しい共同進行だけで再参加する',
            mechanism='一度stopで損失を確定したら、次の1分足というだけで同じ15分履歴の信号を再利用しない。返済完了時の自己/相手Lastを別アンカーにし、それ以降の新しい価格だけで共同進行を判定する。',
            exact_candidate='実損失返済後からの価格変化の符号が両市場で一致し、各市場の純変化>=損失返済時点で既知の各市場固有w、かつ後続価格のER=abs(アンカー差)/累積絶対差>=.4を両市場で満たした最初の新公開特徴で再許可。相手のwも同じ算式で因果計算し、相手時刻が不鮮明なら再許可しない。TOPIXのptをNKにそのまま適用しない。元のC00入口条件も必要。初回の最低1取引には干渉せず、時間固定の休止にはしない。',
            why='ER15は毎分1本更新しても14/15本を共有する。現在はfi>exit_featureだけで、失敗した直前進行をほぼ再利用できる。B00の頻繁な持替えやC00最悪場の上下stop反復に対し、何を新しい根拠と認めるかを具体化する。',
            sources=['00089_予定リスクと中心利確及び失敗後再参加','00103_往復帯の回避と損失後再参加の統合検証','00119_戦略の自動選択と場内黒字の再探索'],
            difference='旧中心価格への復帰、失敗帯の封鎖、10/30分冷却とは異なり、損失返済後の新観測だけから自他の方向効率を再構成する。旧窓の残りを新証拠と数えない対照。',
            unknown='新しい進行を待つことで回復勝ちを失い、遅れてまた終点で参加する危険が残る。既存小診断に相手アンカー価格と全後続累積pathは保存されず、効果は未測定。',
            test='C00再参加の元版と、post-loss情報更新だけを追加した版。期限初回/通常初回は共通とし、後続の回復勝ち喪失・減った負け・新参加を対応付ける。')
    ]
    conclusion=dict(main='今回の売買は、直前のまっすぐな進行を将来の1w以上の継続と見込み、途中の小益を返し、外れた後も近い履歴で再参加している。追加はその不利な戻りを拡大した。',
        not_a_fee_explanation='全注文手数料0。予測が生んだ値幅の余裕が小さく、実売買価格差と反転に負けている。',
        known_limits='12条件すべて両商品合計赤字。0.5%達成や将来の有用候補の発見とはしない。',
        discarded='両建てを戻す、一律の追尾狭幅、単なる損失価格帯封鎖、spread/stop gate追加、強制初回だけ除去、単に追加を増やす案は、新しい解決として提案しない。')
    exceptional=dict(
        ordinary_reversal=dict(session='2026-09-28_Night',entry='23:52:00 売り5枚@4074',exit='翌01:20:44 買戻し@4084',net=-50000,mfe=25000,
            interpretation='途中5ptの有利な動きがあった後の10pt逆行。将来1wまで継続するとの見込みが外れた例で、補充板や参加者の意図を証明した例ではない。'),
        quote_discontinuity=dict(session='2026-10-14_Night',entry='21:07:02 買い5枚@4123',exit='21:30:01 売り@4100',net=-115000,mfe=27500,
            trigger_price=4117,decision_Last=4100,decision_bid=4127.5,decision_ask=4134.5,fill_price=4100,
            interpretation='返済判断のLastと気配が非同期で、次正常rawの売却価格は停止線を17pt通過。小益保全の改善だけで回避できると扱わず、板の騙しやニュースの真のgapとも断定しない。',
            unmeasured='停止線到達前後の同時刻性を保証したBBO推移と取引所イベント履歴。この診断では原板を読み直さない。'))
    result=dict(passed=True,source=dict(path=path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(raw).hexdigest()),
        conclusion=conclusion,findings=findings,six_worst_sessions=case_rows,unmeasured_mechanical_proposals=proposals,
        ordinary_reversal_and_quote_discontinuity=exceptional,
        new_financial_accounts=0,original_market_reads=0,price_input_reads=0,saved_account_cache_additional_reads=0,
        API=0,real_orders=0,registry_changes=0)
    target=HERE/'敵対的所見と二つの未測定機械対策.json';assert not target.exists()
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    brief=HERE/'損失原因と次に反証すべき二条件.md'
    assert not brief.exists()
    brief.write_text('''# 00125 保存会計の敵対的所見

手数料0でも、直前の方向がそのまま利益につながる優位は確認できなかった。C00の判断Lastによる方向寄与はTOPIX−47,500円・NK−7,000円で、実売買価格への移行差を含む最終収支は−1,497,500円・−730,000円。移行差は判断後の値動きも含み、純粋なスプレッドだけではない。

| 原因 | TOPIX C00 | NK C00 |
|---|---:|---:|
| 負け群のうち、一度は清算黒字 | 120/187群 | 129/203群 |
| そのうち1w追尾起動前に反転 | 119/120群 | 128/129群 |
| 一度も清算黒字にならず | 67/187群 | 74/203群 |
| 強制参加を除く通常信号の収支 | −1,210,000円 | −478,000円 |

出口だけで救えない入口と、小益を追尾起動前に返す保有判断が両方ある。A00/B00も通常信号が赤字で、期限参加だけが原因ではない。一律に幅を狭めたC02は両商品で悪化し、追加を許した00→01も3家族×2商品の全6対照で悪化した。初回の売買は対照間で全一致する。追加後の数量と停止線変更は分離していない。

具体例はTOPIX 9/28ナイト23:52売り4074→翌01:20買戻し4084の−50,000円。途中+25,000円から逆行した。10/14ナイト21:07買い4123→21:30売り4100の−115,000円は別で、判断Last4100・bid4127.5・ask4134.5という非同期状態を含み、次rawで停止線4117を17pt通過した。「板に騙された」「ニュースのgap」とは保存会計だけでは断定できない。

次の二案は**未測定**。改善したとの結論は出さない。

1. **両市場の進行が往復へ変わったときだけ小益を保全。** 保有中、新公開ERが両方0.2以下、相手が新鮮、清算黒字の三条件で保全モードへ移り、建値有利側1tickと最高清算価格から0.5w戻りの有利な停止線へ切替。入口と通常時の幅は元のC00を維持する。一律狭幅や片市場の弱支持消失とは区別する。反証は「大勝ちの途中でも同条件が出て、守れた負け以上の勝ちを失う」こと。
2. **損切り後は、その後だけの新しい共同進行を要求。** 返済時点の自他Lastをアンカーにし、それ以後の値動きだけで同方向・各市場固有w以上・ER0.4以上を確認してから再参加する。旧15分履歴の14/15を新しい根拠と数えない。初回参加は変えず、固定時間休止や失敗価格帯封鎖とも区別する。反証は「回復勝ちを失い、また終点で遅れて入る」こと。

両案とも利益を選んで後付け採用せず、仕様・反証・源を先に固定し、単要因の対照にする。今回の保存会計診断では新金融0・原市場読取0。目標の達成は確認できていない。
''',encoding='utf8')
    print(json.dumps(dict(passed=True,path=target.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        brief=brief.relative_to(ROOT).as_posix(),brief_sha256=hashlib.sha256(brief.read_bytes()).hexdigest(),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),conclusion=conclusion),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
