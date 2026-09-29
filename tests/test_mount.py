"""坐骑装备与进化系统测试（10 个）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mount.system import (
    MountSystem,
    Mount,
    MountEquip,
    SLOT_SADDLE,
    SLOT_STIRRUP,
    SLOT_ARMOR,
    SLOT_ORNAMENT,
    STATE_STAND,
    STATE_BATTLE,
    STATE_RUN,
    ZONE_BASE,
    ZONE_PERCENT,
    EVOLVE_PILL_COST,
    EVOLVE_PITY_THRESHOLD,
)


class FixedRng:
    """可注入的伪随机源：预设 random() 序列与 uniform() 返回值。"""

    def __init__(self, randoms=None, uniform_value=1.0):
        self._randoms = list(randoms or [])
        self._uniform_value = uniform_value

    def random(self):
        if self._randoms:
            return self._randoms.pop(0)
        return 0.0

    def uniform(self, low, high):
        value = self._uniform_value
        if callable(value):
            return value(low, high)
        return value


def make_mount(mid="m1", level=50, stage=1, quality="white",
               base_stats=None, intimacy=100, skills=None):
    return Mount(
        mid=mid,
        level=level,
        stage=stage,
        quality=quality,
        base_stats=dict(base_stats or {}),
        intimacy=intimacy,
        skills=dict(skills or {}),
    )


class TestEquipSlots:
    def test_slot_type_mismatch_rejected(self):
        """bug1: 槽位有类型（鞍/镫/甲/饰），类型不匹配不能装备。"""
        ms = MountSystem()
        mount = make_mount()
        ms.mounts["m1"] = mount
        # 攻击向的鞍试图插进防御向的甲槽，类型不匹配必须拒绝
        atk_saddle = MountEquip("e1", SLOT_SADDLE, "atk", 10)
        assert ms.equip("m1", atk_saddle, target_slot=SLOT_ARMOR) is None
        assert SLOT_SADDLE not in mount.equipment
        assert SLOT_ARMOR not in mount.equipment
        # 装备只能进入与自身类型一致的槽
        assert ms.equip("m1", atk_saddle, target_slot=SLOT_SADDLE) is None
        assert mount.equipment[SLOT_SADDLE].eid == "e1"
        # 非法槽位类型直接拒绝
        bad = MountEquip("e3", "not_a_slot", "atk", 10)
        assert ms.equip("m1", bad) is None
        # 损坏装备不能装备
        broken = MountEquip("e4", SLOT_STIRRUP, "def", 10, durability=0)
        assert ms.equip("m1", broken) is None
        assert SLOT_STIRRUP not in mount.equipment


class TestEvolveRequirement:
    def test_evolve_requires_level_material_intimacy(self):
        """bug2: 进化同时检查等级+材料+亲密度，缺一不可。"""
        # 满级但没材料、没亲密度
        ms = MountSystem()
        mount = make_mount(level=50, intimacy=0)
        ms.mounts["m1"] = mount
        assert ms.evolve("m1") is False
        assert mount.stage == 1

        # 补上材料，亲密度仍不足
        ms.inventory["evolve_pill"] = 10
        assert ms.evolve("m1") is False

        # 补亲密度，但等级不足
        mount.intimacy = 100
        mount.level = 49
        assert ms.evolve("m1") is False

        # 三者齐备才能进化成功
        mount.level = 50
        ms.rng = FixedRng(randoms=[0.1], uniform_value=1.0)
        assert ms.evolve("m1") is True
        assert mount.stage == 2
        # 成功进化消耗进化丹
        assert ms.inventory["evolve_pill"] == 10 - EVOLVE_PILL_COST


class TestEvolveBonus:
    def test_bonus_scales_with_base_and_quality(self):
        """bug3: 进化属性 = 进化前属性 x 品质系数 x 波动系数，白板与极品不同。"""
        def evolve_once(quality, base_atk, uniform_value):
            ms = MountSystem(rng=FixedRng(randoms=[0.1], uniform_value=uniform_value))
            mount = make_mount(quality=quality, base_stats={"atk": base_atk})
            ms.mounts["m1"] = mount
            ms.inventory["evolve_pill"] = 10
            assert ms.evolve("m1") is True
            return mount.base_stats["atk"]

        # 相同品质相同波动：进化前属性翻倍，进化后也应翻倍
        a = evolve_once("blue", 100, 1.0)
        b = evolve_once("blue", 200, 1.0)
        assert abs(b - 2 * a) < 1e-9 and a > 100

        # 极品品质成长必须高于白板（波动取下限，极品仍占优）
        white = evolve_once("white", 100, 0.9)
        orange = evolve_once("orange", 100, 0.9)
        assert orange > white

        # 波动范围生效：取下限和上限结果不同
        low = evolve_once("white", 100, 0.9)
        high = evolve_once("white", 100, 1.1)
        assert high > low


class TestSkillGrowth:
    def test_skill_grows_with_level_and_stage(self):
        """bug4: 技能效果随坐骑等级与进化阶段成长，未解锁阶段无效。"""
        ms = MountSystem()
        mount = make_mount(
            level=1,
            stage=1,
            skills={
                "dash": {"base": 100, "unlock_stage": 1},
                "fury": {"base": 100, "unlock_stage": 3},
            },
        )
        ms.mounts["m1"] = mount

        effect_1_1 = ms.get_skill_effect("m1", "dash")
        mount.level = 50
        effect_50_1 = ms.get_skill_effect("m1", "dash")
        mount.stage = 2
        effect_50_2 = ms.get_skill_effect("m1", "dash")

        assert effect_50_1 > effect_1_1
        assert effect_50_2 > effect_50_1

        # 阶段不足，技能未解锁，效果为 0；到达阶段后可用
        assert ms.get_skill_effect("m1", "fury") == 0
        mount.stage = 3
        assert ms.get_skill_effect("m1", "fury") > 100


class TestTransmog:
    def test_appearance_unlocked_by_item(self):
        """bug5: 幻化支持道具解锁，不要求先拥有原坐骑。"""
        ms = MountSystem()
        ms.mounts["m1"] = make_mount()
        # 没抽到限定坐骑（不在拥有列表），无法幻化
        assert ms.transmog("m1", "limited_fox") is False
        # 使用幻化道具解锁后即可幻化
        assert ms.unlock_appearance("limited_fox") is True
        assert ms.transmog("m1", "limited_fox") is True


class TestEquipMutex:
    def test_same_slot_only_one_equip(self):
        """bug6: 同槽位装备互斥，每槽只能一件。"""
        ms = MountSystem()
        mount = make_mount()
        ms.mounts["m1"] = mount

        first = MountEquip("s1", SLOT_SADDLE, "atk", 10)
        second = MountEquip("s2", SLOT_SADDLE, "atk", 20)
        ms.equip("m1", first)
        returned = ms.equip("m1", second)

        saddle_equips = [e for e in mount.equipment.values() if e.slot == SLOT_SADDLE]
        assert len(saddle_equips) == 1
        assert mount.equipment[SLOT_SADDLE].eid == "s2"
        # 被替换下来的旧装备返还给玩家
        assert returned is first


class TestNoDuplicateSaddles:
    def test_three_attack_saddles_do_not_stack(self):
        """回归：同类型（同槽位）装备不能重复堆，3 件攻击马鞍只生效 1 件。"""
        ms = MountSystem()
        mount = make_mount(base_stats={"atk": 100})
        ms.mounts["m1"] = mount

        for i in range(3):
            ms.equip("m1", MountEquip(f"s{i}", SLOT_SADDLE, "atk", 10, ZONE_BASE))

        saddles = [e for e in mount.equipment.values() if e.slot == SLOT_SADDLE]
        assert len(saddles) == 1
        assert len(mount.equipment) == 1
        # 只有最后一件马鞍的 +10 生效，不会变成 +30
        assert ms.get_total_atk("m1") == 110


class TestStatZones:
    def test_additive_within_zone_multiplicative_across_zones(self):
        """bug7: 同类加法、异类乘法，避免多件百分比装备线性爆炸。"""
        ms = MountSystem()
        mount = make_mount(base_stats={"atk": 100})
        ms.mounts["m1"] = mount

        ms.equip("m1", MountEquip("p1", SLOT_SADDLE, "atk", 0.1, ZONE_PERCENT))
        # 两件百分比装在同一乘区内先相加：(100) * (1 + 0.1 + 0.2) = 130，
        # 而不是 (100*1.1*1.2)=132，也不是线性堆到 200
        ms.equip("m1", MountEquip("p2", SLOT_STIRRUP, "atk", 0.2, ZONE_PERCENT))
        assert abs(ms.get_total_atk("m1") - 130.0) < 1e-9

        # 再加一件基础区（加法区）装备：(100 + 50) * 1.3 = 195
        ms.equip("m1", MountEquip("b1", SLOT_ARMOR, "atk", 50, ZONE_BASE))
        assert abs(ms.get_total_atk("m1") - 195.0) < 1e-9


class TestDurability:
    def test_durability_cost_by_state(self):
        """bug8: 耐久消耗按状态区分：奔跑 > 战斗 > 站立。"""
        ms = MountSystem()
        mounts = {}
        for tag in (STATE_STAND, STATE_BATTLE, STATE_RUN):
            m = make_mount(mid=tag)
            ms.mounts[tag] = m
            ms.equip(tag, MountEquip(tag, SLOT_SADDLE, "atk", 10, durability=100))
            mounts[tag] = m

        ms.wear(STATE_STAND, SLOT_SADDLE, STATE_STAND)
        ms.wear(STATE_BATTLE, SLOT_SADDLE, STATE_BATTLE)
        ms.wear(STATE_RUN, SLOT_SADDLE, STATE_RUN)

        remain = {tag: mounts[tag].equipment[SLOT_SADDLE].durability for tag in mounts}
        assert remain[STATE_RUN] < remain[STATE_BATTLE] < remain[STATE_STAND]

        # 耐久耗尽装备自动失效
        dead = make_mount(mid="dead", base_stats={"atk": 0})
        ms.mounts["dead"] = dead
        ms.equip("dead", MountEquip("d1", SLOT_ORNAMENT, "atk", 999, durability=2))
        ms.wear("dead", SLOT_ORNAMENT, STATE_RUN)
        assert SLOT_ORNAMENT not in dead.equipment
        assert ms.get_total_atk("dead") == 0


class TestEvolveFailure:
    def test_failure_loses_half_material_and_pity(self):
        """bug9: 进化失败返还50%材料（损耗一半），连续失败有保底。"""
        ms = MountSystem(rng=FixedRng(randoms=[0.99, 0.99, 0.99, 0.99]))
        mount = make_mount(stage=1)
        ms.mounts["m1"] = mount
        ms.inventory["evolve_pill"] = 100

        # 前三次强制失败
        for _ in range(EVOLVE_PITY_THRESHOLD):
            assert ms.evolve("m1") is False
        # 每次尝试扣 2 返 1，净损 1
        assert ms.inventory["evolve_pill"] == 100 - EVOLVE_PITY_THRESHOLD
        assert mount.fail_count == EVOLVE_PITY_THRESHOLD
        assert mount.stage == 1

        # 达到保底次数，下一次哪怕随机结果仍是失败也必定成功
        assert ms.evolve("m1") is True
        assert mount.stage == 2
        assert mount.fail_count == 0
        assert ms.inventory["evolve_pill"] == 100 - EVOLVE_PITY_THRESHOLD - EVOLVE_PILL_COST
