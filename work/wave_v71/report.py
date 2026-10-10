"""入口のみ・幅のみ・両方の変更を短い説明と全場損益で比較する。"""

from datetime import date,timedelta
import hashlib
import importlib.util
import json
from pathlib import Path

import study

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00068_入口確認とトレーリング幅拡大'
MAIN='入口確認と幅拡大の説明と損益.html'
ALL='全432条件の比較.html'
SPEC=importlib.util.spec_from_file_location('旧レポート71',ROOT/'work/wave_v70/report.py')
OLD=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(OLD)
GATES=['元の入口','直近4中値イベントの両気配前進を確認','両気配に加え16中値イベントの直進性とOFIを確認','両市場の一致も確認（代理時計の参考）']


def summary(config: dict) -> str:
    """機能: 入口・元玉・保険の幅を区別して日本語へ変換する。

    引数: config(dict)。返り値: 短い説明(str)。
    """
    c=config
    text=f"{GATES[c['gate_level']]}。元玉は{c['activation']:g}呼値順行で追跡開始・幅{c['trail']:g}呼値、保険は平均{c['cover_activation']:g}呼値で開始・幅{c['cover_trail']:g}呼値。"
    if c['method']=='D':
        text+='保険は建てない。'
    elif c['method']=='N':
        text+='保険の新規／返済を元玉の縮小／復帰へ置き換える。'
    else:
        text+='逆行8呼値ごとに約25%の保険、利益が残る反転時に保険だけ返済。'
    return text+'元玉stop32・全玉損失枠32呼値相当、最長60分、場内全返済。'


def templates() -> None:
    """機能: 過去の暗色テンプレートを新作業専用へコピーし、29場と確認率を接続する。

    引数: なし。返り値: なし(None)。過去テンプレートは変更しない。
    """
    target=HERE/'report';target.mkdir(exist_ok=True)
    source=(ROOT/'work/wave_v70/report/template.html').read_text(encoding='utf8')
    source=source.replace('const PERIODS=["前16","後12","全28"];','const PERIODS=["前16","後12","全28","追加1","全29"];')
    source=source.replace('全28','全29').replace('p==="全29"?" selected"','p==="全29"?" selected"')
    source=source.replace('const PERIODS=["前16","後12","全29","追加1","全29"];','const PERIODS=["前16","後12","全28","追加1","全29"];')
    source=source.replace('同じ初回列と共通60分枠で途中管理を比較します。初回から管理終了までを一組とし、保険玉の利確や途中の0枚だけでは勝ちに数えません。以下の3手法は比較代表で、採用条件は未達です。',
        '3章は同じ入口部品の「入口だけ」「幅だけ」「両方」の比較です。前16で組合せを選び、後12・追加10/09デイで選び直しません。入口診断は実際の決済勝率と区別します。')
    source=source.replace('同じ入口の対照との比較','入口部品の変更前・保険の対照との比較')
    source=source.replace('同じ初回入口に異なる途中管理を適用した結果を比較するレポートです。','同じ入口部品へ確認条件を追加し、途中管理の幅も変更した結果を比較するレポートです。')
    source=source.replace('<div class="comparison"></div>','<div class="comparison"></div><h3>入口の方向先着率</h3><div class="entry-diagnostic"></div>')
    source=source.replace('<div class="entry-diagnostic"></div>','<div class="entry-diagnostic"></div><details><summary>同じ入口確認で6つの幅を比較</summary><div class="width-comparison"></div></details>')
    source=source.replace('label:"満額IFDトレール基準"','label:"元の入口・元の幅（保険あり）"')
    source=source.replace('label:"同じ条件・保険だけなし（診断）"','label:"今回と同条件・保険なし"')
    source=source.replace('rows.push({label:"今回の管理"','if(method.netControl?.periods)rows.push({label:"今回と同判断・縮小復帰",data:method.netControl.periods?.[state.period]?.[state.symbol]??null});rows.push({label:"今回の管理"')
    source=source.replace('section.querySelector(".comparison-detail").innerHTML=detailTable(rows);','section.querySelector(".comparison-detail").innerHTML=detailTable(rows);section.querySelector(".entry-diagnostic").innerHTML=entryTable(method,state);')
    source=source.replace('section.querySelector(".entry-diagnostic").innerHTML=entryTable(method,state);','section.querySelector(".entry-diagnostic").innerHTML=entryTable(method,state);section.querySelector(".width-comparison").innerHTML=primaryTable(method.widthComparisons.map(w=>({label:w.config.width_id+"："+w.config.width_name,data:w.periods[state.period][state.symbol]})));')
    source=source.replace('<details><summary>入口・約定・検証範囲</summary>', '<details><summary>少数だが両銘柄黒字だった参考例（主選定外）</summary><div id="reference"></div></details><details><summary>入口・約定・検証範囲</summary>')
    source=source.replace('window.reportTest={D,STATE,updateMethod,drawChart};', '''
const ref=D.reference;
document.getElementById("reference").innerHTML=`<p>${esc(ref.id)}：${esc(ref.description)}</p>`+primaryTable(["前16","後12","全28","追加1","全29"].flatMap(p=>["TOPIX","NK225"].map(s=>({label:p+"／"+NAMES[s],data:ref.periods[p][s]}))));
window.reportTest={D,STATE,updateMethod,drawChart};''')
    function=r'''
/**
 * 機能: 決済と独立した方向先着率を、全入口数と未到達を添えて表示する。
 * @param {object} method - 手法データ。
 * @param {object} state - 銘柄と期間。
 * @returns {string} 診断の表HTML。
 */
function entryTable(method,state){
 const current=method.entryDiagnostic?.[state.period]?.[state.symbol],base=method.baseEntryDiagnostic?.[state.period]?.[state.symbol];
 if(!current||!base)return '<p class="small">入口診断なし</p>';
 const lines=[['元の入口',base],['今回の入口',current]].flatMap(([label,data])=>[8,16].map(level=>{const d=data[String(level)];return `<tr><td>${label}</td><td>±${level}呼値</td><td>${num(d.favorable)}／${num(d.total)}</td><td>${ratio(d.favorable_rate_all,true)}</td><td>${num(d.adverse)}</td><td>${num(d.unreached)}</td><td>${ratio(d.favorable_rate_reached,true)}</td></tr>`;}));
 return `<div class="table-wrap"><table><thead><tr><th>入口</th><th>先着幅</th><th>順行先着／全入口</th><th>全件の正答率</th><th>逆行先着</th><th>未到達</th><th>到達した入口のみ</th></tr></thead><tbody>${lines.join('')}</tbody></table></div><p class="small">新規買ask・売bidを基準に、返済可能な気配が順行／逆行のどちらへ先に届いたか。場内返済期限までの事後採点で、60分手法の決済勝率ではありません。未到達は勝ちに含めません。</p>`;
}
'''
    source=source.replace('// 固定データから画面を組み立てる。外部へデータを送信しない。',function+'\n// 固定データから画面を組み立てる。外部へデータを送信しない。')
    source=source.replace('全条件の途中管理比較.html',ALL)
    (target/'template.html').write_text(source,encoding='utf8')
    all_source=(ROOT/'work/wave_v70/report/all_template.html').read_text(encoding='utf8').replace('全28','全29')
    all_source=all_source.replace('["前16","後12","全29"]','["前16","後12","全28","追加1","全29"]')
    all_source=all_source.replace('両建て保険と途中管理の説明と損益.html',MAIN)
    all_source=all_source.replace('★は最初の192条件から前16セッションで選んだ比較代表です。「診断・選定外」は後から加えた対照で、手法選定には使っていません。',
        '★は前16で選んだ組合せに対応する比較3章。G3は約定時計による相手同期の参考で、主選定から除外しています。後12と追加デイでは選び直しません。')
    (target/'all_template.html').write_text(all_source,encoding='utf8')


def weekly(rows: list[dict], sessions: list[str]) -> dict:
    """機能: 全29の場内会計を週ごとに集計する。

    引数: rows(list[dict])、sessions(list[str])。返り値: 商品別週集計(dict)。
    """
    groups={}
    for session in sessions:
        day=date.fromisoformat(session[:10]);monday=day-timedelta(days=day.weekday());groups.setdefault(monday,[]).append(session)
    return {s:[dict(study.aggregate(rows,s,keys),label=f'{day:%m/%d}週（{len(keys)}場）') for day,keys in sorted(groups.items())] for s in study.SYMBOLS}


def main() -> None:
    """機能: 固定選定例の入口・幅対照と全432条件の損益HTMLを作る。

    引数: なし。返り値: なし(None)。
    """
    templates()
    fixed=study.load(HERE/'事前固定.json');selected=study.load(HERE/'前半選定.json')
    all_results=[study.load(p) for p in sorted((HERE/'results').glob('*.json'))];assert len(all_results)==432
    lookup={r['config']['id']:r for r in all_results};ready,features=study.material()
    sessions=fixed['全セッション']+fixed['追加追試']
    diagnostic=study.load(HERE/'analysis/入口方向の独立診断.json')['集計']
    descriptions=['候補に両気配や注文フローの一致を要求する。元玉・保険の幅は従来のまま。入口を減らすことで確率と収支が改善したかを確認する。',
                  '入口は従来のまま、元玉または保険の追跡幅を広げる。途中の揺れに耐える一方、利益の戻しや保険の残留が増えたかを見る。',
                  '入口確認と広い追跡幅を同時に使う。上の2対照と比較し、どちらの変更で改善／悪化したかを分ける。']
    methods=[]
    for i,choice in enumerate(selected['代表']):
        result=lookup[choice['id']];c=result['config'];prefix=c['id'].rsplit('_',1)[0]
        method=dict(result,id=c['id'],title=choice['label'],configText=summary(c),explanation=descriptions[i],
                    eligible=selected['採用条件充足'],baseline=lookup[selected['基準']],control=lookup[prefix+'_D'],
                    netControl=lookup[prefix+'_N'],weeks=weekly(result['rows'],sessions),
                    widthComparisons=[lookup[f"{c['source']}_G{c['gate_level']}_W{w}_H"] for w in range(6)],
                    entryDiagnostic=diagnostic[f"{c['source']}_G{c['gate_level']}"],baseEntryDiagnostic=diagnostic[c['source']+'_G0'])
        ledger=study.load(HERE/'ledgers'/(c['id']+'.pkl'))
        method['orders']={'|'.join(k):[list(o)+[float(ready[k]['time_s'][int(o[0])])] for o in a['orders']] for k,a in ledger.items()}
        methods.append(method)
    joint=lookup[selected['比較代表']]
    conclusion=f"入口確認と幅拡大を432条件で比較。前16の比較代表{selected['比較代表']}は最低数{'充足' if selected['最低数充足'] else '未達'}・採用条件{'充足' if selected['採用条件充足'] else '未達'}。幅拡大で両銘柄黒字になった少数の補充反転例も別枠で掲載し、主比較と区別します。"
    notes=[
        'G0元の入口、G1直近4中値イベントの両気配1呼値前進。G2はG1に16イベント中値2呼値進行・効率0.30以上・OFI方向比0.10以上を追加。自市場は120秒以内・reset無し。',
        'G3は相手30秒の両気配1呼値・OFI方向比0.05以上。自時点より1秒以上前、同時計先頭、参照と30秒前端の古さ5秒以内。原本に共通受信時計がないため実時間の同期は証明不能。参考として主選定除外。',
        'W0元8/保険4、W1元16/保険4、W2元8/保険8、W3元16/保険8、W4元24/保険12、W5元16/保険8かつ開始も16/8。W5は幅だけの変更ではない。',
        'TOP0.5pt／NK10円が参照ラージ1呼値。元stop32・全玉損失枠32・逆行段差8・1段約25%・最長60分・片方向上限10/20は固定。',
        '初回から3630秒は次の入口を待つ共通枠。幅別・管理別は同じ初回列、G別は入口が変わる。元E01/R01の通し運用ではなく入口部品の比較。',
        '前16だけでG1/G2と幅拡大のHを選定。両銘柄20組・8活動場以上を最低数とし、弱い銘柄の1組平均呼値収支を最大化。両黒字かつ平均勝組／負組>1で採用条件充足。後12と追加場では選び直さない。',
        '全28は既知。10/09デイは選定に使わず追加追試へ分離。全29は単なる保存合計。無取引は勝ちに含めない。',
        '保険は全玉の平均利益で追跡し、往復料金相当より利益が残る場合だけ反転返済判断。幅拡大で返済条件が成立しなくなる場合がある。保険単独stopは今回も未検証。',
        '新規買ask/売bid、返済は逆気配、判断した次の有効原本行でfill。親子・保険新規の当行監視無し。保護線は将来の極値を使わない。',
        '新規返済の注文合計で片道TOPIXmini41.8円／NK225micro11円を課金し1円未満切捨て。全両方向の損失・含み時価・最大保有を記録。',
        'ラージ板を小商品の仮想約定へ使用。実商品板・深さ・部分約定・通信・取消競合は未再現。板の受信時計でなく最終約定時計。',
        '現在API取得0、実注文0。保存データのみ。旧成果・App/E01・原本を変更していない。',
    ]
    OUT.mkdir(parents=True,exist_ok=True)
    reference=lookup['T3L1_G1_W4_D']
    reference=dict(id=reference['config']['id'],periods=reference['periods'],description='表示補充後の反転、保険なし、元玉トレール8→24呼値。全28でTOP+184,068円／NK+113,840円、平均勝組／負組1.68／1.23。ただしNK前半6組で最低数未達・前半赤字、TOPは最大黒字場を除くと赤字。G1とG0の入口は同じで、この例は確認精度改善の証拠ではない。追加デイはTOP+14,164円／NK無取引。採用の選定ではなく全結果を見た参考例。')
    OLD.fill(HERE/'report/template.html',dict(title='入口確認と幅拡大の説明と損益',sessions=sessions,methods=methods,
        bars=OLD.bars(sessions),notes=notes,sourceNotes=[
            'T1L1：中値8呼値進行後、中値が4呼値戻り、買い・売り両気配も戻る方向。',
            'T2L0：中値4呼値進行→2呼値押し→2呼値戻りで再開、両気配も再開方向。',
            'T3L1：近傍板の表示回復が最良量1倍以上、接近後に中値4呼値反転、両気配も反転方向。真の注文補充ではなく表示の代理。',
            'T4L0：表示回復価格を2呼値越え、両気配の進行と最良OFIが一致。',
            'E01P/R01P：旧ATR・EMA入口状態の開始／方向変更パルス。旧台帳は使わず、旧アルゴリズム全体ではない。'],
        allUrl=ALL,conclusion=conclusion,reference=reference),OUT/MAIN)
    entries=[dict(r,id=r['config']['id'],configText=summary(r['config'])) for r in all_results]
    OLD.fill(HERE/'report/all_template.html',dict(title='全432条件の入口確認と幅比較',sessions=sessions,methods=entries,
        selectedIds=[c['id'] for c in selected['代表']],mainUrl=MAIN),OUT/ALL)
    study.save(HERE/'公開会計.json',dict(条件数=432,場数=29,比較代表=selected['比較代表'],
        主HTML_SHA256=hashlib.sha256((OUT/MAIN).read_bytes()).hexdigest(),全条件HTML_SHA256=hashlib.sha256((OUT/ALL).read_bytes()).hexdigest()))
    print('00068主HTMLと全432条件HTMLを生成')


if __name__=='__main__':
    main()
