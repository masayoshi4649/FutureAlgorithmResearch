"""実保有ピーク及び活動数を安定指標の分母にする反例を、正式損益前に固定する。"""

import hashlib
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def measure(nets: list[float], quantities: list[int], multiplier: float, opening: float, denominator: int) -> float:
    """
    機能: 同じ場損益に任意の保有数量尺度及び平均母数を適用して下方偏差を求める。
    引数: nets(list[float])、quantities(list[int])、multiplier/opening(float)、denominator(int)。
    返り値: floatは負収支のみの二乗和を母数で平均した平方根。
    """
    assert denominator > 0 and len(nets) == len(quantities)
    assert all(quantity > 0 for quantity in quantities)
    return math.sqrt(sum((min(net,0.)/(quantity*multiplier*opening*.001))**2
                         for net,quantity in zip(nets,quantities))/denominator)


def main() -> None:
    """
    機能: 未使用枠、短い増玉、両建て、活動追加及び縮小の人工比較を保存する。
    引数: なし。
    返り値: None。新しい理論JSONだけを書き、実板又は新正式候補の損益を計算しない。
    """
    results = []
    for symbol,base,extra,cap,multiplier,opening,fee_unit in (
            ('TOPIX',8,2,10,1000.,4000.,41.8),('NK225',16,4,20,10.,68000.,11.)):
        unit = base*multiplier*opening*.001
        red = -unit
        fee = 2*math.floor(extra*fee_unit+1e-8)
        base_nets = [unit*.25]*7+[red]
        zero_extra_nets = base_nets.copy()
        briefly_added_nets = base_nets[:-1]+[red-fee]
        base_peak = [base]*8
        enlarged_peak = [base]*7+[cap]
        original_peak_rms = measure(base_nets,base_peak,multiplier,opening,8)
        no_range_peak_rms = measure(zero_extra_nets,base_peak,multiplier,opening,8)
        brief_peak_rms = measure(briefly_added_nets,enlarged_peak,multiplier,opening,8)
        original_fixed_rms = measure(base_nets,[cap]*8,multiplier,opening,16)
        brief_fixed_rms = measure(briefly_added_nets,[cap]*8,multiplier,opening,16)
        assert no_range_peak_rms == original_peak_rms
        assert brief_peak_rms < original_peak_rms and sum(briefly_added_nets) < sum(base_nets)
        assert brief_fixed_rms > original_fixed_rms
        # 別の不活動場に料金だけ失う一親を加える。最大数量は両者共通に固定。
        extra_activity = base_nets+[-float(fee)]
        activity_before = measure(base_nets,[cap]*8,multiplier,opening,8)
        activity_after = measure(extra_activity,[cap]*9,multiplier,opening,9)
        calendar_after = measure(extra_activity,[cap]*9,multiplier,opening,16)
        assert activity_after < activity_before and calendar_after > original_fixed_rms
        # 同じ価格経路の枚数縮小は数量当たり尺度では一致し、固定上限尺度では実額減少になる。
        small = [net*extra/base for net in base_nets]
        small_peak_rms = measure(small,[extra]*8,multiplier,opening,8)
        small_fixed_rms = measure(small,[cap]*8,multiplier,opening,16)
        assert abs(small_peak_rms-original_peak_rms) < 1e-12
        assert small_fixed_rms < original_fixed_rms
        results.append({'商品':symbol,'始値':opening,'倍率':multiplier,'元枚数':base,'追加枚数':extra,'上限':cap,
                        '元赤字':red,'追加玉の価格損益':0.,'追加往復料金':fee,'追加後赤字':red-fee,
                        '実peak単位の元赤字':1.,'実peak単位の追加後赤字':(unit+fee)/(cap*multiplier*opening*.001),
                        '未稼働rangeと純J8のpeak指標一致':True,
                        '短い増玉':{'元実peak活動RMS':original_peak_rms,'増玉実peak活動RMS':brief_peak_rms,
                                    '悪化した実額なのに指標改善':True,
                                    '元固定上限全16場RMS':original_fixed_rms,'増玉固定上限全16場RMS':brief_fixed_rms,
                                    '固定上限は悪化を悪化と判定':True},
                        '追加活動の母数反例':{'元活動場数':8,'追加活動場数':9,'元活動RMS':activity_before,
                                               '追加活動RMS':activity_after,'追加実額損失':fee,
                                               '活動赤字場増加でも指標改善':True,
                                               '全16固定母数なら悪化':calendar_after>original_fixed_rms},
                        '数量縮小':{'実peak単位なら同率':True,'固定上限単位なら実額損失の縮小を反映':True,
                                     '価格損益だけの相似例':'実手数料の注文別端数に完全相似を仮定せず、正式対照では実数量会計を使う。'},
                        '両建て反例':{'一時gross枚数':cap,'一時net枚数':base-extra,
                                     '未ヘッジ時net枚数':base,'解釈':'gross peakの増加は方向リスクの増加と一致しない。gross分母を安定収益の主尺度にしない。'}})
    report = {'全人工合格':True,'対象':'正式損益前の評価分母の数理反証。新候補又は保存場成績ではない。',
              '人工両商品':results,
              'actualpeak案の認める改善':'rangeが全く稼働しないM82と純J8が完全同じ経済なら、実peakも同じとなり未使用設定枠の差を消せる。',
              'actualpeak案で残る反証':'同じ赤字経路へ短時間の増玉を加えて追加料金を失っても、peak分母が増えて主RMSを改善できる。両建てgross peakはnet方向リスクとも異なる。',
              '独立提案':{'主の比較単位':'全条件共通のユーザー上限TOPIX10/NK20×倍率×各場最初正常価格0.1%。設定又は事後実保有量で分母を書き替えない。',
                            '主の平均母数':'同じ評価期間の全場数を固定。前16は16、後15は15、全31は31。負収支二乗和による順位も同じ。',
                            '活動判定':'20親・8活動場の候補集合を維持。無取引を活動黒字率の勝ちにしない。',
                            'quantity縮小の解釈':'実額損失縮小は運用リスクの削減として記す。価格方向又は入口出口の改善と同じにせず、同数量源対照で別に評価する。',
                            '診断':'設定及び実peak当たりの活動RMSは数量効率の診断として併記し、主の実運用損失の順位と分ける。'},
              '固定尺度の限界':['小さい数量は小さい実額損失を作る。十分な実収益と活動、金額80%・損小利大・最大利益日除外を別に満たす必要がある。',
                                '固定尺度でも場内の大きな含み下落や稀な未出現大損を保証しない。全玉清算時価最大下落・最悪場・方向別の確認は必要。',
                                '全場数固定のRMSで不活動は実損失0として扱うが、黒字又は成功の場へ数えない。全無取引は活動条件を満たせない。',
                                '全条件共通の0.1%単位は市場ごとの金額を揃える比較尺度。停止保証・証拠金・予測成功率ではない。'],
              '売買条件変更':0,'事前主変更':0,'80%目標変更':0,
              '正式新損益閲覧':0,'新保存場損益計算':0,'現在API取得':0,'実注文':0,
              'SHA256':{str(Path(__file__).relative_to(ROOT)):hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    path = HERE/'実保有ピークと活動母数の安定指標への敵対的反証.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'資料':str(path),'SHA256':hashlib.sha256(path.read_bytes()).hexdigest(),
                      '全人工合格':True,'正式損益計算':0},ensure_ascii=False))


if __name__ == '__main__':
    main()
