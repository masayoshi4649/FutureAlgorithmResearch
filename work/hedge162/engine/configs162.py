"""訓練原板の尺度根拠から登録前に固定する26条件。"""
from dataclasses import asdict

from state162 import Config, Policy


def configurations() -> list[dict]:
    """2つの主単独対照と、段間隔×追尾幅×再配置×起動方式の24条件を返す。

    引数: なし。返り値: list[dict]。後半成績による幅選択を行わない。
    """
    result = [dict(id="S00",description="主+100/−50/場末・カバーなし",cover=False,main_stop=50,grid_step=20,trail=10,rearm="none",immediate=False),
              dict(id="N00",description="主+100/場末・カバーなし",cover=False,main_stop=None,grid_step=20,trail=10,rearm="none",immediate=False)]
    index = 1
    for immediate in (False,True):
        for step in (20,40,60):
            for trail in (10,20):
                for rearm in ("fixed_recross","moving_stop"):
                    result.append(dict(id=f"H{index:02d}",description=f"段{step}・"+("即追尾" if immediate else f"利益{trail*2}起動")+f"・追尾{trail}・"+("固定段再交差" if rearm == "fixed_recross" else "完済後新基準"),
                                       cover=True,main_stop=None,grid_step=step,trail=trail,rearm=rearm,immediate=immediate))
                    index += 1
    return result


def make_case(scene: dict, definition: dict) -> tuple[Config, Policy]:
    """一場の時計と登録条件から状態器設定を作る。

    引数: scene/definition(dict)。返り値: tuple[Config,Policy]。
    """
    config = Config(force_close=scene["end"],start=scene["start"],main_stop=definition["main_stop"],
                    main_end="flatten_cover",boundary="carry",rearm=definition["rearm"],use_cover=definition["cover"],immediate_cover_trail=definition["immediate"])
    return config,Policy(definition["grid_step"],definition["trail"]*2,definition["trail"])


def export_configuration(scene: dict, definition: dict) -> dict:
    """省略された共通設定も含む条件の証跡を返す。

    引数: scene/definition(dict)。返り値: dict。
    """
    config,policy = make_case(scene,definition)
    return {"definition":definition,"config":asdict(config),"policy":asdict(policy)}
