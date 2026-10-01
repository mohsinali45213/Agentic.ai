"""
Setup:
    pip install redis fakeredis

Run everything:
    python redis_complete_guide.py

Run one section only (example: strings and hashes):
    python redis_complete_guide.py strings hashes

Sections available:
    strings, ttl, lists, hashes, sets, sorted_sets, keys, json, cache,
    pipeline, pubsub, streams, recipes, fastapi_demo

HOW THIS WORKS
--------------
`fakeredis` is a pure-Python, in-memory imitation of Redis. The commands and
behaviour match real Redis for everything taught here, so you can learn
without installing a server.

To use a REAL Redis server later, change only the `get_client()` function
at the top (see the instructions inside it). Everything else stays the same.

LIMITATION: fakeredis lives inside ONE Python process. Two separate processes
(for example a web server and a Celery worker) will NOT share its data.
Real Redis is shared across processes. That is the main reason it exists.

CONCEPT MAP
-----------
String      basic value, also atomic counters
TTL         auto-expiry, the heart of caching
List        ordered, push/pop at both ends, simple queues
Hash        mini dictionary inside a key, good for objects
Set         unique, unordered values, set math
Sorted set  unique values with scores, leaderboards and rate limits
Pipeline    batch many commands into one round trip
Transaction MULTI/EXEC, commands run together (no rollback)
Pub/Sub     real-time fire-and-forget messages
Stream      durable append-only log with consumer groups
"""

import hashlib
import json
import sys
import time
import uuid


# ---------------------------------------------------------------------------
# CLIENT SETUP
# ---------------------------------------------------------------------------
def get_client():
    """
    Returns a Redis client.

    LEARNING MODE (default): fakeredis, nothing to install except pip packages.

    REAL SERVER MODE: comment out the fakeredis lines and use:

        import redis
        return redis.Redis(host="localhost", port=6379, decode_responses=True)
        # or from a URL (password / TLS):
        # return redis.from_url("redis://:password@host:6379/0", decode_responses=True)
        # TLS URLs start with rediss://

    decode_responses=True makes Redis return Python str instead of bytes.
    Create the client ONCE at startup and reuse it (it manages a connection
    pool internally). Do not create a new client for every request.
    """
    import fakeredis

    return fakeredis.FakeRedis(decode_responses=True)


r = get_client()


def title(text):
    print("\n" + "=" * 70)
    print(text)
    print("=" * 70)


# ---------------------------------------------------------------------------
# STEP 1: STRINGS
# ---------------------------------------------------------------------------
def demo_strings():
    """
    A string is the basic Redis value. It can hold text, numbers, JSON or
    binary data (up to 512 MB).

    Naming convention: use colons to namespace keys, for example
    user:42:profile or cache:product:99.
    """
    title("STEP 1: STRINGS")

    r.set("user:1:name", "Akbar")
    print("get:", r.get("user:1:name"))

    # Set and get many keys in one call
    r.mset({"a": "1", "b": "2", "c": "3"})
    print("mget:", r.mget("a", "b", "c"))

    print("exists a:", r.exists("a"))  # 1 means yes
    r.delete("a")
    print("exists a after delete:", r.exists("a"))  # 0

    # ATOMIC COUNTERS
    # incr is atomic: even with 1000 clients at once, no increments are lost.
    # That is why Redis is the standard tool for counters.
    r.set("views", 0)
    r.incr("views")  # 1
    r.incrby("views", 10)  # 11
    r.decr("views")  # 10
    print("views:", r.get("views"))

    # append and length
    r.set("greeting", "Hello")
    r.append("greeting", " World")
    print("greeting:", r.get("greeting"), "| length:", r.strlen("greeting"))


# ---------------------------------------------------------------------------
# STEP 2: EXPIRY (TTL)
# ---------------------------------------------------------------------------
def demo_ttl():
    """
    Redis can auto-delete keys after a time. This is what makes it a great
    cache: old data cleans itself up.

    ttl() returns: seconds left, -1 if no expiry, -2 if the key is gone.
    """
    title("STEP 2: EXPIRY (TTL)")

    r.set("otp:9876", "123456", ex=300)  # expires in 300 seconds
    print("ttl:", r.ttl("otp:9876"))

    r.set("temp", "x")
    print("ttl without expiry:", r.ttl("temp"))  # -1
    r.expire("temp", 60)  # add an expiry later
    print("ttl after expire:", r.ttl("temp"))
    r.persist("temp")  # remove the expiry
    print("ttl after persist:", r.ttl("temp"))

    # Milliseconds precision
    r.set("short", "v", px=1500)  # 1500 ms
    print("pttl (ms):", r.pttl("short"))

    # NX = only set if the key does NOT exist. Building block for locks.
    print("first lock:", r.set("lock:job1", "worker-1", nx=True, ex=30))  # True
    print("second lock:", r.set("lock:job1", "worker-2", nx=True, ex=30))  # None
    # XX = only set if the key DOES exist (update only).

    # Real expiry in action
    r.set("flash", "gone soon", ex=1)
    print("before sleep:", r.get("flash"))
    time.sleep(1.2)
    print("after sleep:", r.get("flash"))  # None


# ---------------------------------------------------------------------------
# STEP 3: LISTS
# ---------------------------------------------------------------------------
def demo_lists():
    """
    An ordered collection of strings, fast at both ends.
    Use cases: simple job queues, recent-activity feeds.
    The push/pop pattern is how Redis-backed queues (including Celery's
    broker) work: producers push, workers pop.
    """
    title("STEP 3: LISTS")

    r.delete("queue")
    r.lpush("queue", "task1")  # push to the left
    r.rpush("queue", "task2", "task3")  # push to the right
    print("all:", r.lrange("queue", 0, -1))  # 0 to -1 means everything
    print("lpop:", r.lpop("queue"))
    print("rpop:", r.rpop("queue"))
    print("length:", r.llen("queue"))

    # "Last N items" feed: push new items, then trim to keep only N
    r.delete("recent")
    for item in ["a", "b", "c", "d", "e"]:
        r.lpush("recent", item)
        r.ltrim("recent", 0, 2)  # keep only the 3 newest
    print("recent 3:", r.lrange("recent", 0, -1))

    # Blocking pop: wait up to N seconds for an item (a worker idle loop).
    r.delete("jobs")
    print("blpop on empty list (waits 1s):", r.blpop("jobs", timeout=1))  # None
    r.rpush("jobs", "job-1")
    print("blpop with item:", r.blpop("jobs", timeout=1))


# ---------------------------------------------------------------------------
# STEP 4: HASHES
# ---------------------------------------------------------------------------
def demo_hashes():
    """
    A dictionary stored inside one key (field -> value).
    Better than a JSON string when you want to read or update a SINGLE field
    without rewriting the whole object.
    """
    title("STEP 4: HASHES")

    r.delete("user:1")
    r.hset("user:1", mapping={"name": "Akbar", "role": "Engineer", "age": 24})
    print("one field:", r.hget("user:1", "name"))
    print("all fields:", r.hgetall("user:1"))
    print("some fields:", r.hmget("user:1", ["name", "role"]))

    r.hincrby("user:1", "age", 1)
    print("age after hincrby:", r.hget("user:1", "age"))

    r.hdel("user:1", "role")
    print("role exists:", r.hexists("user:1", "role"))
    print("keys:", r.hkeys("user:1"), "| count:", r.hlen("user:1"))


# ---------------------------------------------------------------------------
# STEP 5: SETS
# ---------------------------------------------------------------------------
def demo_sets():
    """
    Unordered collection of UNIQUE values.
    Use cases: unique visitors, tags, "who liked this", mutual friends.
    """
    title("STEP 5: SETS")

    r.delete("tags", "a", "b")
    r.sadd("tags", "python", "redis", "ai")
    r.sadd("tags", "python")  # duplicate, ignored
    print("members:", r.smembers("tags"))
    print("is redis a member:", r.sismember("tags", "redis"))
    print("count:", r.scard("tags"))
    r.srem("tags", "ai")
    print("after remove:", r.smembers("tags"))

    # SET MATH
    r.sadd("a", 1, 2, 3)
    r.sadd("b", 2, 3, 4)
    print("intersection:", r.sinter("a", "b"))  # in both
    print("union:", r.sunion("a", "b"))  # in either
    print("difference a-b:", r.sdiff("a", "b"))  # in a only

    # Unique visitor counting
    for visitor in ["u1", "u2", "u1", "u3", "u2"]:
        r.sadd("visitors:today", visitor)
    print("unique visitors:", r.scard("visitors:today"))  # 3


# ---------------------------------------------------------------------------
# STEP 6: SORTED SETS
# ---------------------------------------------------------------------------
def demo_sorted_sets():
    """
    Like a set, but every member has a SCORE and stays sorted by it.
    Use cases: leaderboards, priority queues, sliding-window rate limits,
    scheduled jobs (score = timestamp).
    """
    title("STEP 6: SORTED SETS")

    r.delete("leaderboard")
    r.zadd("leaderboard", {"alice": 100, "bob": 250, "carol": 180})

    print("ascending:", r.zrange("leaderboard", 0, -1, withscores=True))
    print("top 2:", r.zrevrange("leaderboard", 0, 1, withscores=True))

    r.zincrby("leaderboard", 200, "alice")  # alice now 300
    print("alice rank from top (0 = best):", r.zrevrank("leaderboard", "alice"))
    print("alice score:", r.zscore("leaderboard", "alice"))
    print("scores 100..200:", r.zrangebyscore("leaderboard", 100, 200))
    print("count:", r.zcard("leaderboard"))

    # Sliding window rate limiter idea: score = timestamp
    r.delete("rate:sliding:user1")
    now = time.time()
    for i in range(3):
        r.zadd("rate:sliding:user1", {f"req-{i}": now - i})
    r.zremrangebyscore("rate:sliding:user1", 0, now - 60)  # drop older than 60s
    print("requests in last 60s:", r.zcard("rate:sliding:user1"))


# ---------------------------------------------------------------------------
# STEP 7: KEY MANAGEMENT
# ---------------------------------------------------------------------------
def demo_keys():
    """
    ALWAYS use scan_iter, never keys("*"), on a real server.
    KEYS scans everything in one blocking call and freezes other clients.
    SCAN walks the keyspace in small batches.
    """
    title("STEP 7: KEY MANAGEMENT")

    r.set("demo:1", "x")
    r.set("demo:2", "y")
    r.hset("demo:hash", mapping={"f": "v"})

    print("scan_iter demo:*:", sorted(r.scan_iter(match="demo:*", count=100)))
    print("type of demo:1:", r.type("demo:1"))
    print("type of demo:hash:", r.type("demo:hash"))

    r.rename("demo:1", "demo:renamed")
    print("exists demo:1:", r.exists("demo:1"), "| demo:renamed:", r.exists("demo:renamed"))
    print("total keys in this DB:", r.dbsize())

    # r.flushdb() deletes EVERYTHING in the current DB. Dangerous on real data.

    # Redis has numbered databases 0..15 (db=0 is default). Celery examples
    # often use /0 for the broker and /1 for results. For serious setups,
    # prefer separate Redis instances instead of numbered DBs.


# ---------------------------------------------------------------------------
# STEP 8: STORING JSON
# ---------------------------------------------------------------------------
def demo_json():
    """
    Redis stores strings, so serialize Python dicts to JSON on the way in
    and parse them on the way out. Very common in Python apps.
    """
    title("STEP 8: STORING JSON")

    user = {"id": 1, "name": "Akbar", "skills": ["python", "redis"]}
    r.set("cache:user:1", json.dumps(user), ex=300)

    data = json.loads(r.get("cache:user:1"))
    print("loaded:", data)
    print("skills:", data["skills"])


# ---------------------------------------------------------------------------
# STEP 9: CACHING PATTERNS
# ---------------------------------------------------------------------------
def slow_db_query(product_id):
    time.sleep(0.5)  # pretend this is a slow database
    return {"id": product_id, "name": f"Product {product_id}"}


def get_product(product_id):
    """
    CACHE-ASIDE (the most common pattern):
      1. Check the cache.
      2. On a miss, load from the source (DB / API).
      3. Store in cache with a TTL.
      4. Return.
    """
    key = f"cache:product:{product_id}"
    cached = r.get(key)
    if cached:
        return json.loads(cached)  # cache hit

    product = slow_db_query(product_id)  # cache miss
    r.set(key, json.dumps(product), ex=300)
    return product


def fake_llm_call(prompt):
    time.sleep(0.5)  # pretend this is a slow, paid API call
    return f"Answer to: {prompt}"


def cached_llm(prompt):
    """
    AI use case: cache LLM responses by prompt hash. Repeated prompts become
    instant and free. Replace fake_llm_call with your Claude/Gemini call.
    """
    key = "llm:" + hashlib.sha256(prompt.encode()).hexdigest()
    hit = r.get(key)
    if hit:
        return hit
    answer = fake_llm_call(prompt)
    r.set(key, answer, ex=86400)  # keep for a day
    return answer


def demo_cache():
    """
    OTHER PATTERNS
      Write-through : write to cache and DB together.
      Write-behind  : write to cache, persist to DB later.
      Invalidate    : r.delete(key) whenever the source data changes.

    PROBLEMS TO KNOW
      Cache stampede   : a hot key expires and thousands of requests hit the
                         DB at once. Fix with locks, jittered TTLs, early refresh.
      Stale data       : choose TTLs that match how fresh data must be.
      Cache penetration: requests for keys that never exist. Cache the
                         "not found" result briefly.
    """
    title("STEP 9: CACHING PATTERNS")

    r.delete("cache:product:1")
    t = time.time()
    get_product(1)
    print(f"first call (miss):  {time.time() - t:.3f}s")
    t = time.time()
    get_product(1)
    print(f"second call (hit):  {time.time() - t:.3f}s")

    t = time.time()
    cached_llm("What is Redis?")
    print(f"LLM first call:     {time.time() - t:.3f}s")
    t = time.time()
    print("LLM second call:   ", cached_llm("What is Redis?"))
    print(f"LLM second timing:  {time.time() - t:.3f}s")

    # Invalidate when data changes
    r.delete("cache:product:1")
    print("cache cleared:", r.get("cache:product:1"))


# ---------------------------------------------------------------------------
# STEP 10: PIPELINES AND TRANSACTIONS
# ---------------------------------------------------------------------------
def demo_pipeline():
    """
    PIPELINE: each command normally costs one network round trip. A pipeline
    batches many commands into one trip. On a real server this can be 10x to
    100x faster than separate calls.

    TRANSACTION (MULTI/EXEC): commands run together without other clients
    interleaving. Redis transactions have NO ROLLBACK: if one command errors,
    the others still run.

    WATCH gives optimistic locking: abort if a watched key changed.
    """
    title("STEP 10: PIPELINES AND TRANSACTIONS")

    pipe = r.pipeline(transaction=False)
    for i in range(1000):
        pipe.set(f"pipe:key:{i}", i)
    results = pipe.execute()
    print("pipelined sets:", len(results))

    r.set("a", 0)
    r.set("b", 0)
    pipe = r.pipeline(transaction=True)
    pipe.incr("a")
    pipe.incr("b")
    print("transaction results:", pipe.execute())

    # Optimistic locking with WATCH: safe "read then update"
    r.set("balance", 100)
    with r.pipeline() as pipe:
        while True:
            try:
                pipe.watch("balance")  # abort if changed by someone else
                current = int(pipe.get("balance"))
                pipe.multi()
                pipe.set("balance", current - 30)
                pipe.execute()
                break
            except Exception:  # redis.WatchError, retry on conflict
                continue
    print("balance after safe update:", r.get("balance"))


# ---------------------------------------------------------------------------
# STEP 11: PUB/SUB
# ---------------------------------------------------------------------------
def demo_pubsub():
    """
    Publishers send to a CHANNEL, subscribers receive instantly.
    Pub/Sub is FIRE-AND-FORGET: an offline subscriber misses the message.
    For durable messaging use Streams (next step).
    """
    title("STEP 11: PUB/SUB")

    pubsub = r.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe("notifications")

    r.publish("notifications", "New order received")
    r.publish("notifications", "Payment confirmed")

    for _ in range(2):
        msg = pubsub.get_message(timeout=1)
        if msg:
            print("received:", msg["data"])

    pubsub.close()

    # In a real app the subscriber runs in a separate process/thread:
    #   for msg in pubsub.listen():
    #       handle(msg)


# ---------------------------------------------------------------------------
# STEP 12: STREAMS
# ---------------------------------------------------------------------------
def demo_streams():
    """
    An append-only log with persistence and CONSUMER GROUPS: a lightweight
    Kafka. Multiple workers share the load, and each message is acknowledged
    (xack) when done, so nothing is lost if a worker crashes.
    """
    title("STEP 12: STREAMS")

    r.delete("events")
    r.xadd("events", {"type": "signup", "user": "42"})
    r.xadd("events", {"type": "login", "user": "42"})
    r.xadd("events", {"type": "purchase", "user": "7"})
    print("length:", r.xlen("events"))
    print("all entries:", r.xrange("events"))

    # Consumer group: workers pull messages and acknowledge them
    r.xgroup_create("events", "workers", id="0", mkstream=True)
    messages = r.xreadgroup("workers", "worker1", {"events": ">"}, count=10)
    for _stream, entries in messages:
        for msg_id, fields in entries:
            print("worker1 processing:", msg_id, fields)
            r.xack("events", "workers", msg_id)

    print("pending after ack:", r.xpending("events", "workers")["pending"])


# ---------------------------------------------------------------------------
# STEP 13: PRACTICAL RECIPES
# ---------------------------------------------------------------------------
def allowed(user_id, limit=5, window=60):
    """FIXED-WINDOW RATE LIMITER: at most `limit` requests per `window` seconds."""
    key = f"rate:{user_id}"
    count = r.incr(key)
    if count == 1:
        r.expire(key, window)
    return count <= limit


def acquire_lock(name, ttl=30):
    """Returns a token if the lock was acquired, otherwise None."""
    token = str(uuid.uuid4())
    if r.set(f"lock:{name}", token, nx=True, ex=ttl):
        return token
    return None


def release_lock(name, token):
    """
    Only release if we still own the lock. NOTE: this get-then-delete is not
    fully atomic. In production use a Lua script, or redis-py's built-in
    r.lock("name", timeout=30) which handles ownership safely.
    """
    if r.get(f"lock:{name}") == token:
        r.delete(f"lock:{name}")


def demo_recipes():
    title("STEP 13: PRACTICAL RECIPES")

    # 1. Rate limiter
    r.delete("rate:user1")
    print("rate limiter (limit 5):")
    for i in range(1, 8):
        print(f"  request {i}: {'allowed' if allowed('user1') else 'BLOCKED'}")

    # 2. Distributed lock
    token = acquire_lock("report")
    print("lock acquired:", bool(token))
    print("second attempt:", acquire_lock("report"))  # None
    release_lock("report", token)
    print("after release:", bool(acquire_lock("report")))
    r.delete("lock:report")

    # 3. Session store
    r.hset("session:abc123", mapping={"user_id": 1, "role": "admin"})
    r.expire("session:abc123", 3600)
    print("session:", r.hgetall("session:abc123"), "| ttl:", r.ttl("session:abc123"))

    # 4. Leaderboard
    r.delete("game:scores")
    for player, pts in [("alice", 10), ("bob", 30), ("alice", 25), ("carol", 5)]:
        r.zincrby("game:scores", pts, player)
    print("top players:", r.zrevrange("game:scores", 0, 2, withscores=True))

    # 5. Simple job queue (producer / worker)
    r.delete("job_queue")
    r.rpush("job_queue", json.dumps({"task": "send_email", "to": "a@b.com"}))
    r.rpush("job_queue", json.dumps({"task": "resize_image", "id": 9}))
    while True:
        item = r.lpop("job_queue")
        if item is None:
            break
        print("worker got job:", json.loads(item))


# ---------------------------------------------------------------------------
# STEP 14: FASTAPI EXAMPLE (printed, run it separately)
# ---------------------------------------------------------------------------
FASTAPI_EXAMPLE = '''
# Save as main.py, then: pip install fastapi uvicorn redis fakeredis
# Run with:  uvicorn main:app --reload
import json
import fakeredis
from fastapi import FastAPI

app = FastAPI()
r = fakeredis.FakeRedis(decode_responses=True)   # create ONCE at startup

@app.get("/product/{product_id}")
def product(product_id: int):
    key = f"cache:product:{product_id}"
    cached = r.get(key)
    if cached:
        return {"source": "cache", "data": json.loads(cached)}

    data = {"id": product_id, "name": f"Product {product_id}"}
    r.set(key, json.dumps(data), ex=60)
    return {"source": "db", "data": data}

# Note: with --reload or multiple workers each process has its OWN fakeredis.
# With real Redis they all share the same data.
'''


def demo_fastapi():
    title("STEP 14: FASTAPI EXAMPLE")
    print(FASTAPI_EXAMPLE)


# ---------------------------------------------------------------------------
# REFERENCE NOTES (concepts for a real server)
# ---------------------------------------------------------------------------
NOTES = """
PERSISTENCE (real server)
  RDB   periodic snapshots; fast restart, may lose recent writes
  AOF   logs every write; more durable, bigger files
  None  pure cache; data lost on restart
  Use AOF if Redis holds a job queue or important state.

EVICTION when memory is full (maxmemory-policy)
  noeviction   reject writes
  allkeys-lru  evict least recently used (ideal for caches)
  allkeys-lfu  evict least frequently used
  volatile-lru evict LRU only among keys that have a TTL
  If Redis is your CELERY BROKER, use a separate instance with noeviction
  so queued tasks are never evicted.

SCALING
  Replication : primary copies data to replicas (read scaling, backup)
  Sentinel    : automatic failover to a replica
  Cluster     : data sharded across nodes (16384 hash slots)
  A managed service (Upstash, Redis Cloud, ElastiCache) handles this for you.

SECURITY
  Never expose Redis to the public internet.
  Set a password or ACLs. Use TLS (rediss://) across networks.
  Disable dangerous commands (FLUSHALL, CONFIG, KEYS) in production.

REAL SERVER WITHOUT DOCKER
  Windows : WSL (sudo apt install redis-server) or Memurai
  Ubuntu  : sudo apt install redis-server && redis-server
  macOS   : brew install redis && redis-server
  Cloud   : free instance from Upstash or Redis Cloud gives you a URL

CELERY WITHOUT A REDIS SERVER
  A Celery worker is a separate process, so it cannot share fakeredis.
  For practice use broker="filesystem://" (cross-process) or
  broker="memory://" (same process only). Switch to a real Redis URL later.
"""


def demo_notes():
    title("REFERENCE NOTES")
    print(NOTES)


# ---------------------------------------------------------------------------
# RUNNER
# ---------------------------------------------------------------------------
SECTIONS = {
    "strings": demo_strings,
    "ttl": demo_ttl,
    "lists": demo_lists,
    "hashes": demo_hashes,
    "sets": demo_sets,
    "sorted_sets": demo_sorted_sets,
    "keys": demo_keys,
    "json": demo_json,
    "cache": demo_cache,
    "pipeline": demo_pipeline,
    "pubsub": demo_pubsub,
    "streams": demo_streams,
    "recipes": demo_recipes,
    "fastapi_demo": demo_fastapi,
    "notes": demo_notes,
}


def main():
    wanted = sys.argv[1:] or list(SECTIONS)
    for name in wanted:
        if name not in SECTIONS:
            print(f"Unknown section '{name}'. Choose from: {', '.join(SECTIONS)}")
            return
    for name in wanted:
        SECTIONS[name]()
    print("\nDone.")


if __name__ == "__main__":
    main()