"""
app_factory — Celery 应用工厂

提供统一入口 `create_celery_app`，按设计文档第 9.2 节的顺序执行：
1. 在需要时安装 RedBeat Sentinel 兼容补丁（顺序敏感：必须先于 Celery app 创建）
2. 创建 Celery app
3. 加载标准化配置（依赖 ab_celery.config.build_celery_config）
4. 安装任务计时能力（顺序敏感：必须先于任务注册）
5. 处理任务发现 / 任务模块导入
6. 按需注册 Cron 任务（依赖 ab_celery.cron_registry）
7. 返回完成初始化的 app

设计要点：
- 默认不启用任何具有环境依赖的副作用（RedBeat 补丁、task_timer 计时）
- 缺少可选依赖时不静默忽略，直接抛出原始 ModuleNotFoundError
- 不读取环境变量，不加载 .env，不接入配置中心
- 与 task_timer / cron_registry / redbeat_sentinel / safe_scheduler 协同，
  不重复实现其能力

用法：
    from ab_celery.app_factory import create_celery_app
    from ab_celery.config import CeleryConfig
    from ab_celery.task_base import AutoRetryTask

    app = create_celery_app(
        config=CeleryConfig(
            app_name="myapp",
            broker_url="redis://localhost:6379/0",
        ),
        task_packages=["myapp"],          # 触发 autodiscover_tasks
        default_task_base=AutoRetryTask,  # 可选：默认任务基类
    )
"""

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from celery import Celery

from ab_celery.config import CeleryConfig, build_celery_config

if TYPE_CHECKING:
    from ab_celery.cron_registry import CronRegistry
    from ab_celery.task_timer import MetricsRecorder

logger = logging.getLogger("ab_celery.app_factory")


def create_celery_app(
    config: "CeleryConfig | dict[str, Any]",
    *,
    task_modules: Sequence[str] | None = None,
    task_packages: Sequence[str] | None = None,
    default_task_base: type | None = None,
    enable_task_timer: bool = False,
    task_timer_recorder: "MetricsRecorder | None" = None,
    cron_registry: "CronRegistry | None" = None,
    apply_redbeat_sentinel_patch: bool = False,
) -> Celery:
    """
    创建并完成标准化初始化的 Celery 应用。

    参数:
        config: CeleryConfig 实例或与之兼容的 dict，作为最终 conf.update 的来源。
        task_modules: 显式任务模块路径列表，对应 Celery 的 `imports` 配置。
        task_packages: 包路径列表，对应 Celery 的 `autodiscover_tasks` 入参。
        default_task_base: 默认任务基类（如 AutoRetryTask）。仅在显式传入时生效。
        enable_task_timer: 是否启用任务自动计时；启用时在任务注册前安装。
        task_timer_recorder: 任务计时 recorder；为 None 时由 task_timer 使用默认 logger recorder。
        cron_registry: 已构造的 CronRegistry；提供时在 app 创建后注册周期任务。
        apply_redbeat_sentinel_patch: 是否在创建 app 之前应用 RedBeat Sentinel 兼容补丁。

    返回:
        已完成初始化的 Celery 实例。

    异常:
        TypeError: config 类型不合法（由 build_celery_config 抛出）。
        ModuleNotFoundError: 启用了依赖可选第三方库的能力但库未安装。

    步骤:
    1. 若 apply_redbeat_sentinel_patch=True，先应用补丁（顺序敏感）
    2. 构造扁平 conf 字典 + 解析 app_name
    3. 创建 Celery 实例（可选指定 task_cls=default_task_base）
    4. app.conf.update(conf)
    5. 若 enable_task_timer=True，先于任务注册安装 task_timer（顺序敏感）
    6. 处理 task_modules / task_packages
    7. 若提供 cron_registry，调用其 register_all
    8. 返回 app
    """
    # 1. 顺序敏感：RedBeat 补丁必须先于 Celery app 创建
    if apply_redbeat_sentinel_patch:
        _apply_redbeat_sentinel_patch()

    # 2. 标准化配置 + 解析 app_name
    if isinstance(config, CeleryConfig):
        app_name = config.app_name
    elif isinstance(config, dict):
        app_name = config.get("app_name") or "celery"
    else:
        # 交给 build_celery_config 给出统一的 TypeError
        app_name = "celery"
    conf = build_celery_config(config)

    # 3. 创建 Celery 实例
    celery_kwargs: dict[str, Any] = {}
    if default_task_base is not None:
        # task_cls 接受 "module:Class" 字符串或类对象，这里直接传类对象
        celery_kwargs["task_cls"] = default_task_base
    app = Celery(app_name, **celery_kwargs)

    # 4. 加载标准化配置
    app.conf.update(conf)

    # 5. 顺序敏感：task_timer 必须先于任务注册
    if enable_task_timer:
        _install_task_timer(app, task_timer_recorder)

    # 6. 任务发现 / 任务模块导入
    if task_modules:
        # imports 会被 Celery 在 worker 启动时按需 import
        app.conf.imports = tuple(app.conf.imports or ()) + tuple(task_modules)
    if task_packages:
        app.autodiscover_tasks(list(task_packages))

    # 7. 按需注册 Cron 任务
    if cron_registry is not None:
        cron_registry.register_all(app)

    logger.info(
        "[app_factory] celery app 初始化完成 name=%s timer=%s redbeat_patch=%s "
        "modules=%s packages=%s cron=%s",
        app_name,
        enable_task_timer,
        apply_redbeat_sentinel_patch,
        len(task_modules) if task_modules else 0,
        len(task_packages) if task_packages else 0,
        cron_registry is not None,
    )
    return app


def _apply_redbeat_sentinel_patch() -> None:
    """
    应用 RedBeat Sentinel 补丁。缺少 celery-redbeat / redis 时直接抛出 ModuleNotFoundError，
    不静默吞掉。
    """
    try:
        from ab_celery.redbeat_sentinel import apply_sentinel_patch
    except ModuleNotFoundError as exc:
        # 显式提示调用方需要安装可选依赖
        raise ModuleNotFoundError(
            "启用 apply_redbeat_sentinel_patch 需要安装 celery-redbeat 与 redis；"
            "请先安装对应依赖再调用 create_celery_app。"
        ) from exc
    apply_sentinel_patch()


def _install_task_timer(app: Celery, recorder: "MetricsRecorder | None") -> None:
    """
    安装任务计时能力。task_timer 模块仅依赖 celery 自身，正常情况下不会缺失，
    这里仍保留显式异常路径以便给出可读提示。
    """
    try:
        from ab_celery.task_timer import install_task_timer
    except ModuleNotFoundError as exc:  # pragma: no cover - 防御性
        raise ModuleNotFoundError(
            "启用 enable_task_timer 需要 ab_celery.task_timer 模块可用。"
        ) from exc
    install_task_timer(app, recorder=recorder)
