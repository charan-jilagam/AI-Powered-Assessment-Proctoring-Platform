from fastapi import HTTPException


class ApiError(HTTPException):
    """HTTPException that also carries a machine-readable code the frontend can branch on."""

    def __init__(self, status_code: int, message: str, code: str = "error"):
        super().__init__(status_code=status_code, detail=message)
        self.code = code


def not_found(what: str = "Resource") -> ApiError:
    return ApiError(404, f"{what} not found", "not_found")


def forbidden(message: str = "You do not have permission to do that", code: str = "forbidden") -> ApiError:
    return ApiError(403, message, code)


def bad_request(message: str, code: str = "bad_request") -> ApiError:
    return ApiError(400, message, code)


def conflict(message: str, code: str = "conflict") -> ApiError:
    return ApiError(409, message, code)
