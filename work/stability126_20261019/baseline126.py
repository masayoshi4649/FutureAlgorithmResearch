"""原版Ｅ０１の旧三十場を、保存台帳から料金零で引用する。"""

from pathlib import Path
from io import BytesIO
import pickle
import json
import hashlib
import numpy as np

ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 完成済み旧会計を再生せず、返済脚と完結組の金額を分けて保存する。
    引数: なし。
    返り値: None。市場原本・ＡＰＩ・新たな売買判定は使用しない。
    """
    source=ROOT/"アルゴリズム調査/00081_E01原版と知見統合改修の再検証/公開会計.json"
    saved=json.loads(source.read_text(encoding="utf-8"));old=saved["観測現在値"]["E01"]
    path=ROOT/"work/wave_v85/observed/ledgers/E01.pkl";payload=path.read_bytes()
    assert hashlib.sha256(payload).hexdigest()==old["ledger_SHA256"]
    ledgers=pickle.loads(payload);assert len(ledgers)==60
    original={(r["session"],r["symbol"]):r for r in old["rows"]}
    rows=[];arrays={}
    for key,ledger in sorted(ledgers.items()):
        scene,symbol=key;mult=1000. if symbol=="TOPIX" else 10.
        orders=np.asarray(ledger["orders"]);trades=np.asarray(ledger["trades"]);cycles=np.asarray(ledger["cycles"])
        gain=trades[:,10]*mult;parents=cycles[:,3]*mult
        assert abs(gain.sum()-original[key]["gross"])<1e-5
        assert abs(parents.sum()-gain.sum())<1e-5
        entries=orders[orders[:,7]==1];exits=orders[orders[:,7]==0]
        assert entries[:,4].sum()==exits[:,4].sum()==trades[:,3].sum()
        assert original[key]["residual_long"]==original[key]["residual_short"]==0
        row=dict(symbol=symbol,session=scene,method="E01",model="observed",profit=float(np.maximum(gain,0).sum()),loss=float(np.maximum(-gain,0).sum()),net=float(gain.sum()),fees=0.,parent_profit=float(np.maximum(parents,0).sum()),parent_loss=float(np.maximum(-parents,0).sum()),parent_wins=int((parents>0).sum()),parent_losses=int((parents<0).sum()),entry_orders=len(entries),entry_quantity=int(entries[:,4].sum()),closed_quantity=int(trades[:,3].sum()),winning_quantity=int(trades[gain>0,3].sum()),losing_quantity=int(trades[gain<0,3].sum()),groups=len(parents),unclosed=0,max_long=original[key]["max_long"],max_short=original[key]["max_short"],origin="旧30保存原版の手数料除外引用",account_reference=dict(path=path.relative_to(ROOT).as_posix(),sha256=old["ledger_SHA256"],key=[scene,symbol]))
        assert row["profit"]-row["loss"]==row["net"]==row["parent_profit"]-row["parent_loss"]
        rows.append(row)
        prefix=symbol+"_"+scene
        for name,value in (("orders",orders),("trades",trades),("cycles",cycles)):arrays[prefix+"__"+name]=value
    for symbol,expected in (("TOPIX",643500.),("NK225",244800.)):
        assert sum(r["net"] for r in rows if r["symbol"]==symbol)==expected
    target=HERE/"baseline";assert not target.exists();target.mkdir()
    cache=target/"原版旧三十場の保存注文と返済.npz";np.savez_compressed(cache,**arrays)
    result=dict(passed=True,sessions=saved["全30"],rows=rows,source=dict(path=path.relative_to(ROOT).as_posix(),sha256=old["ledger_SHA256"]),cache=dict(path=cache.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(cache.read_bytes()).hexdigest()),financial_replays=0,new_financial_accounts=0,original_market_reads=0,API=0,real_orders=0,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),accounting="主利益・損失は返済脚の粗損益の正負。完結親組の正負はparent別。手数料0への算術再集計で売買時刻と数量は変えない。")
    (target/"原版旧三十場の費用なし保存引用.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    print("旧60会計を保存引用、金融再生0。",flush=True)


if __name__=="__main__":main()
