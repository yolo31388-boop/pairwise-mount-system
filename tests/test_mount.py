"""坐骑装备与进化系统测试(9 个养成黑洞修复,共 10 个用例)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mount.system import (
    Mount,
    MountEquip,
    MountSystem,
    SLOT_SADDLE,
    SLOT_STIRRUP,
    SLOT_ARMOR,
    SLOT_ORNAMENT,
    STATE_IDLE,
    STATE_COMBAT,
    STATE_RUNNING,
    EVOLVE_COST,
    EVOLVE_LEVEL,
    EVOLVE_INTIMACY,
    EVOLVE_PITY,
    EVOLVE_SUCCESS_RATE,
)


class FakeRng:
    """可控随机源。

    force_success 控制进化成败判定,fixed 控制波动取值(0 取下限,1 取上限)。
    """

    def __init__(self, fixed=0.0, force_success=True, seq=None):
        self.fixed = fixed
        self.force_success = force_success
        self.seq = list(seq or [])

    def random(self):
        if self.seq:
            return self.seq.pop(0)
        return 0.0 if self.force_success else 0.9

    def uniform(self, low, high):
        return low if self.fixed <= 0.5 else high


def make_mount(mid="m1", level=1, stage=1, quality="white",
               skills=None, intimacy=0, base_stats=None, owned=True):
    return Mount(
        mid=mid, level=level, stage=stage, quality=quality,
        skills=skills or {}, intimacy=intimacy,
        base_stats=base_stats or {}, owned=owned,
    )


def ready_for_evolve(ms, mid="m1", materials=None):
    """把坐骑与材料准备到满足全部进化前置条件的状态。"""
    ms.mounts[mid].level = EVOLVE_LEVEL
    ms.mounts[mid].intimacy = EVOLVE_INTIMACY
    ms.player_materials[mid] = EVOLVE_COST if materials is None else materials


class TestEquip:
    def test_slot_type_mismatch_rejected(self):
        # 黑洞1: 槽位有类型(鞍/镫/甲/饰),攻击装备插不进防御槽
        ms = MountSystem()
        ms.mounts["m1"] = make_mount()
        saddle = MountEquip("e1", SLOT_SADDLE, "atk", 10)
        # 装备自身槽位类型非法
        bad_equip = MountEquip("bad", "defense_slot", "atk", 10)
        assert not ms.equip("m1", bad_equip)
        # 显式往类型不匹配的槽位插(鞍插进镫槽)
        assert not ms.equip("m1", saddle, slot=SLOT_STIRRUP)
        # 类型匹配可以装备
        assert ms.equip("m1", saddle)
        assert ms.mounts["m1"].equipment[SLOT_SADDLE] is saddle

    def test_same_slot_mutually_exclusive(self):
        # 黑洞6: 同类型装备互斥,每槽只能一件,不能插 3 个攻击马鞍
        ms = MountSystem()
        ms.mounts["m1"] = make_mount()
        s1 = MountEquip("s1", SLOT_SADDLE, "atk", 10)
        s2 = MountEquip("s2", SLOT_SADDLE, "atk", 20)
        s3 = MountEquip("s3", SLOT_SADDLE, "atk", 30)
        assert ms.equip("m1", s1)
        assert ms.equip("m1", s2)
        assert ms.equip("m1", s3)
        saddle_items = [e for e in ms.mounts["m1"].equipment.values()
                        if e.slot == SLOT_SADDLE]
        assert len(saddle_items) == 1
        # 不同槽位可以共存
        assert ms.equip("m1", MountEquip("a1", SLOT_ARMOR, "def", 5))
        assert len(ms.mounts["m1"].equipment) == 2


class TestEvolve:
    def test_evolve_requires_level_materials_intimacy(self):
        # 黑洞2: 进化同时检查等级 + 进化材料 + 亲密度,缺一不可
        ms = MountSystem()
        ms.mounts["m1"] = make_mount(level=EVOLVE_LEVEL, intimacy=EVOLVE_INTIMACY)
        # 满级但没材料、亲密度即便够也不能进化
        assert not ms.can_evolve("m1")
        assert not ms.evolve("m1")
        ms.player_materials["m1"] = EVOLVE_COST
        # 有材料但亲密度不足
        ms.mounts["m1"].intimacy = 0
        assert not ms.can_evolve("m1")
        assert not ms.evolve("m1")
        assert ms.player_materials["m1"] == EVOLVE_COST  # 条件不满足不耗材料
        # 材料、亲密度都够但等级不足
        ms.mounts["m1"].intimacy = EVOLVE_INTIMACY
        ms.mounts["m1"].level = EVOLVE_LEVEL - 1
        assert not ms.can_evolve("m1")
        assert not ms.evolve("m1")
        # 三者齐备才能进化(rng 强制成功)
        ms.mounts["m1"].level = EVOLVE_LEVEL
        ms.rng = FakeRng(fixed=0.0)
        assert ms.can_evolve("m1")
        assert ms.evolve("m1")
        assert ms.mounts["m1"].stage == 2

    def test_evolve_bonus_derived_from_prior_stats_and_quality(self):
        # 黑洞3: 进化后属性 = 进化前属性 × 品质成长系数(含波动),白板极品有别
        white = MountSystem(rng=FakeRng(fixed=0.0))
        white.mounts["w"] = make_mount(mid="w", quality="white",
                                       base_stats={"atk": 100.0})
        ready_for_evolve(white, "w")
        assert white.evolve("w")
        white_bonus = white.get_evolve_bonus("w")["atk"]

        gold = MountSystem(rng=FakeRng(fixed=0.0))
        gold.mounts["g"] = make_mount(mid="g", quality="gold",
                                      base_stats={"atk": 100.0})
        ready_for_evolve(gold, "g")
        assert gold.evolve("g")
        gold_bonus = gold.get_evolve_bonus("g")["atk"]

        # 极品(金)进化加成必须高于白板
        assert gold_bonus > white_bonus
        # 加成与进化前属性挂钩,不是固定 100
        assert abs(white_bonus - 100.0) > 1e-6
        # 白板系数 1.10,取下波动 1.045:100 -> 104.5,增量 4.5
        assert abs(white.mounts["w"].base_stats["atk"] - 104.5) < 1e-6

    def test_evolve_failure_refunds_half_and_pity(self):
        # 黑洞9: 失败返还 50% 材料且有保底
        ms = MountSystem(rng=FakeRng(force_success=False))  # 恒失败
        ms.mounts["m1"] = make_mount()
        ready_for_evolve(ms, "m1", materials=100)

        assert not ms.evolve("m1")
        # 消耗 2,返还 1(50%,至少 1)
        assert ms.player_materials["m1"] == 99
        assert ms.mounts["m1"].evolve_failures == 1
        assert ms.mounts["m1"].stage == 1

        # 连续失败达到保底次数后,下一次必定成功
        for _ in range(EVOLVE_PITY - 1):
            ms.evolve("m1")
        assert ms.mounts["m1"].evolve_failures == EVOLVE_PITY
        assert ms.evolve("m1")  # 保底必成,即使 rng 仍为失败值
        assert ms.mounts["m1"].stage == 2
        assert ms.mounts["m1"].evolve_failures == 0

    def test_evolve_bonus_has_fluctuation_range(self):
        # 黑洞3 补充: 进化结果在成长系数 ±5% 波动范围内
        low = MountSystem(rng=FakeRng(fixed=0.0))
        low.mounts["l"] = make_mount(mid="l", quality="blue",
                                     base_stats={"atk": 200.0})
        ready_for_evolve(low, "l")
        low.evolve("l")
        low_val = low.mounts["l"].base_stats["atk"]

        high = MountSystem(rng=FakeRng(fixed=1.0))
        high.mounts["h"] = make_mount(mid="h", quality="blue",
                                      base_stats={"atk": 200.0})
        ready_for_evolve(high, "h")
        high.evolve("h")
        high_val = high.mounts["h"].base_stats["atk"]

        # 蓝系数 1.35:下限 200*1.35*0.95,上限 200*1.35*1.05
        assert abs(low_val - 200.0 * 1.35 * 0.95) < 1e-6
        assert abs(high_val - 200.0 * 1.35 * 1.05) < 1e-6
        assert high_val > low_val


class TestSkill:
    def test_skill_effect_grows_with_level_and_stage(self):
        # 黑洞4: 技能效果随坐骑等级和进化阶段成长
        ms = MountSystem()
        ms.mounts["m1"] = make_mount(level=1, stage=1,
                                     skills={"charge": 100.0})
        basic = ms.get_skill_effect("m1", "charge")
        assert basic == 100.0 * (1 + 0.02 + 0.15)

        ms.mounts["m1"].level = 10
        leveled = ms.get_skill_effect("m1", "charge")
        assert leveled > basic

        ms.mounts["m1"].stage = 3
        staged = ms.get_skill_effect("m1", "charge")
        assert staged > leveled
        assert staged == 100.0 * (1 + 10 * 0.02 + 3 * 0.15)


class TestTransmog:
    def test_transmog_unlocked_by_item_without_ownership(self):
        # 黑洞5: 幻化道具解锁外观,不要求先抽到原坐骑
        ms = MountSystem()
        # 玩家只有 m1,限定坐骑 limited 未拥有(甚至未登记)
        ms.mounts["m1"] = make_mount()
        ms.unlock_transmog_item("ticket_limited", "limited_skin")
        # 未解锁时不能幻化
        assert not ms.transmog("m1", "limited_skin")
        # 用道具解锁后即可幻化,无需拥有 limited 坐骑
        assert ms.unlock_transmog("m1", "ticket_limited")
        assert ms.transmog("m1", "limited_skin")
        # 装备时直接附带有效道具也可以解锁幻化
        assert ms.transmog("m1", "other_skin", item_id=None) is False
        ms.unlock_transmog_item("ticket_other", "other_skin")
        assert ms.transmog("m1", "other_skin", item_id="ticket_other")


class TestStats:
    def test_same_zone_additive_cross_zone_multiplicative(self):
        # 黑洞7: 同类加法、异类(跨乘区)乘法;每件 10% 不会变成 +100%
        ms = MountSystem()
        ms.mounts["m1"] = make_mount(base_stats={"atk": 100.0})
        # 三件百分比攻击装备(同类,同乘区):加法合计 30%
        ms.equip("m1", MountEquip("s1", SLOT_SADDLE, "atk_pct", 0.1))
        ms.equip("m1", MountEquip("t1", SLOT_STIRRUP, "atk_pct", 0.1))
        ms.equip("m1", MountEquip("o1", SLOT_ORNAMENT, "atk_pct", 0.1))
        assert abs(ms.get_total_atk("m1") - 130.0) < 1e-6

        # 再加一件固定攻击(跨乘区):固定值与百分比乘法结算
        ms.equip("m1", MountEquip("a1", SLOT_ARMOR, "atk", 50.0))
        assert abs(ms.get_total_atk("m1") - 150.0 * 1.3) < 1e-6


class TestDurability:
    def test_durability_consumption_by_state(self):
        # 黑洞8: 耐久消耗按状态区分,奔跑 > 战斗 > 站立
        idle = MountSystem()
        idle.mounts["i"] = make_mount()
        idle.equip("i", MountEquip("e", SLOT_SADDLE, "atk", 1))
        idle.consume_durability("i", STATE_IDLE)
        idle_left = idle.mounts["i"].equipment[SLOT_SADDLE].durability

        combat = MountSystem()
        combat.mounts["c"] = make_mount(mid="c")
        combat.equip("c", MountEquip("e", SLOT_SADDLE, "atk", 1))
        combat.consume_durability("c", STATE_COMBAT)
        combat_left = combat.mounts["c"].equipment[SLOT_SADDLE].durability

        running = MountSystem()
        running.mounts["r"] = make_mount(mid="r")
        running.equip("r", MountEquip("e", SLOT_SADDLE, "atk", 1))
        running.consume_durability("r", STATE_RUNNING)
        running_left = running.mounts["r"].equipment[SLOT_SADDLE].durability

        # 100 起步:站立耗 1,战斗耗 2,奔跑耗 4
        assert idle_left == 99
        assert combat_left == 98
        assert running_left == 96
        assert idle_left > combat_left > running_left

        # 耐久归零自动损坏并卸下,无法再装备
        running.consume_durability("r", STATE_RUNNING, duration=100)
        assert SLOT_SADDLE not in running.mounts["r"].equipment
        broken = MountEquip("e2", SLOT_SADDLE, "atk", 1, durability=0.0)
        assert not running.equip("r", broken)
