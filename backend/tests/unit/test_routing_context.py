from tfm_rag.application.chat.routing_context import build_routing_context, doc_label


def test_doc_label_with_description() -> None:
    assert doc_label(filename="a.pdf", description="About cats") == "a.pdf — About cats"


def test_doc_label_without_description() -> None:
    assert doc_label(filename="a.pdf", description=None) == "a.pdf"


def test_doc_label_blank_description_falls_back_to_filename() -> None:
    assert doc_label(filename="a.pdf", description="   ") == "a.pdf"


def test_context_lists_kb_names_and_doc_labels() -> None:
    ctx = build_routing_context(
        kb_names=["Handbook", "Policies"],
        doc_source_labels=["onboarding.pdf", "pto.md"],
        db_sources=[],
    )
    assert "Handbook" in ctx and "Policies" in ctx
    assert "onboarding.pdf" in ctx and "pto.md" in ctx


def test_context_includes_sql_block_when_db_sources() -> None:
    db_sources = [{
        "source_id": "11111111-1111-1111-1111-111111111111",
        "type": "database",
        "payload": {"driver": "mysql", "db_name": "shop",
                    "schema_snapshot": {"tables": [
                        {"schema": "public", "name": "orders",
                         "columns": [{"name": "id", "data_type": "int"}]}]}},
    }]
    ctx = build_routing_context(kb_names=[], doc_source_labels=[],
                                db_sources=db_sources)
    assert "orders" in ctx and "shop" in ctx


def test_context_empty_when_nothing_attached() -> None:
    assert build_routing_context(kb_names=[], doc_source_labels=[],
                                 db_sources=[]).strip() == ""
