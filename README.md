# 📚 多 Agent 学习问答助手

基于 **LangGraph 多 Agent 架构** 的智能学习辅导系统。系统通过多个专业 Agent 协作，为学生提供概念讲解、解题辅导、智能出题和复习巩固等个性化学习服务。

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 🔀 智能路由 | 自动识别问题类型（概念/解题/练习/复习） |
| 🔍 向量检索 | 基于 Chroma 的知识库检索，支持查询重写 |
| 📖 苏格拉底式讲解 | 结构化分层讲解，引导思考而非直接给答案 |
| ✏️ 个性化出题 | 根据错误次数自适应难度（基础/变式/易错） |
| 🧠 学习记忆 | 追踪薄弱知识点、错误计数、学习轨迹 |
| 📄 PDF 知识入库 | 上传 PDF 自动分块向量化 |
| 💬 SSE 流式响应 | 实时流式输出，逐节点展示处理进度 |

## 🏗️ 架构

```
┌──────────────────────────────────────────────────┐
│                   Frontend                        │
│          Next.js 14 + TypeScript + Tailwind       │
│                   :3000                           │
└──────────────────┬───────────────────────────────┘
                   │ SSE / REST
┌──────────────────▼───────────────────────────────┐
│                   Backend                         │
│              FastAPI + LangGraph                  │
│                   :8000                           │
│                                                   │
│  ┌────────┐  ┌───────────┐  ┌───────────┐        │
│  │ Router │→ │ Retriever │→ │ Explainer │        │
│  └────────┘  └───────────┘  └─────┬─────┘        │
│                                    │              │
│                              ┌─────▼─────┐        │
│                              │   Quiz    │        │
│                              └─────┬─────┘        │
│                              ┌─────▼─────┐        │
│                              │  Memory   │        │
│                              └───────────┘        │
└──────────────────┬───────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────┐
│              Chroma Vector DB                     │
│                   :8001                           │
└──────────────────────────────────────────────────┘
```

### Agent 执行路径

| 问题类型 | 执行链路 |
|----------|----------|
| concept / problem | router → retriever → explainer → memory |
| practice | router → quiz → memory |
| review | router → retriever → explainer → quiz → memory |

## 📁 项目结构

```
learning-assistant/
├── docker-compose.yml
├── README.md
│
├── backend/
│   ├── main.py                 # FastAPI 入口
│   ├── requirements.txt        # Python 依赖
│   ├── Dockerfile
│   ├── startup.sh              # 启动脚本
│   ├── .env.example            # 环境变量模板
│   ├── schemas/
│   │   └── state.py            # LangGraph State 定义
│   ├── agents/
│   │   ├── router.py           # 路由 Agent
│   │   ├── retriever.py        # 检索 Agent
│   │   ├── explainer.py        # 讲解 Agent
│   │   ├── quiz.py             # 出题 Agent
│   │   └── memory.py           # 记忆 Agent
│   ├── graph/
│   │   └── workflow.py         # LangGraph 工作流编排
│   ├── tools/
│   │   └── retriever.py        # Chroma 向量检索工具
│   └── api/
│       ├── chat.py             # POST /chat (SSE)
│       └── upload.py           # POST /upload (PDF)
│
└── frontend/
    ├── package.json
    ├── Dockerfile
    ├── tailwind.config.ts
    ├── app/
    │   ├── layout.tsx          # 根布局
    │   ├── page.tsx            # 首页 → /chat
    │   ├── chat/page.tsx       # 问答主页
    │   ├── practice/page.tsx   # 刷题页
    │   └── dashboard/page.tsx  # 学习仪表盘
    ├── components/
    │   ├── ChatWindow.tsx      # 消息列表 + SSE
    │   ├── ExplanationCard.tsx # 结构化讲解卡片
    │   ├── InputBar.tsx        # 输入框
    │   ├── KnowledgePanel.tsx  # 知识掌握度面板
    │   └── BottomNav.tsx       # 移动端底部导航
    └── lib/
        └── api.ts              # 后端接口封装
```

## 🚀 快速开始

### 方式一：Docker Compose（推荐）

**1. 克隆项目**

```bash
git clone <repo-url>
cd learning-assistant
```

**2. 配置环境变量**

```bash
cp backend/.env.example backend/.env
```

编辑 `backend/.env`，填入你的 OpenAI API Key：

```env
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
```

**3. 启动所有服务**

```bash
docker-compose up -d
```

**4. 访问**

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:3000 |
| 后端 API | http://localhost:8000 |
| 后端文档 | http://localhost:8000/docs |
| Chroma | http://localhost:8001 |

### 方式二：本地开发

**1. 后端**

```bash
cd backend

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 OPENAI_API_KEY

# 创建数据目录
mkdir -p data/memory

# 启动
python main.py
```

后端运行在 http://localhost:8000，API 文档在 http://localhost:8000/docs

**2. 前端**

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端运行在 http://localhost:3000

**3. Chroma（可选，使用 Docker）**

```bash
docker run -d \
  --name chroma \
  -p 8001:8000 \
  -e IS_PERSISTENT=TRUE \
  chromadb/chroma:latest
```

## ⚙️ 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_API_KEY` | OpenAI API 密钥 | **必填** |
| `OPENAI_BASE_URL` | OpenAI API 地址 | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | 讲解模型 | `gpt-4o` |
| `OPENAI_EMBEDDING_MODEL` | Embedding 模型 | `text-embedding-3-small` |
| `CHROMA_PERSIST_DIR` | Chroma 数据存储路径 | `./chroma_data` |
| `CHROMA_COLLECTION_NAME` | Collection 名称 | `learning_docs` |
| `CHUNK_SIZE` | PDF 分块大小 | `1000` |
| `CHUNK_OVERLAP` | 分块重叠 | `200` |

## 📡 API 接口

### POST /api/chat — 智能问答（SSE 流式）

```bash
curl -N -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id": "u001", "question": "什么是二次函数的顶点式？"}'
```

SSE 事件类型：`routing` → `retrieval` → `explanation` → `quiz` → `memory` → `done`

### POST /api/upload — 上传 PDF

```bash
curl -X POST http://localhost:8000/api/upload \
  -F "file=@textbook.pdf"
```

### GET /health — 健康检查

```bash
curl http://localhost:8000/health
```

## 🛠️ 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Next.js 14, TypeScript, Tailwind CSS |
| 后端 | FastAPI, Python 3.12 |
| Agent 框架 | LangGraph, LangChain |
| LLM | OpenAI GPT-4o / GPT-4o-mini |
| 向量数据库 | Chroma |
| 容器化 | Docker, Docker Compose |

## 📄 License

MIT
