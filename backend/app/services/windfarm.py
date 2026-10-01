"""风电场站业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "windfarm"
REQUIRED_FIELDS = ["场站编码", "场站名称", "所在区域"]
STATUS_ORDER = ["在建", "运行中", "限功率", "停运检修"]
ACTION_RULES = {"并网投运": "运行中", "申请限功率": "限功率", "转入检修": "停运检修"}
NEGATIVE_ACTIONS = []

# 区域目录：还没有场站的区域也要在概览里留占位，所以先维护一份完整目录。
REGION_DIRECTORY = ["华北区域", "西北区域", "华东区域", "西南区域", "华南区域"]

# 概览里每档要逐台统计的状态；停运检修计入场站数量，但不参与台数统计。
COUNTED_STATUSES = ["在建", "运行中", "限功率"]

TIER_PENDING = "pending"  # 装机容量缺失时单独归入的“待补充”档

_CAPACITY_PATTERN = re.compile(r"\d+(?:\.\d+)?")


def _parse_capacity(value: Any) -> float | None:
    """把装机容量解析成 MW 数值；缺失或提取不到数字时返回 None，归入待补充档。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _CAPACITY_PATTERN.search(str(value))
    if match is None:
        return None
    return float(match.group())


class WindfarmService:
    def __init__(self) -> None:
        # 分档口径按版本管理：最后一版为当前生效口径，每次调整前的分档结论留档在 _tier_archive。
        self._tier_versions: list[dict[str, Any]] = [
            {"version": "V1", "生效日期": "2026-01-01", "下限": 50.0, "上限": 150.0, "备注": "初始口径"}
        ]
        self._tier_archive: list[dict[str, Any]] = []

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        region: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("场站编码", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if region:
            rows = [row for row in rows if str(row.get("所在区域") or "").strip() == region.strip()]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["场站状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"风电场站 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于风电场站可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["场站状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"风电场站已{action}"

    def current_version(self) -> dict[str, Any]:
        return dict(self._tier_versions[-1])

    def tier_definitions(self, version: dict[str, Any] | None = None) -> list[dict[str, str]]:
        """当前口径下的分档说明：三档加一档“待补充”。"""
        version = version or self._tier_versions[-1]
        lower, upper = version["下限"], version["上限"]
        return [
            {"key": "small", "label": f"{lower:g}MW 以下"},
            {"key": "medium", "label": f"{lower:g}–{upper:g}MW"},
            {"key": "large", "label": f"{upper:g}MW 及以上"},
            {"key": TIER_PENDING, "label": "待补充"},
        ]

    @staticmethod
    def _tier_key(capacity_mw: float | None, version: dict[str, Any]) -> str:
        if capacity_mw is None:
            return TIER_PENDING
        if capacity_mw < version["下限"]:
            return "small"
        if capacity_mw < version["上限"]:
            return "medium"
        return "large"

    def overview(self) -> dict[str, Any]:
        """区域 × 装机容量分档概览：同一区域的场站归在一起，逐档统计台数。"""
        version = self._tier_versions[-1]
        tiers = self.tier_definitions(version)
        rows = store.rows(MODULE)
        region_names = list(REGION_DIRECTORY)
        for row in rows:
            name = str(row.get("所在区域") or "").strip()
            if name and name not in region_names:
                region_names.append(name)
        regions: list[dict[str, Any]] = []
        for name in region_names:
            farms: list[dict[str, Any]] = []
            stats = {tier["key"]: {"场站数量": 0, "在建": 0, "运行中": 0, "限功率": 0} for tier in tiers}
            for row in rows:
                if str(row.get("所在区域") or "").strip() != name:
                    continue
                capacity_mw = _parse_capacity(row.get("装机容量"))
                tier_key = self._tier_key(capacity_mw, version)
                bucket = stats[tier_key]
                bucket["场站数量"] += 1
                status = str(row.get("status") or "")
                if status in COUNTED_STATUSES:
                    bucket[status] += 1
                farms.append({
                    "id": row.get("id"),
                    "场站编码": row.get("场站编码"),
                    "场站名称": row.get("场站名称"),
                    "装机容量": row.get("装机容量"),
                    "容量MW": capacity_mw,
                    "status": status,
                    "tier": tier_key,
                })
            regions.append({
                "name": name,
                "placeholder": None if farms else f"{name}暂未登记风电场站，登记后会按当前口径自动归入对应档位。",
                "farms": farms,
                "tiers": stats,
            })
        return {"version": self.current_version(), "tiers": tiers, "regions": regions}

    def adjust_tiers(self, lower: Any, upper: Any, remark: str | None = None) -> tuple[dict[str, Any] | None, str]:
        """调整分档口径：旧口径的分档结论留档，已有场站按新口径重算。"""
        try:
            lower_value = float(lower)
            upper_value = float(upper)
        except (TypeError, ValueError):
            return None, "分档上下限必须是数字（单位 MW）"
        if lower_value <= 0 or lower_value >= upper_value:
            return None, "分档口径需满足 0 < 下限 < 上限"
        old_version = self._tier_versions[-1]
        rows = store.rows(MODULE)
        # 留档：按当时那一版口径记录每座场站的分档结论。
        conclusions = []
        for row in rows:
            capacity_mw = _parse_capacity(row.get("装机容量"))
            conclusions.append({
                "entry_id": row.get("id"),
                "场站编码": row.get("场站编码"),
                "场站名称": row.get("场站名称"),
                "所在区域": row.get("所在区域"),
                "装机容量": row.get("装机容量"),
                "容量MW": capacity_mw,
                "档位": self._tier_key(capacity_mw, old_version),
            })
        self._tier_archive.append({
            **self.current_version(),
            "归档时间": datetime.now().isoformat(timespec="seconds"),
            "conclusions": conclusions,
        })
        new_version = {
            "version": f"V{len(self._tier_versions) + 1}",
            "生效日期": date.today().isoformat(),
            "下限": lower_value,
            "上限": upper_value,
            "备注": (remark or "").strip() or "口径调整",
        }
        self._tier_versions.append(new_version)
        # 按新口径重算，并点出档位发生变化的场站。
        moved = [
            item["场站编码"]
            for item in conclusions
            if item["档位"] != self._tier_key(item["容量MW"], new_version)
        ]
        result = {
            "version": dict(new_version),
            "重算场站数": len(rows),
            "档位变动场站": moved,
        }
        return result, f"分档口径已更新为 {new_version['version']}，{len(rows)} 座场站已按新口径重算，其中 {len(moved)} 座档位变动"

    def tier_history(self) -> list[dict[str, Any]]:
        """历史分档留档：最近归档的版本排在前面。"""
        return list(reversed(self._tier_archive))
