"""現在支持の観測源だけを替える仮説と安定性の評価を、新しい正式損益前に保存する。"""

import hashlib
import json
from pathlib import Path

import catalog

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path: Path) -> dict:
    """
    機能: 前段の原因と既存評価条件を読む。
    引数: path(Path)はJSON資料。
    返り値: dict。売買入力に使わない設計根拠。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 結果前に参照した前段資料の同一性を残す。
    引数: path(Path)は資料。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path: Path, value: dict) -> None:
    """
    機能: 正式損益が未作成の段階で仕様を保存する。
    引数: path(Path)、value(dict)。
    返り値: None。正式固定又は損益が既存なら保存しない。
    """
    assert path.parent == HERE and not (HERE / '事前固定.json').exists()
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main() -> None:
    """
    機能: 観測不明と実方向反転を分ける有限比較と評価の優先順を保存する。
    引数: なし。
    返り値: None。新しい正式売買又は現在API取得は行わない。
    """
    old = HERE.parent / 'wave_v98'
    paths = [HERE / 'catalog.py', old / '事前固定.json',
             old / 'review/3正式レビューと追加門番診断の独立原因要旨.json',
             old / 'report/次段の入口観測源案.json', old / 'report/公開結果.json']
    cause = read(paths[2])
    assert cause['全合格'] and cause['両商品金額80'] == []
    plan = dict(
        前の目標ターン='進捗。98の全34条件を全31場で再生し独立検算。00094へ全場損益を公開。安定解は未達。',
        仮説='旧の日経300秒気配中値窓が観測不明なため、TOPIXの押し回復成立点も現在方向支持を得られなかった。独立した取引価格で現在支持を確認すれば、同じ待機機構の測定範囲が変わる。増えた取引が勝つとは仮定しない。',
        予定条件数=34, 理論主=catalog.PRIMARY, 対照=catalog.CONTROL,
        組合せ='L0/L1×C0～3×A1/A7×X1/X3の32条件と、不変の即時A0_X1/A0_X3の2対照。',
        一軸='L0は旧mid300秒による現在J2、L1は既存I3独立LPのtrend_lp_allowed。現在方向支持の2列だけをplay時の浅いコピーへ接続する。C3再準備にも同じ支持列が作用する。',
        L1='両市場の旧execution current.valid、独立LP current.validと有限正値、LP300秒source_validと有限変化率を要求。判断方向の変化率は双方正、弱い側は強い側の25%以上。十分観測された旧15秒OFIが判断と逆へ0.1以上なら除外。未知OFIを支持へ変えない。',
        固定する部品='元候補P0/J8、時計政策C0～3、両BBO進行、未知peerの基準作成、Q/OFI品質、硬い反対取消、待機幾何、TTL、予約競合、次正常BBO約定、出口、数量を98から変更しない。',
        硬い反対='旧mid300秒の双方3bp以上反対という取消は固定。L1支持と競合した場合も旧取消が先で、新支持が取消を救済しない。',
        即時対照='A0二条件はL0のままで診断列も旧と同じ。新しい支持列を無意味に接続してnull対照を変えない。',
        源の分離='独立LPの公表格子/index/rawseq/timeと、旧BBOの源を別に記録。LPの時刻や価格をBBOのextremeや回復量へ投影しない。源が不明なら不参加。L1はL0の上位集合ではなく旧の勝ちも消し得る。',
        入口='A1は両気配各1呼値進行。A7は局所有利極値から1W押した後、不利極値から半W回復と両気配進行。Wは始値0.1%を最低2呼値へ切上げ、半Wを最低1呼値へ切上げ。待機300秒。',
        出口='X1は初期停止0.1%、常時追尾0.4%、実新規から通常30分で返済判断。X3は同じ初期停止と追尾、2S順行後に費用込み建値床、通常期限なし。停止線は不利へ戻さない。',
        数量費用と終了='全条件TOPIXmini8枚・NKmicro16枚、片方向上限10/20。買ask/売bidへ次正常気配で仮想約定。片道41.8円/11円を注文別切捨、倍率1000/10。返済後30秒から再参加。運用区切り60秒前から返済判断、保存終端で全清算。',
        時間制約='既存のCurrentPriceTime代理公表順、厳密過去の格子・peerを保持。真受信時刻と両市場共通受信順は原本にない。実受信の因果順を保証したとは呼ばない。',
        評価='最大収益より赤字額と毎場の黒字率を優先。前16で20親/8活動場を要求し、費用後両黒字・金額利益80%・損小利大・最大利益日除外を残す。安定順は悪い側の下方偏差→活動黒字率→最大赤字→収支下位25%→利益割合→ID。無取引は勝ちにしない。全31既知で未見検証ではない。',
        原因分解='同じ元候補で建値差・返済差・費用差を分離。旧勝ちの取り逃し/旧負けの回避/新固有親を区別。取引激減だけを改善と呼ばない。',
        必要検査='全34人工、旧18対照1116口座の20配列と全経済null、L0/L1の資格正負とC3再準備、未知/逆OFI/硬反対、実接頭と自己相手未来不変、独立人工CLI全8期間集計と保存終端。正式後は全2108口座と544商品期間の会計を独立検算。',
        未検証='真受信時計、実注文、未知セッション、LP以外の品質救済、硬反対をLPへ替える別軸、数量配分変更は未測定。',
        正式新条件売買実行=0, API取得=0, 実注文=0,
        設計根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths})
    save(HERE / '結果前の設計案.json', plan)
    stable = read(old / 'セッション安定性の事前評価.json')
    stable.update(固定時点='99の34条件の正式新損益前。',
                  主の扱い='L1_C1_A7_X3の事前主を、前16参考又は全31の事後診断へ差し替えない。',
                  入口の追加評価='現在方向支持の一軸と、同候補建値差・旧勝負の消失・新固有損益・活動減少を分ける。')
    save(HERE / 'セッション安定性の事前評価.json', stable)
    print(json.dumps(dict(予定条件数=34, 理論主=catalog.PRIMARY, 正式新条件売買実行=0), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
