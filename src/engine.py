"""坐骑装备进化 - 带9个bug"""
from dataclasses import dataclass, field
import random

@dataclass
class MountEquip:
    eid: str
    slot: str
    stat: str
    value: float

@dataclass
class Mount:
    mid: str
    level: int
    stage: int
    quality: str
    skills: dict
    equipment: list

class MountSystem:
    def __init__(self):
        self.mounts: dict[str, Mount] = {}
        self.player_mount = {}

    VALID_SLOTS = ("saddle", "stirrup", "armor", "ornament")

    def equip(self, mid, equip):
        mount = self.mounts[mid]
        # 槽位类型校验：不匹配不能装备
        if equip.slot not in self.VALID_SLOTS:
            return False
        mount.equipment.append(equip)
        return True

    def evolve(self, mid):
        mount = self.mounts[mid]
        # bug2: 只看等级
        if mount.level >= 50:
            mount.stage += 1
            return True
        return False

    def get_evolve_bonus(self, mid):
        # bug3: 固定加成
        return {"atk": 100}

    def get_skill_effect(self, mid, skill_id):
        mount = self.mounts[mid]
        # bug4: 不随等级成长
        return mount.skills.get(skill_id, 0)

    def transmog(self, mid, appearance_id):
        # bug5: 需先拥有
        if appearance_id not in self.mounts:
            return False
        return True

    def get_total_atk(self, mid):
        mount = self.mounts[mid]
        # bug7: 加法叠加
        total = 0
        for e in mount.equipment:
            if e.stat == "atk":
                total += e.value
        return total
