# F1 Quote/0 Docker

一个运行在 Docker 中的 Quote/0 F1 看板服务。它从 OpenF1 和 Jolpica 获取赛程、比赛结果及积分榜数据，将 11 种看板预渲染为 Quote/0 原生的 `296×152` 单色画面，再通过 Dot Canvas API 推送到设备。

项目不需要图形桌面或入站 Web 端口，适合任何能够运行 Docker Engine 与 Docker Compose v2 的 Linux 主机。

## 功能

- 支持比赛结果、下一场比赛、倒数日、车手积分和车队积分等 11 种看板。
- 可固定显示单一看板，也可按指定顺序轮播。
- 手机轻碰 Quote/0 的 NFC 区域时，可从当前 F1 画面打开手机端 F1 Dashboard。
- 从设备 Loop 自动发现 Canvas API 条目，无需手动复制任务 Key。
- 使用 Noto Sans CJK、4 倍超采样和 Lanczos 缩放改善小字号可读性。
- 文字、数字、边框和分隔线使用硬阈值二值化，避免误差扩散在竖直笔画上制造毛刺。
- 赛道轮廓和车队标志单独使用 Atkinson 抖动，保留曲线细节。
- 以非 root 用户运行，启用只读根文件系统、能力移除和 `no-new-privileges`。
- 通过 Docker 命名卷保存非敏感运行状态；凭据仅保存在本地 `.env`。

## 前置条件

1. 安装 Docker Engine 和 Docker Compose v2。
2. 在 Dot App 中取得 API Key 和 Quote/0 设备 ID。
3. 在 Quote/0 的 Loop 中添加一个 Canvas API 内容。

## 快速开始

### 使用 Docker Hub 镜像

已构建的 `linux/amd64` 镜像公开发布在 [Docker Hub](https://hub.docker.com/r/furyth666/f1-quote0-docker)：

```sh
docker pull furyth666/f1-quote0-docker:latest
```

下载仓库中的 `docker-compose.yml` 和 `.env.example`，复制并填写 `.env` 后即可启动，无需本地构建：

```sh
cp .env.example .env
chmod 600 .env
docker compose pull
docker compose up -d --no-build
```

需要固定版本时，将 Compose 中的镜像标签由 `latest` 改为发布版本，例如 `1.2.0`。

### 从源码构建

```sh
git clone https://github.com/furyth666/f1-quote0-docker.git
cd f1-quote0-docker
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，至少填写：

```dotenv
DOT_API_KEY=your_dot_api_key
QUOTE0_DEVICE_ID=your_quote0_device_id
```

构建并启动：

```sh
docker compose up -d --build
docker compose logs --tail 100 -f f1-quote0
```

查看非敏感状态：

```sh
docker compose exec f1-quote0 cat /data/status.json
```

当 `status` 为 `ready` 且 `push_verified` 为 `true` 时，表示数据读取和设备推送均已完成端到端验证。

## Dashboard 选择

`F1_DASHBOARD` 用于固定显示一个看板，并优先于轮播配置：

```dotenv
F1_DASHBOARD=countdown
```

使用 `all` 按下表顺序轮播全部看板：

```dotenv
F1_DASHBOARD=all
```

如需自定义轮播，将单选变量留空并设置逗号分隔的列表：

```dotenv
F1_DASHBOARD=
F1_DASHBOARDS=countdown,nextSession,driverStanding
PUSH_INTERVAL_SECONDS=300
```

| 变量值 | 内容 | 额外选择器 |
| --- | --- | --- |
| `latestAllSession` | 最近一场练习、排位、冲刺或正赛前三名 | 无 |
| `latestRaceOrSprint` | 最近一场冲刺或正赛前三名 | 无 |
| `nextSession` | 接下来两场赛段及本地开始时间 | 无 |
| `countdown` | 下一场正赛的自然日倒数 | 无 |
| `driverStanding` | 指定车手的年度排名与积分 | `F1_DRIVER_ID` |
| `driverLatestAll` | 指定车手最近一场赛段结果 | `F1_DRIVER_ID` |
| `driverLatestRaceOrSprint` | 指定车手最近一场冲刺或正赛结果 | `F1_DRIVER_ID` |
| `teamStanding` | 指定车队的年度排名与积分 | `F1_CONSTRUCTOR_ID` |
| `teamDriversStanding` | 指定车队两位车手的排名与积分 | `F1_CONSTRUCTOR_ID` |
| `teamLatestAll` | 指定车队最近一场赛段结果 | `F1_CONSTRUCTOR_ID` |
| `teamLatestRaceOrSprint` | 指定车队最近一场冲刺或正赛结果 | `F1_CONSTRUCTOR_ID` |

车手或车队 ID 为空、无法匹配时，服务会选择当前积分榜领先者。未知 Dashboard 名称和重复项会被忽略；如果最终没有有效项目，则回退到 `latestAllSession,nextSession`。

## NFC 打开 F1 Dashboard

F1 Canvas 载荷默认包含手机端 Dashboard 链接：

```dotenv
F1_NFC_LINK=https://www.formula1.com/en/timing/f1-live
```

当 F1 看板是 Quote/0 当前显示内容时，用支持 NFC 的手机轻碰设备右侧空白区域，Dot.App 或 iOS App Clip 会读取当前内容并打开该链接。NFC 标签本身仍是 Quote/0 的固定入口，不会被改写。

如需换成其他网页或 App URL Scheme，修改 `F1_NFC_LINK`；将它留空即可让 F1 Canvas 不携带跳转链接。默认目标由 Formula 1 官方提供，服务只把地址写入 Dot Canvas API 的 `link` 字段。

可直接从镜像查询支持的名称：

```sh
docker compose run --rm f1-quote0 --list-dashboards
```

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DOT_API_KEY` | 空 | Dot API Key，必填 |
| `QUOTE0_DEVICE_ID` | 空 | Quote/0 设备 ID，必填 |
| `CANVAS_TASK_KEY` | 自动发现 | 可选的 Canvas 任务 Key |
| `CANVAS_TASK_ALIAS` | `F1 看板` | Canvas 内容名称 |
| `CANVAS_REFRESH_NOW` | `false` | 推送后是否立即切换到 F1 画面；建议保持 `false`，避免打断 Loop 中的其他看板 |
| `F1_NFC_LINK` | `https://www.formula1.com/en/timing/f1-live` | NFC 触碰当前 F1 Canvas 后打开的官方 Live Timing；留空关闭 |
| `F1_DASHBOARD` | 空 | 单一看板名称，或 `all` |
| `F1_DASHBOARDS` | `latestAllSession,nextSession` | 自定义轮播列表 |
| `F1_DRIVER_ID` | 自动选择 | 车手看板使用的 OpenF1/Jolpica ID |
| `F1_CONSTRUCTOR_ID` | 自动选择 | 车队看板使用的构造商 ID |
| `PUSH_INTERVAL_SECONDS` | `300` | 设备推送/轮播间隔，最小 60 秒 |
| `DATA_REFRESH_SECONDS` | `180` | 非比赛时的数据刷新间隔，最小 60 秒 |
| `LIVE_REFRESH_SECONDS` | `15` | 比赛进行中的数据刷新间隔，最小 15 秒 |
| `TZ` | `UTC` | IANA 时区，例如 `Asia/Hong_Kong` |

默认的 `CANVAS_REFRESH_NOW=false` 会更新 Loop 中的 F1 Canvas 内容，但不会要求设备立即跳转到它，因此定时推送不会主动顶掉当前显示的其他看板。设为 `true` 时，每次推送都会请求设备立即显示 F1 看板。

无论该值为何，服务仍会按 `PUSH_INTERVAL_SECONDS` 调用 Canvas API；`false` 控制的是是否立即切换屏幕，并不是停止后台内容更新。固定单一看板时可以适当提高推送间隔；轮播多个 F1 看板时，该值同时决定 F1 内容的更新速度。

## 可选代理

服务默认直接访问：

- `api.openf1.org`
- `api.jolpi.ca`
- `dot.mindreset.tech`

如果 Docker 主机必须通过代理访问外网，可以在 `.env` 中加入标准代理变量：

```dotenv
HTTP_PROXY=http://proxy.example:3128
HTTPS_PROXY=http://proxy.example:3128
NO_PROXY=localhost,127.0.0.1
```

Compose 不依赖任何预先存在的自定义 Docker 网络；如需让服务通过同一 Docker 网络中的代理容器访问外网，可自行在 Compose 中添加该网络并使用代理容器的服务名。

## 常用操作

重新构建并启动：

```sh
docker compose up -d --build
```

修改 `.env` 后重建容器：

```sh
docker compose up -d --force-recreate --no-build
```

查看健康状态和日志：

```sh
docker compose ps
docker compose logs --tail 100 f1-quote0
```

停止服务但保留状态卷：

```sh
docker compose down
```

如明确需要同时删除非敏感状态卷，可使用 `docker compose down -v`。该命令不可撤销，但不会删除主机上的 `.env`。

## 数据与渲染

- OpenF1：赛段、实时/最终排名和异常完赛状态。
- Jolpica：车手、车队及年度积分榜。
- 本地 `assets/`：赛道轮廓、F1 标志和车队标志。
- Pillow + Noto Sans CJK：生成原生 `296×152`、1-bit PNG。
- Dot Canvas API：把完整画面推送到 Quote/0。

所有外部数据都会先归一化为内部 Dashboard 模型，再进入统一栅格渲染器。Canvas 载荷在本地进行尺寸、层级、字符串长度和图片大小检查；当单张 PNG 超过图片数据 URI 限制时，会无损切分为水平分片。

## 安全设计

- `.env`、日志、数据库、私钥和本地运行状态均被 Git 忽略。
- Compose 不发布任何入站端口。
- 容器使用固定的非 root UID/GID `10001:10001`。
- 根文件系统只读，仅 `/tmp` 和命名卷 `/data` 可写。
- 删除全部 Linux capabilities，并设置 `no-new-privileges`。
- `status.json` 只包含运行状态、当前看板和已解析的公开比赛选择器，不包含 API Key 或设备 ID。

## 开发与测试

本地测试：

```sh
python -m pip install -r requirements.txt
cd service
python -m unittest discover -s tests -v
```

验证所有 Dashboard 的实时 Canvas 载荷：

```sh
python scripts/validate_all_dashboards.py
```

## 自动发布

GitHub Actions 会在 `main` 分支每次更新后重新构建并推送 Docker Hub 镜像：

- `latest`：当前 `main` 分支。
- `sha-<提交号>`：可追溯到具体 Git 提交的不可混淆标签。
- 推送形如 `v1.3.0` 的 Git 标签时，同时发布 `1.3.0` 和 `1.3`。

工作流只读取 `DOCKERHUB_USERNAME` 与 `DOCKERHUB_TOKEN` 两个 GitHub Actions Secrets；Docker Hub 令牌不会进入代码、镜像层或构建日志。

项目结构：

```text
assets/                  赛道和车队 PNG 素材
service/f1_quote0/       Python 服务、数据层和渲染器
service/tests/           单元与 Canvas 合约测试
scripts/                 预览、实机回读和载荷验证工具
Dockerfile               非 root 生产镜像
docker-compose.yml       通用 Docker Compose 配置
.env.example             无凭据配置模板
```

## 致谢

本项目的 Dashboard 设计、Quote/0 Canvas 集成思路和部分视觉素材源自 [belcheckyoung/f1-quote0](https://github.com/belcheckyoung/f1-quote0)。特别感谢原作者 [@belcheckyoung](https://github.com/belcheckyoung) 公开该项目，为这个独立的 Python/Docker 实现提供了基础和灵感。

赛道素材和第三方标识的来源及权利说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

这是一个非官方个人项目，与 Formula 1、Dot/Mindreset、OpenF1、Jolpica、任何车队或其合作伙伴不存在隶属或认可关系。Formula 1、车队名称、标志及其他第三方名称和标识归各自权利人所有。
