"""既存の再生結果を読み、結論の範囲と反証を独立に整理する。"""
from pathlib import Path
import hashlib
import json


BASE = Path(__file__).resolve().parents[1]
SYMBOLS = ('TOPIX', 'NK225')
FIELDS = ('profit', 'loss', 'net', 'trades', 'profit_share', 'profit_loss_ratio',
          'payoff', 'drawdown', 'winning_sessions', 'losing_sessions',
          'no_trade_sessions', '利益変化', '損失削減', '収支変化')


def read_json(path):
    """
    機能: UTF-8 の既存証拠を読む。
    引数: path (Path) は対象ファイル。
    返り値: dict または list の保存済み情報。
    """
    return json.loads(path.read_text(encoding='utf-8'))


# ----------------------------------------
def compact(data):
    """
    機能: 比較に必要な会計値だけを抽出する。
    引数: data (dict) は既存の会計集計。
    返り値: dict は選択した会計値。
    """
    return {k: data[k] for k in FIELDS if k in data}


# ----------------------------------------
def main():
    """
    機能: 再生済み 54 条件の足算を照合し、主張と限界を保存する。
    引数: なし。
    返り値: None。既存証拠の参照のみで、取引再生は行わない。
    """
    source = BASE / 'analysis/全条件の効果.json'
    effects = {x['id']: x for x in read_json(source)}
    pairs = read_json(BASE / 'analysis/同じ新規の勝ち損失と新規経路.json')['条件']
    fixed = read_json(BASE / '事前固定.json')
    files = [source, BASE / 'analysis/同じ新規の勝ち損失と新規経路.json', BASE / '事前固定.json']
    checked = 0
    for delay in (1, 5, 15):
        result_dir = BASE / 'results' if delay == 5 else BASE / f'sensitivity/delay{delay}/results'
        for ident, effect in effects.items():
            path = result_dir / f'{ident}.json'
            result = read_json(path)
            files.append(path)
            for symbol in SYMBOLS:
                rows = [r for r in result['rows'] if r['symbol'] == symbol]
                assert len(rows) == 30
                for row in rows:
                    assert row['net'] == row['profit'] - row['loss']
                    assert row['net'] == row['gross'] - row['fees']
                for key in ('profit', 'loss', 'net', 'trades', 'fees', 'gross'):
                    value = sum(r[key] for r in rows)
                    assert value == result['periods']['全30'][symbol][key]
                    assert value == effect['遅延'][str(delay)][symbol][key]
                if delay == 5:
                    for period in effect['期間']:
                        assert effect['期間'][period][symbol]['net'] == result['periods'][period][symbol]['net']
                    for period in effect['期間']:
                        a = effect['期間'][period][symbol]
                        assert a['収支変化'] == a['利益変化'] + a['損失削減']
                    pair = pairs[ident][symbol]
                    decomposition = (
                        pair['元勝ち対応の収支変化'] + pair['元負け対応の収支変化']
                        - pair['元勝ち未対応の元利益'] + pair['元負け未対応の元損失']
                        + pair['新規経路収支'])
                    assert decomposition == effect['期間']['全30'][symbol]['収支変化']
            checked += 1

    comparisons = {}
    for ident in ('E0_X0', 'E0_X1', 'E0_X2', 'E1_X0', 'E2_X0', 'E4_X0', 'E5_X0'):
        effect = effects[ident]
        comparisons[ident] = {
            '入口': fixed[ident[:2]], '出口': fixed[ident[3:]],
            '基準5秒': {period: {s: compact(v) for s, v in values.items()}
                       for period, values in effect['期間'].items()},
            '遅延別全30': {delay: {s: compact(v) for s, v in values.items()}
                        for delay, values in effect['遅延'].items()},
            '同じ新規の対照': pairs[ident],
        }

    output = {
        '結論': '今回の追加条件を両商品共通の改善として採用する根拠は得られない。基準J2は比較の土台として残るが、全日安定・金額利益8割を達成した手法ではない。',
        '新取引再生': False,
        '再選定': False,
        '会計の独立照合': {
            '再生結果ファイル数': checked, 'セッション会計行数': checked * 60,
            '全件合格': True,
            '項目': ['各行の利益−損失＝収支＝売買損益−手数料',
                   '各商品の30場合計と保存集計と比較資料の一致',
                   '5秒の全期間で収支変化＝利益変化＋損失削減',
                   '5秒の同新規・未対応・新経路の分解合計と全再生収支差の一致'],
            '範囲': '保存済み会計の独立な足算確認。信号の再計算や約定の再生は行っていない。'
        },
        '短い説明': [
            '両市場が一緒に動いたという入口根拠は、その後30分の継続を保証しない。支持が本当にあってから逆転した負けもあり、欠測通過だけが主因ではない。',
            '逆行を早く認めるX1は赤字上位3場を改善したが、回復して利益になる取引も切る。全30ではTOPIX−156,928円、NK225−156,760円へ悪化した。',
            '同じ入口だけでも、X1による元勝ちの悪化が元負けの改善を上回る。早期撤退後の新規経路も赤字であり、再エントリー回数だけを抑えても今回の優位は説明できない。',
            'OFIの強い支持・追いかけ防止・距離加重の板厚は、それぞれ一部の悪い入口を消すが、利益になる入口も消す。強い支持の必須化や板厚追加だけで解決したとは言えない。',
            '損失の縮小と利益の維持を同時に満たす選別は未解決。今回の結果は、板読み一般が無価値だという証明でも、将来も基準が勝つという証明でもない。'
        ],
        '主張別の判定': [
            {
                '主張': '幅が広いので狭めれば解決する', '判定': 'この結論は支持されない。全ての狭幅を否定したわけでもない。',
                '理由': '今回は0.4%幅を固定し、追加の価格逆行確認で早く退出するX1/X2を試した。X1はTOPIXの全損失を308,264円減らす一方、全利益を1,198,312円減らした。NK225では利益が631,400円減り、全損失も13,000円増えた。',
                '補足': '元負けへの改善は、総損失削減と同じ量ではない。元勝ちが負けに変わることと新経路の取引があるため。トレール幅そのものの最適値は今回の試験で識別していない。'
            },
            {
                '主張': '両OFIの支持を必須にすれば解決する', '判定': '今回の定義では否定される。',
                '理由': 'E1_X0は5秒でTOPIX+33,184円、NK225+250,640円。基準から699,936円・237,000円減り、1/5/15秒すべてで両商品の収支が悪化した。最悪場にも明確な支持のあった損失が残る。',
                '補足': 'OFIは記録された気配変化に基づく支持であり、注文者の動機や今後の継続注文を観測したものではない。'
            },
            {
                '主張': '根拠価格からの追いかけを止めれば解決する', '判定': '局所的な改善はあるが、共通の改善として未確立。',
                '理由': 'E2_X0は5秒のTOPIX最悪3場を235,000円改善した一方、全30ではTOPIX−159,148円・NK225−244,920円の差。相対効果は1/5/15秒で符号が混在する。',
                '補足': 'E2は旧入口candidate[3]の参照行と発注判断行の自己気配を比較する。追加J2確認の5秒格子の参照行や未来の約定値とは比較していない。遅延ごとに根拠・入口も変わるため、これは同一発注の純粋な約定遅延ストレスとは異なる。'
            },
            {
                '主張': '板厚を見れば解決する', '判定': '今回の距離加重板の追加条件では支持されない。',
                '理由': 'E5_X0は全30でTOPIX+47,412円、NK225+179,440円。損失は減るが利益減少が上回り、1/5/15秒すべてで両商品の収支が基準以下。TOPIXの後14は−135,884円。',
                '補足': '試したのは両方の距離加重表示数量が入口に逆らわない条件。補充・取消・隠れ注文・大口の意図を識別できたとは言わない。'
            },
            {
                '主張': '滑らかな一方向相場だけ選べば両商品で解決する', '判定': '片側の少数標本に可能性があるだけで、共通解ではない。',
                '理由': 'E4_X0はNK225の金額利益比77.0%・17組だが、TOPIXは−150,884円・19組。NK225の一部遅延で8割に達しても、両商品の共通性や安定性の証明にはならない。'
            }
        ],
        '確かめられたこと': [
            '観測された短期の逆行を15秒確認する機械的な返済は、当該大損失例の損失を実際に縮小できた。',
            'その確認は黒字取引中の押し戻しでも発生し、今回の固定ルールでは利益を守る判別にならなかった。',
            '今回の主案X1/X2は、3種類の遅延すべてで全30の両商品を赤字にした。これは今回の条件を採用しない根拠になる。',
            '基準J2は30場全体・前16・後14・3遅延で両商品黒字を維持した。ただし既知標本内の事実であり、全場黒字でも金額利益8割でもない。'
        ],
        '未解決': [
            '継続する短期反転と、元方向へ回復する押し戻しを、判断時点の情報だけで区別すること。',
            '表示数量の変化が成行約定・取消・新規補充のどれに由来するか。今回の原本スナップショットだけでは一意に判別できない。',
            'ラージ気配によるミニ/マイクロの仮想約定と、実商品の板での約定との差。',
            '今回の既知30場で設計された対策が、新しく集まる場でも利益を維持するか。'
        ],
        '将来の案_全て未検証': [
            '即時の全量撤退ではなく、逆行確認時だけ一部を減らして回復を待つ数量管理。ただし方向予測が改善するとは限らず、同じ実効建玉の比較が必要。',
            '高値・安値を更新できなくなった経過と、更新時の価格進展量・表示数量変化を組み合わせる持続性判定。新しい閾値は将来データを見る前に固定する。',
            '先に少量で入る段階的投入。最大損失の減少だけでなく、同じ倍率で小さくした基準との利益/損失比を対照にする。'
        ],
        '比較資料': comparisons,
        '全18条件の5秒要約': {k: {s: compact(v) for s, v in x['期間']['全30'].items()} for k, x in effects.items()},
        '条件への留保': [
            '赤字上位3場は結果から選んだ事後診断標本。そこでの改善を未知データへの効果と呼ばない。',
            '全30場は既知。残27場・対象外25場も未見ではない。診断標本への偏りを点検する比較である。',
            '最悪場を減らした手法へ後から本命を差し替えない。今回の18条件を超える探索や閾値調整は行っていない。',
            'TOPIXmini10枚・NK225micro20枚の費用後会計を各商品内で比較し、円金額を商品間で合算しない。'
        ],
        '出典SHA256': {str(p.relative_to(BASE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    }
    path = BASE / 'report/結論レビュー.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'保存': str(path), '結果照合ファイル数': checked, '会計行数': checked * 60}, ensure_ascii=False))


if __name__ == '__main__':
    main()
