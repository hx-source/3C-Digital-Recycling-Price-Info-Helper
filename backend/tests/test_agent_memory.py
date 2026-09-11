from app.services.agent_service import _arguments_with_memory, _updated_memory


def test_memory_fills_follow_up_tool_arguments() -> None:
    memory = {"brand": "红米", "model": "K80", "storage": "12+256"}
    resolved = _arguments_with_memory({"direction": "down"}, memory)
    assert resolved["brand"] == "红米"
    assert resolved["query"] == "K80 12+256"


def test_tool_arguments_refresh_structured_memory() -> None:
    memory = _updated_memory({}, "查一下红米 K80", [{"brand": "红米", "query": "K80 12+256"}])
    assert memory["brand"] == "红米"
    assert memory["model"] == "K80"
    assert memory["storage"] == "12+256"

