"""時計の取消と再準備を、正式な新損益を見る前に有限仕様へまとめる。"""

import hashlib
import json
from pathlib import Path

import catalog

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path: Path) -> dict:
    """
    機能: 前段で完了した原因又は評価条件を読む。
    引数: path(Path)は日本語JSON。
    返り値: dict。売買入力には使用しない前段の設計根拠。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 仮説がどの原因及び旧仕様に基づくかを保存する。
    引数: path(Path)は参照資料。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path: Path, value: dict) -> None:
    """
    機能: 新正式損益前の仕様だけを作業領域へ保存する。
    引数: path(Path)、value(dict)。
    返り値: None。既存の固定又は正式損益があれば停止する。
    """
    assert path.parent == HERE and not (HERE / '事前固定.json').exists()
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main() -> None:
    """
    機能: 四政策の状態順序と比較条件、未検証の課題を明示する。
    引数: なし。
    返り値: None。ソースと独立検査の凍結は合格した後の別段階で行う。
    """
    paths = [HERE / 'catalog.py', HERE / '98実装前の独立設計整理と未確定事項.json',
             HERE / '公式仕様の時計項目と保存原本の区別.json',
             HERE.parent / 'wave_v97/事前固定.json',
             HERE.parent / 'wave_v97/entry_support/A7の10秒gap全原本時計と保持seq及び同clock実板変化の独立診断.json']
    plan = dict(
        前の目標ターン='進捗。97全36全31を独立検算し00093へ公開。価格時計gapの139取消と同clockの板変化を原本で確認。安定解は未達。',
        仮説='価格公表時刻の10秒超を受信断裂と同じに扱うと、観測可能な板経路を捨てる。取消だけを除く、各源の観測更新を読む、gap後に再確認する対照で、活動と実建値及び実損失がどう変わるか測る。保持すれば勝てるとは仮定しない。',
        予定条件数=34, 理論主=catalog.PRIMARY, 対照=catalog.CONTROL,
        組合せ='C0/C1/C2/C3 × A1/A3/A5/A7 × X1/X3の32条件、即時A0_X1/A0_X3の2対照。全条件のprevious_idは旧97対応ID。',
        入口一覧=dict(A1='価格幅なしで両BBOの進行確認', A3='元候補気配から1W順行＋両BBO',
                      A5='観測した不利extremeから半W回復＋両BBO、初回の押しは必須でない',
                      A7='ランニング有利peakから1W押しを経験後、現在不利extremeから半W回復＋両BBO'),
        出口一覧=dict(X1='初期停止0.1%、常時追尾0.4%、実新規から通常30分で返済判断。',
                      X3='初期停止0.1%、常時追尾0.4%、2S順行後に手数料込み建値床。通常期限なし。'),
        出口選択の根拠='初期停止S及び常時追尾幅を揃え、旧前16参考X1と旧主X3の両方で入口政策を測る。後の34条件結果から出口を選んで遡及表示しない。時間制限と利益床は既存の複合出口として別に表示する。',
        幅='Wは保存ref_open0.1%を最低2呼値へ切上げ、出口Sと独立。半W等は最低1呼値切上げ。候補ID・quote・時刻・方向・W・TTLを保存。旧候補、密なJ2、OFI、Q、peer選択を変更しない。',
        C0='97完全対照。旧gap取消を含む優先順cut→TTL→gap→reset→qok→硬い反対を保持。新しいseq欠番取消やclock故障判定は加えない。',
        C1='既存watch及び新受理直後のgap取消だけを除去。gap行の発注禁止や再基準を追加しない。他の幾何、源資格、fallback、期限は旧通り。観測gapは別診断へ保存するが有効cancel_flagsへは混ぜない。',
        C2='C1に各自anchor基準の源確認を加える別意味の対照。両index/seqが各anchorより厳密増加し、各clockは各anchor以上。両clockが共通phase後という旧要件は外す。現在正常pair・peerclock<=自己now・両bidask各1tick進行・i>phase_rowは保持。未知anchorの最初正常pairはi>phase_rowかつ自己clock>=phase_timeで基準だけ作る。peer>phaseは不要、基準作成同行では触発しない。',
        C3='C1にgap後だけの別epoch再準備を加える。reset又は自己qok不正は旧通り取消する。gap行でpause、元候補及び元TTLと予約枠を保持し、価格幾何の更新を止める。epochの自己現原行及び公開peerを別基準として保存する。gap再発でepochを更新してもTTLは延長しない。',
        C3未知基準='epoch時のpairが未知なら、後続の双方clock>epochである最初正常pairはepoch基準だけ作る。元epoch時刻を移動せず、その行では再準備しない。以後両index/seq及び時計が各epoch基準から更新される必要がある。',
        C3再準備='epochより後の行で、正常pair、quality、非reset、現在J2同方向、双方index/seqがepoch基準より増加、双方clock>epochかつ各基準clockを確認する。方向気配進行自体は再準備に必要ない。現在quoteを局所peak/extremeへ設定、A7の押しarmを解除しBBOphaseを当該行へ更新する。再準備行は発注禁止。A3の候補からの順行尺度は元candidate_quoteを保持する。',
        C3新候補='gap行で新候補を受理しても同じepoch休止を開始。gap前からwatchがあった場合だけへ限定しない。行頭でwatchがあれば、取消や再準備後の同行新候補は消費して復活しない。',
        C1以降の取消優先='cut→TTL→reset→qok不正→両300秒既知の硬い反対。これらがない場合だけgap保持又はpauseを処理。片側弱化、未知OFI/peer、未来peerは支持へ変えず新規停止。旧quality不正時にも発注しない。',
        時計の限界='CurrentPriceTimeは受信時計ではない。保存原seqは商品内保存順であり通信完全性及び二市場の共通受信順を証明しない。旧公表代理時刻・厳密過去peerの仮定内で再生し、同時計末尾や未来源を救済に使わない。TTL300は代理時計上の期限であり実受信経過を証明しない。',
        冗長性='peer_clock>phaseかつpeer_clock<=own_nowならown_now>phaseは必然。自己時計だけseqへ替える同値の枝を別改善と数えない。C2は共通phase後という証拠も変えるためC1と別の解釈として評価する。',
        約定と数量='全条件TOPIXmini8枚・NK225micro16枚。片方向上限10/20。触発後の次正常自己BBOで買ask/売bidへ全量仮想約定。市場予約へ移る前にwatch枠解除、占有二重なし。初期停止・peak・床・期限は実新規から設定する。',
        費用と終了='片道TOPIXmini41.8円・NKmicro11円を注文別切捨。倍率1000/10。返済後30秒から新候補。保存上の運用区切り60秒前に全返済判断、保存終端で全清算。実取引所終了と運用区切りは別。全原板で残玉の返済気配と返済料金を含む清算時価を評価。',
        評価='全31は既知再探索。前16の参考を後15損益前に固定するが未知性能ではない。両商品20親・8活動場の研究活動条件、両費用後黒字、金額利益80%・損小利大、大勝ち除外を残す。共通上限10/20及び全評価場数を分母にし、悪い側の下方偏差・活動黒字率・最大赤字・下位25%を優先。',
        分解='同じ元候補の実建値差、返済差、費用差、旧勝ちの取り逃し、旧負けの回避及び新固有候補を分離する。保持又は新源確認で活動が増えて損失も増え得る。無取引は勝ちへ含めない。',
        必要検査='全34の意味人工と政策境界・買売反射、対応する旧十条件全620口座の旧18配列null、原本からの実接頭及び未来変形、独立局所反証、人工共通CLIの全8期間集計と保存終端。正式後は全2108口座・544商品期間の会計、全原板清算時価と政策が異なる代表の最初触発及び全経路を独立検算。',
        未検証='C4の深板/出来高故障と価格経路故障の分類、真受信時計による二市場同期、現在セッション及び未知期間の安定性は今回未測定。C4は旧Q/OFIを救済せず原本の品質分類と素材再生成を要する別入力仮説であり、今回の時計一軸結果で否定しない。',
        正式新条件売買実行=0, API取得=0, 実注文=0,
        設計根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths},
    )
    save(HERE / '結果前の設計案.json', plan)
    stable = read(HERE.parent / 'wave_v97/セッション安定性の事前評価.json')
    stable.update(固定時点='34条件の正式新損益前。',
                  主の扱い='C1_A7_X3の事前主は前16参考又は全31の事後診断へ差し替えない。',
                  配分='全34条件でTOPIXmini8枚・NK225micro16枚。',
                  入口の追加評価='政策の一軸対照、同出口即時の同候補実建値差、活動増減、旧勝ち/負けの消失と新固有損益を分ける。')
    save(HERE / 'セッション安定性の事前評価.json', stable)
    print(json.dumps(dict(予定条件数=34, 理論主=catalog.PRIMARY, 正式新条件売買実行=0), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
