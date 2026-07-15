"""generator.md rules + HackerEarth reference-code structures as prompt constants.

Folder structures, file names, and dependency pins below are copied from the real
HackerEarth reference questions (Reference code folders/) so generated projects are
platform-compatible. The workflow steps, output location, and the question ledger
are handled by pipeline.py code, not prompts.
"""

# The 7 supported stacks: slug (CLI value / directory prefix) → display name.
STACKS = {
    "flask-sqlite3": "Flask + SQLite3",
    "nodejs-sqlite3": "NodeJS + SQLite3",
    "fastapi-sqlite3": "FastAPI + SQLite3",
    "django-sqlite3": "Django + SQLite3",
    "reactjs-fastapi-sqlite3": "ReactJS + FastAPI + SQLite3",
    "reactjs-django-sqlite3": "ReactJS + Django + SQLite3",
    "reactjs-flask-sqlite3": "ReactJS + Flask + SQLite3",
}

REACT_STACKS = {"reactjs-fastapi-sqlite3", "reactjs-django-sqlite3", "reactjs-flask-sqlite3"}

# Offered when no --domain is given (generator.md: "Ask before assuming a domain").
DOMAIN_SUGGESTIONS = [
    "resource booking/scheduling (rooms, courts, equipment slots — overlap detection)",
    "staff/task assignment (skills, availability, load — capacity-constrained assignment)",
    "lending/inventory (tools, gear, stock — multi-step atomic stock operations)",
    "order/checkout (carts, line items — all-or-nothing checkout + derived totals)",
    "leaderboards/reviews (weighted ranking with tie-breaks)",
    "workflow/ticketing (status state machine with guarded transitions)",
]

UNIVERSAL_RULES = """
# Universal rules (apply to all stacks)

A generated question is valid only if: the skeleton and solution have identical file trees; every
piece of supporting infrastructure (database setup, routing wiring, app bootstrap) is fully
implemented in both; only the business-logic bodies are left for the candidate to fill in the
skeleton; and the problem statement describes exactly what the skeleton actually contains — no
drift between what candidates are told and what they're given.

**No Docker. No test-runner scripts. No execution/validation step.** Nothing is built or run as
part of generation. Test files are a required *written* deliverable — real, logically correct
assertions for the difficulty tier — but never generate a `Dockerfile`, `docker-compose.yml`,
`run-tests.sh`, or any other script whose purpose is to execute tests or build an image. Never
write test-report artifacts (`xunittest.xml`, `xunittest-report.xml`, `junit.xml`, `unit.xml`),
`package-lock.json`, or binary database files (`.db`, `.sqlite`, `db.sqlite3`) — databases are
created at runtime by the fully-implemented setup code.

**Fully-implemented infrastructure, zero TODOs.** The database connection/schema file
(`database.js`, `db.py`, the DB block inside `main.py`, or Django's `settings.py` database
config) is infrastructure, not an exercise. It must be 100% implemented — schema creation, seed
data, connection handling — with no TODO, no stub, no placeholder the candidate is expected to
open, edit, or complete. The same applies to: app bootstrap/wiring code, route
registration/mounting, model/schema field declarations, and migrations. In EVERY stack, DB files
and migration files (e.g. `database.js`, Django's `migrations/*.py`, the DB setup block in
`main.py`) must never contain a TODO or any line the candidate is expected to edit. Only
business-logic handler bodies are stubbed.

**Seed data strategy.** At startup, seed each entity's table with a small fixed set of rows (3–5
per entity) purely so the running app has visible data to browse/demo — this seeding code is part
of the fully-implemented infrastructure and is never stubbed. Hidden and sample tests must be
independent of this seed data: every test creates whatever rows it needs itself (via the API or a
direct DB insert) at the start of the test, and never assumes a seeded row still exists in its
original state. Never write a test that depends on a specific seeded row's id or exact field
values persisting unmodified.

**Stub convention.** Every stubbed handler consists of:
1. A docstring or comment stating the exact contract: HTTP method + URL, request shape, response
   shape, every status code it can return, and the exact wording of any error message.
2. A body that does nothing real: Python — docstring then `pass` (or `return None`); NodeJS — the
   contract comment then `// Your code goes here` as the entire body; Django views — a docstring
   alone as the entire body. Never a bare empty body with no contract detail.

**Test files are written, not executed.** Every question ships two test files: a small sample
suite (visible to the candidate) and a full suite (hidden). The sample suite is a strict subset of
the hidden suite's assertions. Both files must contain real, runnable-looking test code with
concrete inputs/outputs/status codes — write them as if they will be run.

**Test depth scales with difficulty**: Easy → 10–14 test cases. Medium → 16–24 test cases. Hard →
24+ test cases. At EVERY difficulty, at least 40% of the hidden suite must be non-happy-path tests
(validation failures with concrete violating payloads, boundary values, negative business-rule
tests, edge cases from the design) — a naive implementation with no validation and no computed
fields must fail multiple hidden tests. At Medium/Hard, additionally include at least one test per
non-obvious business rule or cross-entity constraint — a shortcut implementation that ignores the
rule must fail it.

**Difficulty tiers — apply identically across stacks, only the domain and file layout change:**

| | Easy | Medium | Hard |
|---|---|---|---|
| Entities | 1 | 3 or more, with 2+ relationships | 3 or more, with non-trivial invariants |
| Endpoints/operations | 3–4 atomic CRUD | 8 or more, at least 3 enforcing domain logic | full CRUD depth + relational integrity checks, or complex query logic |
| Validation depth | required fields + boundary/type checks (reject empty strings, non-positive quantities/amounts) + correct server-computed fields | required fields + boundary checks + at least one derived/aggregated field | foreign-key-existence checks on writes, server-computed fields, cross-entity rules |
| Algorithmic/logic complexity | none | 1 required, from the list below | 2+ required, from the list below, applied to different entities/endpoints |

Difficulty is not one axis — entity count, relationship count, endpoint count, and validation
depth can move independently. A question can be harder with *fewer* entities if it demands deeper
existence/consistency checks and full CRUD completeness.

**Logic complexity requirement (Medium/Hard).** Medium and Hard questions must implement at least
one (Medium) or two (Hard, on different entities/endpoints — not the same rule restated twice) of:
- **Overlap/conflict detection over ranges** — e.g. a booking is rejected if its time range
  overlaps an existing booking for the same resource; real interval comparison, not equality.
- **Capacity-constrained assignment** — assign to the first eligible candidate matching multiple
  criteria (skill, availability, current load), with an explicit tie-break rule.
- **Multi-step atomic operation across 3+ tables** — e.g. checkout: validate stock for every line
  item, decrement stock, create the order and its line items, and reject the *entire* operation if
  any single item fails (all-or-nothing, never partial).
- **Weighted ranking/scoring** — a derived score from multiple weighted fields, results sorted by
  it, with a defined tie-break rule.
- **State machine with guarded transitions** — only specific from→to status transitions are legal;
  illegal transitions are rejected with a specific error, not silently applied.
- **Combined filter + sort + paginate on one endpoint** — not pagination alone.

A Hard question is **invalid** if a plain CRUD implementation with no branching logic could pass
the hidden test suite — every Hard question must have at least one hidden test that a
naive/shortcut implementation demonstrably fails.

**Solution correctness for logic-complexity items.** The solution's implementation of every
required logic-complexity item must be the general, correct algorithm for that rule — e.g. true
interval-overlap comparison that works for any start/end values, not a hardcoded check that only
happens to work against the seeded rows or the specific values used in the hidden tests.

**Domain quality.** Avoid generic, heavily-templated domains (a bare to-do list, a bare blog, a
bare library catalog) unless a genuinely non-obvious rule is added on top. Prefer domains with a
natural cross-entity constraint that maps onto the logic-complexity list.

**Response and error format — one convention per project, consistent everywhere in it.**
- Success responses return the resource/collection directly as JSON — a single object for a
  single-item read, an array for a list — never wrapped in an envelope like `{"data": ...}`.
- Error responses are `{"error": "<message>"}` for Flask, NodeJS, and Django. FastAPI uses its
  native `{"detail": "<message>"}` (from `HTTPException`) — do not rename this key.
- Standard status codes: 200 for a successful read/update, 201 for a successful create, 200 with a
  confirmation body (e.g. `{"message": "deleted"}`) for a successful delete (never 204), 400 for a
  malformed/missing-field request, 404 for a missing resource or a missing referenced parent id,
  409 for a constraint violation (duplicate, overlap, illegal state transition), and — FastAPI
  only — 422 for Pydantic validation failures (automatic, never hand-rolled).
- A list/collection endpoint with zero matching rows returns **200 with an empty array (`[]`)** —
  never 404. Reserve 404 for a single-resource lookup (get/update/delete by id).
- Update endpoints use **PUT** when they replace the full set of writable fields. Only use PATCH
  when partial-update semantics are a deliberate, stated requirement — never mix PUT and PATCH for
  the same resource within one project.

**Ports.** Every backend runs on port **8000**. Every React frontend dev server runs on port
**5000**. Fixed, not configurable:
- Flask: `app.run(debug=True, host="0.0.0.0", port=8000)`
- Django: run command `python manage.py runserver 0.0.0.0:8000`
- FastAPI: `uvicorn.run(app, host="0.0.0.0", port=8000)`
- NodeJS: `app.listen(process.env.port || 8000)`
- React (webpack-dev-server): `devServer: { port: 5000 }` in `webpack.config.js`

**CORS.** Any backend paired with a React frontend must have CORS fully open (Flask-Cors's
`CORS(app)` / FastAPI's `CORSMiddleware(allow_origins=["*"])` / django-cors-headers with
`CORS_ORIGIN_ALLOW_ALL = True` and the middleware first), because the frontend calls
`http://localhost:8000` cross-origin from port 5000.

**React frontend conventions** (all 3 React pairings — copied from the HackerEarth references):
- Functional components with hooks; files are plain **`.js`** (`App.js`, `index.js`,
  `components/<View>.js`) — never `.jsx` file extensions.
- Routing with **react-router-dom v5** (`BrowserRouter as Router`, `Switch`,
  `<Route path=... component={...}/>`, `useHistory`), wrapped as
  `<Router basename={`/${process.env.REACT_APP_HASH}/`}>`.
- HTTP with **axios**, called directly inside components. The backend base URL lives ONLY in
  `src/Constants.js`, exactly:
  ```js
  export const BASE_URL = "http://localhost:8000";
  // export const BASE_URL = `https://he-ide.hackerearth.com/${process.env.REACT_APP_HASH}.backend`;
  ```
  Components `import { BASE_URL } from '../Constants';` — never a literal URL in a component,
  and never a `services/api.js` module.
- UI with **semantic-ui-react** components. Styles: `src/index.css` + `src/App.css` (plus
  optional per-component css like `components/Header.css`) — never a single `styles.css`.
- `src/index.html` is the HtmlWebpackPlugin template (mount point `<div id="root">`);
  `src/__mocks__/axios.js` provides the jest axios mock.
- Frontend test files live at the frontend root: `main.test.js` (hidden) + `sample.test.js`
  (visible sample).
- In the skeleton, markup/JSX, navigation, form input handling, and loading-state scaffolding
  must all be fully wired and functional; only the axios call and the logic that depends on its
  result may be a stub. A skeleton that does not render, does not accept input, or has
  non-functional state is invalid.
"""

PROBLEM_STATEMENT_FORMAT = '''
**Problem statement format.** problem_statement.md must mirror the markdown TEMPLATE below
exactly — same headings, same order, same list style. Angle-bracket placeholders are filled in;
everything else (heading text, bold labels, bullet structure, the Testing/Submission boilerplate)
is kept verbatim. The goal is clean, well-spaced markdown: every section separated by a blank
line, every enumeration a bullet list (never bare lines, which merge into one paragraph when
rendered), code-like values (paths, URLs, methods, status codes, field lists) in backticks.

TEMPLATE (start of file):

# [<Stack>] <Scenario Title>

## Problem statement

<2–4 sentences in plain business language: what system to build and what it must support. At
Medium/Hard, also state every business rule / cross-entity constraint here, clearly enough to
implement without revealing the exact algorithm/code.>

## Technical specifications

**Tech stack**

- Backend: <NodeJS | Flask | FastAPI | Django>
- Frontend: ReactJS            <React stacks only — omit the line otherwise>
- Database: SQLite

**Database model parameters**

- `<table_name>`: [<field>: <type>, <field>: <type>, ...]
- `<table_name>`: [...]        <one bullet per table, matching the skeleton's schema exactly>

**Ports**

- Backend: 8000
- Frontend: 5000               <React stacks only — omit the line otherwise>

## Tasks

Complete the following API Endpoints in `<exact path from the skeleton>`:

- **GET** `/api/products?page=1&limit=10` would return all products with pagination.
- **GET** `/api/products/{id}` would return a single product. If the product with ID is not
  found, return status `404` with an error message.
- **POST** `/api/products` would add a new product to the inventory.

<One such block per file the candidate must edit — heading sentence then one bullet per stubbed
handler ("Complete the following components in `<path>`:" for frontend files). Each bullet:
bolded method, backticked URL, what it does, every status code it can return, and the exact
wording of every error message — word-for-word consistent with the stub's docstring/comment.>

## Testing instructions

- To run any additional commands, use the Terminal. For example, navigate to the '/backend'
  directory in the Terminal and use the command: `<test command>`.
- Use the integrated API testing client in the IDE's left sidebar to test API requests.
- Upon clicking the **Run code** or **Submit code** buttons, access the Build log or Execution
  log to review comprehensive details about the test outcomes.

## Submission instructions

- Clicking **Run code** compiles and runs your code against sample tests, but it will not
  generate scores.
- Clicking **Submit code** runs your code against multiple test cases, assessing different
  scenarios holistically, and the score will be assigned accordingly.

(end of template)

The `<test command>` is `npm run test` for NodeJS/React frontend, `python -m pytest
sample_test.py` for Flask/FastAPI, and `python manage.py test` for Django.

No section may reference a file, endpoint, status code, or error message that doesn't literally
exist in the skeleton. Never mention the hidden test file, db setup/infrastructure files, or any
file the candidate must not edit in the Tasks section.
'''

_FLASK_PLAYBOOK = """
## Playbook: Flask + SQLite3 (mirrors the HackerEarth Flask references)

**File structure — one file, at every difficulty:**
```
backend/
  main.py            (Flask app setup + SQLAlchemy model classes + routes, all together)
  requirements.txt
  test.py            (full/hidden test suite)
  sample_test.py     (visible subset)
```
Do not split into `app.py`/`db.py`/`routes.py`. Do NOT write any `.db` file — SQLite is created at
runtime. Difficulty scales the number of models and routes inside this one `main.py`.

**Routing style by tier:**
- Easy and Medium: `flask_restful` — `Resource` subclasses, one class per resource
  (`class EventList(Resource): def get(self): ...`), registered with `api.add_resource(...)`.
- **Hard: plain `@app.route(...)` function handlers — NO flask_restful** (matching the reference;
  Flask_RESTful is also removed from Hard's requirements.txt).

**Database.** Flask-SQLAlchemy, `SQLALCHEMY_DATABASE_URI = 'sqlite:///<name>.db'`. Model classes
fully defined — never stubbed. `db.create_all()` runs inside `with app.app_context():` in the
`__main__` block, followed by the seed-data inserts (guarded so they only insert into an empty
table), then `app.run(debug=True, host="0.0.0.0", port=8000)`.

**requirements.txt — exact pins (Easy/Medium):**
```
Flask==1.1.2
Flask_RESTful==0.3.8
Flask_SQLAlchemy==2.4.3
SQLAlchemy==1.3.18
Requests==2.32.3
unittest_xml_reporting==3.0.4
xmlrunner==1.7.7
Jinja2==2.11.2
MarkupSafe==1.1.1
pytest==6.2.5
itsdangerous==1.1.0
Werkzeug==1.0.1
```
**Hard** uses the same list MINUS `Flask_RESTful`, `Requests`, `unittest_xml_reporting`, and
`xmlrunner`.

**Solution design.** Factor out small reusable helpers used by every handler: a required-field
validator, a date/number parser, and an error-response formatter — never duplicate this logic per
method. Catch `sqlalchemy.exc.IntegrityError` around every write and translate a
unique/foreign-key violation into a 409 with a specific message rather than a raw 500.

**Difficulty tiers.**
- Easy: 1 model, 1–2 `Resource` classes, ~4–5 methods total (list, create, get-by-id, update,
  delete), required-field + boundary validation (empty strings, non-positive numbers rejected).
- Medium: 3+ models with real relationships (foreign keys, and at least one join/association
  pattern), 6+ `Resource` classes, at least one computed/aggregated field exposed via a small
  model helper method reused everywhere it's needed.
- Hard: same or fewer models than Medium but deeper validation — foreign-key-existence checks on
  writes (404 if a referenced parent id doesn't exist), full CRUD completeness on every resource,
  correctly serialized nested/joined responses (e.g. ISO-8601 dates) — all as plain `@app.route`
  functions.

**Stub convention.** Contract docstring, then `pass` (or `return None`):
```python
class EventList(Resource):
    def get(self):
        \"\"\"Return all events ordered by date, as a JSON list, with status code 200.\"\"\"
        pass
```
"""

_DJANGO_PLAYBOOK = """
## Playbook: Django + SQLite3 (mirrors the HackerEarth Django references)

**File structure by tier:**

Easy (project `project/`, app `app/` — per the Student-management reference):
```
backend/
  manage.py
  requirements.txt
  project/            __init__.py, settings.py, urls.py, wsgi.py, asgi.py
  app/                __init__.py, admin.py, apps.py, models.py, serializers.py, views.py, urls.py
                      migrations/__init__.py, migrations/0001_initial.py
                      tests.py           (full/hidden suite — inside the app)
                      sample_tests.py    (visible subset — inside the app)
```

Medium/Hard (project `backend/`, app `<domain>/` — per the E-commerce/Hotel references):
```
backend/
  manage.py
  requirements.txt
  backend/            __init__.py, settings.py, urls.py, wsgi.py, asgi.py
  <domain>/           __init__.py, admin.py, apps.py, models.py, forms.py, views.py, urls.py
                      migrations/__init__.py, migrations/0001_initial.py
                      templates/<domain>/*.html
  tests/              __init__.py, test.py          (full/hidden suite — a real app,
                                                     listed in INSTALLED_APPS)
  sample_tests/       __init__.py, test.py          (visible subset — also in INSTALLED_APPS)
```
Do NOT write a `db.sqlite3` file — it is created at runtime by migrations.

**Routing/view style by tier.**
- Easy: Django REST Framework — a `ModelSerializer` per model and a `ViewSet` registered through
  `rest_framework.routers.SimpleRouter()` in `project/urls.py`.
- Medium/Hard: plain function-based views returning `render(request, '<template>.html', context)`
  or `JsonResponse`, backed by a `ModelForm` in `forms.py` — no DRF views at these tiers.

**requirements.txt — exact pins:**
- Easy: `Django==3.0.6`, `djangorestframework==3.11.0`, `requests==2.23.0`,
  `unittest-xml-reporting==3.0.2`, `asgiref==3.2.7`, `pytz==2020.1`, `sqlparse==0.3.1`.
- Medium/Hard: `Django==3.2.7`, `django-cors-headers==3.8.0`, `django-nose==1.4.7`,
  `djangorestframework==3.12.4`, `pytz==2021.1`, `sqlparse==0.4.2`, `asgiref==3.4.1`.

**Database & seed.** Standard `DATABASES` sqlite3 config in `settings.py`. Migrations are always
committed as real files (`migrations/0001_initial.py`) — model field declarations complete, never
stubbed. Seed the 3–5 demo rows per entity via a data migration (`migrations/0002_seed.py` using
`RunPython`) — fully implemented, never stubbed. The dev server runs on port 8000.

**CORS (Medium/Hard, and any tier paired with React).** `corsheaders` in INSTALLED_APPS,
`corsheaders.middleware.CorsMiddleware` FIRST in MIDDLEWARE, `CORS_ORIGIN_ALLOW_ALL = True`.

**Solution design.** Catch `django.db.utils.IntegrityError` on any write that violates a unique
or foreign-key constraint and respond 409 with `{"error": ...}` rather than letting Django's
default error page render.

**Difficulty tiers.**
- Easy: 1 model, 0 foreign keys, a `ViewSet` covering list/create/retrieve/update, with
  required-field + boundary validation (empty strings, non-positive numbers rejected).
- Medium: 3+ models with real foreign-key relationships, at least one precise business rule
  spelled out in the problem statement, multi-step flows that write across more than one model in
  a single request (e.g. checkout deducting stock while creating an order).
- Hard: at least one server-computed/overwritten field (e.g. price derived from a category,
  ignoring any client-submitted value) and a form that deliberately excludes that field from what
  the client can write.

**Stub convention.** A view's stubbed body is a docstring describing the exact contract; the
docstring alone is the entire body (valid Python, no `pass` required), and it must not return a
real response:
```python
def apply_job(request, pk):
    \"\"\"
    Check whether the job is already applied.
    If already applied return {'message': 'Job Already Applied'}.
    Otherwise apply and return {'message': 'Job Applied'}.
    \"\"\"
```
"""

_FASTAPI_PLAYBOOK = """
## Playbook: FastAPI + SQLite3 (mirrors the HackerEarth Taxi-booking reference)

**File structure — one file, at every difficulty:**
```
backend/
  main.py            (SQLAlchemy DB setup + ORM model classes + Pydantic schema classes + routes)
  requirements.txt
  test.py            (full/hidden test suite)
  sample_test.py     (visible subset)
```
Keep everything in one `main.py` — plain `@app.get/post/put/delete` decorators, no APIRouter, no
`database.py`/`models.py`/`schemas.py` split. Do NOT write any `.db` file.

**requirements.txt — exact pins:**
```
fastapi==0.104.1
uvicorn==0.24.0
sqlalchemy==1.4.50
pydantic==2.5.0
pytest==7.4.3
httpx==0.25.1
```

**Database.** SQLAlchemy ORM: `sqlite:///./<name>.db`, `connect_args={"check_same_thread": False}`,
`Base.metadata.create_all(bind=engine)` executed unconditionally at import time, followed by a
fully-implemented seed block (guarded to only insert into an empty table). A generator-based
`get_db()` dependency (`yield db` inside try/finally) injected via `Depends(get_db)` into every
route. None of this is ever stubbed. `uvicorn.run(app, host="0.0.0.0", port=8000)` in `__main__`.

**Pydantic schema convention.** For every entity define: a `*Create` schema (request body, no
server-assigned fields), a `*Response` schema (`class Config: from_attributes = True`), and a
`*Update` schema when partial updates are supported. Rely on FastAPI's automatic 422 response for
malformed/missing fields — state this explicitly in the problem statement.

**Solution design.** Let Pydantic handle field-level validation (the automatic 422) — route bodies
only handle business-level checks: existence (404), conflicts (409), and the required
logic-complexity rule(s). Raise `HTTPException(status_code=..., detail="...")` for every
business-level failure. Wrap writes in try/except around the session commit, catch
`IntegrityError`, call `db.rollback()`, and translate it to 409.

**Difficulty tiers.**
- Easy: 1 entity, 0 relationships, 5 full-CRUD routes (list, create, get-by-id, update, delete),
  with boundary validation beyond Pydantic's automatic 422 (e.g. reject empty strings and
  non-positive quantities/amounts with a specific 400/422 detail).
- Medium: 3+ entities with real relationships (FK columns or ORM `relationship()`), at least one
  derived/aggregated response field.
- Hard: foreign-key-existence validation returning 404 with a specific `detail` message, deeper
  cross-entity business rules layered on top of full CRUD.

**Stub convention.** Docstring describing the exact contract, followed by `pass`:
```python
@app.get("/bookings/{booking_id}", response_model=BookingResponse)
def get_booking(booking_id: int, db: Session = Depends(get_db)):
    \"\"\"
    Retrieve a booking by id.
    Response: booking JSON with status 200, or status 404 if not found.
    \"\"\"
    pass
```
"""

_NODEJS_PLAYBOOK = """
## Playbook: NodeJS + SQLite3 (mirrors the HackerEarth Hotel/Library references)

**File structure — flat backend root, single router, at every difficulty:**
```
backend/
  index.js           (the express app defined inline: express.json() middleware, mounts
                      routes.js at /api, `module.exports = { app }`, listens on
                      `process.env.port || 8000` — fully implemented; no cors, matching the
                      reference)
  database.js        (sqlite3 connection on ./<name>.db + CREATE TABLE IF NOT EXISTS for every
                      entity + seed inserts + promise query helpers — 100% implemented, ZERO
                      TODOs; infrastructure the candidate never edits)
  routes.js          (ONE express.Router() holding ALL endpoint stubs — this is the only file the
                      candidate completes)
  package.json
  tests/
    index.test.js    (full/hidden test suite — supertest against the exported app)
    sample.test.js   (visible subset)
```
Do NOT create `src/`, `controllers/`, per-entity route files, `server.js`, or any `.db` file.
All endpoints live in the single `routes.js`, mounted at `/api` (URLs look like `/api/hotels`,
`/api/hotels/:id`).

**package.json — copy this VERBATIM, byte-for-byte, exactly as in the reference (same field
order, same name, no additions — do NOT add cors or rename it):**
```json
{
  "name": "socialmediaapi",
  "version": "1.0.0",
  "description": "",
  "main": "index.js",
  "scripts": {
    "test": "jest --forceExit --runInBand",
    "start": "nodemon index.js",
    "sample_tests": "jest --forceExit --runInBand --verbose --ci --testResultsProcessor=\\"jest-junit\\" -- sample.test.js",
    "main_tests": "jest --forceExit --runInBand --verbose --ci --testResultsProcessor=\\"jest-junit\\" -- index.test.js"
  },
  "keywords": [],
  "author": "",
  "license": "ISC",
  "devDependencies": {
    "jest": "^27.2.0",
    "jest-junit": "^12.2.0",
    "jest-junit-reporter": "^1.1.0",
    "nodemon": "^2.0.12",
    "supertest": "^6.1.6"
  },
  "dependencies": {
    "express": "^4.17.1",
    "sqlite": "^4.0.23",
    "sqlite3": "^5.0.2"
  },
  "jest-junit": {
    "suiteName": "jest tests",
    "outputDirectory": ".",
    "outputName": "xunittest-report.xml",
    "uniqueOutputName": "false",
    "classNameTemplate": "{classname}",
    "titleTemplate": "{title}",
    "ancestorSeparator": " › ",
    "usePathForSuiteName": "true"
  }
}
```

**`database.js` responsibility.** `const sqlite3 = require('sqlite3').verbose();` connection on
`./<name>.db`, `PRAGMA foreign_keys = ON`, `CREATE TABLE IF NOT EXISTS` for every entity, seed
inserts (guarded to only insert into an empty table), and promise helpers (`runQuery`, `getQuery`,
`allQuery`) exported for routes.js. When capturing an autoincrement id from an insert, use a
non-arrow `function(err) { ... }` callback so `this.lastID` resolves correctly.

**Routes responsibility.** Every handler in `routes.js` performs the business logic using
`database.js`'s helpers and sends the JSON response. Catch a `SQLITE_CONSTRAINT` error and
respond 409 with a specific message rather than a raw 500. Parse every `:id` route param with
`parseInt(req.params.id, 10)` and respond 400 with a specific message if it isn't a valid
integer, before querying the database.

**Difficulty tiers.**
- Easy: 1 table, 3–4 routes, no relationships, required-field + boundary validation (empty
  strings, non-positive numbers rejected with 400 and a specific message).
- Medium: 2+ tables, 5+ routes total, explicit pagination (`page`/`limit` query params with
  sensible defaults) on at least one list endpoint, deliberately asymmetric status-code rules
  across similar-looking endpoints (e.g. 404 for a missing resource on one route, 400 for a
  missing required field on another).
- Hard: 2+ tables with a real foreign key, a join/filter endpoint that combines data across the
  relationship (e.g. `GET /api/genres/:id/books`), manual FK-existence validation inside the
  handler, and stricter REST status codes (201 on successful creation, not 200).

**Stub convention.** Contract comment block, then `// Your code goes here` as the entire body:
```js
// routes.js
// POST /api/hotels — body: { name, city, rooms }
// On success: 201 with the created hotel record.
// On missing "name": 400 { error: "name is required" }
router.post('/hotels', (req, res) => {
  // Your code goes here
});
```
"""

_REACT_FRONTEND = """
**Frontend file structure (identical across all 3 React pairings — copied from the references):**
```
frontend/
  package.json
  webpack.config.js
  .babelrc  .eslintrc  .prettierrc  .env  .gitignore
  main.test.js         (full/hidden frontend test suite)
  sample.test.js       (visible subset)
  src/
    index.html         (HtmlWebpackPlugin template, <div id="root">)
    index.js  index.css
    App.js    App.css
    Constants.js       (BASE_URL — localhost active, HE-IDE line commented)
    components/        (one .js file per page/view; optional per-component .css)
    __mocks__/axios.js (jest axios mock)
```

**frontend/package.json — copy this VERBATIM, byte-for-byte, exactly as in the reference (same
field order, no additions, no omissions):**
```json
{
  "name": "frontend",
  "version": "0.1.0",
  "private": true,
  "dependencies": {
    "@babel/plugin-transform-runtime": "^7.16.4",
    "@babel/polyfill": "^7.10.1",
    "@testing-library/jest-dom": "^5.15.0",
    "@testing-library/react": "^12.1.2",
    "@testing-library/user-event": "^13.5.0",
    "axios": "^0.21.1",
    "enzyme": "^3.11.0",
    "react": "^16.13.1",
    "react-dom": "^16.13.1",
    "react-router-dom": "^5.1.2",
    "semantic-ui-react": "^0.88.2"
  },
  "scripts": {
    "start": "webpack-dev-server --hot --mode development --host 0.0.0.0",
    "build": "webpack --mode production",
    "test": "jest --testTimeout=10000 --verbose --ci --testResultsProcessor=\\"jest-junit\\"",
    "sample_tests": "jest --testTimeout=10000 --verbose --ci --testResultsProcessor=\\"jest-junit\\" -- sample.test.js",
    "main_tests": "jest --testTimeout=10000 --verbose --ci --testResultsProcessor=\\"jest-junit\\" -- main.test.js"
  },
  "devDependencies": {
    "@babel/core": "^7.10.2",
    "@babel/plugin-proposal-class-properties": "^7.10.1",
    "@babel/plugin-proposal-object-rest-spread": "^7.10.1",
    "@babel/preset-env": "^7.10.2",
    "@babel/preset-react": "^7.10.1",
    "babel-loader": "^8.1.0",
    "css-loader": "^3.5.3",
    "ejs-loader": "^0.5.0",
    "eslint-config-airbnb": "^18.1.0",
    "eslint-config-prettier": "^6.10.1",
    "eslint-plugin-jsx-a11y": "^6.2.3",
    "eslint-plugin-prettier": "^3.1.2",
    "file-loader": "^6.0.0",
    "html-webpack-plugin": "^4.3.0",
    "prettier": "^2.0.4",
    "style-loader": "^1.2.1",
    "svg-url-loader": "^6.0.0",
    "url-loader": "^4.1.0",
    "webpack": "^4.43.0",
    "webpack-cli": "^3.3.11",
    "webpack-dev-server": "^3.11.0",
    "jest": "^26.6.3",
    "jest-junit": "^12.0.0"
  },
  "jest-junit": {
    "suiteName": "jest tests",
    "outputDirectory": ".",
    "outputName": "xunittest-report.xml",
    "uniqueOutputName": "false",
    "classNameTemplate": "{classname}",
    "titleTemplate": "{title}",
    "ancestorSeparator": " › ",
    "usePathForSuiteName": "true"
  }
}
```

**webpack.config.js** (reference shape): entry `['@babel/polyfill', `${APP_DIR}/index.js`]`,
output to `build/` with `publicPath: `/${process.env.REACT_APP_HASH}/``, babel-loader for
`.js`/`.jsx`, `style-loader`+`css-loader` for css, `url-loader` for images, HtmlWebpackPlugin on
`src/index.html`, `webpack.DefinePlugin` injecting `process.env.REACT_APP_HASH`, and
`devServer: { contentBase: BUILD_DIR, compress: true, port: 5000, historyApiFallback: true,
disableHostCheck: true }`.

**.babelrc** (verbatim):
```json
{
  "presets": ["@babel/preset-env", "@babel/preset-react"],
  "plugins": [
    "@babel/plugin-proposal-class-properties",
    "@babel/plugin-proposal-object-rest-spread",
    "@babel/plugin-transform-runtime"
  ]
}
```
**.env** (verbatim): `PORT=5000`. **.prettierrc**: `{ "tabWidth": 2, "singleQuote": true }`.
**.eslintrc**: airbnb + prettier config as in the references.
**src/__mocks__/axios.js** (verbatim):
```js
export default {
  get: jest.fn(() => Promise.resolve({ data: {} })),
  post: jest.fn((data) => Promise.resolve({ data: {} })),
};
```

**Frontend stub convention** (only axios calls + their downstream logic are stubbed):
```js
const getCourses = async () => {
  /*
  Complete the following code to get list of courses from backend url=BASE_URL+'/courses'
  return response.data
  */
};
```

**Frontend difficulty tiers:** Easy = 3–4 simple pages with no route parameters; Medium = 6–7
components with parameterized routes and at least one derived/aggregate view; Hard = a view that
surfaces one of the backend's required logic-complexity outcomes directly (e.g. a
rejected-overlap error shown inline, or a ranked list from a weighted-scoring endpoint) and/or a
non-CRUD aggregate read combining data from 2+ endpoints. For a medium/hard "list with related
child data" view, nest the related data directly in the response payload (built inside the
backend view) rather than requiring the frontend to make follow-up requests per row.
"""

_REACT_FLASK_BACKEND = """
**Backend (ReactJS + Flask) — structure depends on tier (per the references):**

Easy (Course-application reference) — single file:
```
backend/
  main.py            (Flask + flask_restful Resources + flask_sqlalchemy models, all together;
                      CORS(app) enabled; port 8000)
  requirements.txt   (the Flask Easy/Medium pin list + Flask_Cors==3.0.10)
  test.py            (full/hidden suite)
  sample_test.py     (visible subset)
```

Medium/Hard (Library-management reference) — modular:
```
backend/
  app.py             (entry: creates app, CORS(app), db.init_app(app), registers every blueprint
                      with url_prefix='/api/<domain>', db.create_all() + seed in app context,
                      app.run(host="0.0.0.0", port=8000) — fully implemented)
  db.py              (`db = SQLAlchemy()` instance — fully implemented)
  models/
    <Entity>.py      (one model class per file — fully implemented, never stubbed)
  routes/
    <entity>Routes.py (Flask Blueprint, function-per-route stubs: docstring + pass; ALL stubbing
                       happens here)
  requirements.txt   (same pins as above)
  test.py            (full/hidden suite)
  sample_test.py     (visible subset)
```
Follow the standalone Flask playbook above for response/error handling, IntegrityError→409, and
difficulty scaling of models/routes.
"""

_REACT_DJANGO_BACKEND = """
**Backend (ReactJS + Django) — per the Jobsite/Bookshow references, ALL tiers:**
```
backend/
  manage.py
  requirements.txt   (the Django Medium/Hard pin list: Django==3.2.7, django-cors-headers==3.8.0,
                      django-nose==1.4.7, djangorestframework==3.12.4, pytz, sqlparse, asgiref)
  backend/           __init__.py, settings.py, urls.py, wsgi.py, asgi.py
  <domain>/          __init__.py, admin.py, apps.py, models.py, serializers.py, views.py, urls.py
                     migrations/__init__.py, migrations/0001_initial.py (+ 0002_seed.py)
  tests/             __init__.py, test.py          (full/hidden suite, in INSTALLED_APPS)
  sample_tests/      __init__.py, test.py          (visible subset, in INSTALLED_APPS)
```
- Views are DRF **function-based `@api_view([...])` views** with `ModelSerializer`s — NOT
  ViewSets, NOT template pages — at every tier (this differs from standalone Django).
- django-cors-headers enabled (`CorsMiddleware` first, `CORS_ORIGIN_ALLOW_ALL = True`).
- Stub convention: `@api_view` decorator + docstring-only body (see the standalone Django
  playbook). Difficulty scaling follows the standalone Django tiers.
- Do NOT write `db.sqlite3` — migrations create it at runtime.
"""

STACK_PLAYBOOKS = {
    "flask-sqlite3": _FLASK_PLAYBOOK,
    "nodejs-sqlite3": _NODEJS_PLAYBOOK,
    "fastapi-sqlite3": _FASTAPI_PLAYBOOK,
    "django-sqlite3": _DJANGO_PLAYBOOK,
    "reactjs-fastapi-sqlite3": (
        _FASTAPI_PLAYBOOK
        + "\n**This is the React + FastAPI stack.** The backend follows the playbook above exactly"
        " (one `main.py` under `backend/`), plus `CORSMiddleware(allow_origins=[\"*\"])` added to"
        " the same file.\n" + _REACT_FRONTEND
    ),
    "reactjs-django-sqlite3": (
        _DJANGO_PLAYBOOK + _REACT_DJANGO_BACKEND + _REACT_FRONTEND
    ),
    "reactjs-flask-sqlite3": (
        _FLASK_PLAYBOOK + _REACT_FLASK_BACKEND + _REACT_FRONTEND
    ),
}
