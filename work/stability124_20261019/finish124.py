"""追加一場と前場IVの結果を、表示・出典知見・試行状態へまとめる。"""

import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
from common124 import HERE,ROOT,NAME,SCENE,read,save as save_private,sha

REPORT='追加セッションとオプションの検証.html'
TRIAL='124_追加一場の凍結評価と前完了場IV固定十二条件'
FIX='124c_人工と金融のキャッシュを分離した少額E01追加検証'
STOPPED='124b_追加CSVの排他的終端を維持した少額E01再接続'
MANAGER=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def save(path: Path,value: dict) -> None:
    """
    機能: 私有証跡又は今回の公開参照だけを限定して保存する。
    引数: path(Path)は今回領域、value(dict)は有限JSON。
    返り値: None。前段停止時の同じ集計だけは完全同値なら引用する。
    """
    public=ROOT/'アルゴリズム調査'/NAME
    assert path.resolve().is_relative_to(HERE) or path.resolve().parent==public.resolve(),path
    if path.exists():
        assert read(path)==value,path
        return
    if path.resolve().is_relative_to(HERE):save_private(path,value)
    else:path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8'))


def reference(path: Path) -> dict:
    """
    機能: 完成資料を位置とSHA256で識別する。
    引数: path(Path)は既存ファイル。
    返り値: dictはrepo相対pathとsha256。
    """
    return dict(path=path.relative_to(ROOT).as_posix(),sha256=sha(path))


def prepend(path: Path,marker: str,text: str) -> None:
    """
    機能: 先頭見出しの次へ最新の作業案内を追加する。
    引数: path(Path)は既存文書、marker/text(str)は一意識別と本文。
    返り値: None。既存の金融成績を上書きしない。
    """
    body=path.read_text(encoding='utf-8');assert marker not in body
    n=body.index('\n')+1
    path.write_bytes((body[:n]+'\n'+marker+'\n'+text+'\n'+body[n:]).encode('utf-8'))


def append(path: Path,marker: str,text: str) -> None:
    """
    機能: 条件・分母・限界を持つ知見を出典アンカー付きで保存する。
    引数: path(Path)は分類正本、marker/text(str)は追加項目。
    返り値: None。既存の知見は削除しない。
    """
    raw=path.read_bytes();assert marker.encode('utf-8') not in raw
    path.write_bytes(raw+('\n\n'+marker+'\n\n'+text+'\n').encode('utf-8'))


def metrics(rows: list[dict]) -> dict:
    """
    機能: 金額・場別安定性・大勝ち依存を独立集計する。
    引数: rows(list[dict])は一商品一手法の場会計。
    返り値: dictは全場指標。無取引を勝ちへ含めない。
    """
    n=[r['net'] for r in rows];positive=sorted([v for v in n if v>0],reverse=True)
    return dict(net=sum(n),profit=sum(r['profit'] for r in rows),loss=sum(r['loss'] for r in rows),
        black=sum(v>0 for v in n),red=sum(v<0 for v in n),inactive=sum(r.get('entries',r.get('campaigns',0))==0 for r in rows),
        median=statistics.median(n),worst=min(n),without_top3=sum(n)-sum(positive[:3]))


def main(e01_sha: str,e01_audit: Path,e01_audit_sha: str,html_sha: str) -> None:
    """
    機能: 独立監査と実描画を確認し、初回停止と修正成功を別々に完了記録する。
    引数: e01_sha/e01_audit_sha/html_sha(str)は完成SHA、e01_audit(Path)は独立監査。
    返り値: None。金融・原市場・現在APIの追加実行は行わない。
    """
    grid=HERE/'grid/十二IV条件の全四十一場と旧十九条件の追加一場.json'
    ga=HERE/'audit124/result/十二IV条件と十九追加間隔の保存会計独立監査.json'
    ep=HERE/'e01c/追加一場の固定少額E01二商品.json';e01_audit=e01_audit.resolve()
    assert sha(grid)=='d058543b39d7d0dc4bcc1a06144c0f2f22290de1f272424c7c20c727b9582f5c'
    assert sha(ga)=='0f7904075719a8336a1b72ab26036e61a3b8e1164fbe253270081b0b221d2211' and read(ga)['passed']
    assert sha(ep)==e01_sha and sha(e01_audit)==e01_audit_sha and read(e01_audit)['passed']
    fixed=read(HERE/'固定計画.json');fixedb=read(HERE/'固定計画_E01c.json')
    for frame in (fixed,read(HERE/'固定計画_E01b.json'),fixedb):
        for p,h in frame['sources'].items():assert sha(ROOT/p)==h,p
    public=ROOT/'アルゴリズム調査'/NAME;assert sha(public/REPORT)==html_sha
    d=read(grid);e=read(ep);old=read(ROOT/fixed['old_e01_result']['path']);assert len(e['rows'])==2 and e['financial_accounts']==2
    all_e01=old['rows']+e['rows'];assert len(all_e01)==82 and len({(r['session'],r['symbol']) for r in all_e01})==82
    fresh={r['symbol']:r for r in e['rows']};stats={s:metrics([r for r in all_e01 if r['symbol']==s]) for s in ('TOPIX','NK225')}
    first={s:metrics([r for r in d['rows'] if r['symbol']==s and r['method']=='O00']) for s in ('TOPIX','NK225')}
    assert first['TOPIX']['net']==-1141186 and first['NK225']['net']==168360
    visual=read(HERE/'visual/実描画確認.json');assert visual['passed'] and visual['root_viewed']
    save(HERE/'全四十一場と追加一場の表示集計.json',dict(passed=True,e01=stats,base_grid=first,new_e01=fresh,financial_replay=0))
    save(public/'再現用参照.json',dict(grid=reference(grid),grid_audit=reference(ga),e01=reference(ep),
        e01_audit=reference(e01_audit),previous_e01=fixed['old_e01_result'],options=fixed['option_features'],financial_replay=0))
    et='\n'.join(f"| {s} | {max(0,fresh[s]['profit']):,.0f}円 | {max(0,fresh[s]['loss']):,.0f}円 | {fresh[s]['net']:+,.0f}円 |" for s in ('TOPIX','NK225'))
    text=f'''# 追加セッションと日経オプションの検証

最初に[短い結果と全41セッションの損益]({REPORT})を開いてください。

追加先物は2026年10月19日デイの一場。既存の固定少額E01を再調整せず適用しました。

| E01の取引商品 | 利益 | 損失 | 追加一場収支 |
| --- | ---: | ---: | ---: |
{et}

両商品とも実新規0で、0円を勝ちには数えません。TOPIXの紙上新規2候補・日経の1候補は、従来の60秒出来高方向票の閾値未達により全て見送りました。入力停止をゼロへ代用した結果ではありません。

前回のTOPIX途中利確なしは、初回3pt／間隔3ptが−110,140円、3/10が−49,320円、15/15が−43,492円でした。全19では当日2黒字17赤字（3/8が＋6,516円、12/12が＋16,926円）ですが、全41場合計は19すべて赤字。3/3は10:10:25に買い10枚・売り10枚となり、買平均4040.20／売平均4029.85の不利な建値差−103,500円が固定。終端気配差−5,000円・手数料−1,640円で一致します。[具体的な注文と固定損失](../../work/stability124_20261019/audit124/TOPIX追加一場の両側上限と固定損失.md)。

オプションは608原板ファイル・15場・2限月、約9.57GB。原板の受信時刻が保存されず、同じ約定時刻でもIVが変わるため、その時刻へ場中IVを結合していません。ファイルの場区分が受信時刻に由来することを実装で確認し、直前完了場の末尾提供IVだけを次場で固定利用しました。利用可能11場、不明30場。前場のΔが±0.5に近い次月以後のコール・プット各3銘柄から中央値を求め、不明なら通常設定へ戻します。日経IVをTOPIXへ使う場合は日本株の共通荒さの代理で、TOPIX固有IVではありません。

R=clip(IV%/30,0.5,2)で初回幅・追加間隔・枚数を変える12条件。TOPIX一単位1pt／日経20円、片方向上限10mini／20micro。気配資格は拡大せず、途中利確なし・新規締切15:00／05:20・引け15:45／06:00の直前6分BBO代理精算を共通としました。同じ経済設定は共有し、190新会計と120旧引用で1003表示行を作っています。

**IVによる安定性向上は確認できませんでした。** O01の改善TOPIX＋16,582円／日経＋1,744円は10月19日一場だけ。IV既知11場でも基準・O01とも両商品5黒字6赤字です。基準の日経は全41場合計＋168,360円ですが15黒字26赤字、中央値−12,020円、上位3黒字除外−332,746円。TOPIXは−1,141,186円、11黒字30赤字です。累計黒字だけで有望としません。

オプション1分足は全608CSV・3146足で、同分・同限月・同権利行使価格のC/P対は108組。約65%の足が最初2場へ偏るため、今回は場中の合成先物やIV先行性の有効性まで検証できたとはしません。原板は境界2866標本の診断であり全9.57GBの全行品質検査ではありません。[時刻資格](../../work/stability124_20261019/inventory/オプション時刻の採用可否.json)・[一次資料と未測定仮説](../../work/stability124_20261019/theory/日経オプションを先物判断へ使う事前仮説.md)。

E01初回はCSVの15:40行が旧排他範囲を超え、紙上信号・取引計算前、金融0で停止。別source・別試行124bで、原本を残し旧範囲外の合法末尾だけconsumer表示から除外しました。その後の人工用JITキャッシュ参照による停止も金融0として別記し、124cで人工・金融の保存域を分離。経済部品は同bytes。二度の停止を無取引やゼロ収支へ置換していません。新E01二口座は全玉場内返済、保存会計を独立照合済みです。旧33場と追加8場の入力時計資格は異なり、全期間が同一入力処理の独立試験とは呼びません。

旧40は既知開発、追加一場は固定仕様による比較です。現在API・実注文・旧金融の再実行は0。小型実板・真受信順・待ち順位は未観測です。
'''
    assert not (public/'README.md').exists();(public/'README.md').write_bytes(text.encode('utf-8'))

    # ----------------------------------------
    # 新作業の入口と、前場IV・両側固定損失・入力終端を法則単位で記録する。
    summary='追加10月19日デイとオプション12条件を確認。前場IVによる幅調整は改善が一場だけの条件もあり、両商品での安定性向上は未確認。'
    for path,prefix in [(ROOT/'README.md','アルゴリズム調査/'),(ROOT/'アルゴリズム調査/README.md','')]:
        prepend(path,'<!--00124案内-->',f'最新：[00124：追加セッションと日経オプション]({prefix}{NAME}/{REPORT})。{summary}\n<!--00124案内終了-->')
    index=ROOT/'アルゴリズム調査/index.html';body=index.read_text(encoding='utf-8');assert '<!--00124開始-->' not in body
    match=re.search(r'<main\b[^>]*>',body);assert match
    card=f'\n<!--00124開始--><article class="task latest"><div class="number">作業00124・追加一場と日経オプション</div><h2>前場IVで新規幅・枚数を変える12条件</h2><p>{summary}</p><a class="button" href="{NAME}/{REPORT}">結果と全41場</a> <a href="{NAME}/README.md">条件と根拠</a></article><!--00124終了-->\n'
    body=body[:match.end()]+card+body[match.end():]
    body=body.replace('最新00123では途中利確なしの新規間隔を19条件・全40場で比較。各場の損益と実際の取引枚数を掲載しています。','最新00124では追加一場と日経オプションを検証。既存E01・19間隔と、前場IVによる12条件の全41場を掲載しています。')
    index.write_bytes(body.encode('utf-8'))
    common=ROOT/'アルゴリズム調査/共通/知見台帳'
    prepend(common/'README.md','<!--00124案内-->',f'最新は[00124：追加一場と日経オプション](../../{NAME}/README.md)。時刻不明IVの先読み防止、前場IVの実差分母、追加一場の両側固定損失、CSV終端資格を追記しました。\n<!--00124案内終了-->')
    source=f'**出典：** [00124_追加セッションと日経オプションの検証](../../{NAME}/README.md)。[全41場](../../{NAME}/{REPORT})。'
    append(common/'入口.md','<a id="00124_時刻不明の場中IVと前完了場の固定情報を分ける"></a>',
        '## 最終約定時刻が同じでもIVは変わるため、場中IVをその時計へ結合しない\n\n'+source+'\n\n'
        '**条件・分母：** 日経option608原板15場・2限月、各最大5位置2866標本。標本対1675のうち1495対で同じCurrentPriceTimeのままIV等が変化、1301対はnullのまま。全行発生率ではない。controllerはreceivedAtでsessionを割当てるが原板保存はpayloadだけで受信時刻・共通連番を落としていた。\n\n'
        '**採用した観測：** 直前完了場の末尾だけを次場の固定情報へ移す。旧い都合のよい場へ遡らず、当場年月より後の最小限月、absΔ.25〜.75内で.5に近いC/P各最大3、IV1〜200%の中央値。41場中11既知・30不明、不明は基準運用へ戻す。ファイルの所属により次場前の受信済みは言えるが、提供IVそのものの鮮度・同時気配の裁定整合性は未確認。\n\n'
        '**未測定：** 時刻不明行の並びを秒へ均等配分しない。確定1分足3146本・同分C/P108組も疎で、場中IV・Greeksの先行性や方向予測は本比較では未測定。OIやdealer保有符号は観測していない。[時刻資格](../../../work/stability124_20261019/inventory/オプション時刻の採用可否.json)。')
    append(common/'継続.md','<a id="00124_前場IVによる丸め後の実差と安定性"></a>',
        '## 前場IVが11場あっても、丸め後に幅が変わる場は一場だけの場合があった\n\n'+source+'\n\n'
        '**当時条件：** 途中返済なしの3/3を基準にR=clip(前場IV%/30,.5,2)で初回・追加・上限を調整。TOP一単位1pt、NK20円は固定、幅だけ観測呼値へ上丸め。12条件・両商品41場、190新会計/120旧引用/693同値共有。表示1003行を独立金融1003件へ数えない。\n\n'
        '**実差の分母：** O01追加sqrtR、O03初回sqrtR、O05両sqrtR、O09capのみは丸め後の経済差が1/41場。R比例のO02/04/06/07は4/41、逆尺度O08は10/41。O01の全41改善TOP+16,582円/NK+1,744円は追加10月19日一場の差そのもの。既知11場でも基準/O01は両商品各5黒字6赤字。\n\n'
        '**安定性：** 基準TOP全41−1,141,186円・11黒30赤。NK+168,360円でも15黒26赤、中央値−12,020円、上位3黒字除外−332,746円。O01 NK+170,104円でも同15黒26赤、除外−331,002円。前場IVの尺度変更で両商品安定性が改善した根拠とはしない。方向先行性や他のオプション手法全般を否定したものではない。')
    append(common/'出口.md','<a id="00124_追加上昇場でも等枚数の不利な建値差は回収されなかった"></a>',
        '## 追加場では10時10分の両側上限後、相場が上がっても建値差は残った\n\n'+source+'\n\n'
        '**具体的な時刻：** TOPIX2026年10月19日Day、初回3pt・間隔3pt・途中返済なし。09:01:05に売り10段目uid13を4019.5で新規し、終端代理15:39:59のask4073.5で−54,082円。10:10:25の買uid20で買10売10へ到達。平均買4040.20／売4029.85となり、建値差−103,500円が固定された。\n\n'
        '**会計：** 等枚数の価格変化は相殺され、終端bid4073/ask4073.5の気配幅−5,000円、往復料20枚−1,640円を加えて−110,140円。買側+327,180円に対し売側−437,320円。3/10は買6売4・−49,320円、15/15は買4売2・−43,492円で、間隔拡大でも当場赤字は残った。\n\n'
        '**範囲：** 追加一場の保存玉会計であり、反対玉をどの時点で返せば全場改善するかは未測定。00123の赤字上位三場は両上限未到達だったので、全損失を飽和一つで説明しない。[注文診断](../../../work/stability124_20261019/audit124/TOPIX追加一場の両側上限と固定損失.json)。')
    append(common/'売買の工夫.md','<a id="00124_追加CSVの場末行と金融前停止を別計上する"></a>',
        '## 新CSVの追加末尾足を旧読取範囲へ戻す修正は、取引ゼロと別に記録する\n\n'+source+'\n\n'
        '**反例：** 旧少額E01はDay08:45以上15:40未満のCSV資格だったが、新NK一分足に15:40行が追加され、入力stageで停止。紙上信号・実金融は0。これを無取引の成功やnet0へ置換しなかった。元e01源と停止記録を保存し、別e01b・別124b登録で再接続。\n\n'
        '**修正：** 原CSVをreadonlyで残し、合法終端以上〜実セッション終端の末尾だけconsumer viewから除外。TZなし・不正・逆行/重複・開始前・実場後は引続き拒否。除外原row/timeを記録し、旧数値102源と12部品を変更しない。274人工/90配列、15:40へ極端価格を足しても窓内120行bytesと旧6種信号が不変だった。\n\n'
        '**実行環境：** CSV修正後も人工時の別module名を参照するNumba cacheで金融前停止。旧cache・sourceを消さず、別124cで人工jit_legacyと金融jit_financialを分け、金融開始前に後者が未使用であることを要求した。経済source同bytesのまま新金融だけを実行。\n\n'
        '**実会計：** 修正後の追加2口座のみ金融実行し独立会計照合。旧40保存80行を表示引用し新しい標本へ数えない。原本更新へ適合するI/O資格の修正と、予測・注文アルゴリズム改善の効果を分ける。')
    prepend(ROOT/'アルゴリズム調査/調査方針.md','<!--00124最新指定-->',
        '## 2026年10月19日の追加データとオプション\n\n追加先物1場は旧設定を固定して測定。新オプションは場中の受信時刻が未保存であり、古い約定時計へIVを載せず、前完了場末尾を次場の固定尺度として検証する。時刻不明を並び順から秒へ補完しない。既知11/不明30・丸め後の実差場数を併記し、単一追加場の改善を安定性確立と呼ばない。\n<!--00124最新指定終了-->')

    # ----------------------------------------
    # 初回E01の金融前停止と、別試行の修正後二金融を混同しない。
    ledger=MANAGER.parent/'data/trials.json';raw=ledger.read_bytes();table=json.loads(raw)
    previous={r['id']:r for r in table['trials'] if r['id'] not in (TRIAL,FIX,STOPPED)}
    parent=next(r for r in table['trials'] if r['id']==TRIAL);child=next(r for r in table['trials'] if r['id']==FIX)
    middle=next(r for r in table['trials'] if r['id']==STOPPED)
    assert parent['status']==child['status']==middle['status']=='未実行'
    save(HERE/'終了前の二登録行.json',dict(parent=parent,middle=middle,child=child))
    parent.update(status='格子検証完了・E01は金融前停止',completed_result=reference(grid),completed_audits=[reference(ga)],
        completed_registered_sources=fixed['sources'],completion_accounting=dict(financial_accounts=190,old_references=120,equivalent_references=693,e01_financial_accounts=0),
        result='格子190会計を完成。前場IV12条件で両商品安定黒字は未確認。E01はCSV終端資格で金融0停止し124b、さらに環境隔離124cへ継承。',
        execution_attempts=[dict(status='検証完了',component='格子',financial_accounts=190),dict(status='金融前停止',component='E01',financial_accounts=0,evidence=reference(HERE/'e01/金融前CSV資格停止.json'))],
        replacement_trial=STOPPED,readme=f'アルゴリズム調査/{NAME}/README.md',report=f'アルゴリズム調査/{NAME}/{REPORT}')
    middle.update(status='信号生成中のキャッシュ参照で金融前停止',replacement_trial=FIX,completed_result=reference(HERE/'e01b/金融前キャッシュ環境停止.json'),completion_accounting=dict(financial_accounts=0),result='CSV範囲修正後、人工module名のJIT参照で金融前停止。源と失敗cacheを保存して124cへ継承。')
    child.update(status='検証完了',completed_result=reference(ep),completed_audits=[reference(e01_audit)],completed_registered_sources=fixedb['sources'],
        completion_accounting=dict(financial_accounts=2,old_financial_replay=0,unclosed=0,original_market_reads=0,current_API=0,real_orders=0),
        result=f"旧経済を保持し追加一場2会計を完了。TOPIX{fresh['TOPIX']['net']:+,.0f}円、NK{fresh['NK225']['net']:+,.0f}円。",
        readme=f'アルゴリズム調査/{NAME}/README.md',report=f'アルゴリズム調査/{NAME}/{REPORT}')
    assert previous=={r['id']:r for r in table['trials'] if r['id'] not in (TRIAL,FIX,STOPPED)}
    history=MANAGER.parent/'data/history/00124_終了前の試行台帳.json';assert not history.exists();history.write_bytes(raw)
    table['updated_at']=datetime.now(timezone.utc).isoformat();ledger.write_bytes((json.dumps(table,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8'))
    proc=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),'build'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    save(HERE/'終了後の台帳同期.json',dict(終了コード=proc.returncode,stdout=proc.stdout,stderr=proc.stderr));assert proc.returncode==0,proc.stderr[-1000:]
    save(HERE/'案内と法則別知見及び試行終了.json',dict(passed=True,report_sha256=html_sha,old_trials_unchanged=True,
        grid_financial_accounts=190,e01_financial_accounts=2,first_e01_stopped_before_financial=True,financial_replay=0))
    print('追加一場・前場IV・金融前停止と修正系列を区別して保存しました。',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--e01-sha',required=True);parser.add_argument('--e01-audit',type=Path,required=True)
    parser.add_argument('--e01-audit-sha',required=True);parser.add_argument('--html-sha',required=True)
    args=parser.parse_args();main(args.e01_sha,args.e01_audit,args.e01_audit_sha,args.html_sha)
