from server.schemas import (
    SessionCreate, SessionOut,
    EventCreate, EventOut,
    MessageCreate, MessageOut,
    MemoryCreate, MemoryOut, MemoryUpdate,
)

def test_event_create_schema():
    e = EventCreate(session_id="s1", type="pre_tool", tool_name="Bash")
    assert e.session_id == "s1"

def test_memory_update_schema():
    u = MemoryUpdate(status="active")
    assert u.status == "active"
