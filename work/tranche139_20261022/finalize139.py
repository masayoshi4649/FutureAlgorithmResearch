"""検証の結論と限界を公開し、分類別知見と試行台帳を更新する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from common139 import HERE,ROOT,PUBLIC,read,ref


def append_once(path,marker,addition):
    """
    機能: 過去の知見を保持し、新しい観測を一度だけ追記する。
    引数: path(Path)、marker/addition(str)は対象と追加本文。
    返り値: None。
    """
    text=path.read_text(encoding='utf-8')
    if marker not in text:path.write_text(text+'\n\n'+addition+'\n',encoding='utf-8')


def main():
    """
    機能: 公開資料と監査が存在することを確認して成果を整理する。
    引数: なし。
    返り値: None。既存金融会計・原データ・アプリを変更しない。
    """
    html=PUBLIC/'段階投入と早期参加の全セッション損益.html';assert html.exists()
    paths=[HERE/f'{folder}/結果.json' for folder in ('results','extra_results','early_results','recycle_results','protect_results','guard_results')]
    audits=['金融独立監査.json','金融独立監査_追加.json','金融独立監査_早期_v2.json','recycle_financial_audit139.json','金融独立監査_追撃保護.json','guard_financial_audit139.json']
    assert all(p.exists() for p in paths) and all((HERE/n).exists() for n in audits)
    manifest=dict(results=[ref(p) for p in paths],audits=[ref(HERE/n) for n in audits],report=ref(html),
        account_count=13724,conditions=146,sessions=47,API=0,real_orders=0,
        limit='既知探索。ラージ気配代理、元通知と新造早期入口の数量出口層。実mini全期間とGo本体の全面再現・未知期間は未確認。')
    (PUBLIC/'全結果目録.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    conclusion=read(HERE/'報告の結論.json');stats=read(PUBLIC/'比較集計.json')['summary']
    summary='\n\n'.join([conclusion['lead']]+conclusion['notes'])
    rows=['|商品|手法|全47場収支|赤字場|平均赤字|最大赤字|','|---|---|---:|---:|---:|---:|']
    for symbol in ('NK225','TOPIX'):
        for key in conclusion['main_methods']:
            s=stats[symbol][key]['全47場'];rows.append(f'|{symbol}mini|{key}|{s["net"]:+,.0f}円|{s["reds"]}/47|{s["mean_loss"]:,.0f}円|{s["max_loss"]:,.0f}円|')
    readme=f'''# 00139 複数追撃と早期参加の全体検証

最初に見る資料：[段階投入と早期参加の全セッション損益.html](段階投入と早期参加の全セッション損益.html)。

読む順序：結論 → 主要比較 → 手法を選び全47場の利益・損失・収支 → 必要な場合だけ原因・監査資料。

{summary}

{chr(10).join(rows)}

両商品とも片方向上限10枚。日経はNK225mini（倍率100円、片道38.5円/枚）、TOPIXはTOPIXmini（倍率1,000円、片道41.8円/枚）。1注文で1円未満切捨て。実際の初回・上限枚数は手法ごとに異なる。利益/損失は初回＋追撃の一組の費用後損益を正負に分類し、全場内で全玉を返済した金額。

46基本条件＋48早期口座＋8利益枚数再追加＋8追撃保護＋36早期改善＝146条件、47場×2商品で13,724会計。対照再利用や同じ注文の条件間重複を、独立標本の増加として数えない。9/21デイ〜10/21デイ45場と、追加10/21ナイト・10/22デイ2場を分ける。追加2場も価格を以前参照しており、完全未知とはしない。後続の損失原因に基づく再改善は全47場を見た既知探索。

原通知の入口は固定し、初回の数量と追撃・出口を差し替えた。数量を変えたGo本体で全ての後続判断がどう変わるかは別の確認が必要。保有中の候補見送りは発注判断時点で行う。早期は確定1分足、同時刻を除く新鮮な相手市場だけを参照。管理Rを2倍にした比較も入口の短期支持正規化は変えない。夜の静観は毎日同じ米寄り75〜45分前で、事後に損失日だけを除かない。

## 原因と改善の証拠

- [最大追撃損失の価格・時刻・枚数](../../work/tranche139_20261022/保存結果の独立診断.md)：両商品各3親・15追撃玉はいずれも1.5R利益保護の起動未達。最大損失例に限った診断で、全追撃の予測確率とはしない。
- [早期の損失・初回と追加の分離](../../work/tranche139_20261022/early_diagnosis139_v2.md)：単独E01/E15の最悪3場、費用前からの損失、急変気配を確認。併用の通常補完ID分類を訂正した版。
- [主比較・早期・追撃保護の独立監査](../../work/tranche139_20261022/独立監査概要.md)。追撃保護では初回/補完は不変だが、早く返した空き枠を後段で埋めるため62会計の追加新規が変化。純粋な出口のみの効果とはしない。
- [再追加の費用後信用監査](../../work/tranche139_20261022/recycle_financial_audit139.json)、[早期改善の候補採否監査](../../work/tranche139_20261022/guard_financial_audit139.json)。
- [全条件の比較集計](比較集計.json)、[全結果と監査の指紋](全結果目録.json)。

## 再現と修正履歴

- [基本計画](../../work/tranche139_20261022/試行計画_v2.json) → `run139.py run` → `run139.py extra`。
- [早期計画](../../work/tranche139_20261022/早期計画.json) → `run_early139.py run`。
- [再追加計画](../../work/tranche139_20261022/再追加計画.json) → `run_recycle139.py run`。
- [追撃保護の修正版](../../work/tranche139_20261022/追撃保護_v2計画.json) → `run_protect139_v2.py run`。旧版は幅の設定不整合を金融前に検出し、未実行で保存。
- [早期改善の修正版](../../work/tranche139_20261022/早期改善_v2計画.json) → `run_guard139_v2.py run`。旧版は通常補完IDの制限で初場途中に停止、完了会計の保存なし。数値規則を変えずID専用範囲を修正して再登録。元の早期会計にも独立再監査を行い、補完992親の不変性を追加確認した。旧早期損益の修正はない。

既にある結果へ再実行して上書きしない。新データは別入力目録・別試行登録で追加する。入力目録と各数値源のSHA256は各計画へ固定済み。実mini板は全期間分がなく、実約定検証は未実施。APIによる現在データ取得0・実注文0。稼働アプリとdistは変更していない。

比較元：[00137](../00137_日経ミニの段階投入と時間帯別運用/README.md)、[00138](../00138_玉別の利益トレーリング比較/README.md)。旧一回追撃候補の45場結果を今回の47場とそのまま順位比較しない。
'''
    (PUBLIC/'README.md').write_text(readme,encoding='utf-8')
    # ----------------------------------------
    # 法則の粒度で出典・分母・終点・限界を残す。
    ledger=ROOT/'アルゴリズム調査/共通/知見台帳'
    source=f'**出典：** [{PUBLIC.name}](../../{PUBLIC.name}/README.md)。'
    append_once(ledger/'入口.md','00139_短い準備と予測力を分離',f'''<a id="00139_短い準備と予測力を分離"></a>

## 短い指標で待機は短縮できるが、短期の二市場一致が持続を保証するわけではない

{source}

**当時条件：** 現行はEMA15/60と傾き3本に両市場63確定1分足を要求し、公開遅延込みで朝は最速09:50頃。別入口では確定3足の短ATR、30秒/120秒の二市場支持15秒を使う。EMA3/8、5/20、直近帯突破後の戻り確認も分離比較した。未来足・同時刻の相手行は不使用。

**観測：** E01の朝は日経/TOPIXとも24/24場参加、初回中央値は開始後7.1分/6.5分。夜は両方22/23場参加、中央値5.2分/5.4分。早期区間の費用後収支は朝−24,414円/−190,330円、米前−614,708円/−237,588円。全16入口管理条件は両商品とも全47場の早期累計赤字。観測終点は朝09:50又は米寄り15分前の全返済。

**限界：** 前倒し可能性と予測利益を別々に測った。早期単独の無取引を成功に含めない。最悪3場の損切り玉に直前レンジ端の入口が多くても、勝ち玉との対照なしにその位置を拒否条件へしない。再試行制限・管理幅・指標時計静観の後続比較はレポートへ保存。全早期手法の不可能性や現行待機の最適性を証明しない。''')
    append_once(ledger/'継続.md','00139_追撃の有利さは玉自身で測る',f'''<a id="00139_追撃の有利さは玉自身で測る"></a>

## 初回が順行していても、後から建てた玉の余力は別に測る必要がある

{source}

**当時条件：** C04は二市場の30秒0.05R・120秒0.2R支持が15秒継続し、初回から段階順行したら追加する。玉自身の建値から1.5R順行して初めて利益保護を起動。

**分母と観測：** 両商品それぞれ追撃損失最大3親、計6親・15追撃玉を各玉全返済まで確認。最高順行は全15玉が0〜0.96Rで1.5R未達。日経10/20は初回2枚が売り+8,847円・買い+11,847円でも、追加群は−46,228円・−44,228円。支持が当時成立したことと、その後も持続することは別だった。

**限界：** 最大損失を選んだ事後原因診断であり、全追撃の失敗率や未来の入口精度ではない。上昇/下落は採点にのみ使用。C04の日経は上昇22場中11赤字、下落25場中7赤字で、対称な売買式から無偏向を断定しない。''')
    append_once(ledger/'出口.md','00139_幅より起動条件を点検',f'''<a id="00139_幅より起動条件を点検"></a>

## トレーリングが始まらない損失は、幅短縮では防げない

{source}

**条件：** C04に対しCHAは追撃第1/2/3玉の保護開始を1/.75/.5Rへ下げ、幅を.75/.5/.375Rとする。初回と元親の返済は維持。判断後の次正常気配で返済。

**全47場の実測：** 日経C04→CHAは累計+1,769,952→+1,548,952円、赤字18→17場、最大赤字72,914→66,692円。10/20デイ−36,373→+11,627円を改善する一方、9/28デイ+161,465→+99,465円。TOPIXは+833,781→+720,281円、赤字16場のまま。後段をさらに早く保護するCHBは日経10/20を+69,627円にするが、全累計は+1,495,874円。

**範囲：** 各場全玉返済・手数料後。追撃保護8条件の初回/補完は不変だが、752会計中62会計では空いた枠への後続追加も変化。純出口効果だけとしない。早期TOPIX10/14は21:30気配飛びで停止幅を超える損失があり、条件価格での必達返済ともみなさない。''')
    append_once(ledger/'売買の工夫.md','00139_段数と再追加は別に評価',f'''<a id="00139_段数と再追加は別に評価"></a>

## 段階投入と利益枚数の補充は、赤字頻度と損失規模を分けて評価する

{source}

**段階投入：** NKmini47場のB5は累計+2,116,984円・赤字16・平均赤字61,840円・最大153,304円。P07は初回2枚、0.5/1/1.5R順行で1枚ずつ、支持再確認、追加玉ごとの利益保護で+1,342,794円・赤字16・平均37,210円・最大69,998円。主担当のみ2枚のB2（補完は最大5枚）も+1,035,950円・赤字15・平均35,641円なので、単なる減枚と段階手法の価値を混同しない。TOPIXではB5の赤字11に対しC10でも15、日経向けの順位を流用しない。

**再追加：** 初巡の再追加はTOPIX3夜・5独立時点のみ、日経0。元親途中返済後の追加禁止を、費用後利益を実現した追撃の返済枚数だけ解除し、初回残存・新支持15秒・60秒待機・新UIDで補充する別8条件を測定。極値更新1回のCRE1は日経C04から+51,158円、TOPIX−14,406円、赤字場数はそれぞれ18/16のまま。回数増加や最高値不要の押し戻り再進行でも両商品共通の改善ではなかった。

**限界：** 原通知に接続した枚数・出口層、全47場の既知探索。1〜2枚を先行し強支持で増やす根拠と、将来の校正済み勝率を区別する。全期mini実板・実Goの全面再現は未確認。''')
    # ----------------------------------------
    # 最新資料への導線を更新し、旧文書は保持する。
    link=f'{PUBLIC.name}/段階投入と早期参加の全セッション損益.html'
    for file,href in [(ROOT/'アルゴリズム調査/README.md',link),(ROOT/'README.md','アルゴリズム調査/'+link)]:
        text=file.read_text(encoding='utf-8')
        if PUBLIC.name not in text:file.write_text(f'最新調査：[00139 段階投入と早期参加の全47場比較]({href})。\n\n'+text,encoding='utf-8')
    index=ROOT/'アルゴリズム調査/index.html';text=index.read_text(encoding='utf-8')
    if PUBLIC.name not in text:index.write_text(text.replace('<main>',f'<main>\n<section class="task latest"><h2>00139 段階投入と早期参加</h2><p>朝・米国前の参加、複数追撃、玉別保護と再追加を全47場で比較。</p><a class="button" href="{link}">結論と全セッション損益</a></section>',1),encoding='utf-8')
    append_once(ledger/'README.md',PUBLIC.name,f'最新追加：[00139 複数追撃と早期参加の全体検証](../../{PUBLIC.name}/README.md)。入口・継続・出口・売買の工夫へ、発動条件と反例を追記。')
    append_once(ROOT/'アルゴリズム調査/調査方針.md','00139_待機短縮の評価',f'''## 2026年10月22日：待機時間と利益を別々に評価する

<!--00139_待機短縮の評価-->
朝約1時間・夜の米国開始までの待機は機会を逃しているとの追加指摘を受けた。準備に必要なデータ量と明示的な時刻禁止を分け、短指標による早期参加、少量先行、追撃、損失後停止、特定時刻の静観を比較する。待ち時間を減らすだけで利益改善とみなさず、失った勝ち・増えた負け・単発急変も確認する。[00139]({link})へ保存。''')
    # ----------------------------------------
    # 完了した試行と、再生前/初場途中で置き換えた試行を区別して履歴を残す。
    directory=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合';path=directory/'data/trials.json';old=path.read_bytes();table=json.loads(old)
    mapping={'139_複数追撃と初回待機と再追加':'results','139_朝と米国前の早期参加':'early_results','139_部分利確後の利益枚数再追加':'recycle_results',
        '139_伸びない追撃の早期保護_幅修正':'protect_results','139_早期参加の再試行と急変時刻の制御_ID修正':'guard_results'}
    for row in table['trials']:
        key=row['id']
        if key in mapping:
            row.update(status='全47場・両商品・独立会計と原因再検証完了',result=ref(HERE/f'{mapping[key]}/結果.json'),report=ref(PUBLIC/'README.md')['path'])
            if mapping[key]=='results':row['additional_result']=ref(HERE/'extra_results/結果.json')
        elif key=='139_伸びない追撃の早期保護':row.update(status='金融未実行。保護幅設定を修正して別IDへ移行',report=ref(PUBLIC/'README.md')['path'])
        elif key=='139_早期参加の再試行と急変時刻の制御':row.update(status='初場の補完ID検査で停止・完成会計なし。ID修正版で全場再実行',report=ref(PUBLIC/'README.md')['path'])
    table['updated_at']=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat();backup=directory/'data/history'/('trials_'+hashlib.sha256(old).hexdigest()+'.json')
    if not backup.exists():backup.write_bytes(old)
    path.write_text(json.dumps(table,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('公開資料・知見・試行状態を更新しました。')


if __name__=='__main__':main()
