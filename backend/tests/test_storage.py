"""SupabaseStorage.put retries brief network failures. A fake bucket stands in for Supabase."""

import httpx
import pytest
from storage3.exceptions import StorageApiError

from app.storage import SupabaseStorage


class FlakyBucket:
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0
        self.stored = []

    def upload(self, path, data, options):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        self.stored.append(path)


class FakeClient:
    def __init__(self, bucket):
        self.storage = type("S", (), {"from_": lambda self, name: bucket})()


def make(errors, attempts=4):
    bucket = FlakyBucket(errors)
    pauses = []
    store = SupabaseStorage(FakeClient(bucket), "recon-files", "https://x.supabase.co", attempts=attempts, backoff=0.5, sleep=pauses.append)
    return store, bucket, pauses


def test_server_disconnected_is_retried_with_growing_pauses_then_succeeds():
    store, bucket, pauses = make([httpx.RemoteProtocolError("Server disconnected")] * 2)
    store.put("cycles/a/b/c.pdf", b"x", "application/pdf")
    assert bucket.calls == 3 and bucket.stored == ["cycles/a/b/c.pdf"]
    assert pauses == [0.5, 1.0]


def test_gives_up_after_the_last_attempt_with_the_original_error():
    store, bucket, pauses = make([httpx.ReadTimeout("slow")] * 4, attempts=4)
    with pytest.raises(httpx.ReadTimeout):
        store.put("p", b"x", "application/pdf")
    assert bucket.calls == 4 and len(pauses) == 3


def test_an_already_exists_answer_on_retry_means_the_first_attempt_arrived():
    store, bucket, _ = make([httpx.RemoteProtocolError("Server disconnected"), StorageApiError("Duplicate", "Duplicate", 409)])
    store.put("p", b"x", "application/pdf")  # no exception
    assert bucket.calls == 2


class ListingBucket:
    """Folder listing like Supabase: folders have id None, files have an id."""

    def __init__(self, tree):
        self.tree = tree  # path -> list of entries
        self.removed = []
        self.list_calls = []

    def list(self, path, options):
        self.list_calls.append((path, options["offset"]))
        entries = self.tree.get(path, [])
        return entries[options["offset"] : options["offset"] + options["limit"]]

    def remove(self, paths):
        self.removed.extend(paths)


def test_purge_prefix_removes_every_object_under_a_cycle_including_unrecorded_ones():
    folder = lambda n: {"name": n, "id": None}  # noqa: E731
    file = lambda n: {"name": n, "id": "obj-" + n}  # noqa: E731
    bucket = ListingBucket({
        "cycles/c1": [folder("f1"), folder("f2")],
        "cycles/c1/f1": [file("a.pdf")],
        "cycles/c1/f2": [file("190626_Macfos_715.pdf")],
    })
    store = SupabaseStorage(FakeClient(bucket), "recon-files", "https://x.supabase.co")
    assert store.purge_prefix("cycles/c1") == 2
    assert sorted(bucket.removed) == ["cycles/c1/f1/a.pdf", "cycles/c1/f2/190626_Macfos_715.pdf"]


def test_purge_prefix_on_an_empty_folder_removes_nothing_and_pages_through_long_listings():
    bucket = ListingBucket({})
    store = SupabaseStorage(FakeClient(bucket), "recon-files", "https://x.supabase.co")
    assert store.purge_prefix("cycles/none") == 0 and bucket.removed == []

    many = [{"name": f"f{i}", "id": None} for i in range(150)]
    tree = {"cycles/big": many, **{f"cycles/big/f{i}": [{"name": "x.pdf", "id": "o"}] for i in range(150)}}
    bucket = ListingBucket(tree)
    store = SupabaseStorage(FakeClient(bucket), "recon-files", "https://x.supabase.co")
    assert store.purge_prefix("cycles/big") == 150 and len(bucket.removed) == 150
    assert ("cycles/big", 100) in bucket.list_calls  # the second page was requested


def test_server_errors_are_retried_but_client_errors_are_not():
    store, bucket, _ = make([StorageApiError("busy", "x", 503)])
    store.put("p", b"x", "application/pdf")
    assert bucket.calls == 2

    store, bucket, pauses = make([StorageApiError("bad key", "InvalidKey", 400)])
    with pytest.raises(StorageApiError):
        store.put("p", b"x", "application/pdf")
    assert bucket.calls == 1 and pauses == []
