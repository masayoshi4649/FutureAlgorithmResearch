"""追加一場・前場IV固定十二条件を、比較元と独立人工に拘束して登録する。"""

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from common124 import HERE,ROOT,SCENE,read,save,sha

MANAGER=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
TRIAL='124_追加一場の凍結評価と前完了場IV固定十二条件'


def binding(path: Path) -> dict:
    """
    機能: 小目録と独立証跡を位置・同一性で結ぶ。
    引数: path(Path)は既存の固定資料。
    返り値: dictはrepo相対pathとsha256。
    """
    return dict(path=path.relative_to(ROOT).as_posix(),sha256=sha(path))


def main(grid_audit: Path) -> None:
    """
    機能: 全source・原本copy・前場IV・二人工合格を八部品仕様へ固定する。
    引数: grid_audit(Path)は市場を使わない独立人工の完成証跡。
    返り値: None。登録前の金融、未見10月19日損益の探索をしない。
    """
    paths=[HERE/n for n in ('common124.py','stage124.py','register124.py')]
    paths+=sorted((HERE/'grid').glob('*.py'))
    paths+=sorted((HERE/'e01').rglob('*.py'))
    paths += [HERE/'e01/legacy_root'/p for p in ('work/wave_v38/探索条件の固定.json','work/wave_v44/探索条件の固定.json','work/wave_v27/hierarchy_design_fixed.json')]
    sources={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
    e01_art=HERE/'e01/同bytes源と固定二設定及び新日付の純人工.json'
    assert sha(e01_art)=='9175d44975debd076c6887693d93913595cbe61e4dd6594afa6d91d2e3436860'
    assert read(e01_art)['passed'] and read(grid_audit)['passed']
    artificial=read(grid_audit)
    for key,name in [('engine_sha256','engine123.py'),('core_sha256','core123.py'),('catalog_sha256','catalog124.py')]:
        assert artificial[key]==sha(HERE/'grid'/name),name
    for p,h in read(e01_art)['sources'].items():assert sources[p]==h,p
    assert sha(HERE/'grid/core123.py')=='03866bc8e3319fa15633a69597ded1aafca4507407de5f996bf0578c69d666f8'
    features=HERE/'options/前完了場IV固定特徴.json'
    assert sha(features)=='e36cb5c69bb45a0ab2c3cec91ed6edac1e06ea164083d04b0351135a43d1b443'
    old=ROOT/'work/stability123_20261017/途中利確なしの十九間隔と全四十場.json'
    assert sha(old)=='91475e3757d4a9462f1ecc9405c43e76145967693b0802c56e73068dd0db416c'
    fixed=dict(sources=sources,input_manifest=binding(HERE/'追加原本入力目録.json'),
        quote_manifest=binding(HERE/'保存気配八十入力と追加一場の参照.json'),option_features=binding(features),
        old_gap_result=binding(old),e01_artificial=binding(e01_art),grid_artificial=binding(grid_audit),
        old_e01_result=binding(ROOT/'work/stability119_20261017/v6_resume/measurement/少額E01固定二設定の追加七場と全四十場.json'))
    save(HERE/'固定計画.json',fixed)

    # ----------------------------------------
    # 同じ既知40場の再探索と、追加1場の固定比較を分けて記録する。
    proposal=dict(id=TRIAL,name='追加一場と前場IVによる幅・枚数調整',purpose='新データ',
        question='既存候補は追加デイでも保てるか。前完了場IVによる幅・枚数の変更で、両先物の各場安定性は改善するか。',
        change='新10月19日Dayを固定E01二商品と旧十九間隔へ追加。新オプションは受信時刻を場内に復元せず前完了場末尾から次場固定IVを作り十二条件比較。',
        repeat_reason='追加先物一場と未検証入力家族であるオプション。旧40の同じ完成会計は引用し、同じパラメータの運転は共有。全過去未整理に重複なしとは宣言しない。',
        compares_to=['123_TOPIX途中利確なしで初回距離と新規段間隔を比較','119h_少額E01の時計逆行行除外による入力停止修正'],
        evidence=[binding(grid_audit),binding(e01_art),binding(HERE/'audit/比較元と旧四十場境界及びオプション重複の事前照合.json'),
            binding(HERE/'inventory/オプション時刻の採用可否.json')],
        spec=dict(
            entry=dict(旧固定='少額E01のTOP G50_ADAPT75_P1、NK G25_ADAPT100_P1を数値同bytes接続。旧十九間隔はTOPだけ追加一場へ同じ仕様。',
                新比較='正常Last極値+(initial+j*spacing)*unitで買い、売りは対称。一枚ずつ、初回一枚予約。TOP unit1pt、NK unit20円固定。新規spread<=unit、不利<=unit/2。',
                IV='前完了場の当場月より後の最小限月、C/P各最大3、absDelta .25〜.75内で.5に近い順。IV1〜200%の中央値。既知11/不明30、当場IVを使わない。'),
            management=dict(固定十二='O00なし、O01gap sqrtR、O02gap R、O03initial sqrtR、O04initial R、O05両sqrtR、O06両R、O07両R+cap減、O08両/R、O09cap減、O10固定3/10、O11固定15/15。',
                尺度='R=clip(前場IV%/30,.5,2)。通常initial/spacing3。幅は観測呼値へ上丸め、IV高時capはfloor(cap/max(1,R))。不明ならO00通常設定へ戻す。'),
            exit=dict(保持='新比較は途中利確・損切りなし、予定Day15:45/Night06に引け直前6分内の最後正常BBO代理精算。通常約定と専用終端台帳を分離。',
                旧E01='既存のATR・親目標・減量・損失停止と場内finishを同bytes維持。'),
            allocation=dict(上限='TOPIXミニ片方向10、NKマイクロ片方向20。新比較一注文一枚。O07/O09だけ前場IVで減量。',
                分母='全41場、旧40/追加1、IV既知11/不明30を分ける。無取引と活動zero、黒赤/中央値/最大赤字/上位3黒字除外/枚数を掲載。'),
            costs=dict(手数料='TOPIXmini41.8円/片道、NKmicro11円/片道。各注文全額で切捨て。新比較一枚ごと往復82/22円。気配差は別に含む。'),
            execution=dict(新規='判断より後の最初正常原行BBO、Buy1買/Sell1売の意味。古い価格時計の足算・sort・前値救済なし。',
                終端='買bid/売ask。ユーザー許可の引け前6分代理で実引け約定ではない。実小型板・待ち順位・真受信順は未観測。'),
            data=dict(input_manifests=[fixed['input_manifest'],fixed['quote_manifest'],fixed['option_features']],
                sessions=read(ROOT/fixed['quote_manifest']['path'])['sessions'],new_sessions=[SCENE],
                来歴='旧80所有NPZ参照、新6原本一読copy。options608原板の境界2866標本と608CSV3146足から時刻資格を診断し、前場末尾だけ使用。全9.57GB原板の全行検査ではない。',
                同値共有='TOP基準3/3・3/10・15/15の旧40は保存引用。unknownIVと同じ丸めパラメータは再金融しない。'),
            implementation=sources))
    save(HERE/'試行計画.json',proposal)
    for command,name in [('check','事前照合の全出力.json'),('register','正式登録の全出力.json')]:
        p=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),command,'--proposal',str(HERE/'試行計画.json')],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        save(HERE/name,dict(終了コード=p.returncode,stdout=p.stdout,stderr=p.stderr))
        print(command,p.returncode,flush=True);assert p.returncode==0,p.stderr[-1000:]


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--grid-audit',type=Path,required=True)
    main(parser.parse_args().grid_audit.resolve())
