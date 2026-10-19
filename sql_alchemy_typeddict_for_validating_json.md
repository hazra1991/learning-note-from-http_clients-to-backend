TypeDecorator explained from zero — no magic, just a wrapper class
What is a "type" in SQLAlchemy?
Every column has a type object whose job is to translate between Python and the database:

python
Copy
data = mapped_column(JSON)
#            ↑ this is a TYPE OBJECT — it decides how data looks
#              in Python vs how it's stored in the DB
JSON type: on write, it takes a Python dict and serializes it to a JSON string (or JSONB binary); on read, it parses the JSON back into a dict. That's all it does.

What is TypeDecorator?
A TypeDecorator is a wrapper around an existing type that lets you intercept those two translation steps and add your own logic:

python
Copy
class PydanticJSON(TypeDecorator):
    impl = JSON          # ← "wrap the normal JSON type, use it as the base"
    cache_ok = True      # ← just a flag, see below

    def process_bind_param(self, value, dialect):
        ...              # ← SQLAlchemy CALLS THIS when you WRITE

    def process_result_value(self, value, dialect):
        ...              # ← SQLAlchemy CALLS THIS when you READ
Yes — process_bind_param and process_result_value are predefined hook methods. You don't call them. You only override them; SQLAlchemy calls them at exactly two moments:

code
Copy
WRITE:  user.data = Settings(theme="dark")
             │
             ▼
        process_bind_param(value)     ← your code runs (validation)
             │
             ▼
        impl (JSON) serializes it     ← base type does the SQL part
             │
             ▼
        INSERT INTO users (data) VALUES ('{"theme": "dark"}')

READ:   SELECT data FROM users
             │
             ▼
        impl (JSON) parses to dict
             │
             ▼
        process_result_value(dict)    ← your code runs (→ BaseModel)
             │
             ▼
        user.data  ← you get Settings(theme="dark") object back
Your questions, one by one
1. Do these functions fire DB queries? Do they do SQL?
No DB queries at all. They are pure Python-side transformations that run in your app process, right before/after the actual INSERT/SELECT. They don't touch the network or add SQL — they only reshape the Python value being passed through. The SQL itself (INSERT, SELECT, JSON serialization) is still done by the wrapped JSON type (impl).

So: process_bind_param = "validate + convert to dict" (pure Python), then the base JSON type does the actual DB encoding.

2. impl = JSON — what is it?
It tells TypeDecorator which real type to wrap:

The decorated type behaves like JSON (DDL: JSONB/JSON column, correct serialization)
But with your two hooks injected around it
Without impl, SQLAlchemy wouldn't know what SQL type to create or how to do the low-level encode/decode. You could also wrap String, Integer, anything.

3. cache_ok = True — what is it?
Purely a performance flag. SQLAlchemy caches compiled SQL/type info; for types that take constructor arguments (like yours takes a model), it asks you to confirm "this type is safe to cache based on its args." Set it and the warning goes away; it has nothing to do with validation or the DB. Just always set cache_ok = True on custom types unless you have a weird reason not to.

4. Where does Settings come from?
It's just the Pydantic model you pass into the constructor — the class defined earlier:

python
Copy
class Settings(BaseModel):     # ← this is "Settings" — the JSON schema
    theme: str = "light"
    notifications: bool = True
You hand it to the type when declaring the column:

python
Copy
data: Mapped[Settings] = mapped_column(PydanticJSON(Settings))
#                                                   ↑ ↑ ↑
#                                    stored as self._model = Settings
So self._model is Settings, and the hooks use it to validate:

python
Copy
self._model.model_validate(value)   # same as Settings.model_validate(...)
It's not special to SQLAlchemy at all — it's just a constructor argument your class keeps a reference to.

5. So what is TypeDecorator in one sentence?
A base class for making a custom column type: "behave exactly like impl (here: JSON), but let me run my own Python code (process_bind_param / process_result_value) on the value right before it goes to the DB and right after it comes back."
Full annotated example
python
Copy
class PydanticJSON(TypeDecorator):        # custom column type
    impl = JSON                           # base type: real JSON column in DB
    cache_ok = True                       # allow SQL compilation caching

    def __init__(self, model: type[BaseModel]):
        super().__init__()
        self._model = model               # remember which schema to use

    def process_bind_param(self, value, dialect):
        # runs on EVERY write — pure Python, no SQL, no queries
        if value is None:
            return None
        if isinstance(value, dict):
            value = self._model.model_validate(value)   # dict → validated Settings
        return value.model_dump(mode="json")            # Settings → plain dict
        # ↑ AFTER this returns, the impl (JSON) serializes to DB format

    def process_result_value(self, value, dialect):
        # runs on EVERY read — value is already a dict (parsed by impl)
        if value is None:
            return None
        return self._model.model_validate(value)        # dict → Settings object
python
Copy
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[Settings] = mapped_column(PydanticJSON(Settings))

u = User(data=Settings(theme="dark"))
#        └─ process_bind_param validates → JSON impl stores it

session.get(User, 1).data.theme
#        └─ JSON impl parsed → process_result_value → Settings instance
One-liner: TypeDecorator = "wrap a normal column type (impl = JSON), and let me intercept the value with two predefined hooks — process_bind_param on every write and process_result_value on every read — which are pure Python functions (no queries, no SQL) that here just validate through the Settings BaseModel you passed into the constructor; cache_ok is only a caching-safety flag for SQLAlchemy's internals.
