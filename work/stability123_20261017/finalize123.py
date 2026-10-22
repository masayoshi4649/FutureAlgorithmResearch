"""間隔比較の保存会計を案内・分類別知見・試行状態へ反映する。"""

import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from register123 import HERE,ROOT,MANAGER,TRIAL,read,save,sha

NAME='00123_途中利確なしの新規間隔比較'
REPORT='途中利確なしの新規間隔比較.html'
RESULT='91475e3757d4a9462f1ecc9405c43e76145967693b0802c56e73068dd0db416c'


def prepend(path: Path,marker: str,fragment: str) -> dict:
    """
    機能: 既存見出し直下へ出典付きの案内を一度だけ追加する。
    引数: path(Path)は既存文書、marker/fragment(str)は識別子と追加本文。
    返り値: dictは変更前後の同一性記録。
    """
    raw=path.read_bytes();body=raw.decode('utf-8');assert marker not in body
    pos=body.index('\n')+1
    path.write_bytes((body[:pos]+'\n'+marker+'\n'+fragment+'\n'+body[pos:]).encode('utf-8'))
    return dict(path=path.relative_to(ROOT).as_posix(),before_sha256=hashlib.sha256(raw).hexdigest(),after_sha256=sha(path))


def append(path: Path,marker: str,fragment: str) -> dict:
    """
    機能: 分類別の知見へ実測分母と限界を伴う一項目を追加する。
    引数: path(Path)は知見正本、marker/fragment(str)は出典アンカーと本文。
    返り値: dictは変更前後の同一性記録。
    """
    raw=path.read_bytes();assert marker.encode('utf-8') not in raw
    path.write_bytes(raw+('\n\n'+marker+'\n\n'+fragment+'\n').encode('utf-8'))
    return dict(path=path.relative_to(ROOT).as_posix(),before_sha256=hashlib.sha256(raw).hexdigest(),after_sha256=sha(path))


def main(auditpath: Path,auditsha: str,reportsha: str) -> None:
    """
    機能: 独立合格済み720会計と保存引用40を新資料として登録完了する。
    引数: auditpath(Path)は独立監査、auditsha/reportsha(str)は完成時のSHA256。
    返り値: None。市場再読・売買再実行・実注文は行わない。
    """
    resultpath=HERE/'途中利確なしの十九間隔と全四十場.json';assert sha(resultpath)==RESULT
    auditpath=auditpath.resolve();assert sha(auditpath)==auditsha and read(auditpath)['passed'] is True
    result=read(resultpath);fixed=read(HERE/'固定計画.json')
    assert len(result['runs'])==720 and len(result['baseline']['rows'])==40
    groups={s['id']:(result['baseline']['rows'] if s['reused'] else [r for r in result['runs'] if r['method']==s['id']]) for s in result['specs']}
    assert len(groups)==19 and all(len(rows)==40 and sum(r['net']+r['fees'] for r in rows)<0 for rows in groups.values())
    assert sum(r['net'] for r in groups['I3_G10'])==-318722 and sum(r['entries'] for r in groups['I3_G10'])==271
    for path,value in fixed['sources'].items():assert sha(ROOT/path)==value,path
    public=ROOT/'アルゴリズム調査'/NAME;report=public/REPORT;assert sha(report)==reportsha
    diagnosis=HERE/'adversary/formal_gap10_loss/I3_G10赤字上位三場の注文と値動き及び費用分解.json'
    assert sha(diagnosis)=='c54657fd56aa08efc1f78e25f49b44be5a09e4b9f28dbf049ae20813cb2246ae'
    save(public/'再現用参照.json',dict(result=resultpath.relative_to(ROOT).as_posix(),sha256=RESULT,
        audit=auditpath.relative_to(ROOT).as_posix(),audit_sha256=auditsha,new_financial_replay=0))
    body='''# 途中利確なしの新規間隔比較

最初に[19条件と全40セッションの比較](途中利確なしの新規間隔比較.html)を開いてください。

TOPIXミニ片方向上限10枚。新規間隔を1・2・3・4・5・6・8・10・12・15ptに変更し、初回3pt固定と初回も同じ幅の二系統を比較しました。3/3重複を統合した19条件です。途中利確・損切りなし、新規締切15:00／05:20、15:45／06:00予定の引け前6分以内最終BBO代理精算は共通です。

**間隔変更だけでは安定黒字になりませんでした。19条件すべてで40場合計・手数料控除前とも赤字です。** 初回3pt固定では10pt間隔が合計赤字最小で−318,722円・12黒字28赤字・累計271枚。3pt間隔の−1,031,046円・11黒字29赤字・653枚から損失は縮みましたが、黒字場はほぼ増えていません。

初回と間隔を両方15ptにすると合計−255,406円ですが、6黒字33赤字1無取引・133枚。損失の少なさを安定性の向上とは扱いません。黒字場が最多の4/4も13黒字27赤字・−830,018円です。9月24日デイは3/3が＋91,188円、3/10が＋18,844円で、間隔拡大は勝ちも減らしました。

入口の気配幅上限1pt・判断後不利許容0.5ptは間隔に連動させず固定。注文一枚、往復手数料82円。同じ既知TOPIX40場の開発比較で、日経・未知期間は今回は未検証です。新18条件720会計を一回測定し、旧3/3の40会計は再実行せず引用しました。全注文・玉・費用・時価・DD・数量上限・代理価格を独立監査しています。

間隔10ptでも、10月1日ナイトは買い平均4119.625・売り平均4101.667に対し、終端bid4104／ask4105.5となり両側赤字、計−86,320円。買い4枚・売り6枚で上限未到達です。反発で買い、反落で売った玉が両方残るため、逆側を増やしても必ず損失を回収できるわけではありません。[赤字上位3場の全新規と費用分解](../../work/stability123_20261017/adversary/formal_gap10_loss/十ポイント間隔の損失原因.md)。

実装：[間隔と初回距離](../../work/stability123_20261017/core123.py)、[固定計画](../../work/stability123_20261017/固定計画.json)。知見は[入口](../共通/知見台帳/入口.md#00123_広い新規間隔は数量と勝ち場を同時に減らす)・[継続](../共通/知見台帳/継続.md#00123_上限未到達でも両方向の保有が赤字になる)へ追記しました。
'''
    assert not (public/'README.md').exists();(public/'README.md').write_bytes(body.encode('utf-8'))
    changes=[]

    # ----------------------------------------
    # 旧研究を保持し、新比較へ直接移動できる案内を追加する。
    message='TOPIX19条件・全40場を比較。初回3pt／間隔10ptは−318,722円・12黒字28赤字。間隔変更だけでは安定黒字に至りませんでした。'
    for path,prefix in [(ROOT/'README.md','アルゴリズム調査/'),(ROOT/'アルゴリズム調査/README.md','')]:
        changes.append(prepend(path,'<!--00123案内-->',f'最新：[00123：途中利確なしの新規間隔比較]({prefix}{NAME}/{REPORT})。{message}\n<!--00123案内終了-->'))
    index=ROOT/'アルゴリズム調査/index.html';raw=index.read_bytes();text=raw.decode('utf-8')
    assert '<!--00123開始-->' not in text;match=re.search(r'<main\b[^>]*>',text);assert match
    card=f'\n<!--00123開始--><article class="task latest"><div class="number">作業00123・新規間隔の比較</div><h2>初回幅と追加間隔を分けて19条件を比較</h2><p>{message}</p><a class="button" href="{NAME}/{REPORT}">19条件と全40場</a> <a href="{NAME}/README.md">読む順序</a></article><!--00123終了-->\n'
    text=text[:match.end()]+card+text[match.end():]
    text=text.replace('最新00120では段階トレーリングの114条件・全40場を検証。各場の損益と、残在庫・反復損失の具体箇所を確認しています。',
        '最新00123では途中利確なしの新規間隔を19条件・全40場で比較。各場の損益と実際の取引枚数を掲載しています。')
    index.write_bytes(text.encode('utf-8'))
    changes.append(dict(path=index.relative_to(ROOT).as_posix(),before_sha256=hashlib.sha256(raw).hexdigest(),after_sha256=sha(index)))

    # ----------------------------------------
    # 数量と安定性を分けた入口知見、計算前に発見した実装反例を保存する。
    common=ROOT/'アルゴリズム調査/共通/知見台帳'
    changes.append(prepend(common/'README.md','<!--00123案内-->',
        f'最新は[00123：途中利確なしの新規間隔比較](../../{NAME}/README.md)。幅の拡大で損失額が減っても黒字場数が増えるとは限らないことを入口へ記録。引数上書きの人工反例も売買の工夫へ残しました。\n<!--00123案内終了-->'))
    source=f'**出典：** [00123_途中利確なしの新規間隔比較](../../{NAME}/README.md)。[19条件と全40場](../../{NAME}/{REPORT})。'
    changes.append(append(common/'入口.md','<a id="00123_広い新規間隔は数量と勝ち場を同時に減らす"></a>',
        '## 新規間隔の拡大で合計損失は縮んだが、黒字場数はほぼ増えなかった\n\n'+source+'\n\n'
        '**当時条件・分母：** TOPIXミニ片方向10枚、途中返済なし、引け前6分BBO代理。gap1/2/3/4/5/6/8/10/12/15ptで初回3pt固定と初回gapを比較。3/3重複を統合した19条件×同じ既知40場。気配幅上限1pt・判断後不利許容0.5pt・新規締切は固定。新720会計、基準40は保存引用。\n\n'
        '**実測：** 初回3固定の3pt間隔は11黒字29赤字・−1,031,046円、653枚。10ptは12黒字28赤字・−318,722円、271枚。1枚平均netも−1,579円程度から−1,176円へ改善したため数量減だけとは断定しないが、安定黒字には至らない。9月24日黒字は＋91,188円→＋18,844円で勝ちも縮んだ。初回も15ptの15pt間隔は6黒字33赤字1無・−255,406円、133枚、1枚平均−1,920円。黒字数最多の4/4も13/40・−830,018円。\n\n'
        '**費用との分離：** 全19の費用控除前合計も負。3/10は費用22,222円、費用前−296,500円、費用後−318,722円。手数料だけの問題としない。上位3黒字を除いても全19合計負。全40中央値・赤字規模・無取引・枚数も併記し、取引を減らしただけの赤字縮小を安定性と呼ばない。\n\n'
        '**範囲・限界：** 同じ既知40場からの事後比較であり、最小赤字の間隔が将来最適とはしない。日経、途中利確との同時変更、相場に応じた間隔切替はこの比較では未測定。'))
    changes.append(append(common/'継続.md','<a id="00123_上限未到達でも両方向の保有が赤字になる"></a>',
        '## 反対方向の枚数が元の玉を上回っても、両側の建値が不利なら回収できない\n\n'+source+'\n\n'
        '**条件・分母：** 初回3pt・間隔10pt、途中利確も損切りも無しの固定比較で、事後に赤字上位3場を診断。3/3以外の初回3固定群では合計赤字が最小だったが、新しい予測優位の確認ではない。\n\n'
        '**具体的な3/3場：** 10月1日ナイトは買4枚／平均4119.625・売6枚／平均4101.667→終端bid4104／ask4105.5。買−62,828円、売−23,492円、合計−86,320円。10月13日デイは買4売5で−73,738円、9月29日デイは買2売6で−59,656円。全3場で両側赤字だが片側10枚には未到達。上限ロックだけを原因としない。\n\n'
        '**どの玉か：** 9月29日09:04:34の買4089.5は終端4062.5で−27,082円、14:35:14の売4037は終端4063.5で−26,582円。局所反発で買った玉が残り、安値圏で足した売りも後の回復で損失となる。最初の不利な玉を、反対側を増やすだけで必ず救えるわけではない。\n\n'
        '**費用と値動き：** 10月1日ナイトのLast移動損益−75,500円から、入口BBO対Last差3,000円、終端差7,000円、費用820円を引いて−86,320円。10月13日は−69,500円から入口差−1,000円（有利）・終端差4,500円・費用738円、9月29日は−50,500円から2,500円・6,000円・656円を引く。三場とも手数料を除くだけでは赤字は消えない。\n\n'
        '**全場の飽和との区別：** 初回3固定の両側10枚到達はgap1で38/40場、gap3で8/40場、gap10で0/40場。10ptでも28/40場が赤字なので、飽和を無くすことだけでは解決しない。同数qの終端netは（売建値合計−買建値合計）×1000−q×終端気配幅×1000−82×2q。基準3/3の9月25日ナイトは買平均4116.2／売4107.35で建値差−88,500円、終端幅−5,000円、料−1,640円、合計−95,140円。基準の平均建値は旧NPZを再読せず監査済み方向別損益と終端から逆算した。[飽和集計](../../../work/stability123_20261017/audit/result/十九条件の両側飽和場数と固定建値差の独立集計.json)。\n\n'
        '**限界：** 損失場に条件付けた会計診断であり、当時の回復を見分ける確率や、どちらを返せばよかったかの因果効果は未測定。三場の未来から保有判断を選び直さない。[保存注文と分解](../../../work/stability123_20261017/adversary/formal_gap10_loss/I3_G10赤字上位三場の注文と値動き及び費用分解.json)。'))
    changes.append(append(common/'売買の工夫.md','<a id="00123_通常高速同値だけでは引数の意味の誤りを検出できない"></a>',
        '## 通常版と高速版の一致だけでは、初回距離の上書き誤りを検出できない\n\n'+source+'\n\n'
        '**金融前の反例：** 初回距離を引数initialに追加したが、既存の初回玉損益の局所変数もinitialだったため初回約定後に距離を上書きした。Python/JITの全配列一致でも両方が同じ誤りを再現した。独立した外部期待線の人工で期待2枚に対し誤10枚となり、実データ読取・金融会計・正式登録前に発見して旧源と証跡を保全した。\n\n'
        '**修正・分母：** 損益局所だけentry_netへ改名。全19条件の初回・後続10段と上下鏡像を価格から独立計算し、旧3/3の全返却物一致、新安値で旧建値不変、gap15でも固定気配ガード、代理UID/費用を43人工・340確認で照合。修正後だけを固定・登録・金融実行した。\n\n'
        '**意味・限界：** 計算の同値確認と売買意図の外部期待値確認は別に必要。修正前の人工偽合格を市場成績に数えず、人工の成功率を価格予測力へ転用しない。根拠は00123のadversary保存証跡。'))
    changes.append(prepend(ROOT/'アルゴリズム調査/調査方針.md','<!--00123最新指定-->',
        '## 2026年10月17日の新規間隔比較\n\nユーザーの間隔変更依頼に対し、途中利確なし・引け一括のまま、初回幅と追加段間隔を別引数で比較した。入口の気配幅や不利許容は拡大せず固定。全40場の収支・黒赤無・中央値・最悪・枚数を示し、間隔を広げて数量が減っただけの赤字縮小を安定黒字と扱わない。19条件とも目標未達。\n<!--00123最新指定終了-->'))

    # ----------------------------------------
    # この試行行だけ完了にし、他の試行の意味内容を保持する。
    ledger=MANAGER.parent/'data/trials.json';oldraw=ledger.read_bytes();data=json.loads(oldraw)
    old={r['id']:json.dumps(r,ensure_ascii=False,sort_keys=True) for r in data['trials'] if r['id']!=TRIAL}
    row=next(r for r in data['trials'] if r['id']==TRIAL);assert row['status']=='未実行'
    save(HERE/'試行終了前の登録行.json',row)
    reference=dict(path=resultpath.relative_to(ROOT).as_posix(),sha256=RESULT)
    accounting=dict(financial_accounts=720,reused_baseline_accounts=40,conditions=19,sessions=40,
        previous_financial_replay=0,original_market_reads=0,current_API=0,real_orders=0)
    row.update(status='検証完了',completed_result=reference,
        completed_audits=[dict(path=auditpath.relative_to(ROOT).as_posix(),sha256=auditsha)],
        completed_registered_sources=fixed['sources'],completed_fixed=dict(path=(HERE/'固定計画.json').relative_to(ROOT).as_posix(),sha256=sha(HERE/'固定計画.json')),
        completion_accounting=accounting,result='TOPIX19条件は全40場合計がすべて赤字。初回3pt間隔10ptは−318,722円・12黒字28赤字。取引枚数と赤字額は減ったが安定黒字に至らず。',
        readme=f'アルゴリズム調査/{NAME}/README.md',report=f'アルゴリズム調査/{NAME}/{REPORT}',
        completion_limitations='同じ既知TOPIX40場の開発比較。引け前6分のBBO代理精算。日経未検証。Last評価は同じ玉の感応度。',
        execution_attempts=[dict(status='検証完了',result=reference,accounting=accounting,independent_evidence=False)])
    assert old=={r['id']:json.dumps(r,ensure_ascii=False,sort_keys=True) for r in data['trials'] if r['id']!=TRIAL}
    history=MANAGER.parent/'data/history/00123_終了前の試行台帳.json';assert not history.exists();history.write_bytes(oldraw)
    data['updated_at']=datetime.now(timezone.utc).isoformat()
    ledger.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    process=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),'build'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    save(HERE/'試行終了後の閲覧同期.json',dict(終了コード=process.returncode,stdout=process.stdout,stderr=process.stderr))
    assert process.returncode==0,process.stderr[-1000:]
    save(HERE/'案内と分類別知見及び試行終了.json',dict(passed=True,changes=changes,old_trials_unchanged=True,
        completed_trial=TRIAL,report_sha256=reportsha,new_financial_replay=0))
    print('案内・分類別知見・試行終了を反映しました。',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--audit-sha',required=True);parser.add_argument('--report-sha',required=True)
    args=parser.parse_args();main(args.audit,args.audit_sha,args.report_sha)
