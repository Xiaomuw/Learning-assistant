"""
PDF 重新入库脚本（Gemini Embedding 2 + 多 Key 轮换）
"""

import sys
import time
from pathlib import Path

backend_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
from app.main import app
from app.interfaces.auth.dependencies import require_current_user, AuthenticatedUser

app.dependency_overrides[require_current_user] = lambda: AuthenticatedUser(
    id="script-uploader-id",
    email="admin@example.com",
    display_name="Admin"
)

client = TestClient(app)
pdf_dir = backend_dir.parent / "docs" / "pdf"

ALLOCATIONS = {
    "operating-system": [
        "11计算机操作系统教程-第4版- 张尧学.pdf",
        "《计算机操作系统》（第4版）笔记和课后习题（含考研真题）详解.pdf",
    ],
    "data-structure": [
        "数据结构（C语言版）（第2版）.pdf",
    ],
    "computer-organization": [
        "计算机组成原理 (谭志虎).pdf",
    ],
}

results = []
total = sum(len(f) for f in ALLOCATIONS.values())
current = 0

print("=" * 60)
print(f"📚 PDF 入库开始 — 共 {total} 份 (Gemini Embedding 2)")
print("=" * 60)

for subject_id, filenames in ALLOCATIONS.items():
    print(f"\n📁 {subject_id}")
    print("-" * 40)
    for filename in filenames:
        current += 1
        file_path = pdf_dir / filename
        if not file_path.exists():
            print(f"  [{current}/{total}] ❌ 文件不存在: {filename}")
            continue
        size_mb = file_path.stat().st_size / 1024 / 1024
        print(f"  [{current}/{total}] ⬆️  {filename} ({size_mb:.1f}MB)")
        start = time.time()
        with open(file_path, "rb") as f:
            resp = client.post(
                "/api/upload",
                data={"subject_id": subject_id},
                files={"file": (filename, f, "application/pdf")},
            )
        elapsed = time.time() - start
        if resp.status_code == 200:
            data = resp.json()
            print(f"             ✅ {data.get('total_pages')} 页 → {data.get('total_chunks')} chunks ({elapsed:.1f}s)")
            results.append({"file": filename, "subject": subject_id, "status": "OK",
                          "pages": data.get("total_pages"), "chunks": data.get("total_chunks"), "time": elapsed})
        else:
            print(f"             ❌ HTTP {resp.status_code}: {resp.text[:200]}")
            results.append({"file": filename, "subject": subject_id, "status": "FAIL", "detail": resp.text[:200]})

# 状态检查
print("\n" + "=" * 60)
print("📊 知识库状态")
print("=" * 60)
for subject_id in ALLOCATIONS:
    resp = client.get(f"/api/notebooks/{subject_id}/knowledge/status")
    if resp.status_code == 200:
        s = resp.json()
        print(f"  {subject_id}: docs={s.get('doc_count')}, embedding={s.get('embedding_ready')}, retrieval={s.get('retrieval_ready')}")

# 总结
print("\n" + "=" * 60)
ok = [r for r in results if r["status"] == "OK"]
fail = [r for r in results if r["status"] != "OK"]
print(f"✅ 成功: {len(ok)} | ❌ 失败: {len(fail)}")
for r in ok:
    print(f"  ✅ {r['file']} → {r['subject']} ({r['pages']}p, {r['chunks']}c, {r['time']:.0f}s)")
for r in fail:
    print(f"  ❌ {r['file']} → {r.get('detail','')}")
