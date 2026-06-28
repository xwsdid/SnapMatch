import os
import tempfile

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse

from search import ClipSearcher


TOP_K = int(os.environ.get("CLIP_TOP_K", "5"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://8.130.157.142:8080").rstrip("/")

app = FastAPI(title="Template CLIP Search")
searcher = ClipSearcher()


def build_cover_url(request: Request, cover_url_path: str) -> str:
    if cover_url_path.startswith("http://") or cover_url_path.startswith("https://"):
        return cover_url_path
    return PUBLIC_BASE_URL + cover_url_path


@app.post("/search")
async def search_templates(request: Request, file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename or "")[1] or ".jpg"
    tmp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        results = searcher.search(tmp_path, top_k=TOP_K)
        data = [
            {
                "template_id": item["template_id"],
                "score": item["score"],
                "cover_url": build_cover_url(request, item["cover_url_path"]),
            }
            for item in results
        ]
        return {"code": 200, "msg": "success", "data": data}
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"code": 500, "msg": "search failed", "error": str(exc)},
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.get("/health")
def health():
    return {"code": 200, "msg": "ok"}
