"""风电场站业务规则：状态流转、字段校验、区域容量分档概览与口径版本留档。

分档口径（三档 + 待补充）是有版本的：每次调整口径都会生成一个新版本，存量场站
立刻按新口径重算；旧版本当时的分档结论整版快照留档，只供回看，不再参与当前统计。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "windfarm"
VERSION_TABLE = "windfarm_tier_versions"
ARCHIVE_TABLE = "windfarm_tier_archives"

REQUIRED_FIELDS = ["场站编码", "场站名称", "所在区域"]
OPTIONAL_FIELDS = ["装机容量", "并网日期", "运营单位", "海拔高度"]

STATUS_ORDER = ["在建", "运行中", "限功率", "停运检修"]
# 概览只点这三态的台数；停运检修计入总数，不单独列示
OVERVIEW_STATUSES = ["在建", "运行中", "限功率"]
ACTION_RULES = {"并网投运": "运行中", "申请限功率": "限功率", "转入检修": "停运检修"}
NEGATIVE_ACTIONS = []

# 区域字典：即使还没有场站，概览也要给出占位行
REGIONS = ["华北", "东北", "华东", "华中", "西北", "西南", "华南"]

# 装机容量统一换算成 MW 后再分档
CAPACITY_UNIT_FACTORS = [
    ("万千瓦", 10.0),
    ("万kw", 10.0),
    ("万", 10.0),
    ("千瓦", 0.001),
    ("kw", 0.001),
    ("兆瓦", 1.0),
    ("mw", 1.0),
]

BUCKET_SMALL = "small"
BUCKET_MEDIUM = "medium"
BUCKET_LARGE = "large"
BUCKET_PENDING = "pending"
BUCKET_KEYS = [BUCKET_SMALL, BUCKET_MEDIUM, BUCKET_LARGE, BUCKET_PENDING]

DEFAULT_THRESHOLDS = [50.0, 200.0]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_capacity(raw: Any) -> float | None:
    """把「49.5MW」「12 万千瓦」这类写法换算成 MW；缺失或解析不出来归 None（待补充）。"""
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "")
    if not text:
        return None
    match = re.search(r"\d+(?:\.\d+)?", text)
    if match is None:
        return None
    value = float(match.group())
    if value <= 0:
        return None
    lowered = text.lower()
    factor = 1.0
    for unit, unit_factor in CAPACITY_UNIT_FACTORS:
        if unit.lower() in lowered:
            factor = unit_factor
            break
    return value * factor


def bucket_of(capacity_mw: float | None, thresholds: list[float]) -> str:
    """按给定口径把容量归入三档之一；容量缺失归待补充。"""
    if capacity_mw is None:
        return BUCKET_PENDING
    low, high = thresholds
    if capacity_mw < low:
        return BUCKET_SMALL
    if capacity_mw < high:
        return BUCKET_MEDIUM
    return BUCKET_LARGE


def bucket_labels(thresholds: list[float]) -> dict[str, str]:
    low, high = thresholds
    return {
        BUCKET_SMALL: f"小型（< {low:g}MW）",
        BUCKET_MEDIUM: f"中型（{low:g}–{high:g}MW）",
        BUCKET_LARGE: f"大型（≥ {high:g}MW）",
        BUCKET_PENDING: "待补充（装机容量缺失）",
    }


class WindfarmService:
    # ---- 口径版本 -------------------------------------------------------

    def _bootstrap_versions(self) -> None:
        """首次使用时落一版默认口径，后续重启内存仓也能自愈。"""
        table = store.rows(VERSION_TABLE)
        if table:
            return
        table.append({
            "id": 1,
            "code": "v1",
            "thresholds": list(DEFAULT_THRESHOLDS),
            "created_at": _now(),
            "remark": "初始分档口径",
            "active": True,
        })

    def active_version(self) -> dict[str, Any]:
        self._bootstrap_versions()
        return next(version for version in store.rows(VERSION_TABLE) if version.get("active"))

    def list_versions(self) -> dict[str, Any]:
        self._bootstrap_versions()
        versions = sorted(store.rows(VERSION_TABLE), key=lambda item: int(item["id"]), reverse=True)
        # 列表只给摘要；整版快照（含每个场站的分档结论）走 /tiers/archives/{id}
        archives = [
            {
                key: archive.get(key)
                for key in ("id", "version_code", "thresholds", "archived_at", "superseded_by", "remark")
            }
            for archive in sorted(
                store.rows(ARCHIVE_TABLE), key=lambda item: int(item["id"]), reverse=True
            )
        ]
        active = next(version for version in versions if version.get("active"))
        return {
            "active_code": active["code"],
            "thresholds": active["thresholds"],
            "versions": versions,
            "archives": archives,
        }

    def adjust_thresholds(
        self, thresholds: list[float], remark: str | None
    ) -> tuple[dict[str, Any] | None, str]:
        """调整分档口径：旧口径整版留档，新口径立即对存量场站重算。"""
        message = self._validate_thresholds(thresholds)
        if message:
            return None, message
        thresholds = [float(thresholds[0]), float(thresholds[1])]

        old = self.active_version()
        if thresholds == [float(value) for value in old["thresholds"]]:
            return None, "新口径与当前口径完全一致，无需另起版本"

        rows = store.rows(MODULE)
        archive = self._build_snapshot(
            old, rows, old["thresholds"], superseded_by=None, remark=old.get("remark")
        )
        archives = store.rows(ARCHIVE_TABLE)
        archive["id"] = max((int(item.get("id", 0)) for item in archives), default=0) + 1
        archives.append(archive)

        versions = store.rows(VERSION_TABLE)
        next_id = max(int(item["id"]) for item in versions) + 1
        new_version = {
            "id": next_id,
            "code": f"v{next_id}",
            "thresholds": thresholds,
            "created_at": _now(),
            "remark": (remark or "").strip() or "调整装机容量分档口径",
            "active": True,
        }
        old["active"] = False
        # 留档发生在切版本之前：superseded_by 在新版本号确定后补回去
        archive["superseded_by"] = new_version["code"]
        archive["archived_at"] = _now()
        versions.append(new_version)
        return new_version, f"已按新口径重算 {len(rows)} 个场站，原口径 {old['code']} 已留档"

    @staticmethod
    def _validate_thresholds(thresholds: Any) -> str:
        if not isinstance(thresholds, (list, tuple)) or len(thresholds) != 2:
            return "请给出两档分界值（小型/中型、中型/大型，单位 MW）"
        try:
            low, high = float(thresholds[0]), float(thresholds[1])
        except (TypeError, ValueError):
            return "分界值必须是数字，单位为 MW"
        if low <= 0 or high <= 0:
            return "分界值必须大于 0"
        if low >= high:
            return "第一档分界值必须小于第二档分界值"
        return ""

    def _build_snapshot(
        self,
        version: dict[str, Any],
        rows: list[dict[str, Any]],
        thresholds: list[float],
        *,
        superseded_by: str | None,
        remark: str | None,
    ) -> dict[str, Any]:
        """把某一版口径下「区域 × 档位」的完整结论冻结成快照。"""
        return {
            "id": None,
            "version_code": version["code"],
            "thresholds": [float(value) for value in thresholds],
            "remark": remark or version.get("remark"),
            "archived_at": _now(),
            "superseded_by": superseded_by,
            "regions": self._build_regions(rows, thresholds, include_stations=True),
        }

    def get_archive(self, archive_id: int) -> dict[str, Any] | None:
        self._bootstrap_versions()
        return next(
            (item for item in store.rows(ARCHIVE_TABLE) if int(item.get("id", 0)) == archive_id),
            None,
        )

    # ---- 区域 × 档位矩阵 -------------------------------------------------

    def overview(self) -> dict[str, Any]:
        version = self.active_version()
        thresholds = [float(value) for value in version["thresholds"]]
        return {
            "version": {
                "code": version["code"],
                "thresholds": thresholds,
                "updated_at": version["created_at"],
                "remark": version.get("remark"),
            },
            "buckets": [
                {"key": key, "label": bucket_labels(thresholds)[key]} for key in BUCKET_KEYS
            ],
            "regions": self._build_regions(store.rows(MODULE), thresholds, include_stations=False),
        }

    def _build_regions(
        self, rows: list[dict[str, Any]], thresholds: list[float], *, include_stations: bool
    ) -> list[dict[str, Any]]:
        labels = bucket_labels(thresholds)
        region_names = list(REGIONS)
        for row in rows:
            name = str(row.get("所在区域") or "").strip()
            if name and name not in region_names:
                region_names.append(name)

        result: list[dict[str, Any]] = []
        for name in region_names:
            region_rows = [row for row in rows if str(row.get("所在区域") or "").strip() == name]
            cells: list[dict[str, Any]] = []
            for key in BUCKET_KEYS:
                bucket_rows = [
                    row
                    for row in region_rows
                    if bucket_of(parse_capacity(row.get("装机容量")), thresholds) == key
                ]
                status_counts = {
                    status: sum(1 for row in bucket_rows if row.get("status") == status)
                    for status in OVERVIEW_STATUSES
                }
                cell = {
                    "bucket": key,
                    "label": labels[key],
                    "count": len(bucket_rows),
                    "statuses": status_counts,
                }
                if include_stations:
                    cell["stations"] = [
                        {
                            "id": row.get("id"),
                            "场站编码": row.get("场站编码"),
                            "场站名称": row.get("场站名称"),
                            "装机容量": row.get("装机容量"),
                            "status": row.get("status"),
                        }
                        for row in bucket_rows
                    ]
                cells.append(cell)
            result.append({
                "region": name,
                "stations": len(region_rows),
                "empty": len(region_rows) == 0,
                "cells": cells,
            })
        return result

    # ---- 场站清单 -------------------------------------------------------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        region: str | None = None,
        bucket: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("场站编码", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if region:
            rows = [row for row in rows if str(row.get("所在区域") or "").strip() == region]
        if bucket:
            if bucket not in BUCKET_KEYS:
                return [], 0
            thresholds = [float(value) for value in self.active_version()["thresholds"]]
            rows = [
                row
                for row in rows
                if bucket_of(parse_capacity(row.get("装机容量")), thresholds) == bucket
            ]
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
        for field in OPTIONAL_FIELDS:
            value = values.get(field)
            if value is not None and str(value).strip():
                entry[field] = value
        entry["status"] = STATUS_ORDER[0]
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
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"风电场站已{action}"
