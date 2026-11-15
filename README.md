# 多种计时记录的原始直方图和中心对比

dwell-distribution 是 Python 业务分析应用，目前提供原始资料核对和已有口径概览；摘要只说明观测记录本身，不代表尚未建立的推断、个性化、潜在分布或决策收益。

## 目录和边界

`dwell_distribution/data.py` 读取资料并冻结公开日期可见的版本。`product.py` 实现当前领域摘要，`latent.py` 实现与记录机制相容的潜在时长界限分析，`workflow.py` 串联资料读取与成果发布，`service.py` 提供本地 HTTP 资料和消费接口，`store.py` 保存不可变成果和当前消费约束，`client.py` 是调用适配层。服务接口见 `docs/protocol.md`，具体资料含义见 `docs/data-contract.md`。`tests` 覆盖已有业务口径与联调，不代表新增方法已经实现。

## 环境和依赖

兼容 Python 3.11.x，具体范围见 `pyproject.toml`；`.python-version` 固定受支持的次版本，不限定补丁版本。独立 Docker 镜像使用固定摘要的 Python 3.11.14，生产验证容器使用 Python 3.11.2，两者采用相同的完整锁定依赖。`requirements.lock` 与 `requirements.txt` 固定数值计算和模型分析的完整依赖版本。应用运行、测试及资料均在本地，不请求外部 API；构建时预装依赖，正式运行不安装或下载资料。

```bash
docker build -t dwell-distribution:local .
docker run --rm --network none dwell-distribution:local python tools/demo.py
docker run --rm --network none dwell-distribution:local python -m unittest discover -s tests -v
```

已有 Python 环境可以先执行 `python -m pip install -r requirements.lock`，然后执行以下检查与产品演示：

```bash
python -m compileall -q dwell_distribution tests tools
python -m unittest discover -s tests -v
python -m build --wheel --no-isolation
python tools/demo.py
```

演示会启动真正的本地 HTTP 服务，读取业务资料，计算当前概览、发布后读回成果，结束时自动退出。每次使用临时数据库，不覆盖工作目录。它展示当前产品，新增分析以最终实现的业务入口为准。

## 交互服务

```bash
python -m dwell_distribution.service --port 8765
```

默认服务地址为 `127.0.0.1:8765`，本地成果保存在 `local-state.sqlite3`。启动后资料只读；本地消费约束可通过管理接口变更，不会修改已发布成果。中断运行可正常退出。已有概览使用 `observed-overview-v1` 标明方法版本，额外分析可使用自己的方法和结果结构，不能复用旧方法名掩盖语义变化。

## 潜在时长界限分析

`publish_latent_analysis`（方法名 `latent-dwell-bounds-v1`）是研究员视图，与对外的原始分布 `observed-overview-v1` 分开发布、互不改写。它把每条记录按当时的计时口径还原为潜在时长区间：sensor 按 devices 规则的步长取整并在 cap 封顶（封顶记录只有有限下界），gate 按契约取整分钟且 90 分钟封顶，interview 的报整点步长由全量回访记录识别（当前为 15 分钟，半宽 7.5 分钟）。paired_timing 复计资料按 inclusion_probability 逆概率加权，只用于验证机制模型与报整点宽度，不做点式偏误修正；复计与模型不一致时分析直接报错。

结果中 `strata` 给出各中心、各讲解方式的潜在中位数与长停留比例（默认阈值 45 分钟）的上下界，`measurement_basis` 标明该判断用到的计时口径构成（方式、规则代次、封顶与报整点记录数）。`comparisons` 只比较讲解方式构成相同的中心对，以及整体讲解方式对比；每项比较给出差值界限、`supported_sign` 和 `depends_on_extra_assumptions`：界限跨过零表示符号依赖区间内分布假设，讲解方式因只在中心之间变化而始终需要中心可比假设，复计仅覆盖 daytime 的中心另需口径推广假设。真实峰与报数偏好仅凭现有资料无法完全区分时，结果就是这些范围，不提供过度精细的还原曲线。
