import base64
import binascii
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth import CurrentUser
from database import get_db
from models import Post
from schemas import (
    CursorPostsResponse,
    PaginatedPostsResponse,
    PostCreate,
    PostResponse,
    PostUpdate,
)

router = APIRouter()



@router.get("", response_model=PaginatedPostsResponse, name="posts")
async def read_posts(
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):

    count_result = await db.execute(select(func.count()).select_from(Post))
    total = count_result.scalar() or 0

    result = await db.execute(
        select(Post)
        .options(selectinload(Post.author))
        .order_by(Post.date_posted.desc())
        .offset(skip)
        .limit(limit),
    )
    posts = result.scalars().all()
    has_more = skip + len(posts) < total

    return PaginatedPostsResponse(
        posts=[PostResponse.model_validate(post) for post in posts],
        total=total,
        skip=skip,
        limit=limit,
        has_more=has_more,
    )

def encode_cursor(post: Post) -> str:
    payload = {"d": post.date_posted.isoformat(), "i": post.id}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    payload = json.loads(base64.urlsafe_b64decode(cursor))
    return datetime.fromisoformat(payload["d"]), payload["i"]


@router.get("/cursor", response_model=CursorPostsResponse, name="posts_cursor")
async def read_posts_cursor(
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):

    stmt = (
        select(Post)
        .options(selectinload(Post.author))
        .order_by(Post.date_posted.desc(), Post.id.desc())
        .limit(limit + 1)
    )

    if cursor:
        try:
            cursor_date, cursor_id = decode_cursor(cursor)
        except (ValueError, KeyError, TypeError, binascii.Error) as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid cursor",
            ) from err

        stmt = stmt.where(
            or_(
                Post.date_posted < cursor_date,
                and_(Post.date_posted == cursor_date, Post.id < cursor_id),
            ),
        )

    posts = list((await db.execute(stmt)).scalars().all())

    has_more = len(posts) > limit
    posts = posts[:limit]

    return {
        "posts": posts,
        "has_more": has_more,
        "next_cursor": encode_cursor(posts[-1]) if has_more and posts else None,
    }


@router.get("/{post_id}", response_model=PostResponse)
async def read_post(
    post_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Post).options(selectinload(Post.author)).where(Post.id == post_id)
    )
    post = result.scalars().first()
    if post:
        return post
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")


@router.post("", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
async def create_post(
    post: PostCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    new_post = Post(
        author=current_user,
        title=post.title,
        content=post.content,
    )

    db.add(new_post)
    await db.commit()
    await db.refresh(new_post, attribute_names=["author"])

    return new_post


@router.put("", response_model=PostResponse)
async def update_post_full(
    post_id: int,
    current_user: CurrentUser,
    post_data: PostCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Post).options(selectinload(Post.author)).where(Post.id == post_id)
    )
    post = result.scalars().first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )

    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this post",
        )

    post.title = post_data.title
    post.content = post_data.content

    await db.commit()
    await db.refresh(post)

    return post


@router.patch("/{post_id}", response_model=PostResponse)
async def update_post_partial(
    post_id: int,
    post_data: PostUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Post).options(selectinload(Post.author)).where(Post.id == post_id)
    )
    post = result.scalars().first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )

    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this post",
        )

    update_data = post_data.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in update_data.items():
        setattr(post, field, value)

    await db.commit()
    await db.refresh(post)
    return post


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: int,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Post).where(Post.id == post_id))
    post = result.scalars().first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Post not found"
        )

    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this post",
        )
    await db.delete(post)
    await db.commit()
