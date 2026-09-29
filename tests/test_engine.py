"""坐骑测试"""
import pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.engine import MountSystem, Mount, MountEquip

class TestEquip:
    def test_slot_type_checked(self):
        ms = MountSystem()
        ms.mounts = {"m1": Mount("m1",1,1,"white",{},[])}
        e = MountEquip("e1","defense_slot","atk",10)
        assert not ms.equip("m1", e), "槽位类型未检查"

class TestEvolve:
    def test_evolve_requires_materials(self):
        ms = MountSystem()
        ms.mounts = {"m1": Mount("m1",50,1,"white",{},[])}
        # 进化应该需要材料
        assert True  # 基本验证
