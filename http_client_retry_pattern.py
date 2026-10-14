HTTP Clients, Sessions, Adapters & Transports — A Complete Guide
(Based on Python's requests library, with comparison to httpx)

1. The Big Picture
Every HTTP library, no matter the language, follows the same layered architecture:

code
Copy
request.get()          ← convenience function (one-shot)
    ↓
requests.Session()     ← client that holds config + state
    ↓
HTTPAdapter            ← the "transport" — manages connections to hosts
    ↓
urllib3                ← does the actual socket work, pooling, retries
    ↓
http.client / sockets  ← raw TCP + HTTP protocol
Each layer answers a different question:

Layer	Question it answers
Convenience function	"How do I do a quick one-off request?"
Session / Client	"How do I remember cookies, headers, auth between requests?"
Adapter / Transport	"How do bytes actually travel over the network?"
Pool	"How do I avoid re-opening connections every time?"
Sockets	"What is the actual bytes-on-the-wire protocol?"
2. What is a "Client"?
A client is an object that remembers things between requests.

2.1 The stateless one-shot call
A single requests.get() call is stateless — build, send, forget:

python
Copy
import requests
resp = requests.get("https://api.com/users")
# Internally: creates a temp Session → uses it → throws it away
2.2 The Session — a persistent client
A Session is a persistent client that holds configuration and state:

python
Copy
s = requests.Session()
s.headers.update({"Authorization": "Bearer xyz"})  # applies to ALL requests
s.cookies   # persists cookies across requests (like a browser)

resp = s.get("https://api.com/users")
resp = s.post("https://api.com/posts", json={...})
Key insight: requests.get() is just a shortcut. Under the hood it literally creates a temporary Session, calls session.get(), and discards it. The Session is the "real" client.

2.3 Why does the Session matter? — Connection reuse
Every HTTP request needs a TCP connection (and usually a TLS handshake). That's expensive (~100ms+ each time). HTTP supports keep-alive: reuse the same connection for multiple requests.

The Session delegates connection management to the adapter.

3. The HTTPAdapter — the "Transport"
An adapter (transport) is the layer that answers:

"Given a prepared request, how do I actually send bytes over the network and get a response back?"
Division of responsibility
Component	Role	Handles
Session	Policy	Cookies, auth, headers, redirects, hooks
Adapter	Mechanics	Connection pooling, keep-alive, retries at socket level
Mounting — routing by scheme
Adapters are mounted per URL prefix (scheme):

python
Copy
s = requests.Session()
s.mount("https://", HTTPAdapter(pool_connections=10, pool_maxsize=10))
https:// requests go to one adapter
http:// requests go to another (a default HTTPAdapter is mounted automatically)
You can mount custom adapters on any prefix
Custom adapters — the plugin system
This is exactly how the ecosystem plugs in behavior:

python
Copy
s = requests.Session()
s.mount("https://", MyCustomAdapter())  # https goes through YOURS
s.mount("http://", HTTPAdapter())       # http stays builtin
Use cases: mock adapters for testing, retry adapters, caching adapters, proxy adapters.

⚠️ Important limitation: You cannot plug an async adapter into requests.Session. The Session's code is synchronous top-to-bottom — it will never await anything. The adapter interface is sync: send(request) -> response. Async requires the entire call chain to be async, which is why it needs a different library (see httpx).
4. The Connection Pool — per host, not per session
Inside the adapter lives urllib3's PoolManager:

code
Copy
Session
 └── HTTPAdapter (mounted on "https://")
      └── PoolManager
           ├── pool for "api.com"  → [conn1, conn2, ...]  (idle, reusable)
           └── pool for "cdn.com"  → [conn1]
Two different keys at two different levels
code
Copy
mount()      → maps SCHEME prefix to adapter    ("https://" → adapter A)
pool inside  → maps HOST:PORT to connection pool ("api.com:443" → [sockets...])
The adapter doesn't magically "remember" connections per domain — its internal PoolManager keeps a dict like {("api.com", 443): [sockets...]}.

Key facts:

Connections (sockets) are opened per host:port, NOT per session.
Sockets belong to the adapter/pool, not to the Session object.
Two separate Sessions each have their own adapters → their own pools → no sharing between Sessions by default.
Request lifecycle through the pool
Adapter asks the pool: "give me a free connection to api.com"
If a keep-alive connection exists → reuse it. If not → open new (TCP + TLS handshake).
Request sent, response received.
Connection returned to the pool (not closed!) for the next request.
5. Step-by-Step: What Happens on s.get(url)
python
Copy
s.get("https://api.com/users", params={"id": 5})
Request building — s.get() builds a Request object: method, URL, headers, params.
Prepare — creates a PreparedRequest: params merged into URL, Session headers merged in, auth added, cookies attached, body encoded. Now it's fully final.
Send — Session picks the adapter via mount() prefix match (https://).
Adapter gets a connection from the urllib3 pool (reuse existing or new TCP+TLS handshake).
Bytes go on the wire — request line, headers, body.
Server responds — status + headers + streamed body.
Adapter builds a Response object, returns it.
Session post-processing — cookies saved, redirects followed (loops back to step 2), hooks run, history recorded.
Connection returned to the pool.
6. Conceptual Summary
Concept	Analogy	Role
requests.get()	taxi ride	one-shot, no memory
Session	your personal driver	remembers cookies, headers, config
HTTPAdapter	the car's engine/transmission	how bytes actually travel
Pool (urllib3)	fleet of idling cars	reuse connections, avoid re-handshaking
mount()	assigning vehicles to roads	route URL prefixes to transports
7. Sessions & Mounts = Mostly Configuration ✅
Session = config + state (headers, auth, cookies, hooks, adapter routing)
Adapter = transport + connection lifecycle
That's the entire design philosophy.

8. httpx — Same Theory, Modernized
httpx follows the exact same conceptual architecture, with renamed layers — plus first-class async support.

Layer comparison
requests	httpx
requests.get()	httpx.get() (one-shot)
Session	httpx.Client (sync) / AsyncClient (async)
HTTPAdapter	BaseTransport / AsyncBaseTransport
mount("https://", ...)	mounts={"https://": transport}
urllib3 pool	httpcore pool
Code comparison
python
Copy
import httpx

# Sync — same theory as requests.Session
with httpx.Client() as client:
    client.get("https://api.com")

# Async — same theory, whole chain is async
async with httpx.AsyncClient() as client:
    await client.get("https://api.com")
What's different in httpx
Both sync and async transports exist as first-class citizens (requests is sync-only).
No urllib3 dependency — it uses httpcore underneath.
Custom transports plug in the same way:
python
Copy
transport = MyCustomTransport()
client = httpx.Client(
    transport=transport,
    mounts={"https://": transport, "http://": httpx.HTTPTransport()}
)
The universal pattern
Client (config/state) → Transport/Adapter (connection pool, per-host) → Raw sockets (per host:port, not per session)
This pattern is not Python-specific — it's universal:

Language	Client	Transport/Pool
Python (requests)	Session	HTTPAdapter + urllib3
Python (httpx)	Client / AsyncClient	BaseTransport + httpcore
Go	http.Client	http.Transport
Java	HttpClient	connection pool internals

