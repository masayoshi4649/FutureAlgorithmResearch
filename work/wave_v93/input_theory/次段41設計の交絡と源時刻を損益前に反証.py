"""次段41対照の入力・新規・停止・利確を混同しない事前反証を保存する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DESIGN = ROOT / 'work/wave_v94/結果前の設計案.json'


def fingerprint(path: Path) -> str:
    """
    機能: 読み取った事前設計又は理論の内容を識別する。
    引数: path (Path)。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artificial_logic() -> list[dict]:
    """
    機能: 源番号混同、機会の後付け再評価、中心出口の利益保証を人工数値で反証する。
    引数: なし。実市場損益を参照しない。
    返り値: list[dict] は人工仕様反例。
    """
    price = {'原seq': 7, '配列位置': 6, 'clock': 10., 'LastPrice': 100., '最良正常': False}
    quote = {'原seq': 8, '抽出位置': 4, 'clock': 10., 'bid': 100., 'ask': 101., '最良正常': True}
    assert price['原seq'] != quote['原seq'] and price['配列位置'] != quote['抽出位置']
    center, decision_ask, next_ask = 101., 100., 102.
    assert center > decision_ask and center < next_ask
    next_bid = 101.
    assert next_bid - next_ask < 0
    consumed = False
    first_eligible = False
    if not first_eligible:
        consumed = True
    later_eligible = True
    assert later_eligible and consumed
    place_second_same_episode = later_eligible and not consumed
    assert not place_second_same_episode
    return [
        {'ケース': '価格源と執行気配源が同clockでも別原seq', '価格源': price, '気配源': quote,
         '正しい仕様': '両源の種類と原seqを別保存。価格current配列位置を旧quote配列位置として使用しない。', '人工合格': True},
        {'ケース': '判断時は利益側中心でも次成行が中心を通り越す',
         '中心': center, '判断買ask': decision_ask, '次新規ask': next_ask, '次返済bid': next_bid,
         '正しい仕様': '旧中心を書替えず次観測から出口を評価。中心到達という理由でもnet負は損失。入口をT1だけに追加制限しない。', '人工合格': True},
        {'ケース': '最初回復でG1不合格後に現在窓が回復', '初回合格': first_eligible, '後行合格': later_eligible,
         '同エピソード再評価で新規': place_second_same_episode,
         '正しい仕様': '新しい旧仮説解除と新準備を要求。後から初回採否を変えない。', '人工合格': True},
        {'ケース': 'LP正常・BBO不正', '価格窓の資格': True, 'その行の約定資格': False,
         '正しい仕様': '現在価格の分類に使えてもそのLPでは約定しない。回復witnessと実注文価格は正常BBOで別判定。', '人工合格': True},
        {'ケース': 'BBO正常・LP不明', 'LP価格窓の資格': False, '最良価格の資格': True,
         '正しい仕様': 'G1/G2のLP分類へ前LPやmidを代用しない。S1のBBO停止と既知場末の返済は独立の観測資格を保持。', '人工合格': True},
        {'ケース': '遠段異常の後だけ旧flow初期化bit1', '旧flow初期化': True, '新価格の実初回': False,
         '正しい仕様': '新価格resetを独立の実初回/clock/原行状態から作り、flowのbit1を丸ごとコピーしない。', '人工合格': True},
        {'ケース': '価格格子確認が進んでもBBO極値形成源は未更新', '価格源更新': True, 'BBO回復源更新': False,
         '正しい仕様': 'LP源更新をpeerのmid回復更新へ代用しない。価格mode確認と回復確認の源を別に保存。', '人工合格': True},
        {'ケース': 'LastPrice変位正常でも一方向ERが高い', '入力有効': True, '低ER往復': False,
         '正しい仕様': 'G1は可観測性を通過できるがG2は通過しない。観測可能性を逆張り成功確率へ混同しない。', '人工合格': True},
    ]


def main() -> None:
    """
    機能: 根の41設計だけを読み、仕様不足と人工反例を次段損益前に保存する。
    引数: なし。
    返り値: None。新93のinput_theory以外を変更しない。
    """
    design = json.loads(DESIGN.read_text(encoding='utf-8'))
    assert design['基本対照数'] == 3 * 3 * 2 * 2 == 36
    assert design['予定合計条件数'] == 41
    assert design['新条件損益閲覧'] == design['新条件売買実行'] == 0
    cases = artificial_logic()
    value = {
        '段階': '次段の設計だけを損益前に敵対評価。41候補の実装又は有用性を認定していない。',
        '設計': str(DESIGN.relative_to(ROOT)), '設計SHA256': fingerprint(DESIGN),
        '主案': 'I2_G1_S0_T1', '予定条件数': 41,
        '論理評価': '正常LPを価格分類へ使い、次正常BBOで実行する分離は許容。現在の観測可否、新規、停止、目標を直積で固定し、rho2/N4を外して旧C00を基点にするため、93主との比較だけで単独効果を誤認しない設計である。',
        '最優先の仕様不足': [
            'price_currentとquote_currentについて、入力チャンネル種別・配列位置・原本rawseq・CurrentPriceTime・資格・ageを全て別保存する。異なる配列のindexを直接比較しない。',
            '価格modeの持続確認は新価格源rawseqとclockで行い、回復witnessの自己/peer極値と更新は旧正常BBO源で行う。price sourceをpeer_mid又は極値源へ代入しない。',
            '旧共同方向ガードをI1/I2でどの価格源から計算するか固定する。価格分類を新LPへ替えたのにwatch解除だけ旧mid commonを使うなら、残す旧ガードと新price commonを別名で保存し明記する。',
            'G1の300ERには両市場の正の総変動、current/30/300変位/180範囲の資格が必要。G2はG1に含まれた可観測性に加えて、元と同じ確認済みmode2を要求する。raw Trueだけ又は無効によるmode0へ置換しない。',
            '最初の双方回復成立でG1/G2を一度だけ判定。不合格で同エピソードを消費し、後のLP正常化から同じ回復へ入り直さない。決定済み注文を未来の再判定で消さない。',
            'T1にだけ利益側中心の新規ゲートを暗黙追加しない。旧中心が判断気配又は実新規より利益側に無くても、中心を後付け更新せず、実net負の中心返済を損失へ計上する。中心余地ゲートを加えるなら別入口対照が必要。',
            '正常LPが追加raw行で観測できても、第一段の新規/出口/約定観測列は旧抽出行に固定する。LP追加行で停止を早める変更は別の出口観測対照へ置く。',
            '新LPで最初の観測点が早くなっても、幅の旧始値とknown_from原seqを暗黙更新しない。始値更新は別軸で、当段では旧の観測済み始値幅を保持する。',
            'I1の価格端点spread上限とage上限を事前に明示する。最良正常と狭いspreadは別資格で、旧2呼値上限を変更するなら入力源正常性だけの効果と扱わない。',
            '限月/銘柄識別は実際の原キーだけで検査。キーが無ければ推定して検査済みとしない。場単位ファイルの境界は履歴を切断するが、未記録の場内限月変更を検出したとは言わない。'],
        '前提が外れる反例': [
            '正常LastPriceは直近約定の値であり今の実買ask/売bidでない。LPの上昇後に既にaskが上がっていれば、見込み利益の大半が取得価格へ消費される。',
            'LPは変化が少ない又は出来高薄い市場で、midと異なる総変動ERになる。LPの観測可能性が高いことは均衡復元や低リスクを保証しない。',
            'CurrentPriceTimeが動かない間にも板は変わる。現在の受信時計が無ければ、時計が古いのは無約定か受信欠測かを判別できない。age上限を緩めて解決したとは扱わない。',
            '古い中心を現在の観測が可能な時だけ使っても、中心自体が今の均衡と一致する証拠にはならない。G1が通ってもG2は非往復になり得る。',
            '狭い極値停止を外せば以前救えた勝ちもある一方、1幅まで負けが増えて中心より先に止まる親もある。入力改善とこの出口変化は独立差で読む。',
            'G2がほぼ無取引になることもある。0収支・損失なしを安定成功にせず、活動数と逃した勝ちを掲載する。',
            '配分源の実際の金額割合は各親G/Lの加重平均。弱い源を追加すれば平均負け親金額が小さく見えても、合計PF又は収支が改善するとは限らない。'],
        '実装人工検査': cases,
        '正式前に必要な対照': {
            '旧完全一致': 'I0_G0_S0_T0→旧C00、I0_G0_S1_T0→旧C01、旧追従8/10及び追加C11を全31で全注文/親/全行清算へ一致させる。',
            '単一軸': '入力だけは同G/S/T、入口だけは同I/S/T、停止だけは同I/G/T、目標だけは同I/G/Sで比較する。最終統合との差を単独効果へ割当てない。',
            'Q_F独立': 'I1/I2でも旧OFI/Q/補充の源と値と正常性は不変。LP正常を不明OFI0へ替えない。',
            '価格正常': 'I1の全正常人工列は旧mid列へ一致。I2のLP列は原本全seqと時計・値へ一致し、LP不正・clock/seq不明を補完しない。',
            '未来不変': '原行prefix、同clock後続毒入れ、自己未来価格、相手未来価格、旧Q/F未来値の変更で過去の各sourceとゲート・予約が不変。',
            '源同時性': '異なる源の観測は当時公開済みの格子だけ。同clock内の後続をpeerの最新とみなさず、真受信同期とは認定しない。',
            '配分': '追従8と反発2を同枚数単独へ全経済注文/全原板清算まで一致。追加差と同上限置換差、両源赤字と救済を分ける。'},
        'この評価で行っていないこと': ['新41条件の損益閲覧又は売買実行', '93の正式結果又は凍結条件の変更', '新入力の性能認定又は未知データの成功認定'],
        '新条件損益閲覧': 0, '新条件売買実行': 0, '正式実装変更': 0, '正式損益変更': 0,
        'API取得': 0, '実注文': 0, '有用性認定': False,
        '理論コードSHA256': fingerprint(Path(__file__))}
    target = HERE / '次段41対照の源分離と入口出口の交絡の事前反証.json'
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'保存先': str(target), '人工ケース': len(cases), 'SHA256': fingerprint(target),
                      '新損益閲覧': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
