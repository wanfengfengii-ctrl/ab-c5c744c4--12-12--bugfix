# 复合材料截面 · 四向投影复核台

检测员在浏览器中编辑二值截面的 **行 / 列 / r−c / r+c** 四向投影与已知单元，
通过真实 FastAPI 发起重建；后端穷举判定 **无解 / 唯一解 / 多解**，并在多解时
按 **行优先位串（0 先于 1）** 返回最小的两个见证。页面对每条投影线显示
「见证实算和 / 目标值」，并在两份歧义见证间切换、高亮全部差异单元——正是那些
横、纵投影（甚至局部填格）看似满足、却在斜向投影下无法察觉的伪截面。

- 截面规模：4–12 行 × 4–12 列，行列均从 0 编号
- 行投影自上而下；列投影自左向右
- 两组对角投影分别按 `r−c`、`r+c` 递增排列（各 `R+C−1` 条）
- 已知单元不得重复或冲突

## 目录

```
backend/            FastAPI 服务
  app/solver.py     穷举回溯 + 强制传播求解器（无贪心、无随机）
  app/validation.py 结构化、可定位的输入校验
  app/main.py       API（/api/reconstruct、/api/health）与静态托管
  tests/            求解器 2^n 暴力枚举对照测试、API 测试
  acceptance/       一次性验收脚本（仅用标准库，含独立暴力复核）
frontend/           React + Vite 复核台
  nginx.conf        静态托管 + /api 反向代理 + /health
docker-compose.yml  api / web（健康检查、端口可配）+ 一次性 verify 服务
```

## 运行

需要 Docker 与 Docker Compose v2。

```bash
# 可选：配置宿主机端口（默认 WEB 8080 / API 8000）
cp .env.example .env

docker compose up -d --build
# 浏览器打开 http://localhost:${WEB_PORT:-8080}
```

健康检查：

- API：`GET http://localhost:${API_PORT:-8000}/api/health`
- Web：`GET http://localhost:${WEB_PORT:-8080}/health`

## 一次性验收（verify 服务）

`verify` 是 **一次性** 服务：等待 api、web 健康后，经真实 HTTP 执行 72 项检查，
完成即退出，并以退出码报告结果（0 全部通过，非 0 存在失败）。

```bash
docker compose run --rm verify
# 或随栈一起运行（跑完自行退出，不重启）：
docker compose up --build verify
docker inspect compose 中 verify 容器 --format '{{.State.ExitCode}}'
```

验收内容包括：API/Web 健康检查与静态资源、`/api` 反代、4×4 歧义对（并用
**独立的 2^16 暴力枚举** 复核返回的恰为最小两解）、已知单元锁定唯一解、
本地合法但联合无解的实例、六类可定位非法输入（422/400），以及 12×12 冒烟
（独立重算两份见证的全部四向实算和与已知单元、位串序、差异单元）。

## API

`POST /api/reconstruct`

```json
{
  "rows": 4,
  "cols": 4,
  "row":  [1, 1, 1, 1],
  "col":  [1, 1, 1, 1],
  "diff": [0, 1, 1, 0, 1, 1, 0],
  "sum":  [0, 1, 1, 0, 1, 1, 0],
  "known": [{"row": 0, "col": 2, "value": 1}]
}
```

响应（HTTP 200，`status` 为 `none` / `unique` / `multiple`；无解是合法的
计算结果而非请求错误）：

```json
{
  "status": "multiple",
  "rows": 4, "cols": 4,
  "targets": {"row": [...], "col": [...], "diff": [...], "sum": [...]},
  "witnesses": [
    {"grid": "0010100000010100",
     "lines": {"row": [...], "col": [...], "diff": [...], "sum": [...]}}
  ],
  "differences": [{"index": 2, "row": 0, "col": 2, "values": [1, 0]}]
}
```

非法输入返回 HTTP 422，`errors[].field` 为可定位路径，如 `row[2]`、
`known[3].col`、`diff[0]`：

```json
{"message": "输入校验未通过，请定位下列字段后重试",
 "errors": [{"field": "known[1]", "code": "conflict", "message": "单元 (0,0) 冲突……"}]}
```

前端在非法输入或判定无解时会 **清除旧网格**，并在对应输入处与错误列表中
给出可定位反馈。

## 求解器的正确性与完整性

求解器对四组线性和约束做 **穷举深度优先回溯 + 弧一致性强制传播**：

1. 按 **行优先** 顺序选择下一个自由单元，并先尝试 `0` 再尝试 `1`；
2. 每次赋值后传播「只能取某一值」的单元（当前前缀的逻辑推论）至不动点，
   记录推断以便回滚；记录强制值不会跳过任何解；
3. 找到第一个解后 **继续搜索**，直到找到第二个（证明多解）或穷尽搜索空间
   （证明唯一 / 无解）——不使用贪心、随机或「找到首解即推测唯一」。

因分支顺序固定为行优先且 0 先于 1，产出解严格按行优先位串升序到达，故
多解时返回的就是最小的两个。

`backend/tests/test_solver.py` 对数百个 4×4 / 4×5 / 5×4 随机实例逐一与
**2^n 全枚举** 比对状态及最小两解；12×12 最坏多解约 0.2 s、唯一约 0.06 s、
深层无解约 3.4 s（认证型计算，按钮触发）。

## 歧义见证（切换构件）

下列两个 4×4 截面四向投影完全相同，但互为伪截面；页面会高亮全部 8 个
差异单元（`0↔1`），可在两份见证间切换核对：

```
.01.        .10.
1...        ...1
...1   ≡    1...     （行=列=[1,1,1,1]，
.1..        ..1.      两对角=[0,1,1,0,1,1,0]）
```

（`.` 与 `0` 同义，均表示基体 0；这里统一用 `.` 表示零。）
位串分别为 `0010100000010100` 与 `0100000110000010`（前者为最小解）。

## 本地开发（不用 Docker）

```bash
# 后端
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端（/api 经 Vite 代理到 8000）
cd frontend
npm install
npm run dev
```

运行测试：

```bash
cd backend && . .venv/bin/activate
python -m unittest discover -s tests -v
```
