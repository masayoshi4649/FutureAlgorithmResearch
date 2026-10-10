"""損益を読む前に固定する、多思想の注文管理カタログ。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent
OLD = OUT.parent/'wave_v23'
if str(OLD) not in sys.path:
    sys.path.insert(0,str(OLD))
import managers as legacy
from engine import PARAMS

ENTRIES = [
    ('小幅を長く待つ',{'entry_mode':0,'entry_atr':.1,'ttl_seconds':600.}),
    ('標準の順行確認',{'entry_mode':0,'entry_atr':.25,'ttl_seconds':120.}),
    ('大きな順行を確認',{'entry_mode':0,'entry_atr':.5,'ttl_seconds':300.}),
    ('小幅の新規追跡',{'entry_mode':1,'entry_atr':.25,'ttl_seconds':300.}),
    ('深い戻りの新規追跡',{'entry_mode':1,'entry_atr':.5,'ttl_seconds':600.}),
    ('次観測で成行',{'entry_mode':2,'entry_atr':.25,'ttl_seconds':120.}),
]

# 機構が共通の幅違いも明示し、名称だけ変えた同一条件は具体的な両銘柄設定で除外する。
DESIGNS = [
    ('固定１枚','基準の追跡',{},'一定の損切りと追跡で方向信号だけの効果を測る。','継続しない往復で損切りが積み重なる。'),
    ('固定１枚','狭い初期損失',{'stop_atr':.5},'初回の誤判断を半ATRで認める。基準と同じ機構の狭幅対照。','雑音による連続損切りが増える。'),
    ('固定１枚','長い波を保持',{'stop_atr':1.5,'main_trail':3.,'activation_atr':1.5,'timeout_min':540.},'初期の揺れを許容し長い波を保持する。同じ追跡機構の広幅対照。','反転時の利益返上と初期損失が大きい。'),
    ('固定１枚','追跡を早く有効化',{'main_trail':1.,'activation_atr':.5},'小さな順行から追跡返済を有効にする。','早い押し戻りで長い波から降りる。'),
    ('固定１枚','建値保護',{'breakeven_atr':.75},'0.75ATR進めば組全体の最低損益をゼロへ上げる。','細かな往復で同値返済と再注文を繰り返す。'),
    ('固定１枚','建値より利益を残す',{'breakeven_atr':1.,'breakeven_floor':.2},'1ATR進めば最低0.2ATR相当を保護する。建値保護の床を変える対照。','一時的な戻りで早く降りる。'),
    ('固定１枚','最高利益の四分の一を保護',{'lock_fraction':.25,'main_trail':3.},'最高含み益が初期リスクを超えれば25%を保護する。','75%の返上を許すため急反転で効率が下がる。'),
    ('固定１枚','最高利益の半分を保護',{'lock_fraction':.5},'最高含み益の50%を組全体の最低損益へ反映する。','大波の途中の深い戻りで降りる。'),
    ('固定１枚','利益拡大後に幅を縮める',{'main_trail':2.5,'tighten_atr':2.,'tight_width':.75},'2ATR進むまでは広く、進んだ後は0.75ATRへ追跡幅を縮める。','２段階境界付近の利益が経路に強く依存する。'),
    ('固定１枚','短い期限で見切る',{'timeout_min':30.},'30分で予測の期限切れとして全返済する。','緩やかな数時間の波を途中で切る。'),
    ('固定１枚','中程度の期限で見切る',{'timeout_min':90.},'90分で全返済する。時間撤退の長さを変える対照。','反転が早ければ時間退出前に利益を返す。'),
    ('固定１枚','進まない玉だけ損失を縮める',{'failure_min':10.,'failure_mfe':.5,'failure_stop':.35},'10分で0.5ATR進まなかった玉の許容損失を0.35ATRへ縮める。','遅れて始まる波を損切りする。'),
    ('固定１枚','失敗判定と建値保護を両立',{'failure_min':15.,'failure_mfe':.5,'failure_stop':.35,'breakeven_atr':1.},'進まない玉は損失縮小、伸びた玉は建値保護に分ける。','失敗と成功の判定境界が細かな変化に敏感。'),
    ('固定１枚','反対根拠で撤退',{'signal_exit':1},'反対方向を検知すれば次の観測で全返済する。','短い誤信号で保有を切らされる。'),
    ('固定１枚','中立の継続で撤退',{'neutral_min':5.},'中立が５分続けば方向の根拠消失とみなす。','一時的に板根拠が弱まるだけでも降りる。'),
    ('固定１枚','反対根拠で実反転',{'reverse_mode':1,'max_reversals':3},'反対根拠で返済と反転を同時に行い、反転は区間３回まで。','往復信号が続くと反転が連続損失になる。'),
    ('固定１枚','逆行を伴う時だけ実反転',{'reverse_mode':2,'max_reversals':3},'反対信号に加え主玉が0.75ATR以上逆行した時だけ反転する。','利益中の大きな転換への反応が遅れる。'),
    ('固定１枚','同方向２連敗で休止',{'max_same_losses':2,'rearm_atr':1.},'２連敗後は反対信号か出口から1ATR順行まで再注文しない。','損切り直後の本当の転換へ参加が遅れる。'),
    ('固定１枚','再開を厳しくする連敗休止',{'max_same_losses':3,'rearm_atr':2.},'３連敗後は2ATRの順行まで待つ。連敗休止の復帰幅を変える対照。','損失が増えてから止まり、再開が遅い。'),
    ('固定１枚','セッション損失を２Rで制限',{'session_budget_r':2.},'最初の注文時リスク２回分で区間の新規を停止し全返済する。','前半の損失で後半の大波も見送る。'),
    ('固定１枚','連敗と３R予算を組み合わせる',{'max_same_losses':2,'session_budget_r':3.},'同方向の連敗と区間全体の損失の両方を止める。','同方向の小刻みな再武装で細かな損切りが続く場合がある。'),
    ('固定１枚','米国開始後に追跡を短縮',{'signal_exit':1,'after_open_factor':.7},'米国開始後は追跡を70%へ縮め、反対信号も返済理由にする。','値動き拡大時ほど狭い幅で振り落とされる。'),
    ('固定１枚','米国開始帯で全休止',{'us_mode':1},'米国開始15分前から30分後まで新規を止め、保有も返済する。','その時間に発生する大きな初動を捨てる。'),
    ('固定１枚','米国開始帯の新規だけ停止',{'us_mode':2},'同じ米国開始帯は新規だけ止め、既存玉の価格管理を継続する。','保有玉は突発変動を受け続ける。'),
    ('可変枚数','共通円リスク',{'risk_yen':20000.},'呼値丸め後の初期損切りが２万円以下となる整数枚数を決める。','低ATRでは枚数が増え、想定以上の飛びに弱い。'),
    ('可変枚数','共通円リスクと複合防御',{'risk_yen':10000.,'session_budget_yen':30000.,'max_same_losses':2,'signal_exit':1,'breakeven_atr':1.,'lock_fraction':.5},'初期１万円、区間３万円、連敗停止、方向撤回、利益保護を統合する。','保護条件が重なり利益の芽も早く切る。'),
    ('複数玉','部分利確と建値保護',{'quantity_fraction':.5,'split_target':1.,'breakeven_atr':.75,'main_trail':1.5},'上限半分で開始し1ATRで半分を整数切捨てで利確、残りを保持する。','先に閉じる利益玉だけを見ると損失玉を過小評価する。'),
    ('複数玉','遠い部分利確と長い残玉',{'quantity_fraction':.5,'split_target':2.,'main_trail':3.,'activation_atr':1.5},'2ATRまで待って一部を利確し、残りは3ATR追跡で伸ばす。','利確まで届かず多枚数の損失になる。'),
    ('複数玉','利益中だけ一定枚数を追加',{'quantity_fraction':.1,'add_fraction':.1,'add_mode':1,'add_step':1.,'lock_fraction':.5,'signal_exit':1},'上限10%から1ATRごとに10%を追加。当初の組リスクは増やさない。','押し戻りで追加直後の玉がまとめて損失になる。'),
    ('複数玉','利益中だけ段階倍増',{'quantity_fraction':.1,'add_fraction':.1,'add_mode':3,'add_step':1.,'lock_fraction':.5,'signal_exit':1},'順行時に現在主玉と同程度を追加。片方向上限と初期組リスクを維持。','後半へ枚数が偏り、小さな戻りで全体利益が減る。'),
    ('複数玉','利益中の追加を徐々に小さく',{'quantity_fraction':.25,'add_fraction':.1,'add_mode':4,'add_step':1.,'lock_fraction':.5,'signal_exit':1},'現在枚数が増えるほど追加枚数を小さくし過熱時の集中を抑える。','最初の枚数が相対的に大きく誤判断の損失が先行する。'),
    ('複数玉','半量カバーで押し戻りを受ける',{'quantity_fraction':.5,'hedge_ratio':.5,'hedge_trigger':.75,'cover_trail':.5,'lock_fraction':.5},'直近の有利価格から0.75ATR戻ったら逆向き半量を建て、全玉合算で管理する。','往復で両脚の損失が累積し、両建て自体は利益源にならない。'),
    ('複数玉','カバーを新主玉へ昇格',{'quantity_fraction':.5,'hedge_ratio':.5,'hedge_trigger':.75,'cover_trail':.5,'reverse_mode':1,'max_reversals':2,'lock_fraction':.5},'逆向きカバーを持ち、反対根拠が確定したら旧主玉を閉じカバーを主玉へ昇格。','誤反転では過去の損失を残したまま新主玉も損失になる。'),
]


def canonical(spec: dict) -> str:
    """機能: 両銘柄へ具体化した全パラメータから重複判定用の文字列を作る。

    引数: spec (dict)。返り値: 安定した設定表現 (str)。
    """
    values = []
    for symbol in ('TOPIX','NK225'):
        cfg = legacy.make_config(spec,symbol,{})
        values.append({key:float(cfg[key]) for key in PARAMS+['audit_cap']})
    return json.dumps(values,sort_keys=True,separators=(',',':'),allow_nan=False)


def catalog() -> list[dict]:
    """機能: 原型20条件と新管理思想×６入口を、重複なしで返す。

    引数: なし。返り値: 既存 make_config に対応する管理条件 (list[dict])。
    条件決定に価格・損益・ファイルの結果を参照しない。
    """
    result,seen = [],set()
    for old in legacy.manager_catalog():
        scope = '複数玉' if any(key in old['changes'] for key in ('quantity_fraction','add_mode','hedge_ratio')) else ('可変枚数' if old['changes'].get('risk_yen',0)>0 else '固定１枚')
        item = dict(old,family=f'{scope}／原型比較')
        key = canonical(item)
        if key not in seen:
            seen.add(key);result.append(item)
    for index,(scope,name,changes,logic,counterexample) in enumerate(DESIGNS):
        for entry_index,(entry_name,entry) in enumerate(ENTRIES):
            item = {'id':f'D{index:02d}{entry_index}','name':name+'＋'+entry_name,
                    'family':scope+'／'+name,'description':logic+' 新規は'+entry_name+'。',
                    'changes':{**changes,**entry},'反証':counterexample,'管理設計番号':index,'入口設計番号':entry_index}
            key=canonical(item)
            if key not in seen:
                seen.add(key);result.append(item)
    assert 100<=len(result)<=300 and len(seen)==len(result)
    assert all(set(item['changes'])<=set(PARAMS)|{'quantity_fraction','add_fraction'} for item in result)
    return result


def main() -> None:
    """機能: 新成績を見ずに条件と反証計画を固定し、日本語の設計表を保存する。

    引数: なし。返り値: なし (None)。既存の固定と不一致なら停止する。
    """
    specs=catalog()
    path=OUT/'管理条件の固定.json'
    if path.exists():
        old=json.loads(path.read_text(encoding='utf-8'))
        if old['条件']!=specs:
            raise ValueError('既存の管理条件固定と不一致です')
    else:
        payload={'固定時刻':datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),'新成績参照':False,
                 '元条件数':len(legacy.manager_catalog()),'設計系統数':len(DESIGNS),'入口設計数':len(ENTRIES),
                 '重複除去前':len(legacy.manager_catalog())+len(DESIGNS)*len(ENTRIES),'一意条件数':len(specs),'条件':specs}
        path.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    note=['# 注文管理の発見条件','',f'原型20条件と{len(DESIGNS)}管理系統×６入口を具体化し、両銘柄の全設定が同一の条件を除いて **{len(specs)}条件** に固定した。新しい損益は参照していない。',
          '', '６入口は小幅0.1ATR/10分待ち、標準0.25ATR/２分待ち、大幅0.5ATR/５分待ち、追跡0.25ATR/５分、小さくない追跡0.5ATR/10分、次観測成行。成行も同じ行では約定しない。',
          '', '管理機構は固定追跡、初期損失、追跡開始、建値保護、含み益比例保護、段階短縮、保有期限、進まない玉、方向撤回、中立撤回、即時反転、逆行確認反転、連敗停止、再開条件、区間損失予算、米国開始の幅変更、全休止、新規休止、ATR逆比例枚数、部分利確、一定追加、倍増追加、逓減追加、限定カバー、カバー昇格を含む。同機構の幅違いも表に明記し、それだけを独立の思想数として扱わない。',
          '', '固定１枚を中心とし、可変枚数・複数玉をfamilyで分離する。複数玉の円額だけで１枚条件より優秀とは判定しない。TOPIXミニ片方向10枚、NK225マイクロ片方向20枚。初期/追加枚数の割合は切捨て最低１枚、部分利確は保有半分を整数切捨て。',
          '', '|区分|管理思想|論理|主な反証|','|---|---|---|---|']
    for scope,name,changes,logic,counterexample in DESIGNS:
        note.append(f'|{scope}|{name}|{logic}|{counterexample}|')
    note += ['', '## 実装上の共通条件','',
             '費用０・指定価格約定。設置時に通過済みの価格条件は次観測実価格で執行する。新規締切は返済基準５分前、場末は日中15:35/夜間05:50に返済指示して次観測で執行する。損失予算は保証価格ではない。',
             '', '方向切替の信号も全て同じ口座へ渡し、含み損を含む全玉の会計を評価する。増玉は利益がある時だけで初期組リスクを増やさない。反転・カバーでも過去の損失は消えない。',
             '', '## 次巡に回す未実装思想','',
             '- 負けている玉の価格格子追加、注文ごとの独立OCO、複数価格の同時待機。既存engineには必要な注文状態がないため今回含めない。',
             '- 日中から夜間への口座リスク連結、セッション累積利益を守る日次追跡、実ボラでの動的追跡再拡張。現engineと異なる状態設計が必要。',
             '- 委託待ち行列・出来高制約・約定照合と取消競合、明示的通信遅延。指定価格の主条件とは別の執行モデルが必要。',
             '- 別価格の複数エントリーを同時に監視する二方向ブレークアウト、建玉ごとの独立時間期限。現engineの単一pending/組期限では正確に表現できない。']
    (OUT/'manager_design.md').write_text('\n'.join(note)+'\n',encoding='utf-8')
    print(json.dumps({'一意条件数':len(specs),'設計系統数':len(DESIGNS),'元候補保有':all(any(r['id']==v for r in specs)for v in ('G00','G08','G18'))},ensure_ascii=False))


if __name__=='__main__':
    main()
