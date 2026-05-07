import sys
import os
import asyncio
from pathlib import Path

backend_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
from app.main import app
from app.interfaces.auth.dependencies import require_current_user, AuthenticatedUser

# Override authentication
app.dependency_overrides[require_current_user] = lambda: AuthenticatedUser(
    id="script-uploader-id",
    email="admin@example.com",
    display_name="Admin"
)

client = TestClient(app)

def main():
    pdf_dir = backend_dir.parent / "docs" / "pdf"
    
    allocations = {
        "operating-system": [
            "11计算机操作系统教程-第4版- 张尧学.pdf",
            "《计算机操作系统》（第4版）笔记和课后习题（含考研真题）详解.pdf",
            "《计算机操作系统》（第4版）配套题库【考研真题精选＋章节题库】.pdf",
            "汤小丹《计算机操作系统 第4版》.pdf",
            "汤小丹《计算机操作系统（第4版）》学习指导与题解 含实验.pdf"
        ],
        "data-structure": [
            "数据结构习题解析与实验指导.pdf",
            "数据结构（C语言版）（第2版）.pdf"
        ],
        "computer-organization": [
            "计算机组成原理 (谭志虎).pdf"
        ]
    }

    for subject_id, filenames in allocations.items():
        print(f"\n================ Processing Notebook: {subject_id} ================")
        
        for filename in filenames:
            file_path = pdf_dir / filename
            if not file_path.exists():
                print(f"File not found: {file_path}")
                continue
            
            print(f"Reading file: {filename} ({file_path.stat().st_size / 1024 / 1024:.2f} MB)")
            
            with open(file_path, "rb") as f:
                response = client.post(
                    "/api/upload",
                    data={"subject_id": subject_id},
                    files={"file": (filename, f, "application/pdf")}
                )
            
            if response.status_code == 200:
                data = response.json()
                print(f"Success: {filename}")
                print(f"Result: {data.get('total_pages')} pages, {data.get('total_chunks')} chunks.")
            else:
                print(f"Failed to ingest {filename}. Status: {response.status_code}")
                print(response.text)
                
        # Check status
        status_resp = client.get(f"/api/notebooks/{subject_id}/knowledge/status")
        if status_resp.status_code == 200:
            print(f"Current status for {subject_id}: {status_resp.json()}")

if __name__ == "__main__":
    main()
