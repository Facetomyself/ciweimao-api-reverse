"""使用单 worker 启动 FastAPI 服务。"""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "service.app:app",
        host=os.getenv("CIWEIMAO_HOST", "127.0.0.1"),
        port=int(os.getenv("CIWEIMAO_PORT", "8000")),
        workers=1,
    )


if __name__ == "__main__":
    main()
