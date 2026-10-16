"""元E01を変えず、待機指値と成行の気配約定だけを比較する固定仕様。"""

from bridge import ROOT, read


CASES = (
    dict(id='L_D20_BBO', execution='気配指値', offset_atr=.2),
    dict(id='E01_G_U_BBO', execution='気配成行', offset_atr=0.),
    dict(id='L_D20_PRICE', execution='旧現在値参考', offset_atr=.2),
)
VALUE = {'TOPIX': 1000., 'NK225': 10.}
FEE = {'TOPIX': 41.8, 'NK225': 11.}
QUANTITY = {'TOPIX': 5, 'NK225': 10}
CAP = {'TOPIX': 10, 'NK225': 20}


def specification() -> dict:
    """
    機能: 元の条件と今回の約定差分を数値で確定する。
    引数: なし。
    返り値: dict。将来利益・特定日時から調整しない。
    """
    old = read(ROOT / 'work/wave_v85/prepared/入力準備の完了.json')
    sessions = old['全30'] + ['2026-10-12_Day', '2026-10-12_Night', '2026-10-13_Day']
    assert len(sessions) == 33 and sessions == sorted(sessions)
    return dict(条件=list(CASES), 全33=sessions, 前16=sessions[:16], 後17=sessions[16:],
        紙上条件=dict(id='E01_G_U', mask=1, time_mode='U', changes={}),
        初回枚数=QUANTITY, 片方向上限=CAP, 円倍率=VALUE, 片道料金=FEE,
        指値='紙上新規行で固定ATRの0.2倍有利にtick丸め。公開当行は約定不可。以後最初の正常気配で買ask<=線/売bid>=線なら当該ask/bidで約定。',
        成行='紙上新規行より後の最初の正常気配で買ask/売bid。',
        返済='紙上GU返済行より後の最初の正常気配で返済。未約定新規は最初の紙上返済で永久取消。',
        参考='旧round12のL_D20 CurrentPriceによる到達/返済/時価をそのまま使用。',
        同行順序='既知休止と期限が先。次に前行予約返済、待機指値、新しい紙上注文。到達と紙上返済が同じ行なら約定を保持し返済は次正常気配。',
        時価='BBOは買玉bid・売玉askで清算時価、気配不正時は直前正常気配を保持。',
        紙上共有='各66口座で元GUを1回だけ計算。紙上判断は実際の約定や費用から独立。',
        料金='注文別にfloor(枚数×片道料金)、新規と返済の双方。部分返済の注文も個別に切捨て。',
        時間='原CurrentPriceTime・原行順。元price-lag/足公開+120秒/NY開始前後15分U休止を保持。受信時計ではない。',
        比較限界=['全33は既知データ。未知データの成功証明ではない。',
                    'ラージ板の気配をミニ/マイクロ取引価格代理として使用。実商品板・板数量・指値列順と部分約定を再現しない。',
                    '一度の遅延仮定を今回は加えない。待機指値の到達と成行の次気配を区別する。'],
        再検証理由='既存30のCurrentPrice指値成績をBBOで修正比較し、追加3場を条件不変で接続する。新規パラメータ探索ではない。')
