from typing import Any, Dict

from fastapi import Query


class PageParams:
    def __init__(self, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200)):
        self.page = page
        self.page_size = page_size


def paginate(query, params: PageParams, serialize) -> Dict[str, Any]:
    total = query.count()
    rows = query.offset((params.page - 1) * params.page_size).limit(params.page_size).all()
    return {"items": [serialize(r) for r in rows], "total": total, "page": params.page, "page_size": params.page_size}
