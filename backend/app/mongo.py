"""A small MongoDB mapper for ORVEXA.

Why this exists: the application grew up on a relational ORM. Instead of rewriting ~140 queries and every
service by hand, this module gives MongoDB the same *shape* of API (models with attributes, a unit-of-work
``Session``, ``db.query(Model).filter(Model.col == x)``), so business logic stays readable and testable, while the
data is stored as plain MongoDB documents.

What you get
  * Integer ids from an atomic ``counters`` collection (so the public API and the frontend are unchanged).
  * Change tracking: mutate an attribute, ``db.commit()`` writes only the changed fields with ``$set``.
  * Queries translate to MongoDB filters (``find``) or, with ``.join()``, to ``$lookup`` pipelines.
  * Unique / compound indexes declared on the models and created by ``ensure_indexes()``.

What it deliberately is NOT: multi-document transactions (writes are applied per document, atomic claims use
``update_many`` with a status condition) and a full SQL emulation. Unsupported constructs raise
``NotImplementedError`` loudly instead of returning wrong data.

Datetimes are stored and returned as naive UTC (MongoDB stores UTC; ``app.timeutil.as_utc`` re-attaches the zone).
"""
import copy
import datetime as dt
import logging
import re
import threading
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

log = logging.getLogger("orvexa.mongo")

# =============================================================================
# connection
# =============================================================================
_lock = threading.Lock()
_client: Any = None
_db: Any = None


class IntegrityError(Exception):
    """A unique index was violated (the Mongo equivalent of a duplicate key)."""


def connect(uri: str, db_name: str) -> Any:
    """Open (once) and return the MongoDB database. ``mongomock://`` gives an in-memory fake used by the test-suite."""
    global _client, _db
    with _lock:
        if _db is None:
            if uri.startswith("mongomock://"):
                import mongomock  # test dependency only

                _client = mongomock.MongoClient()
            else:
                _client = MongoClient(uri, appname="orvexa", serverSelectionTimeoutMS=8000, connectTimeoutMS=8000,
                                      retryWrites=True, tz_aware=False, maxPoolSize=30)
            _db = _client[db_name]
        return _db


def database() -> Any:
    if _db is None:
        from app.config import settings

        return connect(settings.mongodb_uri, settings.mongodb_db)
    return _db


def close() -> None:
    global _client, _db
    with _lock:
        if _client is not None and not type(_client).__module__.startswith("mongomock"):
            _client.close()
        _client = _db = None


def ping() -> None:
    database().command("ping")


def utcnow_naive() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _norm_dt(value: Any) -> Any:
    if isinstance(value, dt.datetime) and value.tzinfo is not None:
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return value


def _norm(value: Any) -> Any:
    """Normalise a Python value before it goes into a MongoDB filter or document."""
    if isinstance(value, dt.datetime):
        return _norm_dt(value)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day)
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_norm(v) for v in value]
    return value


def _clean_keys(value: Any) -> Any:
    """MongoDB field names may not be empty and are awkward with leading '$' or '.': neutralise user-supplied keys."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key = str(k).replace(".", "_")
            if key.startswith("$"):
                key = "_" + key[1:]
            out[key or "_"] = _clean_keys(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_clean_keys(v) for v in value]
    return _norm_dt(value)


def next_id(collection: str) -> int:
    from pymongo import ReturnDocument

    row = database()["counters"].find_one_and_update({"_id": collection}, {"$inc": {"seq": 1}}, upsert=True,
                                                     return_document=ReturnDocument.AFTER)
    return int(row["seq"])


# =============================================================================
# expressions (what `Model.column == value` builds)
# =============================================================================
class Expr:
    def models(self) -> set:
        return set()


class Col(Expr):
    """A column of a model class, used while building queries."""

    __slots__ = ("model", "name")

    def __init__(self, model, name):
        self.model, self.name = model, name

    @property
    def field(self) -> str:
        return "_id" if self.name == "id" else self.name

    def models(self):
        return {self.model}

    __hash__ = object.__hash__

    def __eq__(self, other):  # noqa: D105
        return Cmp("eq", self, other)

    def __ne__(self, other):  # noqa: D105
        return Cmp("ne", self, other)

    def __lt__(self, other):
        return Cmp("lt", self, other)

    def __le__(self, other):
        return Cmp("le", self, other)

    def __gt__(self, other):
        return Cmp("gt", self, other)

    def __ge__(self, other):
        return Cmp("ge", self, other)

    def in_(self, values):
        return Cmp("in", self, list(values))

    def not_in(self, values):
        return Cmp("nin", self, list(values))

    def is_(self, other):
        return Cmp("eq", self, other)

    def is_not(self, other):
        return Cmp("ne", self, other)

    isnot = is_not

    def like(self, pattern):
        return Cmp("like", self, pattern)

    def ilike(self, pattern):
        return Cmp("ilike", self, pattern)

    def startswith(self, prefix):
        return Cmp("like", self, prefix.replace("%", r"\%").replace("_", r"\_") + "%")

    def contains(self, text):
        return Cmp("ilike", self, "%" + text + "%")

    def asc(self):
        return Order(self, False)

    def desc(self):
        return Order(self, True)

    def __repr__(self):
        return f"{self.model.__name__}.{self.name}"


class Order(Expr):
    def __init__(self, target, descending):
        self.target, self.descending = target, descending

    def nulls_last(self):
        return self  # MongoDB sorts null/missing lowest, which already puts NULLs last for DESC

    nullslast = nulls_first = nullsfirst = nulls_last

    def models(self):
        return self.target.models() if isinstance(self.target, Expr) else set()


class Fn(Expr):
    """func.count(...), func.lower(...), ..."""

    AGG = {"count", "max", "min", "sum", "coalesce"}

    def __init__(self, name, *args):
        self.name, self.args = name, args

    @property
    def is_agg(self):
        return self.name in self.AGG and (self.name != "coalesce" or any(isinstance(a, Fn) and a.is_agg for a in self.args))

    def models(self):
        out = set()
        for a in self.args:
            if isinstance(a, Expr):
                out |= a.models()
        return out

    # lower(col) usage in filters
    def like(self, pattern):
        return Cmp("ilike", self, pattern)

    def __eq__(self, other):  # noqa: D105
        return Cmp("eq", self, other)

    def __ne__(self, other):  # noqa: D105
        return Cmp("ne", self, other)

    __hash__ = object.__hash__

    def desc(self):
        return Order(self, True)

    def asc(self):
        return Order(self, False)


class _Func:
    def __getattr__(self, name):
        return lambda *a: Fn(name, *a)


func = _Func()


class Cmp(Expr):
    def __init__(self, op, left, right):
        self.op, self.left, self.right = op, left, right

    def models(self):
        out = self.left.models() if isinstance(self.left, Expr) else set()
        if isinstance(self.right, Expr):
            out |= self.right.models()
        return out


class Bool(Expr):
    def __init__(self, op, parts):
        self.op, self.parts = op, [p for p in parts if p is not None]

    def models(self):
        out = set()
        for p in self.parts:
            out |= p.models()
        return out


class Not(Expr):
    def __init__(self, part):
        self.part = part

    def models(self):
        return self.part.models()


def and_(*parts):
    return Bool("and", parts)


def or_(*parts):
    return Bool("or", parts)


def not_(part):
    return Not(part)


def _like_regex(pattern: str) -> str:
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern) and pattern[i + 1] in "%_":
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if ch == "%" else "." if ch == "_" else re.escape(ch))
        i += 1
    return "^" + "".join(out) + "$"


def _path(col: Col, pm: Dict[Any, str]) -> str:
    if col.model not in pm:
        raise NotImplementedError(f"{col!r} is not part of this query (join it first)")
    return pm[col.model] + col.field


def render(expr: Any, pm: Dict[Any, str]) -> dict:
    """Translate an expression tree to a MongoDB filter. `pm` maps each model to its field-path prefix."""
    if isinstance(expr, Bool):
        parts = [render(p, pm) for p in expr.parts]
        if not parts:
            return {}
        return {"$and" if expr.op == "and" else "$or": parts}
    if isinstance(expr, Not):
        return {"$nor": [render(expr.part, pm)]}
    if not isinstance(expr, Cmp):
        raise NotImplementedError(f"cannot use {expr!r} as a filter")

    left, op, right = expr.left, expr.op, expr.right
    lowered = isinstance(left, Fn) and left.name == "lower"
    if isinstance(left, Fn) and not lowered:
        raise NotImplementedError(f"func.{left.name} is not supported in filters")
    col = left.args[0] if lowered else left
    path = _path(col, pm)
    if isinstance(right, Col):
        raise NotImplementedError("comparing two columns is only supported in join conditions")
    if lowered:
        ci_field = getattr(col.model, "_lower_fields", ())
        if op in ("eq", "ne") and isinstance(right, str):
            if col.name in ci_field:  # stored lower-case: an exact (indexable) match
                return {path: right.lower()} if op == "eq" else {path: {"$nin": [right.lower(), None]}}
            rx = {"$regex": "^" + re.escape(right) + "$", "$options": "i"}
            return {path: rx} if op == "eq" else {path: {"$not": re.compile("^" + re.escape(right) + "$", re.I)}}
        if op == "ilike" or op == "like":
            return {path: {"$regex": _like_regex(right), "$options": "is"}}
        raise NotImplementedError(f"lower() with {op}")

    right = _norm(right)
    if op == "eq":
        return {path: right}
    if op == "ne":
        return {path: {"$ne": None}} if right is None else {path: {"$nin": [right, None]}}
    if op in ("lt", "le", "gt", "ge"):
        return {path: {"$" + {"lt": "lt", "le": "lte", "gt": "gt", "ge": "gte"}[op]: right}}
    if op == "in":
        return {path: {"$in": right}}
    if op == "nin":
        return {path: {"$nin": right + [None]}}
    if op == "like":
        return {path: {"$regex": _like_regex(right), "$options": "s"}}
    if op == "ilike":
        return {path: {"$regex": _like_regex(right), "$options": "is"}}
    raise NotImplementedError(op)


# =============================================================================
# fields, relationships, models
# =============================================================================
class Field:
    """A stored attribute. ``now`` fills the current time on insert, ``onupdate`` refreshes it on every change."""

    def __init__(self, default=None, *, factory=None, index=False, unique=False, now=False, onupdate=False, lower=False):
        self.default, self.factory = default, factory
        self.index, self.unique, self.now, self.onupdate, self.lower = index, unique, now, onupdate, lower
        self.name = None

    def __set_name__(self, owner, name):
        self.name = name

    def fresh(self):
        return self.factory() if self.factory else copy.copy(self.default)

    def __get__(self, obj, owner=None):
        if obj is None:
            return Col(owner, self.name)
        return obj._data.get(self.name)

    def __set__(self, obj, value):
        if isinstance(value, dt.datetime):
            value = _norm_dt(value)
        elif self.lower and isinstance(value, str):
            value = value.lower()
        obj._data[self.name] = value


class Rel:
    """A relationship. ``fk`` => children (one-to-many) whose fk points at us; ``local`` => parent (many-to-one)."""

    def __init__(self, target: str, fk: Optional[str] = None, *, local: Optional[str] = None, order: Sequence[str] = (), cascade: bool = False):
        self.target, self.fk, self.local, self.order, self.cascade = target, fk, local, tuple(order), cascade
        self.name = None

    def __set_name__(self, owner, name):
        self.name = name

    @property
    def uselist(self):
        return self.fk is not None

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        if self.name in obj._pending:
            return obj._pending[self.name]
        if obj._session is None:
            return [] if self.uselist else None
        if self.name in obj._relcache:
            return obj._relcache[self.name]
        target = Model._by_name[self.target]
        if self.uselist:
            q = obj._session.query(target).filter(Col(target, self.fk) == obj.id)
            if self.order:
                q = q.order_by(*[Col(target, n) for n in self.order])
            value = q.all()
        else:
            fk = obj._data.get(self.local)
            value = obj._session.get(target, fk) if fk is not None else None
        obj._relcache[self.name] = value
        return value

    def __set__(self, obj, value):
        if self.uselist:
            obj._pending[self.name] = list(value)
        else:
            obj._relcache[self.name] = value
            obj._data[self.local] = getattr(value, "id", None)


class Model:
    """Base class. Subclasses set ``__collection__`` and declare ``Field``/``Rel`` attributes."""

    __collection__: str = ""
    __indexes__: Sequence[Tuple[Sequence[str], bool]] = ()
    _by_name: Dict[str, Any] = {}
    _fields: Dict[str, Field] = {}
    _rels: Dict[str, Rel] = {}
    _lower_fields: Tuple[str, ...] = ()
    id = Field()

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        fields, rels = {}, {}
        for klass in reversed(cls.__mro__):
            for k, v in vars(klass).items():
                if isinstance(v, Field):
                    fields[k] = v
                elif isinstance(v, Rel):
                    rels[k] = v
        cls._fields, cls._rels = fields, rels
        cls._lower_fields = tuple(k for k, f in fields.items() if f.lower)
        Model._by_name[cls.__name__] = cls

    def __init__(self, **kw):
        self._data: Dict[str, Any] = {}
        self._orig: Optional[Dict[str, Any]] = None
        self._session: Optional["Session"] = None
        self._deleted = False
        self._pending: Dict[str, list] = {}
        self._relcache: Dict[str, Any] = {}
        for name, f in self._fields.items():
            setattr(self, name, kw.pop(name)) if name in kw else self._data.__setitem__(name, f.fresh())
        for name in list(kw):
            if name in self._rels:
                setattr(self, name, kw.pop(name))
        if kw:
            raise TypeError(f"{type(self).__name__} has no field(s): {', '.join(kw)}")

    @property
    def persisted(self) -> bool:
        return self._orig is not None

    def _doc(self) -> dict:
        doc = {k: _clean_keys(v) if isinstance(v, (dict, list)) else _norm_dt(v) for k, v in self._data.items() if k != "id"}
        doc["_id"] = self._data["id"]
        return doc

    def _changes(self) -> dict:
        out = {}
        for k in self._fields:
            if k != "id" and self._data.get(k) != self._orig.get(k):
                v = self._data.get(k)
                out[k] = _clean_keys(v) if isinstance(v, (dict, list)) else _norm_dt(v)
        if out:
            for k, f in self._fields.items():
                if f.onupdate and k not in out:
                    now = utcnow_naive()
                    self._data[k] = now
                    out[k] = now
        return out

    @classmethod
    def _from_doc(cls, doc: dict, session: "Session"):
        obj = cls.__new__(cls)
        obj._deleted, obj._pending, obj._relcache, obj._session = False, {}, {}, session
        obj._data = {}
        for name, f in cls._fields.items():
            if name == "id":
                obj._data["id"] = doc["_id"]
            elif name in doc:
                v = doc[name]
                obj._data[name] = _norm_dt(v) if isinstance(v, dt.datetime) else v
            else:
                obj._data[name] = f.fresh()
        obj._orig = copy.deepcopy(obj._data)
        return obj

    def __repr__(self):
        return f"<{type(self).__name__} id={self._data.get('id')}>"


def ensure_indexes() -> None:
    """Create collections and indexes (idempotent). This is also what makes the database appear in Atlas."""
    db = database()
    for cls in {m for m in Model._by_name.values() if m.__collection__}:
        coll = db[cls.__collection__]
        for name, f in cls._fields.items():
            if name == "id":
                continue
            if f.unique:
                coll.create_index([(name, ASCENDING)], unique=True, name=f"uq_{name}")
            elif f.index:
                coll.create_index([(name, ASCENDING)], name=f"ix_{name}")
        for fields, unique in cls.__indexes__:
            coll.create_index([(f, ASCENDING) for f in fields], unique=unique, name=("uq_" if unique else "ix_") + "_".join(fields))


def drop_all_data() -> None:
    """Empty every collection (tests, and `manage.py reset-db`)."""
    db = database()
    for cls in {m for m in Model._by_name.values() if m.__collection__}:
        db[cls.__collection__].delete_many({})
    db["counters"].delete_many({})


# =============================================================================
# query
# =============================================================================
class Query:
    def __init__(self, session: "Session", entities: Sequence[Any]):
        self.s = session
        self.entities = list(entities)
        self._filters: List[Any] = []
        self._orders: List[Any] = []
        self._offset = 0
        self._limit: Optional[int] = None
        self._joins: List[Tuple[Any, Any, bool]] = []
        self._group: List[Any] = []

    # ---- builders -------------------------------------------------------
    def filter(self, *conds):
        self._filters.extend(c for c in conds if c is not None)
        return self

    def filter_by(self, **kw):
        m = self._primary()
        self._filters.extend(Col(m, k) == v for k, v in kw.items())
        return self

    def order_by(self, *orders):
        self._orders.extend(o for o in orders if o is not None)
        return self

    def offset(self, n):
        self._offset = int(n or 0)
        return self

    def limit(self, n):
        self._limit = None if n is None else int(n)
        return self

    def join(self, model, on, outer=False):
        self._joins.append((model, on, outer))
        return self

    def outerjoin(self, model, on):
        return self.join(model, on, outer=True)

    def group_by(self, *cols):
        self._group.extend(cols)
        return self

    # ---- helpers --------------------------------------------------------
    def _primary(self):
        for e in self.entities:
            if isinstance(e, type) and issubclass(e, Model):
                return e
            if isinstance(e, Col):
                return e.model
            if isinstance(e, Fn):
                ms = e.models()
                if ms:
                    return next(iter(ms))
        raise NotImplementedError("query without an entity")

    def _coll(self, model=None):
        return database()[(model or self._primary()).__collection__]

    def _is_agg(self):
        return any(isinstance(e, Fn) and (e.is_agg) for e in self.entities)

    def _filter_doc(self, only: Optional[set] = None) -> dict:
        pm = {self._primary(): ""}
        parts = [render(f, pm) for f in self._filters if only is None or f.models() <= only]
        if not parts:
            return {}
        return parts[0] if len(parts) == 1 else {"$and": parts}

    def _sort_spec(self, pm) -> List[Tuple[str, int]]:
        spec = []
        for o in self._orders:
            desc = isinstance(o, Order) and o.descending
            target = o.target if isinstance(o, Order) else o
            if isinstance(target, Fn):
                raise NotImplementedError("ordering by an aggregate is not supported; sort in Python")
            spec.append((_path(target, pm), DESCENDING if desc else ASCENDING))
        return spec

    def _model_entities(self):
        return [e for e in self.entities if isinstance(e, type) and issubclass(e, Model)]

    # ---- execution ------------------------------------------------------
    def _rows(self) -> List[tuple]:
        if self._is_agg():
            return self._agg_rows()
        if self._joins:
            return self._join_rows()
        primary = self._primary()
        cur = self._coll().find(self._filter_doc())
        spec = self._sort_spec({primary: ""})
        if spec:
            cur = cur.sort(spec)
        if self._offset:
            cur = cur.skip(self._offset)
        if self._limit is not None:
            cur = cur.limit(self._limit)
        out = []
        for doc in cur:
            row = []
            for e in self.entities:
                if isinstance(e, type) and issubclass(e, Model):
                    row.append(self.s._materialize(e, doc))
                elif isinstance(e, Col):
                    row.append(_value(doc, e.field))
                else:
                    raise NotImplementedError(f"cannot select {e!r}")
            out.append(tuple(row))
        return out

    def _join_rows(self) -> List[tuple]:
        primary = self._primary()
        pm: Dict[Any, str] = {primary: ""}
        stages_join: List[dict] = []
        for i, (model, on, outer) in enumerate(self._joins):
            if not (isinstance(on, Cmp) and on.op == "eq" and isinstance(on.left, Col) and isinstance(on.right, Col)):
                raise NotImplementedError("only `A.x == B.y` join conditions are supported")
            new_side, local_side = (on.left, on.right) if on.left.model is model else (on.right, on.left)
            if local_side.model not in pm:
                raise NotImplementedError("join condition must reference a model already in the query")
            alias = f"_j{i}"
            stages_join.append({"$lookup": {"from": model.__collection__, "localField": pm[local_side.model] + local_side.field,
                                            "foreignField": new_side.field, "as": alias}})
            stages_join.append({"$unwind": {"path": "$" + alias, "preserveNullAndEmptyArrays": outer}})
            pm[model] = alias + "."
        pre = [f for f in self._filters if f.models() <= {primary}]
        post = [f for f in self._filters if not f.models() <= {primary}]
        sort_models = set().union(*[o.models() for o in self._orders]) if self._orders else set()
        early_page = not post and sort_models <= {primary}
        pipeline: List[dict] = []
        if pre:
            pipeline.append({"$match": render(Bool("and", pre), {primary: ""})})
        spec = self._sort_spec(pm) if self._orders else []

        def paging():
            out = []
            if spec:
                out.append({"$sort": dict(spec)})
            if self._offset:
                out.append({"$skip": self._offset})
            if self._limit is not None:
                out.append({"$limit": self._limit})
            return out

        if early_page:
            pipeline += paging() + stages_join
        else:
            pipeline += stages_join
            if post:
                pipeline.append({"$match": render(Bool("and", post), pm)})
            pipeline += paging()
        out = []
        for doc in self._coll().aggregate(pipeline):
            by_model = {primary: doc}
            for i, (model, _, _) in enumerate(self._joins):
                by_model[model] = doc.get(f"_j{i}")
            row = []
            for e in self.entities:
                if isinstance(e, type) and issubclass(e, Model):
                    d = by_model.get(e)
                    row.append(self.s._materialize(e, d) if d is not None else None)
                elif isinstance(e, Col):
                    d = by_model.get(e.model)
                    row.append(_value(d, e.field) if d is not None else None)
                else:
                    raise NotImplementedError(f"cannot select {e!r} in a join")
            out.append(tuple(row))
        return out

    def _agg_rows(self) -> List[tuple]:
        if self._joins:
            raise NotImplementedError("aggregates over joins: query the pieces separately")
        coll, flt = self._coll(), self._filter_doc()
        if not self._group:
            return [tuple(self._agg_value(e, coll, flt) for e in self.entities)]
        # grouped: fetch the needed fields once and group in Python (bounded, filtered sets only)
        need = set()
        for e in list(self.entities) + list(self._group):
            for c in _cols_in(e):
                need.add(c.field)
        groups: Dict[tuple, List[dict]] = {}
        for doc in coll.find(flt, {f: 1 for f in need}):
            groups.setdefault(tuple(_group_key(g, doc) for g in self._group), []).append(doc)
        rows = []
        for key, docs in groups.items():
            row = []
            for e in self.entities:
                if isinstance(e, Fn) and e.is_agg:
                    row.append(_agg_python(e, docs))
                else:
                    idx = next((i for i, g in enumerate(self._group) if _same(g, e)), None)
                    if idx is None:
                        raise NotImplementedError(f"{e!r} must appear in group_by")
                    row.append(key[idx])
            rows.append(tuple(row))
        if self._offset:
            rows = rows[self._offset:]
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows

    def _agg_value(self, e, coll, flt):
        if isinstance(e, Fn) and e.name == "coalesce":
            inner, default = e.args
            v = self._agg_value(inner, coll, flt)
            return default if v is None else v
        if not (isinstance(e, Fn) and e.is_agg):
            raise NotImplementedError(f"{e!r} needs group_by")
        arg = e.args[0] if e.args else None
        if e.name == "count":
            if isinstance(arg, Col) and arg.name != "id":
                flt = {"$and": [flt, {arg.field: {"$ne": None}}]} if flt else {arg.field: {"$ne": None}}
            return coll.count_documents(flt)
        op = {"max": "$max", "min": "$min", "sum": "$sum"}[e.name]
        res = list(coll.aggregate(([{"$match": flt}] if flt else []) + [{"$group": {"_id": None, "v": {op: "$" + arg.field}}}]))
        return res[0]["v"] if res else None

    # ---- public result API ---------------------------------------------
    def all(self):
        rows = self._rows()
        return [r[0] for r in rows] if len(self.entities) == 1 and isinstance(self.entities[0], type) else rows

    def __iter__(self):
        return iter(self.all())

    def first(self):
        self._limit = 1 if self._limit is None else min(self._limit, 1)
        out = self.all()
        return out[0] if out else None

    def one_or_none(self):
        out = self.all()
        if len(out) > 1:
            raise ValueError("expected at most one row")
        return out[0] if out else None

    def one(self):
        r = self.one_or_none()
        if r is None:
            raise ValueError("expected one row, found none")
        return r

    def scalar(self):
        rows = self._rows()
        return rows[0][0] if rows else None

    def count(self) -> int:
        if self._joins:
            saved = (self._offset, self._limit, self._orders)
            self._offset, self._limit, self._orders = 0, None, []
            try:
                return len(self._join_rows())
            finally:
                self._offset, self._limit, self._orders = saved
        return self._coll().count_documents(self._filter_doc())

    def delete(self, synchronize_session=None) -> int:
        if self._joins:
            raise NotImplementedError("delete over a join")
        return self._coll().delete_many(self._filter_doc()).deleted_count

    def update(self, values: dict, synchronize_session=None) -> int:
        if self._joins:
            raise NotImplementedError("update over a join")
        return self._coll().update_many(self._filter_doc(), {"$set": {k: _norm(v) for k, v in values.items()}}).matched_count


def _value(doc: dict, field: str):
    v = doc.get(field)
    return _norm_dt(v) if isinstance(v, dt.datetime) else v


def _cols_in(e):
    if isinstance(e, Col):
        yield e
    elif isinstance(e, Fn):
        for a in e.args:
            yield from _cols_in(a)


def _same(a, b) -> bool:
    if isinstance(a, Col) and isinstance(b, Col):
        return a.model is b.model and a.name == b.name
    if isinstance(a, Fn) and isinstance(b, Fn):
        return a.name == b.name and len(a.args) == len(b.args) and all(_same(x, y) for x, y in zip(a.args, b.args))
    return False


def _group_key(g, doc):
    if isinstance(g, Col):
        return doc.get(g.field)
    if isinstance(g, Fn) and g.name == "date":
        v = doc.get(g.args[0].field)
        return v.date().isoformat() if isinstance(v, dt.datetime) else None
    raise NotImplementedError(f"group by {g!r}")


def _agg_python(e: Fn, docs: List[dict]):
    if e.name == "coalesce":
        v = _agg_python(e.args[0], docs)
        return e.args[1] if v is None else v
    arg = e.args[0] if e.args else None
    vals = [d.get(arg.field) for d in docs] if arg is not None and arg.name != "id" else [1] * len(docs)
    vals = [v for v in vals if v is not None]
    if e.name == "count":
        return len(vals)
    if not vals:
        return None
    return {"max": max, "min": min, "sum": sum}[e.name](vals)


# =============================================================================
# update statement (atomic claims)
# =============================================================================
class _Update:
    def __init__(self, model):
        self.model, self._where, self._values = model, [], {}

    def where(self, *conds):
        self._where.extend(conds)
        return self

    def values(self, **kw):
        self._values.update(kw)
        return self


def update(model):
    return _Update(model)


class _Result:
    def __init__(self, rowcount):
        self.rowcount = rowcount


# =============================================================================
# session (unit of work)
# =============================================================================
class Session:
    def __init__(self):
        self.info: Dict[str, Any] = {}
        self._ident: Dict[Tuple[Any, int], Model] = {}
        self._new: List[Model] = []
        self._deleted: List[Model] = []

    # ---- tracking -------------------------------------------------------
    def _materialize(self, model, doc: dict):
        key = (model, doc["_id"])
        obj = self._ident.get(key)
        if obj is None:
            obj = model._from_doc(doc, self)
            self._ident[key] = obj
        return obj

    def add(self, obj: Model) -> None:
        if obj._session is self and (obj in self._new or obj.persisted):
            return
        if obj._data.get("id") is None:
            obj._data["id"] = next_id(obj.__collection__)
        obj._session = self
        self._ident[(type(obj), obj.id)] = obj
        if not obj.persisted:
            self._new.append(obj)
        for name, children in list(obj._pending.items()):
            rel = obj._rels[name]
            for child in children:
                child._data[rel.fk] = obj.id
                self.add(child)
            obj._relcache[name] = children
        obj._pending.clear()

    def add_all(self, objs: Iterable[Model]) -> None:
        for o in objs:
            self.add(o)

    def get(self, model, ident) -> Optional[Model]:
        if ident is None:
            return None
        obj = self._ident.get((model, ident))
        if obj is not None:
            return None if obj._deleted else obj
        doc = database()[model.__collection__].find_one({"_id": ident})
        return self._materialize(model, doc) if doc else None

    def query(self, *entities) -> Query:
        return Query(self, entities)

    def delete(self, obj: Model) -> None:
        for rel in obj._rels.values():
            if rel.cascade and rel.uselist:
                for child in list(rel.__get__(obj, type(obj)) or []):
                    self.delete(child)
        if obj in self._new:
            self._new.remove(obj)
            self._ident.pop((type(obj), obj.id), None)
            return
        obj._deleted = True
        self._deleted.append(obj)

    def execute(self, stmt) -> _Result:
        if isinstance(stmt, _Update):
            q = Query(self, [stmt.model]).filter(*stmt._where)
            res = database()[stmt.model.__collection__].update_many(
                q._filter_doc(), {"$set": {k: _norm(v) for k, v in stmt._values.items()}})
            return _Result(res.matched_count)
        raise NotImplementedError(type(stmt).__name__)

    # ---- persistence ----------------------------------------------------
    def flush(self) -> None:
        db = database()
        for obj in list(self._new):
            for k, f in obj._fields.items():
                if f.now and obj._data.get(k) is None:
                    obj._data[k] = utcnow_naive()
            try:
                db[obj.__collection__].insert_one(obj._doc())
            except DuplicateKeyError as exc:
                self._new.remove(obj)
                self._ident.pop((type(obj), obj.id), None)
                raise IntegrityError(str(exc)) from exc
            obj._orig = copy.deepcopy(obj._data)
        self._new.clear()
        for obj in list(self._ident.values()):
            if obj._deleted or not obj.persisted:
                continue
            changes = obj._changes()
            if changes:
                try:
                    db[obj.__collection__].update_one({"_id": obj.id}, {"$set": changes})
                except DuplicateKeyError as exc:
                    raise IntegrityError(str(exc)) from exc
                obj._orig = copy.deepcopy(obj._data)
        for obj in self._deleted:
            db[obj.__collection__].delete_one({"_id": obj.id})
            self._ident.pop((type(obj), obj.id), None)
        self._deleted.clear()

    def commit(self) -> None:
        self.flush()
        for obj in self._ident.values():
            obj._relcache.clear()
        from app import background

        background.run_after_commit(self)

    def rollback(self) -> None:
        for obj in self._new:
            self._ident.pop((type(obj), obj.id), None)
        self._new.clear()
        for obj in self._deleted:
            obj._deleted = False
        self._deleted.clear()
        for obj in self._ident.values():
            if obj.persisted:
                obj._data = copy.deepcopy(obj._orig)
            obj._relcache.clear()
        from app import background

        background.drop_after_commit(self)

    def refresh(self, obj: Model) -> None:
        doc = database()[obj.__collection__].find_one({"_id": obj.id})
        if doc is None:
            raise LookupError(f"{type(obj).__name__} {obj.id} no longer exists")
        fresh = type(obj)._from_doc(doc, self)
        obj._data, obj._orig = fresh._data, fresh._orig
        obj._relcache.clear()

    def expire_all(self) -> None:
        pass

    def close(self) -> None:
        self._ident.clear()
        self._new.clear()
        self._deleted.clear()
        self.info.clear()
