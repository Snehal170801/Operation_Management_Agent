"""A hung mailbox read must never freeze the worker: the lock wait is limited and IMAP connections have a timeout."""
import threading

from app.clients import imap_client
from app.orchestrator import worker


def test_read_mailbox_gives_up_when_another_read_hangs(monkeypatch):
    monkeypatch.setattr(worker, "MAIL_LOCK_WAIT_SECONDS", 0.05)
    called = []
    monkeypatch.setattr(worker.imap_client, "process_unseen_replies", lambda *_a, **_k: called.append(1) or 1)
    worker._mail_lock.acquire()
    try:
        done = []
        t = threading.Thread(target=lambda: done.append(worker.read_mailbox()))
        t.start()
        t.join(2)
        assert not t.is_alive() and done == [0] and called == []
    finally:
        worker._mail_lock.release()


def test_read_mailbox_releases_lock_after_error(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("down")
    monkeypatch.setattr(worker.imap_client, "process_unseen_replies", boom)
    try:
        worker.read_mailbox()
    except RuntimeError:
        pass
    assert worker._mail_lock.acquire(timeout=0.1)
    worker._mail_lock.release()


def test_imap_connections_have_a_timeout(monkeypatch):
    seen = []

    class Fake:
        def __init__(self, host, port, timeout=None):
            seen.append(timeout)
            raise OSError("stop")
    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", Fake)
    monkeypatch.setattr(imap_client.settings, "IMAP_HOST", "h")
    monkeypatch.setattr(imap_client.settings, "TEST_MAIL_DIR", "")
    for call in (lambda: imap_client.process_unseen_replies(lambda m: None), lambda: imap_client.wait_for_new_mail(1)):
        try:
            call()
        except OSError:
            pass
    assert seen and all(t == imap_client.CONNECT_TIMEOUT_SECONDS for t in seen)
