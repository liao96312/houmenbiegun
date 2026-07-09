# 后门五分钟 MVP

一期最小可跑版本：H5 场景页 + FastAPI API + OpenAI 兼容模型接口。

## 启动

零依赖启动：

```powershell
$env:AI_API_KEY="你的 key"
$env:AI_BASE_URL="https://api.deepseek.com/v1"
$env:AI_MODEL="deepseek-chat"
python -m app.server
```

或：

```powershell
.\scripts\start.ps1
```

FastAPI 启动：

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

打开：http://127.0.0.1:8000

后台：http://127.0.0.1:8000/admin

健康检查：http://127.0.0.1:8000/health

Docker：

```powershell
Copy-Item .env.example .env
docker compose up --build
```

## 可选 TTS

默认关闭：

```powershell
$env:TTS_ENABLED="true"
```

当前只返回占位响应，不阻塞一期主流程。

前端另有浏览器原生朗读开关，不依赖服务端 TTS。

## 配置文件

- 场景：`data/scenes.json`
- Prompt：`data/prompts.json`
- 分支语料：`data/branches.json`（预置分支对话树 + 陪伴手法解析，离线可用）
- 运行数据：`data/app.db`（SQLite，本地生成，不入库）

后台支持直接编辑场景和 Prompt JSON。
部署到公网前设置 `ADMIN_TOKEN`，后台保存时会要求输入口令。

导出每个场景配置：

```powershell
python scripts/export_scene_configs.py
```

重新生成本地 poster：

```powershell
python scripts/make_posters.py
```

重写场景角色：

```powershell
python scripts/seed_characters.py
```

## 分支语料与陪伴手法解析（二期新增）

参考 what.arksec.net 聊天模拟器「选项推进剧情 + 手法解析」的形态，把 PUA 操控解析反转为**陪伴/倾听手法解析**。解决一期完全依赖大模型、质量不稳定的问题。

- **不知道说什么**模式：用户不想自由输入时，每步给出 2-3 个真实可说的人话选项，每选一项接一句手写的陪伴回复。分支模式不依赖大模型，离线也能跑，保证每一句都到位。
- **陪伴手法解析**：顶栏「解析」开关打开后，每句陪伴回复下方显示一条解析，点出背后的倾听原则（先接住不解决、把今天和整个人切开、允许沉默……）。对应参考站的「查看 PUA 手法解析」，方向相反。
- **多结局**：每个场景的分支树有 2-4 个结局（松了一点 / 今晚先到这儿 / 安全转介），按情绪走向收尾。
- **安全转介**：分支里出现自伤自杀信号时，退出场景感，给现实安全建议与援助热线（400-161-9995 / 120）。

自由聊天仍是默认模式，分支只是「不知道说什么」时的引导，两种模式随时可切。

接口：

- `GET /api/branches/{scene_id}` — 取某场景的整棵分支树
- `POST /api/chat/branch` — `{conversation_id, node_id?, user_label?}`，返回下一节点的 `companion_line / analysis / options / is_ending / ending_type / should_end`

数据结构见 `data/branches.json` 顶部 `_meta`。设计与参考说明见 `docs/branches_design.md`。
