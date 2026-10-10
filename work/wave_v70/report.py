"""全玉の途中管理を、基準・保険なし対照・縮小復帰と短く比較する。"""

import csv
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path

import study

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT/'アルゴリズム調査/00067_両建て保険と途中管理'
MAIN = '両建て保険と途中管理の説明と損益.html'
ALL = '全条件の途中管理比較.html'


def summary(config: dict) -> str:
    """機能: 固定した注文管理を短い日本語へ変換する。

    引数: config(dict)。返り値: 設定説明(str)。
    """
    c = config
    common = f"元玉の損切り{c['stop']:g}呼値、{c['activation']:g}呼値順行で幅{c['trail']:g}呼値の追跡、最長{c['hold_seconds']/60:g}分。"
    if c['paired']:
        return f"{c['paired_manager']}の保険と同じ判断で元玉を縮小・復帰。保険を実際には建てず、仮想保険の状態を監視。"+common
    if c['kind'] in (1,2):
        text = f"逆行{c['grid']:g}呼値ごとに上限の約{c['step_fraction']*100:g}%を逆方向へ追加（端数切上げ、上限厳守）。保険の平均順行{c['cover_activation']:g}呼値で追跡、幅{c['cover_trail']:g}呼値の反転で全保険返済。"
        if c['kind']==2:
            text += f"保険が上限の{c['flip_fraction']*100:g}%以上で入口信号も逆になれば、元方向を返済し保険方向へ1回だけ持ち替える。"
        if c['grid_mode']==1:
            text += '保険がない間はグリッド基準を順行高安へ追従させる。'
        return text+common
    if c['kind']==3:
        return f"{c['partial_level']:g}呼値の順行で約{c['partial_fraction']*100:g}%を一度だけ利確、残りを追跡。"+common
    if c['kind']==4:
        return f"{c['tighten_minutes']:g}分で追跡幅を4呼値、{c['tighten_minutes']*2:g}分で2呼値へ短縮。"+common
    if c['kind']==5:
        return f"順行が{c['ratchet_step']:g}呼値進むごとに保護線をその段階から{c['ratchet_keep']:g}呼値下へ引き上げる。保護線は次の観測から有効。"+common
    return common+f"全玉の損失枠{c['basket_stop']:g}呼値相当、利益保護開始{c['basket_activation']:g}呼値相当。"


def bars(sessions: list[str]) -> dict:
    """機能: 読取専用の五分足を売買図へ接続する。

    引数: sessions(list[str])。返り値: 場と銘柄の五分足(dict)。
    """
    data = {}
    for session in sessions:
        for symbol in study.SYMBOLS:
            with (ROOT/'candle_5min'/symbol/(session+'.csv')).open(encoding='utf-8-sig',newline='') as stream:
                data[session+'|'+symbol] = [[datetime.fromisoformat(r['time']).timestamp(),
                                            *[float(r[k]) for k in ('open','high','low','close')]] for r in csv.DictReader(stream)]
    return data


def weekly(rows: list[dict], sessions: list[str]) -> dict:
    """機能: 場内完結した会計をカレンダー週ごとに集計する。

    引数: rows(list[dict])、sessions(list[str])。返り値: 銘柄ごとの週集計(dict)。
    """
    groups = {}
    for session in sessions:
        day = date.fromisoformat(session[:10])
        monday = day-timedelta(days=day.weekday())
        groups.setdefault(monday,[]).append(session)
    return {symbol:[dict(study.aggregate(rows,symbol,keys),label=f'{monday:%m/%d}週（{len(keys)}場）')
                    for monday,keys in sorted(groups.items())] for symbol in study.SYMBOLS}


def fill(path: Path, data: dict, target: Path) -> None:
    """機能: JSONを安全に一箇所のHTMLへ埋め込む。

    引数: path/target(Path)、data(dict)。返り値: なし(None)。
    """
    source = path.read_text(encoding='utf8')
    assert source.count('__DATA__')==1
    payload = json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    target.write_text(source.replace('__DATA__',payload),encoding='utf8')


def main() -> None:
    """機能: 全監査完了を確認し、三代表と全222の会計・図を生成する。

    引数: なし。返り値: なし(None)。
    """
    assert study.load(HERE/'audit/全条件の独立監査.json')['合格']
    assert study.load(HERE/'audit/追加診断対照の独立監査.json')['合格']
    assert study.load(HERE/'audit/両建てと減玉対照の全行監査.json')['合格']
    fixed = study.load(HERE/'事前固定.json')
    selected = study.load(HERE/'前半選定.json')['代表']
    results = [study.load(p) for p in sorted((HERE/'results').glob('*.json'))]
    controls = [study.load(p) for p in sorted((HERE/'controls/results').glob('*.json'))]
    assert len(results)==192 and len(controls)==30
    lookup = {r['config']['id']:r for r in results}
    ready = study.load(ROOT/'work/wave_v69/prepared/inputs.pkl')
    explanations = {
        '保険両建て':'元玉を満額のまま保有し、逆行が進むたびに反対玉を段階追加する。反対方向の動きが止まり、保険が手数料後で利益の見込みなら保険を返済する。元玉の含み損も成績に含める。',
        '縮小復帰':'同じ保険判断を使い、反対玉を建てる代わりに元玉を減らす。保険を返済するはずの時に元方向を買い戻す／売り直す。ネット枚数は元の両建てと同じで、終端に両建てを解く往復を省く。',
        '利益固定':'反転を検知して満額で入り、4呼値進んだら4呼値の利益を保護する逆指値を準備。その後も4呼値刻みで保護線を引き上げる。小さい勝ちを増やして負けの回数を減らすが、残る大きな負けは解消しない。',
    }
    methods = []
    for choice in selected:
        result = lookup[choice['id']]
        c = result['config']
        method = dict(result,id=c['id'],title=c['name'],configText=summary(c),eligible=choice['eligible'],
                      explanation=explanations[c['group']],baseline=lookup[choice['baseline']],
                      weeks=weekly(result['rows'],fixed['全セッション']))
        h = c['source']+'_'+(c['paired_manager'] if c['paired'] else c['manager'])
        method['control'] = next((r for r in controls if h in r['config']['matched_Hids']),None)
        ledger = study.load(HERE/'ledgers'/(c['id']+'.pkl'))
        method['orders'] = {'|'.join(key):[list(o)+[float(ready[key]['time_s'][int(o[0])])] for o in account['orders']]
                            for key,account in ledger.items()}
        methods.append(method)
    notes = [
        '主要探索は6入口×32管理=192条件。前16だけで物理保険首位・同判断の縮小復帰・その他首位を選択、後12で選び直さない。全三代表が両銘柄黒字かつ平均勝組／負組損益比>1という採用条件を満たさない。',
        '追加30は損失枠を対応保険と揃えた無保険の原因診断。初192の結果を見た後に追加し、採用の選定に使用していない。',
        '基準B00の元玉stopは16呼値、H03/N03は32呼値。基準との差には幅変更も含む。同条件・保険だけなしD32との差が、保険有無の切り分けになる。',
        '同じ初回の時刻・方向・満額数量。初回fillから3630秒は全管理で次の親予約を待つ。共通60分枠の管理単独比較で、00066や旧E01/R01の通し運用を再現した結果ではない。',
        '一組は共通入口から管理を終了するまで。縮小復帰は途中で実玉が0枚になっても仮想保険の状態を監視し、同じ組で復帰する場合がある。途中の0枚を成功で組終了とはしない。',
        '初回TOPIXミニ10枚・日経マイクロ20枚。逆方向もそれぞれ10枚・20枚まで、合計は20枚・40枚まで。25%追加は端数を切り上げTOP3枚・NK5枚。残量は上限までに制限。',
        '買いask・売りbid。判断した次の有効原本行で仮想約定し、IFD子は新規の次観測から監視。保険集約トレールも追加した当行には監視しない。保護線の変更は次観測から有効。',
        '価格幅は参照ラージの呼値。TOPIX0.5pt・日経10円。子の基準は親予約時の価格で、部分利確後も維持。持ち替え時は新方向へ基準を付け替える。',
        '保険利確は判断時の利益見込みを要求するが、約定は次行なので実決済が損失になる場合も記録する。保険だけの高い勝率を全体の成績としない。',
        '料金は片道TOPIXmini41.8円・NK225micro11円／枚、新規返済の1注文合計を1円未満切捨て。部分明細へ新規／返済料金を累積切捨て差分で配賦。収支へ既に含めている。',
        '両方向の全玉をそれぞれ返済気配へ時価評価。セッション末は全返済。利益玉の利確だけを取り上げず、元玉と保険玉の全損失・全料金を含める。',
        '保存28場は既知。未来切断・改変、共通満額初回、部分料金とFIFO、全原本行時価、前半順位を独立照合済み。将来の収益性を証明する未知検証ではない。',
        '参照ラージの板をミニ／マイクロの仮想約定へ使う。実商品の板、数量による価格悪化、通信・取消競合は再現していない。板受信時計でなく最終約定時計を使用。',
        '追加診断の補充反転・無保険2設定は同じ売買となり全28でTOP+234,068円／NK+1,840円。NKは14組、前半は−78,640円、平均勝組／負組比はTOP0.85／NK0.76。選定外であり損小利大未達。',
        '未検証：保険玉ごとの独立トレール、損失保険の早切り、分割利確後の再増玉、取消照合を含む実時間執行。今回32管理で全てのテクニックを否定しない。',
        '現在API取得0、実注文0。保存データだけで管理を比較。App/E01・過去の成果・元データは変更していない。',
    ]
    source_notes = ['T1L1：中値8呼値の進行後に4呼値戻り、両気配も反転。',
                    'T2L0：中値4呼値進行→2呼値押し→2呼値戻り、両気配も再開方向。',
                    'T3L1：強い表示回復と接近後の中値4呼値反転、両気配も反転。補充は表示回復の代理。',
                    'T4L0：表示回復価格の2呼値突破、両気配進行・OFI一致。',
                    'E01P/R01P：旧ATR・EMA入口状態の開始／方向変更パルス。旧台帳の入口行は使わず、旧アルゴ全体とは呼ばない。']
    data = dict(title='両建て保険と途中管理の説明と損益',sessions=fixed['全セッション'],methods=methods,
                bars=bars(fixed['全セッション']),notes=notes,sourceNotes=source_notes,allUrl=ALL,
                conclusion='入口だけでなく、段階両建て・縮小復帰・持ち替え・分割利確・幅短縮・利益固定を32管理で比較しました。利益固定は負け組の損失合計を約36〜38%減らしましたが、主要192条件では両銘柄黒字になりませんでした。')
    OUT.mkdir(parents=True,exist_ok=True)
    fill(HERE/'report/template.html',data,OUT/MAIN)
    all_results = []
    for r in results+controls:
        all_results.append(dict(r,id=r['config']['id'],configText=summary(r['config'])))
    fill(HERE/'report/all_template.html',dict(title='全192管理条件と追加30診断対照',sessions=fixed['全セッション'],
          methods=all_results,selectedIds=[c['id'] for c in selected],mainUrl=MAIN),OUT/ALL)
    study.save(HERE/'公開会計.json',dict(主要条件=192,追加診断=30,代表=selected,
                                      主HTML_SHA256=hashlib.sha256((OUT/MAIN).read_bytes()).hexdigest(),
                                      全条件HTML_SHA256=hashlib.sha256((OUT/ALL).read_bytes()).hexdigest()))
    print('00067の主HTML・全222条件HTMLを生成:',OUT)


if __name__=='__main__':
    main()
