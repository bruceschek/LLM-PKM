from llm_pkm.stores import Fact, LocalStore


def test_add_and_search(tmp_path):
    store = LocalStore(tmp_path / "facts.jsonl")
    store.add(Fact("The user's wife's name is Hemmie.", "my wife's name is Hemmie"))
    store.add(Fact("The user's garage code is on the fridge.", "garage code is on the fridge"))

    hits = store.search("wife name")
    assert hits[0].text == "The user's wife's name is Hemmie."
    assert store.search("dentist") == []


def test_log_is_append_only_jsonl(tmp_path):
    store = LocalStore(tmp_path / "facts.jsonl")
    store.add(Fact("A.", "a"))
    store.add(Fact("B.", "b"))
    assert [f.text for f in store.all()] == ["A.", "B."]
