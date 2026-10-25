In Pydantic v2, the recommended way to declare regex and numeric constraints is through Field(...) parameters or Annotated[...] types — not constr/conint anymore. Those constrained types still exist for backward compatibility, but the modern style is Field(pattern=..., gt=..., le=...) or Annotated[int, Gt(0)].

✅ Field Constraints in Pydantic v2
You can use Field directly to enforce validation:

python
from pydantic import BaseModel, Field, EmailStr

class UserCreate(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=20,
        pattern=r"^[a-zA-Z0-9_]+$",
        description="3–20 chars, alphanumeric + underscore"
    )
    age: int = Field(ge=18, le=120)
    email: EmailStr
min_length / max_length → string length

pattern → regex validation

gt, ge, lt, le → numeric ranges

multiple_of → enforce divisibility (e.g., multiples of 5)

strict=True → disable type coercion (e.g., "10" won’t be accepted as int)

🎯 Annotated Style (Preferred for Complex Constraints)
Instead of Field, you can use Annotated with constraint helpers:

python
from typing import Annotated
from pydantic import BaseModel
from pydantic.types import Gt, Le, Pattern

class Product(BaseModel):
    quantity: Annotated[int, Gt(0), Le(100)]
    code: Annotated[str, Pattern(r"^[A-Z0-9]{6}$")]
This is more declarative and integrates better with type hints.

🛠️ Validators in v2
@field_validator → replaces v1’s @validator, runs on individual fields.

@model_validator → runs on the whole model, useful for cross‑field checks.

Example:

python
from pydantic import BaseModel, field_validator, model_validator

class PasswordSchema(BaseModel):
    password: str
    confirm_password: str

    @field_validator("password")
    def strong_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password too short")
        return v

    @model_validator(mode="after")
    def check_match(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self
⚡ Quick Reference Table
Validation Type	v2 Syntax	Example
Regex	Field(pattern=...)	Field(pattern=r"^[a-z]+$")
Length	Field(min_length=, max_length=)	Field(min_length=3, max_length=50)
Numeric Range	Field(gt=, ge=, lt=, le=)	Field(ge=1, le=10)
Multiple Of	Field(multiple_of=5)	enforce divisibility
Strict Mode	Field(strict=True)	no coercion
Annotated	Annotated[int, Gt(0), Le(100)]	declarative constraints
Field Validator	@field_validator("field")	per‑field checks
Model Validator	@model_validator(mode="after")	cross‑field checks


👉 So to answer your doubt: yes, Pydantic v2 still supports constr/conint, but the modern, idiomatic way is Field(...) or Annotated[...]. That’s what you should use going forward.

Do you want me to prepare a ready‑to‑use cheat sheet file (like validators.py) with examples of regex, numeric ranges, enums, and cross‑field checks, so you can just import and reuse in your FastAPI project?
