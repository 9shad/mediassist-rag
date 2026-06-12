class MediBotException(Exception):
    status_code: int = 500
    detail: str = "Internal server error"


class AuthenticationError(MediBotException):
    status_code = 401
    detail = "Invalid username or password"


class AuthorizationError(MediBotException):
    status_code = 403
    detail = "You do not have access to this resource"


class NotFoundError(MediBotException):
    status_code = 404
    detail = "Resource not found"


class QdrantConnectionError(MediBotException):
    status_code = 503
    detail = "Vector database is unavailable"


class LLMServiceError(MediBotException):
    status_code = 502
    detail = "Language model service is unavailable"
