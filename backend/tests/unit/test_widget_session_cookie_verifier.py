"""Smoke test for the new session_origin / public_session_cookie kwargs
on answer_query. Full behavior is covered in Task 3 integration tests."""
import inspect

from tfm_rag.application.chat.answer_query import answer_query


def test_answer_query_accepts_session_origin_kwarg() -> None:
    sig = inspect.signature(answer_query)
    assert "session_origin" in sig.parameters
    assert "public_session_cookie" in sig.parameters
    # Defaults preserve old behavior:
    assert sig.parameters["session_origin"].default == "playground"
    assert sig.parameters["public_session_cookie"].default is None
