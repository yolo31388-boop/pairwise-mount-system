"""坐骑装备与进化系统核心。

修复九个养成黑洞:
1. 装备槽按类型区分(鞍/镫/甲/饰),类型不匹配不能装备。
2. 进化同时检查等级、进化材料、亲密度,缺一不可。
3. 进化后属性 = 进化前属性 × 品质成长系数 × 随机波动,白板/极品有差异。
4. 技能效果随坐骑等级与进化阶段成长。
5. 幻化支持道具解锁,不再要求先拥有原坐骑。
6. 同类型装备互斥,每个槽位只能装备一件。
7. 属性加成分乘区:同区加法、跨区乘法。
8. 耐久消耗按状态区分(奔跑 > 战斗 > 站立)。
9. 进化失败有材料损耗(返还50%)且有保底。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

# 槽位类型
SLOT_SADDLE = "saddle"   # 鞍
SLOT_STIRRUP = "stirrup"  # 镫
SLOT_ARMOR = "armor"     # 甲
SLOT_ORNAMENT = "ornament"  # 饰

VALID_SLOTS = (SLOT_SADDLE, SLOT_STIRRUP, SLOT_ARMOR, SLOT_ORNAMENT)

# 耐久消耗状态
STATE_IDLE = "idle"        # 站立
STATE_COMBAT = "combat"    # 战斗
STATE_RUNNING = "running"  # 奔跑

DURABILITY_RATE = {
    STATE_IDLE: 1.0,
    STATE_COMBAT: 2.0,
    STATE_RUNNING: 4.0,
}

# 进化配置
EVOLVE_LEVEL = 50          # 需要的坐骑等级
EVOLVE_INTIMACY = 100      # 需要的亲密度
EVOLVE_COST = 2            # 单次进化消耗的进化丹
EVOLVE_SUCCESS_RATE = 0.5  # 基础成功率
EVOLVE_REFUND_RATE = 0.5   # 失败返还比例
EVOLVE_PITY = 3            # 连续失败达到此次数后下一次必成
EVOLVE_FLUCTUATION = 0.05  # 属性波动范围 ±5%

# 各品质的进化成长系数(极品成长远高于白板)
QUALITY_GROWTH = {
    "white": 1.10,
    "green": 1.20,
    "blue": 1.35,
    "purple": 1.55,
    "gold": 1.80,
}

# 属性乘区:同区加成加法叠加,跨区之间乘法叠加
ZONE_ATK_FLAT = "atk_flat"      # 攻击力固定值
ZONE_ATK_PERCENT = "atk_pct"    # 攻击力百分比
ZONE_DEF_FLAT = "def_flat"
ZONE_DEF_PERCENT = "def_pct"
ZONE_HP_FLAT = "hp_flat"
ZONE_HP_PERCENT = "hp_pct"

# 装备属性归入的乘区
STAT_ZONE = {
    "atk": ZONE_ATK_FLAT,
    "atk_pct": ZONE_ATK_PERCENT,
    "def": ZONE_DEF_FLAT,
    "def_pct": ZONE_DEF_PERCENT,
    "hp": ZONE_HP_FLAT,
    "hp_pct": ZONE_HP_PERCENT,
}

# 参与攻击力结算的乘区(跨区相乘)
ATK_ZONES = (ZONE_ATK_FLAT, ZONE_ATK_PERCENT)


@dataclass
class MountEquip:
    """坐骑装备。

    slot 必须是 VALID_SLOTS 之一;stat 为属性名,value 为数值。
    百分比属性的 value 按小数表示(如 0.1 表示 10%)。
    """

    eid: str
    slot: str
    stat: str
    value: float
    durability: float = 100.0

    def is_broken(self) -> bool:
        return self.durability <= 0

    def wear(self, amount: float) -> float:
        """消耗耐久,耐久归零时装备损坏。返回剩余耐久。"""
        self.durability = max(0.0, self.durability - amount)
        return self.durability


@dataclass
class Mount:
    mid: str
    level: int = 1
    stage: int = 1
    quality: str = "white"
    skills: dict = field(default_factory=dict)
    # 槽位 -> 装备,天然保证每槽至多一件(互斥)
    equipment: dict = field(default_factory=dict)
    intimacy: int = 0
    # 基础属性(进化前属性),进化后按系数×波动更新
    base_stats: dict = field(default_factory=dict)
    evolve_failures: int = 0          # 连续进化失败次数(保底计数)
    last_evolve_bonus: dict = field(default_factory=dict)
    # 坐骑是否已被玩家拥有
    owned: bool = True


class MountSystem:
    def __init__(self, rng: Optional[random.Random] = None):
        self.mounts: dict[str, Mount] = {}
        # 兼容旧接口的玩家坐骑记录
        self.player_mount: dict = {}
        # 玩家各坐骑的进化丹数量: mid -> 数量
        self.player_materials: dict[str, int] = {}
        # 已解锁的幻化外观: appearance_id -> True
        self.player_transmog: dict[str, bool] = {}
        # 外观幻化道具: item_id -> appearance_id
        self.transmog_items: dict[str, str] = {}
        self.rng = rng or random.Random()

    # ------------------------------------------------------------------
    # 装备:槽位类型检查 + 同槽互斥 + 耐久
    # ------------------------------------------------------------------
    def equip(self, mid: str, equip: MountEquip, slot: Optional[str] = None) -> bool:
        """装备坐骑装备。

        槽位类型不匹配、装备已损坏时返回 False。
        显式传入 slot 时,装备自身的槽位类型必须与目标槽位一致。
        每个槽位只能有一件装备,新装备直接替换旧装备。
        """
        mount = self.mounts[mid]
        if equip.slot not in VALID_SLOTS:
            return False
        if slot is not None and slot != equip.slot:
            return False
        if not self._slot_open(mount, equip.slot):
            return False
        if equip.is_broken():
            return False
        # 兼容历史数据中 equipment 为 list 的情况
        if isinstance(mount.equipment, list):
            mount.equipment = {item.slot: item for item in mount.equipment if getattr(item, "slot", None) in VALID_SLOTS}
        mount.equipment[equip.slot] = equip
        return True

    def unequip(self, mid: str, slot: str) -> Optional[MountEquip]:
        """卸下指定槽位的装备。"""
        mount = self.mounts[mid]
        return mount.equipment.pop(slot, None)

    @staticmethod
    def _slot_open(mount: Mount, slot: str) -> bool:
        return slot in VALID_SLOTS

    def consume_durability(self, mid: str, state: str, duration: float = 1.0) -> None:
        """按坐骑状态消耗全部已装备装备的耐久。

        消耗速度: 奔跑(4) > 战斗(2) > 站立(1)。
        耐久归零的装备视为损坏,自动从槽位移除。
        """
        mount = self.mounts[mid]
        rate = DURABILITY_RATE.get(state, DURABILITY_RATE[STATE_IDLE])
        broken_slots = []
        for slot, equip in mount.equipment.items():
            equip.wear(rate * duration)
            if equip.is_broken():
                broken_slots.append(slot)
        for slot in broken_slots:
            mount.equipment.pop(slot, None)

    # ------------------------------------------------------------------
    # 进化:等级 + 材料 + 亲密度,失败损耗 + 保底
    # ------------------------------------------------------------------
    def can_evolve(self, mid: str) -> bool:
        """进化前置条件:等级、进化材料、亲密度缺一不可。"""
        mount = self.mounts[mid]
        if mount.level < EVOLVE_LEVEL:
            return False
        if mount.intimacy < EVOLVE_INTIMACY:
            return False
        if self.player_materials.get(mid, 0) < EVOLVE_COST:
            return False
        return True

    def evolve(self, mid: str) -> bool:
        """尝试进化。

        成功:阶段 +1、保底计数清零,按进化前属性 × 品质系数 × 波动更新属性。
        失败:返还 50% 材料(向下取整,至少返还 1),失败计数 +1,
        连续失败达到 EVOLVE_PITY 次后下一次必定成功。
        前置条件不满足直接返回 False,不消耗任何材料。
        """
        if not self.can_evolve(mid):
            return False

        mount = self.mounts[mid]
        self.player_materials[mid] -= EVOLVE_COST

        guaranteed = mount.evolve_failures >= EVOLVE_PITY
        if guaranteed or self.rng.random() < EVOLVE_SUCCESS_RATE:
            growth = QUALITY_GROWTH.get(mount.quality, QUALITY_GROWTH["white"])
            factor_min = growth * (1.0 - EVOLVE_FLUCTUATION)
            factor_max = growth * (1.0 + EVOLVE_FLUCTUATION)
            bonus = {}
            new_stats = {}
            for stat, value in mount.base_stats.items():
                factor = self.rng.uniform(factor_min, factor_max)
                new_value = value * factor
                bonus[stat] = new_value - value
                new_stats[stat] = new_value
            mount.base_stats = new_stats
            mount.last_evolve_bonus = bonus
            mount.stage += 1
            mount.evolve_failures = 0
            return True

        # 失败:返还 50% 材料,计入保底
        refund = max(1, int(EVOLVE_COST * EVOLVE_REFUND_RATE))
        self.player_materials[mid] = self.player_materials.get(mid, 0) + refund
        mount.evolve_failures += 1
        return False

    def get_evolve_bonus(self, mid: str) -> dict:
        """返回最近一次进化实际获得的属性增量(白板与极品差异由此体现)。"""
        return dict(self.mounts[mid].last_evolve_bonus)

    # ------------------------------------------------------------------
    # 技能:随坐骑等级与进化阶段成长
    # ------------------------------------------------------------------
    def get_skill_effect(self, mid: str, skill_id: str) -> float:
        """技能效果 = 基础值 × (1 + 等级成长 + 进化阶段成长)。

        等级每级 +2%,进化阶段每阶 +15%。
        """
        mount = self.mounts[mid]
        base = mount.skills.get(skill_id, 0)
        level_bonus = mount.level * 0.02
        stage_bonus = mount.stage * 0.15
        return base * (1.0 + level_bonus + stage_bonus)

    # ------------------------------------------------------------------
    # 幻化:道具解锁,不要求先拥有原坐骑
    # ------------------------------------------------------------------
    def unlock_transmog_item(self, item_id: str, appearance_id: str) -> None:
        """登记一个幻化道具及其对应的外观。"""
        self.transmog_items[item_id] = appearance_id

    def unlock_transmog(self, mid: str, item_id: str) -> bool:
        """消耗幻化道具解锁外观,不要求拥有对应坐骑。"""
        appearance_id = self.transmog_items.get(item_id)
        if appearance_id is None:
            return False
        self.player_transmog[appearance_id] = True
        return True

    def transmog(self, mid: str, appearance_id: str, item_id: Optional[str] = None) -> bool:
        """幻化外观。

        已拥有原坐骑、已通过道具解锁该外观、或本次附带有效幻化道具均可。
        """
        mount = self.mounts[mid]
        if item_id is not None and self.transmog_items.get(item_id) == appearance_id:
            self.player_transmog[appearance_id] = True
        if mount.owned and self.mounts.get(appearance_id) is not None:
            return True
        if self.player_transmog.get(appearance_id):
            return True
        return False

    # ------------------------------------------------------------------
    # 属性结算:同乘区加法,跨乘区乘法
    # ------------------------------------------------------------------
    def _zone_bonuses(self, mid: str) -> dict:
        """汇总装备加成:同一乘区内加法叠加,返回 zone -> 总加成。"""
        mount = self.mounts[mid]
        zones: dict[str, float] = {}
        for equip in mount.equipment.values():
            zone = STAT_ZONE.get(equip.stat)
            if zone is None:
                continue
            if zone.endswith("_pct"):
                zones[zone] = zones.get(zone, 0.0) + equip.value
            else:
                zones[zone] = zones.get(zone, 0.0) + equip.value
        return zones

    def get_stat(self, mid: str, stat: str) -> float:
        """按乘区结算属性。

        固定值乘区与百分比乘区之间乘法结算:
        (base + Σ固定值) × (1 + Σ百分比)。多件同类装备在同一乘区内只做加法。
        """
        mount = self.mounts[mid]
        zones = self._zone_bonuses(mid)
        flat_zone = STAT_ZONE.get(stat)
        pct_zone = STAT_ZONE.get(stat + "_pct")
        base = mount.base_stats.get(stat, 0.0)
        result = base + zones.get(flat_zone, 0.0)
        result *= 1.0 + zones.get(pct_zone, 0.0)
        return result

    def get_total_atk(self, mid: str) -> float:
        """攻击力结算:固定值与百分比两个乘区相乘。"""
        return self.get_stat(mid, "atk")
