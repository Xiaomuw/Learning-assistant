from __future__ import annotations

import requests
from bs4 import BeautifulSoup
from loguru import logger


def extract_text_from_url(url: str) -> str | None:
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.extract()
        return soup.get_text(separator="\n", strip=True)
    except Exception as exc:
        logger.warning(f"⚠️ URL 抓取失败 {url}: {exc}")
        return None
