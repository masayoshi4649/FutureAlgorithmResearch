"""保存された数量診断だけから、無観測と時間の限界を明確にした小結を作る。"""

import copy
import json
from pathlib import Path

from diagnose import OWN, ROOT, digest, rate, save


def main() -> None:
    """
    機能: 数量更新を一度も観測できない窓を未知へ分け、固定対照を再集計する。
    引数: なし。保存済み小診断JSONだけを読み、原本・NPZ・金融を読み直さない。
    返り値: Noneは簡潔な結論と入力指紋を私有領域へ保存する。
    """
    p = OWN/'板数量と直前30秒の全33対照.json'
    data = json.loads(p.read_text(encoding='utf-8')); records = copy.deepcopy(data['全場'])
    changes = []
    for record in records:
        if not record['実入口あり']:
            continue
        for event, item in record['入口'].items():
            qty = item['直前30秒']['量']
            if qty['買板']['有効連続更新'] == 0 or qty['売板']['有効連続更新'] == 0:
                changes.append({'session': record['session'], 'symbol': record['symbol'], '時点': event,
                    '旧観点値': item['直前30秒']['固定観点']['反対表示量回復優勢'], '新観点値': None,
                    '理由': '十段の連続数量更新が一度もなく、回復優勢を観測できない'})
                item['直前30秒']['固定観点']['反対表示量回復優勢'] = None
    comparison = rate(records)
    examples_path = OWN/'赤字上位3の本物の数量と原板推移.json'
    examples = json.loads(examples_path.read_text(encoding='utf-8'))['例']; small_examples = []
    for example in examples:
        times = example['時点']; paper = times['紙上新規公開']['直前30秒']; fill = times['実指値到達']['直前30秒']
        small_examples.append({'session': example['session'], 'symbol': example['symbol'], '場収支': example['場収支'],
            '最初の損失親収支': example['最初の損失親']['収支'], '方向': example['最初の損失親']['方向'],
            '紙上新規時計': paper['価格時計'], '紙上新規bid': paper['bid'], '紙上新規ask': paper['ask'],
            '実指値到達時計': fill['価格時計'], '実指値到達bid': fill['bid'], '実指値到達ask': fill['ask'],
            '実返済時計': times['最初の損失親の返済']['直前30秒']['価格時計'],
            '紙上公開の固定観点': paper['固定観点'], '実到達の固定観点': fill['固定観点'],
            '当時買板の表示回復厚さ比': fill['量']['買板']['減少後回復_厚さ比'],
            '当時売板の表示回復厚さ比': fill['量']['売板']['減少後回復_厚さ比']})
    widths = []
    for example in examples:
        for event, source in example['時点'].items():
            for point in source['板推移']['前後板']:
                distance = point['実差秒']
                if distance is not None and abs(distance) > 30:
                    widths.append({'session': example['session'], 'symbol': example['symbol'], '時点': event,
                        '指定差秒': point['指定差秒'], '実価格時計差秒': distance,
                        '扱い': '30秒内の観測ではない。時計間隙を示す近傍参考に限る。'})
    firstline = {'対象': 'book/TOPIX/2026-09-24_Night.jsonl', '読取': '先頭1行のみ', '先頭行価格時計': '2026-09-24T15:39:58+09:00',
        '観測した時刻欄': ['TradingVolumeTime','CurrentPriceTime','PreviousCloseTime','OpeningPriceTime','HighPriceTime','LowPriceTime'],
        'その行に存在しない欄': ['ReceivedAt','BuySellTime','BidTime','AskTime','書込時刻'],
        '限界': '場前残存値の一行。これだけで原本全行の任意時刻欄の不存在までは保証しない。',
        '先頭行SHA': None, '先頭行SHA注記': '最初のschema確認時に行SHAは採取していない。原本再読して作らない。'}
    entry_count = {}; parent_count = {}; inactive = {}
    for symbol in ('TOPIX', 'NK225'):
        subset = [item for item in records if item['symbol'] == symbol]
        entries = [item for item in subset if item['実入口あり']]
        assert len(subset) == 33
        entry_count[symbol] = len(entries)
        parent_count[symbol] = {'件数':sum(item['初回親収支'] > 0 for item in entries),'分母':len(entries)}
        inactive[symbol] = len(subset)-len(entries)
    output = {'全合格': True, 'scope': '全33初回実入口の固定量観点・保存診断の補正集計のみ',
        '新金融': 0, '原本追加読取': 0, 'NPZ再読': 0, '全実入口数': entry_count,
        '初回親黒字': parent_count, '無取引場': inactive, '数量未観測を未知へ分離': changes, '対照': comparison,
        '具体的負け6場':small_examples, '時計間隙で30秒外となった近傍参考':widths,
        '原本時刻schemaの一行確認':firstline,
        '読取失敗履歴': {'種類':'schema事前probeのKeyError','誤仮定':'normal_execution_to_raw_index',
            '実在列':'execution_to_raw_index','金融':0,'修正':'npz.filesで列を確認。診断本実行は最初から正しい原seq接続。'},
        '結論': [
            '今回の四固定観点は、両商品共通で初回親の負けを安定して選別できるとは言えない。',
            '紙上公開の相手反対は両商品とも3件中2件が親黒字。反対だけで除外すれば実際の勝ちも除外する。',
            '紙上公開で反対板回復が優勢でもTOPIXは6件中6件が親黒字、日経は3件中2件が親黒字。補充量の多さを単純な逆行予告とは呼べない。',
            '指値到達時に自己支持気配が後退していた親も、TOPIX20/23、日経20/25が黒字。戻りを待つ指値はその条件を意図的に多く踏む。',
            'TOPIX9/24Nightは買い判断18:31:27から実到達18:37:16までに自己買気配4055→4053.5、相手反対も続き、実到達時の方向代理量が半減していた。しかし同様の代理量半減でも実到達TOPIX9/11、日経4/5が親黒字。',
            '日経9/28Nightは売り判断18:08:41のbid65330から到達18:17:40の65370へ反対に4tick動いた。到達直前は買側の同価格回復厚さ比1.94、売側0.24で、相手も売り方向に反対だった。これだけで全場へ通じる除外則にはならない。',
            '指値到達行で初めて見えた悪化を、同じ行で取消して未約定だったことにはできない。待機中の以前の観測による取消、または約定後の管理が別途必要。',
            '最終価格の時計が止まっても保存板は大量に更新する。受信時計を持たない資料で実秒単位の板予測を証明することはできない。',
            '数量だけの新金融試行を今増やす根拠は弱い。まず受信時計で測れる入力を今後保存し、今回の数量観点は失敗知見として保持する。'],
        '事象の区別': '親の手数料後黒字と場の手数料後黒字を別分母で掲載。方向のいつか到達確率や先着確率ではない。',
        'source': {str(p.relative_to(ROOT)):digest(p), str(examples_path.relative_to(ROOT)):digest(examples_path),
            str((OWN/'diagnose.py').relative_to(ROOT)):digest(OWN/'diagnose.py'),str(Path(__file__).relative_to(ROOT)):digest(Path(__file__))}}
    save('数量観点と時計定義の簡潔な結論.json', output)
    print('数量未観測補正', len(changes), '結論保存合格', flush=True)


if __name__ == '__main__':
    main()
