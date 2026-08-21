

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from database import engine
from models import Base
from routers import posts, users


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/media", StaticFiles(directory="media"), name="media")

app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(posts.router, prefix="/api/posts", tags=["posts"])


@app.exception_handler(StarletteHTTPException)
async def general_http_exception_handler(request: Request, exception: StarletteHTTPException):

    if request.url.path.startswith("/api"):
        return await http_exception_handler(request, exception)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exception: RequestValidationError):

    if request.url.path.startswith("/api"):
        return await request_validation_exception_handler(request, exception)