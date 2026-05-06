"""兼容入口：请优先使用 `app.main:app`。"""

from app.main import app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
    )
