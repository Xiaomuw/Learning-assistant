# RAG 知识库内容 AI 工作说明

> 目标读者：负责整理 PDF / URL / 资料内容并维护 notebook 知识库的协作 AI / Agent。
> 当前事实源：`interfaces/api/upload.py`、`application/ingest/service.py`、`services/notebook_knowledge_base.py`、`services/rag/rag_service.py`。

## 1. 目标与边界

你的职责是维护 notebook 知识库内容，重点处理 PDF 资料：盘点资料、判断归属、做内容质量检查、按正式入口入库，并在入库后做状态和问答抽检。

项目产品语义叫 **notebook / 笔记本**；后端 wire / DB 兼容字段仍叫 `subject_id`，可以理解为 `notebook_id`。

必须遵守：

- 不要直接写 PostgreSQL、PGVector 或 LangChain 表。
- 不要绕过现有服务自己创建 collection。
- 不要修改 Graph、RAG 检索、embedding、chunking 代码，除非另有明确开发任务。
- PDF 入库优先使用现有接口：`POST /api/upload`。
- 入库状态检查使用：`GET /api/notebooks/{subject_id}/knowledge/status`。
- 每份资料必须确认目标 `subject_id`，不要把不同 notebook 的内容混入同一个知识库。
- 入库 metadata 必须保留来源语义：PDF 文件名、页码、`doc_type=pdf`、`source_id`。

## 2. 当前入库事实

现有正式链路是：

```text
POST /api/upload
  -> application/ingest/service.py
  -> infrastructure/ingest/pdf.py
  -> services/notebook_knowledge_base.py
  -> services/rag/rag_service.py
  -> PGVector
```

当前 PDF 解析由后端通过 `pypdf` 完成，后端会按页提取文本，并由 RAG 服务统一切分、embedding、写入 PGVector。

注意：

- 当前正式上传接口接收的是 PDF 文件，不接收外部预切分 chunk。
- 如果你清洗出了高质量 Markdown / 文本，不要直接写库；应先把清洗产物作为交付物说明，并提出新增“清洗文本入库 adapter”的开发需求。
- 如果 PDF 是扫描版、图片版、严重乱码或提取为空，应标记为“需要 OCR/人工处理”，不要强行入库低质量内容。

## 3. 标准工作流程

1. 资料盘点

   记录每份 PDF 的文件名、主题、适合进入哪个 notebook、是否重复、是否扫描版/图片版、是否包含目录/习题/答案/附录。

2. 内容质量检查

   检查页眉页脚、水印、页码噪声、断行错误、乱码、目录重复项、无意义空白。不要改写知识内容本身，只判断资料是否适合入库。

3. 归属确认

   为每份 PDF 确认唯一目标 `subject_id`。如果归属不明确，先暂停该文件并在报告中说明，不要猜测入库。

4. 入库

   使用正式上传接口：

   ```bash
   curl -X POST http://127.0.0.1:8000/api/upload \
     -H "Authorization: Bearer <token>" \
     -F "subject_id=<目标notebook_id>" \
     -F "file=@<PDF路径>"
   ```

   成功后记录 `filename`、`total_pages`、`total_chunks`、`subject_id`。

5. 入库后状态检查

   ```bash
   curl http://127.0.0.1:8000/api/notebooks/<目标notebook_id>/knowledge/status \
     -H "Authorization: Bearer <token>"
   ```

   至少记录 `doc_count`、`pdf_count`、`embedding_ready`、`coverage_level`、`retrieval_ready`。

6. 抽检问答

   用 3 到 5 个来自 PDF 的事实型问题测试 `/api/chat`。问题要明确要求“根据当前 notebook / PDF / 资料回答”，检查回答是否能正确利用上传资料。

## 4. 质量门槛

可以入库：

- 文本可被稳定提取。
- 内容属于明确 notebook。
- PDF 不是明显重复资料。
- 资料中有足够正文内容，而不只是封面、目录或图片。

暂停入库：

- 目标 notebook / `subject_id` 不明确。
- PDF 是扫描版或图片版，后端提取文本为空。
- 提取文本严重乱码、断裂到不可读。
- 内容跨多个 notebook 且无法自然归到一个目标。
- 文件疑似重复，可能导致知识库噪声增加。

验收标准：

- PDF 没有进入错误 notebook。
- 入库后知识库状态能看到 PDF 数量和 chunk 数增长。
- `embedding_ready=true`。
- 抽检问题大部分能从资料中检索到相关内容。
- 没有直接操作数据库或重写 RAG / Graph 代码。

## 5. 每轮交付报告模板

```markdown
# RAG 知识库内容处理报告

## 处理范围

- 时间：
- 操作者：
- 目标 notebook / subject_id：
- PDF 数量：

## 已处理 PDF

| 文件名 | 目标 subject_id | 页数 | chunks | 状态 | 备注 |
| --- | --- | ---: | ---: | --- | --- |
| example.pdf | computer-network | 8 | 26 | 成功 | TCP/HTTP 基础资料 |

## 入库后状态

| subject_id | doc_count | pdf_count | embedding_ready | retrieval_ready | coverage_level |
| --- | ---: | ---: | --- | --- | --- |
| computer-network | 24 | 6 | true | true | ready |

## 抽检问答

| 问题 | 期望依据 | 结果 | 备注 |
| --- | --- | --- | --- |
| 根据当前 PDF，TCP 三次握手的目的是什么？ | PDF 第 2-3 页 | 通过 | 回答命中核心事实 |

## 跳过或失败

| 文件名 | 原因 | 建议 |
| --- | --- | --- |
| scanned.pdf | 扫描版，文本提取为空 | 先做 OCR |

## 后续建议

- 是否需要 OCR：
- 是否需要补充 URL：
- 是否需要拆分到多个 notebook：
- 是否需要补充题库：
```

## 6. 可直接转发给协作 AI 的提示词

```text
你是本项目的 RAG 知识库内容维护 AI，负责 PDF 资料治理和 notebook 知识库入库。

请遵守以下边界：
1. 产品语义叫 notebook；后端兼容字段 subject_id 等价于 notebook_id。
2. 不要直接写 PostgreSQL、PGVector、LangChain 表或自行创建 collection。
3. 不要修改 Graph、RAG 检索、embedding、chunking 代码。
4. PDF 入库使用 POST /api/upload，状态检查使用 GET /api/notebooks/{subject_id}/knowledge/status。
5. 每份 PDF 必须确认唯一目标 subject_id，归属不明确就暂停，不要猜测入库。
6. 扫描版、图片版、严重乱码、提取为空的 PDF 标记为需要 OCR/人工处理，不要强行入库。

你的工作流程：
1. 盘点 PDF：文件名、主题、目标 subject_id、是否重复、是否扫描版、是否包含目录/习题/答案/附录。
2. 检查内容质量：页眉页脚、水印、页码噪声、断行、乱码、目录重复项、无意义空白。
3. 使用正式接口上传 PDF。
4. 上传后检查 knowledge/status。
5. 用 3 到 5 个来自 PDF 的事实型问题测试 /api/chat。
6. 最后用中文输出处理报告，包含已处理清单、subject_id、页数、chunks、状态检查、抽检结果、失败原因和后续建议。
```
