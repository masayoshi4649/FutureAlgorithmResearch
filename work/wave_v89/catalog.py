"""独立した仮想成績に応じて、固定枠への新規参加だけを停止・再開する。"""

PROFILES = {
    '0622': dict(reference_id='A0622', budgets=dict(GU=6, M3=2, C03=2)),
    '0820': dict(reference_id='A0820', budgets=dict(GU=8, M3=2, C03=0)),
    'HALF': dict(reference_id='GU_HALF', budgets=dict(GU=5, M3=0, C03=0)),
}
PRIMARY = 'B0622_C16_P60'


def catalog():
    """
    機能: 三配分に同じ停止再開条件を適用し、81条件を損益前に列挙する。
    引数: なし。
    返り値: list[dict]。
    """
    result = []
    for profile, settings in PROFILES.items():
        base = dict(mode='all', history_mode='session', window=0, threshold=0.,
                    minimum_completed=4, loss_count=0, publication='source_end', reverse=False)
        variants = [(f'B{profile}_ALL','停止なし',base)]
        for scope, code in (('session','S'),('carry','C')):
            for window in (8,16):
                for threshold in (.5,.6,.7,.8):
                    gate = dict(base,mode='share',history_mode=scope,window=window,threshold=threshold)
                    variants.append((f'B{profile}_{code}{window:02d}_P{round(threshold*100)}',
                        f'過去{window}親の利益割合{threshold:.0%}以上なら参加',gate))
                variants.append((f'B{profile}_{code}{window:02d}_R60',
                    f'逆対照：過去{window}親の利益割合60%未満なら参加',
                    dict(base,mode='share',history_mode=scope,window=window,threshold=.6,reverse=True)))
            for count in (1,2,3):
                variants.append((f'B{profile}_{code}_L{count}',f'仮想{count}連敗から停止',
                    dict(base,mode='streak',history_mode=scope,loss_count=count)))
        assert len(variants)==27
        for identifier,name,gate in variants:
            result.append(dict(id=identifier,name=name,profile_id=profile,**settings,gate=gate,primary=identifier==PRIMARY))
    assert len(result)==81 and len({r['id'] for r in result})==81
    return result


def specification():
    """
    機能: 完了公開、同時計除外、停止中の仮想継続と会計対照を固定する。
    引数: なし。
    返り値: dict。
    """
    return dict(主仮説=PRIMARY,件数=81,
        思想='源の損小利大が足元で失われたら新規だけ止める。実停止中も独立仮想口座を完走させ、その仮想成績が条件を回復したら次の新規から再開する。',
        配分='0622＝追従6・中期逆張り2・短期反転2、0820＝追従8・中期逆張り2、HALF＝追従5のみ。TOPIX枚数で表示し、NKは各2倍。空き枠を貸さず親内増量もしない。',
        源='無変更v88のGU/M3/C03公開注文を使用。源の判定に新しい実採否や実損益を戻さない。所与qの常時仮想口座と採用実口座を同じ価格・数量丸め・手数料で独立執行する。',
        条件='配分ごと27条件＝停止なし1＋金額割合(8/16親×50/60/70/80%×場内/過去場)16＋連敗(1/2/3×場内/過去場)6＋60%逆対照(8/16親×場内/過去場)4。',
        金額割合='商品×源ごとの最新8/16完了仮想親に対しG/(G+L)を計算。通常は基準以上で新規、逆対照は60%未満で新規。最低4完了未満は双方許可、4以上なら現にある窓を使う。分母0は許可だが勝ちと扱わない。',
        連敗='最低4条件は適用しない。過去の仮想親net<0が1/2/3連続したら次新規を拒否。仮想net>=0の完了で連敗を0へ戻す。拒否しても紙上親は通常どおり継続する。',
        公開='仮想親の元紙上全返済が公開された次有効観測で、仮想qの全料金後netを完了情報として公開する。整数丸めで仮想qが早期0でも紙上終了まで待つ。場末強制全返済による終了はその場末観測で公開。未確定親損益や未来MFEは参照しない。',
        時計='新規判断の代理時計よりstrictに古い完了だけを参照。同じ時計の終了は原本seqが前でも後でも除外する。新規判断は紙上新規公開行、実約定は次有効観測。',
        履歴='sessionは各場空から開始。carryは過去場の完了仮想成績だけを商品×源に持越す。建玉は全場0にし、履歴も他商品・他源・別配分へ混ぜない。',
        親採否='初回新規判断で一度だけ採否を固定。拒否親の途中入場なし。採用後の途中減量と全返済は元sourceと同じ。選定都合で現在の利益玉を切らず、拒否枠を他源へ回さない。',
        実行='v88と同じ源新規・返済の次有効CurrentPrice全量約定。既知場末を優先して新規取消し残玉全返済。固定秒遅延0。ラージ観測によるミニ/マイクロ換算で実小型板約定の再現ではない。',
        料金='各実注文と各常時仮想注文に片道TOPIX41.8円/NK11円×数量、1円未満切捨て。仮想料金は実口座へ二重計上せず、履歴評価だけに用いる。',
        会計='源別親G/Lを商品内で合算して金額利益割合を評価。無取引を勝ちにしない。全原板行末清算時価は既払料と残玉全返済見込料を源ごとに控除し、場を時価連結して最大下落を測る。',
        差分証明='採用親は同配分停止なしと全実注文・価格・数量・返済・料金が一致（UID番号の詰め直しだけ許容）。全収支差は拒否した負けの損失−拒否した勝ちの利益。三基準は旧v88と完全一致。',
        反証='過去好調の持続と不調後の回復を同じ条件で対照する。通常60%＋逆60%＝停止なし＋両方が許可した準備親という源別親の金額・料金恒等式を確認する。未来の親結果で採否を作らない。',
        選定='事前主0622/過去16親/60%以上/過去場持越を差替えない。参考は前16だけで両商品黒字・各20実親以上・各DD>0からmin(商品別net/DD)最大、同点min(商品別最悪場net/DD)最大、最後ID昇順。該当なし参考なし。後14や全30で選び直さない。',
        限界='全30は既知探索。過去窓を80%にしても次の親が80%になる保証はない。準備中の損失と、止めた間に逃した回復利益も含める。',
        API取得数=0,実注文数=0)
