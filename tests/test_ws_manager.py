from server.ws_manager import ConnectionManager

def test_connection_manager_init():
    manager = ConnectionManager()
    assert manager.active_connections == []
