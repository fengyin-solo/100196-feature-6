"""风电场站接口：场站清单、区域容量分档概览、口径版本管理与历史留档。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.windfarm import BUCKET_KEYS, WindfarmService

router = APIRouter(prefix="/api/windfarm", tags=["风电场站"])

service = WindfarmService()

LIST_FIELDS = ["场站编码", "场站名称", "所在区域", "装机容量", "并网日期", "运营单位", "海拔高度", "场站状态"]
STATUSES = ["在建", "运行中", "限功率", "停运检修"]


class TierAdjustPayload(BaseModel):
    """装机容量分档口径调整入参：两档分界值，单位 MW。"""

    thresholds: list[float]
    remark: str | None = None


# 注意：下面这些固定路径都要声明在 /{entry_id} 之前，否则会被当成场站 id 匹配。


@router.get("/overview")
def region_overview() -> dict[str, Any]:
    """区域 × 装机容量档位概览：每格给场站数量与在建/运行中/限功率台数。"""
    return service.overview()


@router.get("/tiers")
def list_tier_versions() -> dict[str, Any]:
    """查看当前生效口径与历次口径版本。"""
    return service.list_versions()


@router.post("/tiers/adjust", response_model=ActionResult)
def adjust_tiers(payload: TierAdjustPayload) -> ActionResult:
    """调整装机容量分档口径：存量场站按新口径重算，旧口径整版留档。"""
    entry, message = service.adjust_thresholds(payload.thresholds, payload.remark)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/tiers/archives/{archive_id}")
def get_tier_archive(archive_id: int) -> dict[str, Any]:
    """回看某一版历史口径当时的分档结论；不提供修改入口，留档只读。"""
    archive = service.get_archive(archive_id)
    if archive is None:
        raise HTTPException(status_code=404, detail=f"历史分档留档 {archive_id} 不存在")
    return archive


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按场站编码检索"),
    status: str | None = Query(default=None, description="在建、运行中、限功率、停运检修"),
    region: str | None = Query(default=None, description="按所在区域过滤，供概览下钻"),
    bucket: str | None = Query(default=None, description="按装机容量档位过滤：small/medium/large/pending"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按场站编码、状态、区域、档位过滤风电场站列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if bucket is not None and bucket not in BUCKET_KEYS:
        raise HTTPException(
            status_code=400,
            detail="档位只支持 small、medium、large、pending（装机容量缺失）",
        )
    items, total = service.list_entries(
        keyword=keyword,
        status=status,
        region=region,
        bucket=bucket,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条风电场站，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="风电场站已登记", entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出风电场站清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "windfarm", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条风电场站明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"风电场站 {entry_id} 不存在或已归档")
    return entry


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条风电场站执行并网投运、申请限功率、转入检修；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
