"""源契約・窓差の純人工・未固定の三入口案を保存し、実入力や金融を開始しない。"""

import hashlib
import json
from pathlib import Path

import window_evidence

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCES=(
    'work/wave_v106/trade_gate/votes.py','work/wave_v106/e01_trade_gate/prepare.py',
    'work/wave_v106/e01_trade_exit/features.py','work/wave_v106/e01_trade_exit/prepare.py','work/wave_v106/e01_trade_exit/rebind_input.py',
    'work/e01_opportunity_trace_20261015/prepare_v2/analysis.py','work/e01_opportunity_trace_20261015/prepare_v2/run.py',
    'work/e01_fak_evidence_20261014/engine/core.py','work/e01_fak_evidence_20261014/engine/catalog.py',
    'work/e01_fak_evidence_20261014/engine/price_votes.py','work/e01_fak_evidence_20261014/engine/entry_gate.py',
    'work/e01_protect_reentry_20261014/engine/core.py','work/e01_protect_reentry_20261014/engine/catalog.py',
    'work/e01_price_exit_ablation_20261014/engine/core.py','work/e01_entry_information_20261014/engine/entry_gate.py')


def digest(path: Path) -> str:
    """
    機能: 許可source又はownedの小資料をSHA256へ結ぶ。
    引数: path(Path) は検査対象。
    返り値: str は指紋。cache/金融本文には使わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint() -> dict:
    """
    機能: 提案に使ったsourceと私有純算術を開始終端で束縛する。
    引数: なし。
    返り値: dict はpath/SHA256。旧sourceへimportせずJITを書かない。
    """
    paths=[ROOT/name for name in SOURCES]+list(HERE.glob('*.py'))
    return {p.relative_to(ROOT).as_posix():digest(p) for p in sorted(paths)}


def run() -> None:
    """
    機能: 純範囲和を検査して最小観測・三入口・旧対照・未確定点を保存する。
    引数: なし。
    返り値: None。アルゴ運転/正式freeze/登録/大本文/金融/APIは0。
    """
    target=HERE/'現在窓と新反対更新の最小観測及び三入口の準備案.json';assert not target.exists()
    before=fingerprint();art=window_evidence.self_check();assert fingerprint()==before
    art.update(source_SHA256=before,JSON保存確認=True)
    artifact=HERE/'窓差と新方向更新の下限を集合和で検算する純人工.json';assert not artifact.exists()
    artifact.write_text(json.dumps(art,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    value=dict(全合格=True,状態='SOURCE_ONLYの観測理論と提案。新金融条件/新entry実装/入力読取は未固定。',
        source_SHA256=before,人工SHA256=digest(artifact),説明MD_SHA256=digest(HERE/'現在参加の最小観測と三入口の準備案.md'),
        比較元=dict(id='E01_EVID_VOL_SELECTED_TARGET',scope='111の元E01 PUB一回。TOP W60 .5/NK .25、保存結果参照は根が後に固定。'),
        能力元='112 TradeGate33＋TradeExit33のstrictjoin/PUB同値/当時paper方向と全normal別母集団。新取引効果の証拠ではない。',
        最小列=dict(volume=['known','reason','up_votes','down_votes','first_vote_raw_row','candidate_raw_row','candidate_raw_seq','candidate_price_time_s'],
            identity=['同source_SHA256','window_seconds','normal順序','既知連続flag','TradeGate.mapping'],
            quote=['bid','ask','quote_valid','record.price','record.seq','record.time_s','start','limit','tick'],
            optional_paper=['feed全10列','quiet','quiet_force'],
            保存されない=['最後に実方向票が生じたrawseq/時刻','正常行間の全raw BBO','主体/約定と取消の区別','受信時刻/真の攻撃量/保有平均原価']),
        結合必須=['同session/商品のrecord/quotes型shape/値/欠測位置一致','候補原row==mapping、seq/clock==record',
            'PUB signedと全normal unsignedの符号一回/known零票/unknowndebugを照合','最終TradeExit目録＋finite clock補完＋corrected代理sourceの指紋を結ぶ'],
        窓差の定義=dict(counter='固定side買ならdown、売ならup。総票/balance差を反対活動としない。',
            preconditions='同源/同W、前後knownかつ間のnormalが既知連続、candidate rawrow/seq前進・clock非逆行、窓始rawrow非後退。',
            formula='ΔC=A\u2032−E\u2032。A\u2032=count[max(s1,r0+1),r1]、E\u2032=count[s0,min(s1,r0+1)−1]。',
            exact='窓始不変なら新方向票の追加数。',lower_bound='窓始前進では正増分だけ新反対proxy票の存在下限。非重複窓も集合差で扱う。',
            cannot_infer='差が0/負でも新票なしとは言えない。最後の新票seq/時刻をcandidateへ補完しない。',
            empty='canonical known零票＋first=-1だけ空範囲first=candidate+1。正票数でfirst欠落なら停止。',
            windows='10/30/60は同じ更新を再掲するため独立票として合算0。初案はW60一つ。'),
        候補母集団=[dict(id='E01_CURRENT',scope='paper方向が当時活動中の継続区間だけ。旧PUBを持越さず現在窓再審査。',用途='111への条件付き参考・非金融対照。全市場機会にはしない。'),
            dict(id='ALL_NORMAL_STRUCTURE',scope='paper zero中も含め全normalのBUY/SELL。現在flowと接触前固定Lから独立eventを生成する提案。',用途='新三入口の共通母集団を推奨。')],
        三入口案=[dict(id='CURRENT_VOL_SEL',条件='現在W60 known/min2/side balance TOP .5 NK .25。'),
            dict(id='CURRENT_VOL_SEL_PRICE_BOTH',条件='VOL_SEL＋現在自己/strict過去peerのW60 known/各min2/side balance .25。'),
            dict(id='CURRENT_VOL_PRICE_RESPONSE',条件='前項＋固定L接触後の新反対proxy票存在＋観測normal両BBO逆進行なし＋後別rawrowの両BBO再順行で初公開。')],
        共通候補案=dict(level='直前確定5分足高値BUY/安値SELLを第一案。認定rowは接触前、接触後L固定。',
            event='当時観測した抜け→接触→後の両気配1観測T再進行を逐次確認。未来押し安値/勝ち方向で再描画0。',
            current_evidence='新方向proxy更新の正差をfresh存在下限として扱う案。未知→既知は新票証明にせず新比較基準を初期化。',
            consumed='支持episodeは公開試行で一回消費。拒否/busy/FAK失効を旧根拠で復活0。後参加には新現在根拠と新構造episode。',
            quote_path='観測normalの途中逆進行を端点回復で隠さない。非normal/未知で証明を中断、全raw維持/吸収を断定0。'),
        比較の共通案=dict(quantity={'TOPIX':10,'NK225':20},pricing='手数料注文別floor/正常bidask/公開固定0T1T一回FAK→初normalでfill又は失効。',
            allowance='現在両price票known/min2/.75なら1T、他0T。到着BBOを過去公開maskへ混ぜない。',
            exits='Native TARGET/TIGHT_TRAIL/WIDE_TRAIL、親/場リスク/quiet/期限を同条件にする案。具体係数は根の正式固定待ち。',
            main_goal='TOP全33session net平均100000円＋金額比65/赤字20/最大赤字<=平均黒字。NK円床未指定。'),
        未確定点=['全normal方式でpaper全撤回reason151を使えないため、Native退出共通化と111比較の構造差を明示する必要。',
            '共通構造Lは確定5分高安を第一案、MAは同時走査せず別事前固定。',
            '全normal候補event/episodeの消費・flat後fresh再開始、現在票/quote未知の取消境界は実装前に根が固定。',
            '全登録の8部品重複照合は正式条件決定後に根が実施。現案を未測金融と扱う。'],
        旧試行との差=[dict(source='111',差='元PUB一回のVOL_SELと強price時FAK許容。現在全normal公開や構造応答eventは無い。'),
            dict(source='112',差='資格観測の非金融診断。新エントリー/忙しい状態/収益を運転していない。'),
            dict(source='108',差='paper方向内のprice geometry PULL/BREAK追加。fresh出来高代理＋当時確定L＋反対更新へのquote反応を検証していない。'),
            dict(source='109',差='反対price票による退出枝をOFFにした継続対照。現在入場の情報・構造応答ではない。'),
            dict(source='110/111',差='volumeは旧paper公開rowだけ、FAK許容一部品対照。volumeを後rowへ流用しない既範囲。')],
        今後人工=['同源同W/未知連続/失効/非重複/空窓の数学境界','同clock自己原row上限/peerstrict過去/age',
            'unsigned sign一回・元PUB値持越し0','確定水準の接触前固定/足の未来suffix/認定row巻戻し禁止',
            'BBO途中逆進行→端点回復を支持維持へ誤認0','episode一回消費/失効後新根拠のみ/同paperと非paperの母集団分離',
            'Native実UID/q/予約/fees/quiet/期限/nextnormal・未来prefix'],
        金融前条件='根がSOURCE_ONLY論点と少数差分の正式値を固定→実装/人工/有効源指紋/8部品照合→登録→唯一新金融。現在はここまで進めない。',
        読取=dict(sourceのみ=True,実cache=0,元金融本文=0,元実台帳=0,原NPZ=0,原book=0,API=0,新金融=0,正式登録=0))
    assert fingerprint()==before
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('SOURCE_ONLY三入口準備、純集合和 '+str(art['算術照合'])+' 検査。金融/大本文/API0。提案SHA '+digest(target),flush=True)


if __name__=='__main__':run()
