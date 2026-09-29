"""坐骑装备与进化系统。

修复点：
1. 装备槽有类型（鞍/镫/甲/饰），类型不匹配不能装备；
2. 进化同时检查等级、进化材料、亲密度，缺一不可；
3. 进化属性按进化前属性 x 成长系数计算，带波动范围，并受品质影响；
4. 技能效果随坐骑等级和进化阶段成长，未解锁阶段不可用；
5. 幻化支持道具解锁，不要求先拥有原坐骑；
6. 同槽位装备互斥，每槽只能一件；
7. 属性加成区分乘区：同类加法，异类乘法；
8. 耐久消耗按状态区分（奔跑 > 战斗 > 站立）；
9. 进化失败有材料损耗（返还50%），并带保底。

仅使用标准库。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Optional


# 槽位类型：鞍 / 镫 / 甲 / 饰
SLOT_SADDLE = "saddle"      # 鞍
SLOT_STIRRUP = "stirrup"    # 镫
SLOT_ARMOR = "armor"        # 甲
SLOT_ORNAMENT = "ornament"  # 饰

VALID_SLOTS = (SLOT_SADDLE, SLOT_STIRRUP, SLOT_ARMOR, SLOT_ORNAMENT)

# 进化前置条件
EVOLVE_MIN_LEVEL = 50
EVOLVE_MIN_INTIMACY = 100
# 每次进化消耗的进化丹数量
EVOLVE_PILL_COST = 2
# 进化失败材料返还比例（剩余50%损耗）
EVOLVE_FAIL_RETURN_RATE = 0.5
# 连续失败该次数后，下一次进化必定成功（保底）
EVOLVE_PITY_THRESHOLD = 3
# 进化属性成长系数的波动范围
GROWTH_RANGE = (0.9, 1.1)

# 品质对应的基础成长系数
QUALITY_GROWTH = {
    "white": 1.0,
    "green": 1.1,
    "blue": 1.25,
    "purple": 1.45,
    "orange": 1.7,
}

# 每点坐骑等级 / 每个进化阶段对技能效果的加成
SKILL_LEVEL_GROWTH = 0.02
SKILL_STAGE_GROWTH = 0.1

# 不同状态下的耐久消耗（奔跑 > 战斗 > 站立）
STATE_STAND = "stand"
STATE_BATTLE = "battle"
STATE_RUN = "run"
DURABILITY_COST = {
    STATE_STAND: 1,
    STATE_BATTLE: 3,
    STATE_RUN: 5,
}

# 乘区：同一乘区内加法叠加，不同乘区之间乘法叠加
ZONE_BASE = "base"
ZONE_PERCENT = "percent"


@dataclass
class MountEquip:
    """坐骑装备。

    slot: 装备自身适用的槽位（鞍/镫/甲/饰）。
    stat: 加成的属性名，如 "atk"。
    value: 加成本值。
    zone: 乘区，"base" 为基础加法区，"percent" 为百分比加法区。
    durability: 当前耐久，<=0 视为损坏不再生效。
    max_durability: 耐久上限。
    """
    eid: str
    slot: str
    stat: str
    value: float
    zone: str = ZONE_BASE
    durability: float = 100.0
    max_durability: float = 100.0

    @property
    def broken(self) -> bool:
        return self.durability <= 0


@dataclass
class Mount:
    mid: str
    level: int
    stage: int
    quality: str
    skills: dict = field(default_factory=dict)
    equipment: dict = field(default_factory=dict)
    # 基础属性，进化成长基于此值滚动计算
    base_stats: dict = field(default_factory=dict)
    # 亲密度（进化前置条件之一）
    intimacy: int = 0
    # 连续进化失败次数（保底计数）
    fail_count: int = 0


class MountSystem:
    def __init__(self, rng=None):
        self.mounts: dict[str, Mount] = {}
        # 玩家拥有的坐骑 id
        self.player_mount: set = set()
        # 玩家背包材料，如 {"evolve_pill": 5}
        self.inventory: dict = {}
        # 已解锁的幻化外观 id，无需拥有原坐骑
        self.unlocked_appearances: set = set()
        # 最近一次进化属性的成长系数（便于查询/测试）
        self.last_growth_rate: dict[str, float] = {}
        # 随机源，可注入便于测试
        self.rng = rng or random

    # ---------- 装备 ----------

    def equip(self, mid: str, equip: MountEquip, target_slot: Optional[str] = None):
        """装备一件坐骑装备。

        装备只能放入与自身类型一致的槽位；指定 target_slot 时若与
        equip.slot 不一致则拒绝。装备已损坏也不允许装备。
        同槽位已有装备时，新装备替换旧装备（每槽仅一件）。
        成功返回被替换下来的旧装备（无则 None），类型不匹配返回 None。
        """
        mount = self.mounts[mid]
        if target_slot is not None and target_slot != equip.slot:
            return None
        if equip.slot not in VALID_SLOTS:
            return None
        if equip.broken:
            return None
        old = mount.equipment.get(equip.slot)
        mount.equipment[equip.slot] = equip
        return old

    def unequip(self, mid: str, slot: str) -> Optional[MountEquip]:
        """卸下指定槽位的装备。"""
        mount = self.mounts[mid]
        if slot not in VALID_SLOTS:
            return None
        return mount.equipment.pop(slot, None)

    def wear(self, mid: str, slot: str, state: str = STATE_STAND) -> Optional[MountEquip]:
        """按状态消耗指定槽位装备的耐久度（奔跑 > 战斗 > 站立）。"""
        mount = self.mounts[mid]
        equip = mount.equipment.get(slot)
        if equip is None:
            return None
        cost = DURABILITY_COST.get(state, DURABILITY_COST[STATE_STAND])
        equip.durability = max(0.0, equip.durability - cost)
        # 耐久耗尽后自动失效（取下）
        if equip.broken:
            mount.equipment.pop(slot, None)
        return equip

    # ---------- 进化 ----------

    def can_evolve(self, mid: str) -> tuple[bool, str]:
        """检查进化条件：等级 + 进化材料 + 亲密度，缺一不可。"""
        mount = self.mounts[mid]
        if mount.level < EVOLVE_MIN_LEVEL:
            return False, "level"
        if self.inventory.get("evolve_pill", 0) < EVOLVE_PILL_COST:
            return False, "material"
        if mount.intimacy < EVOLVE_MIN_INTIMACY:
            return False, "intimacy"
        return True, "ok"

    def evolve(self, mid: str) -> bool:
        """进化坐骑。条件不足或进化失败返回 False。

        - 材料在尝试时全额扣除，失败返还 50%（即损耗 50%）；
        - 连续失败达到保底次数后，下一次必定成功；
        - 成功后清空失败计数，基础属性按进化前属性 x 品质系数 x 波动系数成长。
        """
        ok, _reason = self.can_evolve(mid)
        if not ok:
            return False

        mount = self.mounts[mid]
        self.inventory["evolve_pill"] -= EVOLVE_PILL_COST

        guaranteed = mount.fail_count >= EVOLVE_PITY_THRESHOLD
        if guaranteed:
            success = True
        else:
            success = self.rng.random() < 0.7

        if not success:
            mount.fail_count += 1
            returned = int(EVOLVE_PILL_COST * EVOLVE_FAIL_RETURN_RATE)
            self.inventory["evolve_pill"] = self.inventory.get("evolve_pill", 0) + returned
            return False

        # 保底或随机成功：滚动成长基础属性
        low, high = GROWTH_RANGE
        factor = self.rng.uniform(low, high)
        quality_mult = QUALITY_GROWTH.get(mount.quality, 1.0)
        growth_rate = quality_mult * factor
        self.last_growth_rate[mid] = growth_rate
        for stat, value in list(mount.base_stats.items()):
            mount.base_stats[stat] = value * growth_rate

        mount.stage += 1
        mount.fail_count = 0
        return True

    def get_evolve_bonus(self, mid: str) -> dict:
        """返回最近一次进化实际生效的属性成长系数。"""
        return {"rate": self.last_growth_rate.get(mid)}

    # ---------- 技能 ----------

    def get_skill_effect(self, mid: str, skill_id: str) -> float:
        """技能效果 = 基础值 x (1 + 等级加成 + 阶段加成)。

        未到达技能解锁进化阶段时返回 0。
        技能配置支持纯数值（基础值，默认可用）或
        {"base": x, "unlock_stage": n} 的字典形式。
        """
        mount = self.mounts[mid]
        skill = mount.skills.get(skill_id)
        if skill is None:
            return 0

        if isinstance(skill, dict):
            base = skill.get("base", 0)
            unlock_stage = skill.get("unlock_stage", 1)
        else:
            base = skill
            unlock_stage = 1

        if mount.stage < unlock_stage:
            return 0

        multiplier = (
            1.0
            + SKILL_LEVEL_GROWTH * mount.level
            + SKILL_STAGE_GROWTH * mount.stage
        )
        return base * multiplier

    # ---------- 幻化 ----------

    def unlock_appearance(self, appearance_id: str) -> bool:
        """通过幻化道具解锁外观，不要求拥有原坐骑。"""
        self.unlocked_appearances.add(appearance_id)
        return True

    def transmog(self, mid: str, appearance_id: str) -> bool:
        """幻化：拥有原坐骑或通过道具解锁外观，二者满足其一即可。"""
        if appearance_id in self.player_mount:
            return True
        if appearance_id in self.unlocked_appearances:
            return True
        return False

    # ---------- 属性汇总（乘区） ----------

    def get_total_stat(self, mid: str, stat: str) -> float:
        """汇总装备属性。

        同一乘区内加成做加法，不同乘区之间做乘法：
        total = (基础属性 + 基础区装备和) x (1 + 百分比区装备和)。
        已损坏装备不生效。
        """
        mount = self.mounts[mid]
        base_sum = float(mount.base_stats.get(stat, 0))
        percent_sum = 0.0
        for equip in mount.equipment.values():
            if equip.broken or equip.stat != stat:
                continue
            if equip.zone == ZONE_PERCENT:
                percent_sum += equip.value
            else:
                base_sum += equip.value
        return base_sum * (1.0 + percent_sum)

    def get_total_atk(self, mid: str) -> float:
        return self.get_total_stat(mid, "atk")
