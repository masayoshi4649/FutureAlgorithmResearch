"""追加担当の利益回転と再参加を比較する事前固定条件。"""


def configurations():
    """
    機能: 原仕様からの一要素対照と構造的な組合せを返す。
    引数: なし。
    返り値: list[dict]は追加担当最大3枚に適用する固定16条件。
    """
    base = dict(exit_unit=0, activation=1.25, trail=.75, partial_at=0.,
                rotate=False, reenter=False, reentry_wait=120., flip=False,
                regime=False, profit_fraction=0., high_only=False, flow=False,
                pullback=.75, rebound=.25, confirmation=15., fee10=0)
    definitions = [
        ('V00', 'TG04原追加・手数料0', {}),
        ('V01', '広い初回幅で保護だけ早期化', dict(activation=.75, trail=.5)),
        ('V02', '初回損切りと短期利益追尾の幅を分離', dict(exit_unit=1, activation=1., trail=.75)),
        ('V03', '利益幅だけ160ptを上限', dict(exit_unit=2, activation=1., trail=.75)),
        ('V04', '半分利確と残りの広い短期追尾', dict(exit_unit=1, activation=1., trail=1.5, partial_at=1.)),
        ('V05', '半分利確後に押し戻りを待って回転', dict(exit_unit=1, activation=1., trail=1.5, partial_at=1., rotate=True)),
        ('V06', '全利確後の状態再確認・時刻待ちなし', dict(exit_unit=1, activation=1., trail=.75, reenter=True, reentry_wait=0.)),
        ('V07', '全利確後60秒と状態再確認', dict(exit_unit=1, activation=1., trail=.75, reenter=True, reentry_wait=60.)),
        ('V08', '全利確後300秒と状態再確認', dict(exit_unit=1, activation=1., trail=.75, reenter=True, reentry_wait=300.)),
        ('V09', '全利確後900秒と状態再確認', dict(exit_unit=1, activation=1., trail=.75, reenter=True, reentry_wait=900.)),
        ('V10', '全利確後の押し戻り再参加と確認ドテン', dict(exit_unit=1, activation=1., trail=.75, reenter=True, reentry_wait=60., flip=True)),
        ('V11', '継続効率による広保持と回転の切替', dict(exit_unit=1, activation=1., trail=1.5, partial_at=1., rotate=True, reenter=True, reentry_wait=60., flip=True, regime=True)),
        ('V12', '最高利益の60%保護と40pt以上の戻り許容', dict(exit_unit=1, activation=1., trail=.75, profit_fraction=.6)),
        ('V13', '広い帯と短期幅が乖離した時だけ回転', dict(exit_unit=1, activation=1., trail=1.5, partial_at=1., rotate=True, high_only=True)),
        ('V14', '回転再投入に二市場の短期と板支持を要求', dict(exit_unit=1, activation=1., trail=1.5, partial_at=1., rotate=True, flow=True)),
        ('V15', '回転玉利確と60秒再参加と確認ドテン', dict(exit_unit=1, activation=1., trail=1.5, partial_at=1., rotate=True, reenter=True, reentry_wait=60., flip=True)),
    ]
    return [dict(base, **changes, id=code, name=name) for code, name, changes in definitions]


SPECIFICATION = {
    '基本比較': 'CG04基本5・CS04別入口2を手数料0で再構成して固定。追加担当3の変更を合成し片側10以内。全50場の全注文を保存。',
    '短期利益単位': '新規の判断時点で既知のATRからmax(80pt,min(元R,1.5ATR))を固定。ATR不明時は元R。固定160pt上限案はmax(80,min(R,160))。初回損切りRと入口条件は維持。',
    '部分利確': '短期単位の1倍順行で、利益が残る玉から合計保有の半数切捨てを返済。1枚は部分返済しない。返済は次の正常気配。通常追撃は部分利確後停止。',
    '回転': '部分利確後に利確時基準から有利な押戻り0.75単位を観測し、その極値から0.25単位再加速・自己30/120秒支持15秒を確認して1枚追加。直前利確価格より不利な再取得は拒否。最大3枚・初回の損失予算を維持。追加玉自身の1単位利益で利益玉1枚だけ返済し再武装する。',
    '全退出後': '黒字全退出の後だけ、待機0/60/300/900秒と押戻り0.75単位＋再加速0.25単位＋短期支持15秒を要求して同方向へ再参加。損切り後は元の120秒/連敗900秒停止。将来の入口・終値を使わない。',
    'ドテン': '全退出後に自己5分差・120秒差が逆向き、現在価格が公開MA20の逆側、自己30秒も逆を15秒確認した場合に新しい親として反対新規。既存玉の返済約定前に逆新規はしない。',
    '状態選択': '当時公開40分効率>=0.35なら元の広い利益保持と追撃を維持。効率<0.35は短期利益保護・部分回転。状態は親の初回判断で固定。全日高低ラベルは売買入力にしない。',
    '高幅限定': '新規時R>=2.5×max(80pt,ATR)の親だけ短期保護と回転。それ以外は元追加担当。',
    '板条件': '回転時に自己・相手30/120秒が方向支持し、自己OFI30秒と相手OFI30秒も方向支持。相手は厳密過去15秒以内のみ。',
    '費用と執行': '最新指定で手数料0。気配差と判断後の次正常原行BBOは維持。全日取引・元玉・回転玉・反対玉の損失をすべて計上。場末は元15:35/05:50判断。',
}
