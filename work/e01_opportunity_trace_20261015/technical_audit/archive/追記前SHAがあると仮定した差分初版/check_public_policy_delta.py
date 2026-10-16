"""根の三留保追記だけを旧指紋へ逆変換し、公開文書は変更せず確認する。"""

import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def main() -> None:
    """
    機能: 現在二文書を同bytesで読み、三留保追記と既方針の保持を静的確認する。
    引数: なし。
    返り値: None。別証跡をtechnical_auditへ保存し、公開/共通へ書き戻さない。
    """
    previous=HERE/'公開方針の心理仮説と観測限界の静的監査.json'
    before=json.loads(previous.read_text(encoding='utf-8'))
    public=ROOT/before['公開文書'];policy=ROOT/before['方針文書']
    raw=public.read_bytes();policyraw=policy.read_bytes();restored=raw
    added='表の「買い／売り活動」は、取得できる出来高更新と気配による方向代理の略称で、真の攻撃注文方向とは区別する。'
    highnew='接触前に確定・保存した高値等';highold='当時までの高値等'
    pivot='押し安値は、実際に認定できた行とその時刻を保存する。後の反発を見て安値と認定した場合、その資格を過去の安値行へ巻き戻さない。'
    assert raw.count(added.encode('utf-8'))==raw.count(highnew.encode('utf-8'))==raw.count(pivot.encode('utf-8'))==1
    restored=restored.replace(added.encode('utf-8'),b'')
    restored=restored.replace(highnew.encode('utf-8'),highold.encode('utf-8'))
    newline=b'\r\n' if b'\r\n' in raw else b'\n'
    restored=restored.replace(pivot.encode('utf-8')+newline+newline,b'')
    oldsha=before['文書SHA256'][public.relative_to(ROOT).as_posix()]
    oldpolicy=before['文書SHA256'][policy.relative_to(ROOT).as_posix()]
    assert hashlib.sha256(restored).hexdigest()==oldsha,'三追記以外の差分あり。公開を変更せず根へ確認する。'
    assert hashlib.sha256(policyraw).hexdigest()==oldpolicy,'調査方針にも変更あり。本文差を別に確認する。'
    text=raw.decode('utf-8-sig')
    assert '勝率や収支はまだ測っていない' in text and '同一主体の補充と断定できない' in text and '新規／返済・隠れ注文は今回の板から確定できない' in text
    proof=dict(全合格=True,範囲='SOURCE_ONLY。旧表現の留保を明確化した差分だけ。金融又はアルゴリズム有効性の合格ではない。',
        旧証跡SHA256=hashlib.sha256(previous.read_bytes()).hexdigest(),現在文書SHA256={p.relative_to(ROOT).as_posix():hashlib.sha256(v).hexdigest() for p,v in ((public,raw),(policy,policyraw))},
        三追記だけを除くと旧公開文書SHA一致=True,調査方針SHAは旧監査時点と同値=True,
        確認=['売買活動は方向代理の略称と明示。','突破の参照高値は接触前に確定・保存。','押し安値は認定行と時刻を保存し過去行へ巻き戻さない。'],
        未測定と観測限界の記述維持=True,共有公開編集=0,金融=0,原入力=0,巨大cache=0,元API=0)
    target=HERE/'公開方針への三留保追記と二文書指紋の差分監査.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
