"""独立監査の範囲と限界を一つの記録へまとめる。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent


def main():
    """
    機能: 完了した監査の合否と指紋を集約する。
    引数: なし。
    返り値: None。総括JSONを保存する。
    """
    names = ['原E01入力の独立照合.json', '四部品の人工境界監査.json',
             '原E01とR01の局所完全一致.json', '共同信号境界と統合版の未来切断.json',
             '時間回避境界と旧16不変の人工監査.json', '時間帯あり統合版の未来切断.json',
             '独立会計器の人工自己検査.json', '全25条件二モデルの独立会計監査.json',
             '時間帯指定の対象外不変とJU合成一致.json', '公開HTMLの数値と解釈監査.json']
    evidence = {}
    for name in names:
        path = HERE / name
        data = json.loads(path.read_text(encoding='utf-8'))
        assert data['全合格'], name
        evidence[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    full = json.loads((HERE / '全25条件二モデルの独立会計監査.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((HERE / 'accounts.py').read_bytes()).hexdigest() == full['コードSHA256']
    for name, expected in full['実装固定SHA256'].items():
        assert hashlib.sha256((WORK / name).read_bytes()).hexdigest() == expected
    summary = {'全合格': True,
               '対象': '原E01・4部品16組合せと、主3条件に事前指定の時間帯を加えた9条件。指定線／観測現在値の2モデル。',
               '範囲': {key: full[key] for key in ('条件数', '口座数', '注文数', '決済脚数', '組数',
                                                   'P証跡数', 'C証跡数', '時間証跡数', '原版旧一致口座数')},
               '完了': ['独立FIFO会計・注文単位料金・部分返済への新規料配分・全行時価と最大下落を照合',
                        '3,000口座の残玉ゼロ、初回枚数・片方向上限、全期間集計を照合',
                        'Pの実組評価・予約継続、Cの方向別連敗と新しい根拠による解除を照合',
                        '時間窓開始後の初有効観測での全返済と古い準備の持越し禁止を照合',
                        '旧原E01とG相当R01の224口座で注文・決済・組・金額の完全一致',
                        '74人工検査、時間制御追加前後64人工経路の元配列完全一致',
                        '時間あり統合版118途中切断・3,304配列で未来追加による過去改変なし',
                        '対象外の時間制御とJUの合成を720口座対照・15,840台帳項目で照合',
                        '公開2HTMLの全50結果と57入力指紋、主結論と部品比較の根拠を照合'],
               '証跡SHA256': evidence,
               '実装固定SHA256': full['実装固定SHA256'],
               '限界': ['3,000口座は同じ60商品セッションを条件違いで再生した数であり、独立した3,000市場標本ではない。',
                        '全30セッションは既知。前16／後14への区分は未知期間の成功を証明しない。',
                        '観測価格はラージのCurrentPriceで、小型商品の売買気配や数量消化による約定可能性は未検証。',
                        'CurrentPriceTimeと保存順で因果性を点検した。真の受信時計や通信遅延は復元していない。',
                        '時間なし初期監査は追加前エンジンの証跡。最終版は旧16不変・時間あり切断・全口座会計で別途照合した。',
                        'Pは予約後の次保存観測で返済する。最高利益の半分を約定利益として保証しない。',
                        '日本／米国市場開始の回避時間は成績ではなくユーザー指定に基づく事前固定。冬時間は時計の人工検査のみ。',
                        '基本信号を原本から再抽出する未来切断は準備担当が担当。ここでは公開済み信号から注文までを独立点検した。'],
               '採用判断との分離': '実装と会計の合格であり、両銘柄の全日黒字・金額利益割合80%・将来の安定収益の証明ではない。'}
    (HERE / '独立監査総括.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'全合格': True, '証跡数': len(evidence), '口座数': full['口座数']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
