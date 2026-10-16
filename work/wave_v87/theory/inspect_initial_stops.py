"""既存の条件・コード・保存台帳だけから、初期停止幅の重複試行を確認する。"""
from pathlib import Path
import gzip
import hashlib
import json

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent


def read_result(identifier):
    """
    機能: 既存00065の観測価格再生結果を読む。
    引数: identifier(str)。
    返り値: dict。新たな売買再生は実行しない。
    """
    path=ROOT/'work/wave_v68/observed'/(identifier+'.json.gz')
    return json.loads(gzip.decompress(path.read_bytes()))


def compare(original,changed,symbol):
    """
    機能: 同じ初回注文の親組を対応させ、旧勝ちと旧負けの変化を分ける。
    引数: original/changed(dict)、symbol(str)。
    返り値: dict。保存された全料金後台帳のみを集計する。
    """
    left={(v['session'],v['symbol']):v for v in original['ledgers']}
    right={(v['session'],v['symbol']):v for v in changed['ledgers']}
    pairs=[]
    for key,a in left.items():
        if key[1]!=symbol:continue
        b=right[key]
        assert [o for o in a['orders'] if o[7]]==[o for o in b['orders'] if o[7]]
        ga={int(c[0]):sum(t['収支'] for t in a['trades'] if t['組']==int(c[0])) for c in a['cycles']}
        gb={int(c[0]):sum(t['収支'] for t in b['trades'] if t['組']==int(c[0])) for c in b['cycles']}
        assert ga.keys()==gb.keys()
        pairs.extend((v,gb[cid]) for cid,v in ga.items())
    fields=('net','campaign_profit','campaign_loss','campaign_wins','campaign_losses','campaigns','positive_sessions')
    return dict(初回注文完全一致=True,対応親組数=len(pairs),
        元勝ち組数=sum(a>0 for a,b in pairs),元勝ちから赤字=sum(a>0 and b<0 for a,b in pairs),
        元勝ち組の収支差=sum(b-a for a,b in pairs if a>0),元負け組の収支差=sum(b-a for a,b in pairs if a<0),
        全親組の収支差=sum(b-a for a,b in pairs),
        既存期間={period:dict(元={field:original['periods'][period][symbol][field] for field in fields},
            変更={field:changed['periods'][period][symbol][field] for field in fields}) for period in ('前16','後12','全28')})


def main():
    """
    機能: 既往・未同条件・実験価値を区別した短い日本語資料を保存する。
    引数: なし。
    返り値: None。新条件の実装・新損益・公開レポート変更を行わない。
    """
    sources=['work/wave_v49/early/run.py','work/wave_v49/early/条件の事前固定.json',
        'work/wave_v67/replay.py','work/wave_v67/engine_shadow.py','work/wave_v68/risk_replay.py',
        'work/wave_v68/run_study.py','work/wave_v68/事前固定.json','work/wave_v71/study.py',
        'work/wave_v85/catalog.py','work/wave_v85/strategy.py','work/wave_v86/catalog.py',
        'work/wave_v86/strategy.py','work/wave_v87/round1/catalog.py','work/wave_v87/round1/strategy.py']
    baseline=read_result('R01')
    results={identifier:{symbol:compare(baseline,read_result(identifier),symbol) for symbol in ('TOPIX','NK225')}
        for identifier in ('R01_S50','R01_S375')}
    sources += ['work/wave_v68/observed/'+name+'.json.gz' for name in ('R01','R01_S50','R01_S375')]
    result=dict(
        範囲='コード・固定条件・保存済み損益の読取整理だけ。新売買再生、新条件実装、公開変更なし。',
        結論='同じ思想は既に試行済み。元GUのU回避・全30場で停止0.25/0.5/0.75/1ATRの四つを直接比較した固定試験は、確認した既往にはない。ただし未開拓の手法とは言えない。',
        最も近い既往=dict(公開='00065',実装='work/wave_v68/risk_replay.py',
            条件=['R01','R01_S50','R01_S375'],期間='既知28場、前16/後12',
            同じ部分='R01は現在のE01_G相当。EMA入口再確認、通常影の新規時計、広い3ATR追尾、3ATR順行後0.75ATR短縮、2ATR部分返済、B00半減、初回5/10枚を維持。初期stop_atrだけ0.75→0.5/0.375。',
            違う部分='米国現物開始前後のU回避なし。10/09の昼夜は当時の入力にない。0.25と1ATRはこのR01対照に含まれない。',
            実装確認='通常影baseには変更stopを渡さず、modifiedだけへ反映。gate_badは通常影から計算し、早期全返済しても通常影終了後5分まで待つ。保存初回注文は全件一致。'),
        更に古い既往=dict(実装='work/wave_v49/early/run.py',
            条件='E00停止1ATR、E01停止0.75ATR、E02停止0.5ATRを、通常影・広い3ATR出口・途中半減を保って比較。現在の原E01はこの0.75ATR案から来ている。',
            違い='16場・指定価格・手数料0。GとUなし。1ATRへの変更も新しい思想ではない。'),
        指定資料の確認=[
            dict(公開='00068',実装='wave_v71',判定='別のティック入口と保険方式。元玉停止32呼値固定で追尾幅8〜24呼値を比較し、元GU初期停止の直接対照ではない。'),
            dict(公開='00081',実装='wave_v85',判定='G/P/D/CとJ/Uの25条件。GUの停止0.75ATRは固定。'),
            dict(公開='00082',実装='wave_v86とphase2',判定='5出口×時計4と黒字後のみの高速再参加10条件。追尾始動/追尾幅は変えるが停止0.75ATRは固定。'),
            dict(公開='00083 第1段階',実装='wave_v87/round1',判定='停止0.25/0.5/0.75は比較済み。ただし出口はT2幅0.5ATR、黒字後60秒P1再参加であり、元GUの広出口・通常時計と違う。'),
            dict(公開='00083 第2〜9段階',判定='部分確保・支持・数量・独立保険の対照。コアGUの停止は固定。第7〜9段階の停止幅変更は保険だけで、元GUの初期停止変更ではない。')],
        旧R01の保存台帳比較=results,
        何が起きたか='0.75→0.5で元負けの金額は両商品とも改善したが、元勝ちの取り逃しがそれを上回った。利益を伸ばす出口を広いまま残しても、途中の狭い損切りで先に終了すれば後の上昇・下落の利益は取れない。',
        実装上の重要な区別='旧stop_atrは出口影の初期数量×固定ATRに対する損失予算であり、永続する単純な建値±幅ではない。2ATRの影部分利確後は、既実現と残影数量から同じ予算を守る線へ更新する。実B00半減後の実口座損失上限とも同じではない。固定価格の逆指値を新設するなら別仮説と明示する。',
        残る検証価値=dict(判定='限定的な再現確認としてはある。新たな方向優位の発見と扱う価値は低い。',
            狙い='U回避が旧停止比較の負け方を変えるか、追加2場でも旧勝ちを壊す機構が残るか、0.25で削減効果が飽和するか、1で回復勝ちを残す利益が追加損失を上回るかを分ける。',
            最低比較='通常影と入口・初回数量・B00根拠・広出口・U予定を完全固定し、出口影の損失予算だけ変える。停止0.75対照はGU完全一致を要求。',
            評価='同一初回原本行＋方向で対応し、旧負けの改善額と旧勝ちの取り逃し額を全件示す。新勝ち/負けの集合だけでは再分類で損失削減を誤解する。前16/後14、各銘柄、料金前後、最大下落と最悪場を併記。',
            反例='先に0.5ATR逆行した後3ATR以上順行する元勝ちを、狭い停止は捨てる。反対に最初から0.75ATRまで逆行する元負けでは損失を減らせる。最終方向を見てどちらだけを選ぶことはしない。',
            限界='1ATRは0.75より名目損失予算が三分の一増える。0.25はより呼値丸め・価格飛びに敏感。設定幅が実際の損失上限を保証するわけではない。'),
        次の作業='この確認段階では実装も新損益も行わない。再生する場合も既往R01_S50との重複範囲・Uとの相互作用を明記し、旧失敗を未検証扱いにしない。',
        参照SHA256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources})
    (HERE/'元GUの初期停止幅と既往対照の確認.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('既存台帳だけの初期停止比較と重複確認を保存',flush=True)


if __name__=='__main__':main()
