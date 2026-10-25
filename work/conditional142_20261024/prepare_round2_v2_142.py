"""金融開始前に見つかった親ID衝突を、源版を残して修正する。"""

from pathlib import Path

HERE=Path(__file__).resolve().parent
source=(HERE/'round2_142.py').read_text(encoding='utf-8')
source=source.replace('import run142 as first','import run142 as first\nfrom portfolio142 import merge_patrol')
source=source.replace("id='142_第二巡_活動時の早期参加と再参加と方向不一致の数量選択'", "id='142_第二巡_活動時の早期参加と再参加と方向不一致の数量選択_v2'")
source=source.replace("purpose='条件比較'", "purpose='不具合修正'")
source=source.replace("change='保有率", "change='金融開始前の独立査読でTOPIX主担当内の親IDと巡回IDの衝突を発見。専用500万台と非重複assertへ修正。旧第二巡版は金融未実行。保有率")
source=source.replace("compares_to=['142_状況判断と売買を分離した時間軸原板リスク切替']", "compares_to=['142_第二巡_活動時の早期参加と再参加と方向不一致の数量選択','142_状況判断と売買を分離した時間軸原板リスク切替']")
source=source.replace("'round2_142.py','patrol_features142.py'", "'round2_142_v2.py','portfolio142.py','patrol_features142.py'")
for word in ('計画','照合','登録'):
    source=source.replace(f'第二巡{word}142.json',f'第二巡{word}142_v2.json')
source=source.replace('first.first.round2_140.parallel(main,orders)','merge_patrol(main,orders)')
source=source.replace('first.first.round2_140.parallel(small,orders)','merge_patrol(small,orders)')
destination=HERE/'round2_142_v2.py';assert not destination.exists();destination.write_text(source,encoding='utf-8')
print('旧第二巡版を保持してID衝突を修正しました。金融再生は未実行です。')
