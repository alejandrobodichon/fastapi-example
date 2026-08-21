from typing import Annotated, TypeVar

from pydantic import AfterValidator

T = TypeVar("T", bound=str)

def to_lower[T: str](v: T) -> T:
    return v.lower()  # type: ignore[return-value]

type Lower[T: str] = Annotated[T, AfterValidator(to_lower)]