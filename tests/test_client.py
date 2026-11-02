import pytest

from vndb.client import ResponseCache, VNDBClient, VNDBError
from vndb.tags import Tag, TagIndex


class FakeResp:
    def __init__(self, status, data=None, headers=None, text=""):
        self.status_code = status
        self._data = data
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        return self.responses.pop(0)


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def make_client(responses, **cfg_over):
    from settings import load_config
    cfg = load_config()
    cfg.update(cfg_over)
    clock = FakeClock()
    sess = FakeSession(responses)
    client = VNDBClient(cfg, session=sess, cache=ResponseCache(":memory:", 3600),
                        sleep=clock.sleep, clock=clock.now)
    return client, sess, clock


def test_user_agent_set():
    client, sess, _ = make_client([])
    assert sess.headers["User-Agent"].startswith("yoru-no-toshokan")


def test_throttle_spaces_requests():
    ok = FakeResp(200, {"results": [], "more": False})
    client, sess, clock = make_client([ok, ok, ok], min_request_interval=1.5)
    for i in range(3):
        client.query("vn", ["id", "=", f"v{i}"], use_cache=False)
    assert len(sess.calls) == 3
    assert clock.sleeps == [1.5, 1.5]


def test_429_retries_then_succeeds():
    client, sess, clock = make_client(
        [FakeResp(429), FakeResp(429, headers={"Retry-After": "7"}),
         FakeResp(200, {"results": [{"id": "v17"}], "more": False})]
    )
    data = client.query("vn", ["id", "=", "v17"])
    assert data["results"][0]["id"] == "v17"
    assert len(sess.calls) == 3
    assert 2.0 in clock.sleeps and 7.0 in clock.sleeps  # backoff + Retry-After


def test_429_gives_up():
    client, sess, _ = make_client([FakeResp(429)] * 3, max_retries=2)
    with pytest.raises(VNDBError):
        client.query("vn")
    assert len(sess.calls) == 3


def test_400_raises_immediately():
    client, sess, _ = make_client([FakeResp(400, text="bad filter")])
    with pytest.raises(VNDBError, match="bad filter"):
        client.query("vn", ["nope", "=", 1])
    assert len(sess.calls) == 1


def test_cache_hit_skips_http():
    client, sess, _ = make_client([FakeResp(200, {"results": [{"id": "v1"}], "more": False})])
    a = client.query("vn", ["id", "=", "v1"], fields="title")
    b = client.query("vn", ["id", "=", "v1"], fields="title")
    assert a == b and len(sess.calls) == 1


def test_cache_ttl_expiry():
    cache = ResponseCache(":memory:", ttl_seconds=-1)
    cache.set("k", {"x": 1})
    assert cache.get("k") is None


def test_query_all_follows_more():
    client, sess, _ = make_client([
        FakeResp(200, {"results": [{"id": "g1"}], "more": True}),
        FakeResp(200, {"results": [{"id": "g2"}], "more": False}),
    ])
    ids = [r["id"] for r in client.query_all("tag", fields="name")]
    assert ids == ["g1", "g2"]
    assert [c[1]["page"] for c in sess.calls] == [1, 2]


def test_tag_index_lookup_prefers_vn_count():
    idx = TagIndex.build([
        Tag("g1", "Fantasy", ["fantasy world"], "cont", True, True, 100),
        Tag("g2", "Fictional World", ["Fantasy World"], "cont", True, True, 500),
    ])
    assert idx.lookup("FANTASY").id == "g1"
    assert idx.lookup("fantasy world").id == "g2"
    assert idx.by_name("fictional world").id == "g2"


@pytest.mark.live
def test_live_known_vn():
    client = VNDBClient()
    data = client.query("vn", ["id", "=", "v17"], fields="title, rating")
    assert data["results"][0]["title"] == "Ever17 -the out of infinity-"
