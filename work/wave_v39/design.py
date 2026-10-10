"""予想外の板圧力について、入口と反証を実収支の計算前に定義する。"""

from __future__ import annotations

PRIMARY = 'I00'


def catalog() -> list[dict]:
    """機能: 固定出口に対する情報成分と一軸感度の一覧を返す。

    引数: なし。返り値: 主・比較・感度の条件 (list[dict])。交差最適化はしない。
    """
    base = dict(mode='residual',lag=3,threshold=1.,price_confirm=.05,rearm=.5,
        peer='none',invert=False,delay=0.,observed=False,seed=None,role='comparison')
    definitions = [
        ('I00','予想外の板圧力',dict(role='primary')),
        ('I01','素の板圧力',dict(mode='raw')),
        ('I02','予想された板圧力',dict(mode='predicted')),
        ('I03','価格変化だけ',dict(mode='price')),
        ('I04','予想外の圧力を逆方向へ',dict(invert=True)),
        ('I05','相手市場の予想外の圧力も一致',dict(peer='residual')),
        ('I06','相手市場の価格変化も一致',dict(peer='price')),
        ('I07','価格だけに相手価格の確認',dict(mode='price',peer='price')),
        ('I08','板残差だけ・価格確認なし',dict(price_confirm=0.)),
        ('I09','素の板だけ・価格確認なし',dict(mode='raw',price_confirm=0.)),
        ('I10','予想成分だけ・価格確認なし',dict(mode='predicted',price_confirm=0.)),
        ('I11','残差閾値0.5',dict(threshold=.5,role='sensitivity')),
        ('I12','残差閾値1.5',dict(threshold=1.5,role='sensitivity')),
        ('I13','過去1区間の予想',dict(lag=1,role='sensitivity')),
        ('I14','過去6区間の予想',dict(lag=6,role='sensitivity')),
        ('I15','価格確認0.025ATR',dict(price_confirm=.025,role='sensitivity')),
        ('I16','価格確認0.10ATR',dict(price_confirm=.10,role='sensitivity')),
        ('I17','再準備は閾値0.25まで戻る',dict(rearm=.25,role='sensitivity')),
        ('I18','再準備は閾値0.75まで戻る',dict(rearm=.75,role='sensitivity')),
        ('I19','板条件なしの独立価格入口',dict(mode='price_independent')),
    ]
    rows = [dict(base,id=identifier,name=name,**changes) for identifier,name,changes in definitions]
    # ----------------------------------------
    # 成績を見て選ばず、主要6入口へ同じ実行感度を課す。
    for identifier in ('I00','I01','I03','I04','I05','I06','I19'):
        main = next(r for r in rows if r['id'] == identifier)
        for delay in (1.,5.,15.):
            item = dict(main);item.update(id=f'{identifier}_D{int(delay):02d}',name=main['name']+f'・伝達{delay:g}秒',
                delay=delay,role='execution')
            rows.append(item)
        item = dict(main);item.update(id=identifier+'_OBS',name=main['name']+'・観測価格返済',observed=True,role='execution')
        rows.append(item)
    assert len(rows) == len({r['id'] for r in rows}) == 48
    return rows


def supplementary() -> list[dict]:
    """機能: 主と両市場確認の全公開機会を保つ固定乱数対照を定義する。

    引数: なし。返り値: 192個の方向乱数条件 (list[dict])。
    実取引時刻は各口座の返済・休止に依存するので、同一約定時刻とは主張しない。
    """
    specs = {r['id']:r for r in catalog()}
    result = []
    for original in ('I00','I05','I06'):
        for seed in range(64):
            item = dict(specs[original]);item.update(id=f'{original}_R{seed:02d}',
                name=specs[original]['name']+f'・方向乱数{seed}',seed=seed,role='random',parent=original)
            result.append(item)
    return result


def rules() -> dict:
    """機能: 評価開始・売買・機会と採否の意味を先に固定する。

    引数: なし。返り値: 共通契約 (dict)。既知期間での探索であることを維持する。
    """
    return dict(主仮説=PRIMARY,主48条件=True,方向乱数192条件=True,
        各銘柄1枚=True,片方向上限={'TOPIX':10,'NK225':20},円倍率={'TOPIX':1000.,'NK225':10.},
        最初2セッション='学習のみ、全入口の取引は0。残り11も既知データ。',
        評価母集団='各lagとも最大lag6の有効連続区間、40過去標本、2過去完了、開始20分後を共通に使う。I19だけ板条件と40標本を課さず、最初2期間除外と価格連続性を揃える。',
        学習='銘柄別、過去完了全区間、ridgeのmeanSE+0.01二乗罰則、切片無罰則。',
        品質='新公開1件以上、ブロック間隔<=60秒、素材遅れ<=60秒、リセットなし、分決定間隔<=90秒かつ連続minute。',
        分母='直前区間で最後に公開された行の両側最良数量。素材ブロック平均ではない。',
        圧力='新たに公開された板ブロックOFI合計/直前公開両側数量の符号付きlog1p。厳密な取引時刻1分OFIではない。',
        発火='初の有効区間又は再準備後に閾値へ到達した方向。その時点の価格確認に不合格なら消費して捨て、閾値外で一致するまで待たない。',
        価格='原本のminute跨ぎ最初行同士の価格差/判断行公開ATR。全方式に有限性・連続minute・決定間隔<=90秒。価格入口は0.05ATRを1とする。',
        再準備='絶対スコアが閾値×再準備率より小さくなると再準備。欠測中の値を0にしないが、次の連続有効6区間では新たに準備可。',
        反対側='反対符号の閾値到達は新しい反対方向の機会。同じ強い符号を毎分再発火させない。',
        相手確認='自市場I00の候補パルスを先に固定。相手は公開時刻から60秒後、追加遅延後の古さ<=120秒の最後の有効/無効イベントを参照。',
        相手残差='相手の残差スコアが自己方向へ1以上。',相手価格='相手の公開区間価格変化が自己方向へ0.05ATR以上。',
        乱数='入口条件通過後の候補時刻を維持し、元方向×v39|seed|session|symbol|seqのSHA256先頭bit符号。上下反射時も同じ符号を使う。実取引時刻まで揃えた検査ではない。',
        新規='決定の次原本行、かつδ秒以上後の観測価格。入口予約は後続信号で変更せず、場末で取消。',
        出口='入口判断時ATRと2呼値の大きい方を呼値切上げでrへ固定。1r損切り/2r利確OCO、約定から30分で成行返済予約。',
        IFD='返済OCOは新規実約定後に発注。子注文も次原本行かつδ秒後から有効。追加二重遅延ではなく別注文の伝達。',
        優先='成熟OCO、成熟時間返済、新規約定、新時間返済予約、新規パルス。未成熟時間返済中も成熟OCOは有効。',
        休止='全返済後5分、新規は安全返済時刻5分前まで。保有中・予約中の候補は蓄積しない。',
        場末='15:35/05:50で全返済を予約し15:45/06:00より前に全返済。保存内で完結できなければ検査失敗。',
        約定='主は指定返済価格、成行と新規は観測価格。費用0。観測価格返済を別対照。',
        基礎条件=dict(各銘柄決済数下限=20,各銘柄活動セッション下限=6,各銘柄ロングショート各下限=3,
            各銘柄収支正=True,利益損失比下限=1.2,平均利益平均損失比下限=1.2,
            最大勝ち取引除外収支非負=True,最大黒字セッション除外収支非負=True),
        板付加価値='両銘柄で主I00の合計Rが素OFI I01・共通価格I03・独立価格I19・逆I04・方向乱数64の中央値を超える。I03内差とI19参加差は別記し、因果効果とは呼ばない。円収支も併記。',
        実行感度='I00の1/5/15秒・観測価格の全4条件が基礎条件を通過。閾値/ラグの周辺8条件は別記し、採用条件を後付けしない。',
        両市場付加価値='I05/I06は同じ自己候補への追加確認として、確認なしI00と各方向乱数を超えるか別に報告。失敗を主I00の失敗と混ぜない。',
        未来反応='各候補の次行価格から5/15分後の原本価格。各 horizon を場内で観測できないラベルは除外。重複窓は独立標本と呼ばない。',
        選択='手動の日別切替なし。I00は主の固定方式。両市場フィルターは別の機械的候補で後付け勝者へ置換しない。',
        現在API取得数=0,保存ライブ使用=False,全体目標達成=False)
