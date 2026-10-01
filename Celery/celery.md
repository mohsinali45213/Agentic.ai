# Celery: Complete Step-by-Step Guide

A single-file tutorial covering every core Celery concept, in the order you should learn them.

## Table of Contents

1. What problem does Celery solve?
2. The architecture (4 pieces)
3. Installation and setup
4. Your first task
5. Run the worker
6. Send a task
7. `delay` vs `apply_async`
8. Task states
9. Configuration
10. Retries
11. Timeouts
12. Idempotency and acknowledgements
13. Multiple queues and routing
14. Concurrency and worker pools
15. Workflows (Canvas): chain, group, chord
16. Periodic tasks with Celery Beat
17. Celery with Django
18. Celery with FastAPI
19. Progress reporting
20. Monitoring with Flower
21. Error handling and best practices
22. Production deployment
23. Full mini project (AI document pipeline)
24. Common mistakes and troubleshooting
25. Quick recap and practice path

---

## Step 1: What problem does Celery solve?

Normally, when a user hits your API, your code runs and returns a response. If the work takes 30 seconds (an LLM call, image processing, sending 1,000 emails), the user waits, and the request may time out.

**Celery lets you say: "Don't do this now. Put it in a queue, and let another process do it."**

The API returns instantly ("job started"), and the heavy work happens in the background.

## Step 2: The architecture (the 4 pieces)

```
[Your App] --task--> [Broker] --task--> [Worker] --result--> [Result Backend]
 (producer)          (queue)           (executor)             (storage)
```

1. **Producer (your app):** Django/FastAPI code that *sends* a task.
2. **Broker:** a message queue holding tasks until a worker picks them up. Usually **Redis** or **RabbitMQ**.
3. **Worker:** a separate process that *pulls* tasks from the broker and runs them.
4. **Result backend (optional):** stores the return value or status of tasks (Redis, a database, etc.).

Key insight: **the worker is a separate process from your web server.** It has its own code loaded and can run on another machine.

## Step 3: Installation and setup

```bash
pip install celery redis
```

Start Redis (Docker is easiest):

```bash
docker run -d -p 6379:6379 redis
```

## Step 4: Your first task

Create `tasks.py`:

```python
from celery import Celery

app = Celery(
    "myapp",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1",
)

@app.task
def add(x, y):
    return x + y
```

- `Celery("myapp", ...)` creates the app. The first argument is just a name.
- `broker=` is where tasks are queued.
- `backend=` is where results are stored.
- `@app.task` turns a normal function into a Celery task.

## Step 5: Run the worker

In one terminal:

```bash
celery -A tasks worker --loglevel=info
```

`-A tasks` means "the Celery app lives in `tasks.py`". The worker starts, connects to Redis, and waits for jobs.

## Step 6: Send a task

In a Python shell:

```python
from tasks import add

result = add.delay(4, 6)
print(result.id)               # unique task ID
print(result.status)           # PENDING -> STARTED -> SUCCESS
print(result.get(timeout=10))  # 10
```

**What happened:**

1. `.delay(4, 6)` did **not** run the function. It serialized the call and pushed a message to Redis.
2. The worker picked up the message, ran `add(4, 6)`, and stored `10` in the result backend.
3. `.get()` fetched it.

`.delay(*args)` is shorthand for `.apply_async(args=[...])`. Use `apply_async` when you need options.

## Step 7: `delay` vs `apply_async`

```python
add.apply_async(args=(4, 6), countdown=30)           # run after 30 seconds
add.apply_async(args=(4, 6), expires=60)             # discard if not started within 60s
add.apply_async(args=(4, 6), queue="high_priority")  # send to a specific queue
add.apply_async(args=(4, 6), retry=True)             # retry publishing if broker is down
```

## Step 8: Task states

A task moves through states:

| State | Meaning |
|---|---|
| `PENDING` | Waiting, or unknown task ID |
| `STARTED` | Worker began it (only visible if `task_track_started=True`) |
| `RETRY` | Failed and will be retried |
| `SUCCESS` | Finished OK |
| `FAILURE` | Raised an exception |
| `REVOKED` | Cancelled |

Note: `PENDING` also appears for IDs Celery has never heard of, which is a common source of confusion.

## Step 9: Configuration

Instead of passing settings in the constructor, use config:

```python
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    result_expires=3600,        # keep results for 1 hour
)
```

**Important:** always use **JSON** serialization. The old default (`pickle`) can execute arbitrary code if someone can write to your broker. This also means **task arguments must be JSON-serializable**: pass IDs, not objects.

## Step 10: Retries (essential for AI/API work)

External APIs fail. Celery can retry automatically.

**Manual retry:**

```python
@app.task(bind=True, max_retries=3)
def call_llm(self, prompt):
    try:
        return llm_call(prompt)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10)
```

- `bind=True` gives you `self`, the task instance.
- `max_retries=3` stops after 3 retries.
- `countdown=10` waits 10 seconds before retrying.

**Automatic retry (cleaner):**

```python
@app.task(
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,       # 1s, 2s, 4s, 8s...
    retry_backoff_max=300,    # cap at 5 minutes
    retry_jitter=True,        # randomize to avoid thundering herd
    max_retries=5,
)
def call_llm(prompt):
    ...
```

**Exponential backoff** matters for rate-limited APIs like LLMs, since hammering them makes things worse.

## Step 11: Timeouts

Prevent a stuck task from blocking a worker forever:

```python
@app.task(soft_time_limit=60, time_limit=90)
def long_job():
    ...
```

- `soft_time_limit`: raises `SoftTimeLimitExceeded` inside your code, so you can clean up.
- `time_limit`: hard kill of the worker process after this many seconds.

Handling the soft limit:

```python
from celery.exceptions import SoftTimeLimitExceeded

@app.task(soft_time_limit=60, time_limit=90)
def long_job():
    try:
        do_heavy_work()
    except SoftTimeLimitExceeded:
        cleanup()
        raise
```

## Step 12: Idempotency and acknowledgements

Retries and crashes mean a task can run **more than once**. Design for that.

**Idempotent** means running it twice has the same effect as once. Example: "set status = done" is idempotent, but "charge the customer" is not unless you guard it.

Related settings:

```python
app.conf.task_acks_late = True              # ack AFTER the task finishes
app.conf.worker_prefetch_multiplier = 1     # fetch one task at a time
```

- By default, a worker **acknowledges** a task when it *starts*. If the worker crashes mid-task, the task is lost.
- `acks_late=True` acknowledges after finishing, so a crash means the task is redelivered. This is safer but requires idempotent tasks.
- `prefetch_multiplier=1` stops a worker from hoarding tasks, which matters when tasks are long (LLM calls).

## Step 13: Multiple queues and routing

Not all tasks are equal. Separate fast from slow:

```python
app.conf.task_routes = {
    "tasks.send_email": {"queue": "emails"},
    "tasks.generate_embeddings": {"queue": "ai_heavy"},
}
```

Run dedicated workers:

```bash
celery -A tasks worker -Q emails --concurrency=8
celery -A tasks worker -Q ai_heavy --concurrency=2
```

`-Q` selects which queues a worker listens to. This stops a flood of slow AI jobs from blocking quick emails.

## Step 14: Concurrency and worker pools

`--concurrency=N` sets how many tasks run in parallel. The **pool** decides *how*:

| Pool | Use for |
|---|---|
| `prefork` (default) | CPU-bound work, uses multiple processes |
| `threads` | I/O-bound work (HTTP calls, DB) |
| `gevent` / `eventlet` | Thousands of concurrent I/O tasks |
| `solo` | Debugging, runs in one process |

```bash
celery -A tasks worker --pool=gevent --concurrency=100
```

LLM API calls are I/O-bound (mostly waiting), so `threads` or `gevent` can handle far more concurrent calls than `prefork`.

## Step 15: Workflows (Canvas)

Celery can combine tasks into pipelines.

**Chain** runs tasks in sequence, passing each result to the next:

```python
from celery import chain
chain(fetch_doc.s(url), chunk.s(), embed.s(), save.s())()
```

`.s()` creates a **signature**, a task call "frozen" with its arguments, not yet run.

**Group** runs tasks in parallel:

```python
from celery import group
group(embed.s(chunk) for chunk in chunks)()
```

**Chord** is a group followed by a callback once all finish:

```python
from celery import chord
chord(group(embed.s(c) for c in chunks))(combine_results.s())
```

Example AI use: split a document into 50 chunks, embed them in parallel (group), then store everything (callback).

Other primitives: `chunks`, `map`, `starmap`, `link` (callback on success), `link_error` (callback on failure).

Immutable signatures (ignore the previous result) use `.si()`:

```python
chain(task_a.s(1), task_b.si(2))   # task_b ignores task_a's result
```

## Step 16: Periodic tasks with Celery Beat

Beat is a scheduler that sends tasks at set times. It's a separate process.

```python
from celery.schedules import crontab

app.conf.beat_schedule = {
    "refresh-every-5-min": {
        "task": "tasks.refresh_data",
        "schedule": 300.0,
    },
    "nightly-report": {
        "task": "tasks.make_report",
        "schedule": crontab(hour=2, minute=0),
    },
}
```

```bash
celery -A tasks beat --loglevel=info
```

Run **only one** Beat instance, or tasks will be scheduled twice.

## Step 17: Using Celery with Django

Project layout:

```
myproject/
  myproject/
    __init__.py
    celery.py
    settings.py
  myapp/
    tasks.py
```

`myproject/celery.py`:

```python
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")

app = Celery("myproject")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

`myproject/__init__.py`:

```python
from .celery import app as celery_app
__all__ = ("celery_app",)
```

`settings.py`:

```python
CELERY_BROKER_URL = "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = "redis://localhost:6379/1"
```

`myapp/tasks.py`:

```python
from celery import shared_task

@shared_task
def process_upload(upload_id):
    ...
```

- `namespace="CELERY"` means all settings start with `CELERY_`.
- `autodiscover_tasks()` finds `tasks.py` in every installed app.
- `@shared_task` works without importing the app object.

Run the worker:

```bash
celery -A myproject worker --loglevel=info
```

**Pitfall:** call `.delay()` **after** the DB transaction commits, or the worker may not find the row:

```python
from django.db import transaction
transaction.on_commit(lambda: process_upload.delay(upload.id))
```

## Step 18: Using Celery with FastAPI

```python
from fastapi import FastAPI
from celery.result import AsyncResult
from tasks import app as celery_app, generate_report

api = FastAPI()

@api.post("/reports")
def start_report(user_id: int):
    task = generate_report.delay(user_id)
    return {"task_id": task.id}

@api.get("/reports/{task_id}")
def get_status(task_id: str):
    res = AsyncResult(task_id, app=celery_app)
    return {
        "status": res.status,
        "result": res.result if res.ready() else None,
    }
```

This is the standard **submit and poll** pattern: submit returns an ID immediately, and the client polls (or you use webhooks/websockets) for the result.

## Step 19: Progress reporting

```python
@app.task(bind=True)
def process_batch(self, items):
    for i, item in enumerate(items):
        do_work(item)
        self.update_state(
            state="PROGRESS",
            meta={"done": i + 1, "total": len(items)},
        )
    return "complete"
```

Your status endpoint can then show a progress bar by reading `res.info` while the state is `PROGRESS`.

## Step 20: Monitoring with Flower

```bash
pip install flower
celery -A tasks flower
```

Opens a web dashboard at `localhost:5555` showing workers, queues, task history, failures, and letting you revoke tasks.

Useful CLI commands:

```bash
celery -A tasks inspect active      # running tasks
celery -A tasks inspect scheduled   # tasks with ETA
celery -A tasks inspect registered  # known tasks
celery -A tasks purge               # delete all waiting tasks (careful!)
```

Revoking a task:

```python
from tasks import app
app.control.revoke(task_id, terminate=True)
```

## Step 21: Error handling and best practices

1. **Pass IDs, not objects.** Fetch fresh data inside the task.
2. **Make tasks idempotent.** Assume they may run twice.
3. **Keep tasks small.** Break big jobs into chains/groups.
4. **Set timeouts and retries** for every external call.
5. **Don't block on results inside a task** (`result.get()` in a task can deadlock).
6. **Ignore results you don't need:** `@app.task(ignore_result=True)` saves memory.
7. **Use separate queues** for slow vs fast jobs.
8. **Log task IDs** so you can trace failures.
9. **Restart workers after deploying new code.** Workers keep old code in memory.
10. **Set `worker_max_tasks_per_child`** to recycle processes and avoid memory leaks (common with ML libraries):

```python
app.conf.worker_max_tasks_per_child = 100
```

Custom failure handling with a base class:

```python
from celery import Task

class BaseTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        log_error(task_id, exc)

    def on_success(self, retval, task_id, args, kwargs):
        log_ok(task_id)

@app.task(base=BaseTask)
def risky():
    ...
```

## Step 22: Production deployment

- Run workers under **systemd**, **Supervisor**, or **Docker/Kubernetes**.
- Run **one Beat** process.
- Use **Redis** for simplicity; **RabbitMQ** if you need stronger delivery guarantees.
- Scale by adding more worker processes or machines.
- Monitor queue length. A growing queue means you need more workers.

Example `docker-compose.yml`:

```yaml
services:
  redis:
    image: redis:7
  web:
    build: .
    command: uvicorn main:api --host 0.0.0.0 --port 8000
    depends_on: [redis]
  worker:
    build: .
    command: celery -A tasks worker --loglevel=info --concurrency=4
    depends_on: [redis]
  beat:
    build: .
    command: celery -A tasks beat --loglevel=info
    depends_on: [redis]
  flower:
    build: .
    command: celery -A tasks flower
    ports: ["5555:5555"]
    depends_on: [redis]
```

## Step 23: Full mini project (AI document pipeline)

`tasks.py`:

```python
from celery import Celery, chain, group, chord

app = Celery("docs", broker="redis://localhost:6379/0",
             backend="redis://localhost:6379/1")

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
)

@app.task(autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=3)
def fetch_text(url):
    # download and return text
    return "long document text ..."

@app.task
def split_chunks(text):
    return [text[i:i + 500] for i in range(0, len(text), 500)]

@app.task(autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def embed_chunk(chunk):
    # call embedding API
    return [0.1, 0.2, 0.3]

@app.task
def save_all(embeddings):
    # store vectors in DB
    return {"saved": len(embeddings)}

@app.task
def process_document(url):
    text = fetch_text(url)
    chunks = split_chunks(text)
    job = chord(group(embed_chunk.s(c) for c in chunks))(save_all.s())
    return job.id
```

Run it:

```bash
celery -A tasks worker --loglevel=info
```

```python
from tasks import process_document
process_document.delay("https://example.com/doc.txt")
```

Flow: fetch, split into chunks, embed all chunks in parallel (group), then save everything once all are done (chord callback).

## Step 24: Common mistakes and troubleshooting

| Problem | Likely cause / fix |
|---|---|
| Task stays `PENDING` forever | Worker not running, wrong broker URL, task not registered, or unknown ID |
| `NotRegistered` error | Worker did not import the module; check `-A` and `autodiscover_tasks` |
| Old code running | Worker not restarted after deploy |
| `EncodeError` / not serializable | Passed an object (model, datetime, file) instead of JSON-safe data |
| Task runs twice | Normal with retries or `acks_late`; make it idempotent |
| Memory keeps growing | Use `worker_max_tasks_per_child`, `ignore_result=True` |
| Django row not found in task | `.delay()` called before commit; use `transaction.on_commit` |
| Deadlock | Calling `.get()` inside another task |
| Beat tasks fire twice | More than one Beat instance running |
| One slow job blocks others | Use separate queues and `prefetch_multiplier=1` |

## Step 25: Quick recap and practice path

| Concept | One-line meaning |
|---|---|
| Task | A function the worker runs |
| Broker | Queue holding pending tasks |
| Worker | Process executing tasks |
| Backend | Stores results |
| `delay` / `apply_async` | Send a task |
| Retry | Re-run on failure, ideally with backoff |
| `acks_late` | Redeliver tasks if a worker crashes |
| Queue / route | Separate task types |
| Pool | How concurrency is achieved |
| Chain / group / chord | Sequence / parallel / parallel + callback |
| Beat | Cron-like scheduler |
| Flower | Monitoring dashboard |

**Practice path:**

1. Run the `add` example end to end.
2. Add a task that fails randomly and watch retries in the worker logs.
3. Build a chain: fetch text, summarize with an LLM, save result.
4. Add a second queue and a dedicated worker.
5. Add a Beat schedule and open Flower.
6. Build the full mini project in Step 23 and run it with Docker Compose.