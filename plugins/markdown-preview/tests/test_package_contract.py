from importlib.metadata import entry_points


def test_entry_point_loads_canonical_plugin() -> None:
    matches = [
        item
        for item in entry_points(group="reflex.commands")
        if item.name == "markdown-preview"
    ]
    assert len(matches) == 1
    assert matches[0].load()().descriptor.plugin_id == "markdown-preview"
