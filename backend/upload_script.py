import sys
import os
import asyncio
from pathlib import Path

# Setup paths
backend_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(backend_dir))

# Ensure environment variables are loaded
from dotenv import load_dotenv
load_dotenv()

# We need to initialize the db connection
from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import User
from app.application.ingest.service import ingest_pdf_bytes
from app.services.rag.vector_store import count_collection_documents, ensure_vector_store_ready
from sqlalchemy import select

async def main():
    # 1. Fetch any user to act as the uploader
    with session_scope() as session:
        user = session.execute(select(User).limit(1)).scalar_one_or_none()
        if not user:
            print("No user found in the database. Creating a dummy user...")
            from app.infrastructure.auth.security import hash_password
            user = User(
                id="dummy-user-id",
                email="admin@example.com",
                hashed_password=hash_password("admin123"),
                display_name="Admin"
            )
            session.add(user)
            session.commit()
            print("Created dummy user.")
        user_id = user.id

    # 2. Define the allocations
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

    # 3. Process each file
    for subject_id, filenames in allocations.items():
        print(f"\n================ Processing Notebook: {subject_id} ================")
        # Ensure vector store is ready for this subject
        ensure_vector_store_ready(subject_id)
        
        for filename in filenames:
            file_path = pdf_dir / filename
            if not file_path.exists():
                print(f"File not found: {file_path}")
                continue
            
            print(f"Reading file: {filename} ({file_path.stat().st_size / 1024 / 1024:.2f} MB)")
            content = file_path.read_bytes()
            
            print(f"Ingesting into {subject_id}...")
            try:
                # We need to run this in a thread or just call it directly since it's synchronous
                result = ingest_pdf_bytes(
                    filename=filename,
                    content=content,
                    subject_id=subject_id,
                    user_id=user_id
                )
                print(f"Success: {filename}")
                print(f"Result: {result.total_pages} pages, {result.total_chunks} chunks.")
            except Exception as e:
                print(f"Failed to ingest {filename}: {e}")
                
        # Print status after subject
        doc_count = count_collection_documents(subject_id)
        print(f"Current document count for {subject_id}: {doc_count}")

if __name__ == "__main__":
    asyncio.run(main())
