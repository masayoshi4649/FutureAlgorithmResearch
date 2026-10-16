"""追記前SHAが未保存という時点留保を保ち、現三留保と二文書を確認する。"""

import hashlib
import json
from pathlib import Path
import shutil


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def main() -> None:
    """
    機能: 初版の比較基準誤りを保全し、現在三記述と二文書指紋を確認する。
    引数: なし。
    返り値: None。新証跡を所有域へ保存し、公開/共通の本文は変更しない。
    """
    archive=HERE/'archive/追記前SHAがあると仮定した差分初版';assert not archive.exists()
    archive.mkdir(parents=True)
    initial=HERE/'check_public_policy_delta.py';shutil.copyfile(initial,archive/initial.name)
    failed=dict(全合格=False,失敗sourceSHA256=hashlib.sha256(initial.read_bytes()).hexdigest(),
        原因='三追記を逆変換すれば旧SHAへ戻るという初版assertが失敗。初回監査のSHA採取は根の追記後だったため旧証跡も現修正版と同値。公開文書の欠陥ではない。',
        失敗箇所='check_public_policy_delta.py:32',SOURCE_ONLY=True,金融=0,原入力=0,巨大cache=0,元API=0)
    (archive/'初版Falseと基準時点の訂正理由.json').write_text(json.dumps(failed,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    previous=HERE/'公開方針の心理仮説と観測限界の静的監査.json';old=json.loads(previous.read_text(encoding='utf-8'))
    public=ROOT/old['公開文書'];policy=ROOT/old['方針文書'];raw=public.read_bytes();policyraw=policy.read_bytes();text=raw.decode('utf-8-sig')
    clauses=['表の「買い／売り活動」は、取得できる出来高更新と気配による方向代理の略称で、真の攻撃注文方向とは区別する。',
             '接触前に確定・保存した高値等',
             '押し安値は、実際に認定できた行とその時刻を保存する。後の反発を見て安値と認定した場合、その資格を過去の安値行へ巻き戻さない。']
    assert all(text.count(x)==1 for x in clauses)
    current={p.relative_to(ROOT).as_posix():hashlib.sha256(value).hexdigest() for p,value in ((public,raw),(policy,policyraw))}
    assert all(old['文書SHA256'][key]==sha for key,sha in current.items())
    assert '勝率や収支はまだ測っていない' in text and '同一主体の補充と断定できない' in text and '新規／返済・隠れ注文は今回の板から確定できない' in text
    proof=dict(全合格=True,範囲='SOURCE_ONLY。現在三留保の存在・観測限界・二文書指紋を確認したもの。金融又は実効能の合格ではない。',
        旧静的監査SHA256=hashlib.sha256(previous.read_bytes()).hexdigest(),現在文書SHA256=current,
        現在三留保確認=clauses,旧証跡に採取されたSHAと現在二文書は同値=True,
        初版Falseの訂正='初回監査のレビュー後に根が追記し、SHA採取時には既に修正版だった。旧証跡SHAを追記前として逆変換する前提を撤回。公開文書と金融sourceは変更0。',
        追記前のbyte差分証明='未確認。追記前本文bytes/SHAをこの監査は保有しない。他の変更がなかったとは独立証明しない。',
        未測定と観測限界の記述維持=True,共有公開編集=0,金融=0,原入力=0,巨大cache=0,元API=0,
        独立sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target=HERE/'現在三留保と二文書指紋及び差分基準時点の監査_v2.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
