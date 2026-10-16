"""保存小根拠とMarkdownの六群の分子分母・段階比較・参照先を確認する。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote


HERE=Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 新しい金融を行わず、過去方向予測の文書と小再加算を照合する。
    引数: なし。
    返り値: None。原NPZ・台帳・巨大金融結果は未読。
    """
    md=HERE/'過去三候補の方向予測を到達と先着に分けた確認.md'
    data_path=HERE/'旧三候補の方向到達と先着及び実取引の小根拠.json'
    data=json.loads(data_path.read_text(encoding='utf-8'))
    text=md.read_text(encoding='utf-8')
    for row in data['商品群']:
        prefix=f"| {row['候補']} | {row['symbol']} |"
        line=next(line for line in text.splitlines() if line.startswith(prefix))
        n=row['入口数']
        assert f"{n}入口／{row['活動場数']}場" in line
        assert f"{row['順行到達']}/{n}＝{row['順行到達率']*100:.2f}%" in line
        assert f"{row['順行先着']}/{n}＝{row['全入口順先率']*100:.2f}%" in line
        assert f"{row['逆行到達']}/{n}" in line and f"{row['逆行先着']}/{n}" in line
        assert line.endswith(f"| {row['未到達']} |")
    nk=next(r for r in data['商品群'] if r['候補']==3 and r['symbol']=='NK225')
    assert (nk['順行到達'],nk['順行先着'],nk['逆先着後に順行到達'])==(22,14,8)
    assert '8入口は逆側0.10%へ先に届いてから' in text
    for symbol,name in (('TOPIX','TOPIX'),('NK225','日経')):
        p=data['候補3の全力トレール'][symbol]
        assert f"{p['wins']}勝{p['losses']}敗・−{abs(p['net']):,.0f}円" in text
    assert data['NK候補3の段階']['旧判断mid同幅']['1']==14
    assert data['NK候補3の段階']['新建値からmid同幅']['1']==12
    assert data['NK候補3の段階']['開始0_11']['1']==11
    for phrase in ('既知25場','その場の事後最大順行値','未到達を除外しない','50%との未調整',
                   '未知将来も同確率','統計的有意性も主張しない','原NPZ・台帳・巨大金融結果・新金融・APIは0'):
        assert phrase in text
    links=re.findall(r'\]\(([^)]+)\)',text)
    assert all((md.parent/unquote(link)).exists() for link in links)
    proof=dict(全合格=True,MD_SHA256=hashlib.sha256(md.read_bytes()).hexdigest(),
        小根拠SHA256=hashlib.sha256(data_path.read_bytes()).hexdigest(),群数=6,保存行再加算=281,
        既知場数=25,リンク数=len(links),原NPZ=0,台帳=0,巨大金融結果=0,新金融=0,API=0,
        source_SHA256={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ('review.py','verify_md.py')},
        意味='保存された採点と文章の再照合。新たな予測力の測定・有意性証明ではない。')
    target=HERE/'過去方向予測の分子分母と説明範囲の確認.json'
    assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,MD_SHA256=proof['MD_SHA256'],証跡SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
