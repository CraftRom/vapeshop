"""Runs without live Redis/Telegram credentials; tests the actual realtime transport."""
from __future__ import annotations

import asyncio
import ast
import importlib.util
import json
import pathlib
import sys
import types

BASE = pathlib.Path(__file__).resolve().parents[1]
settings = types.SimpleNamespace(redis_url="", redis_password="", serverless=True)
shop = types.ModuleType("shop")
shop.__path__ = [str(BASE / "shop")]
conf = types.ModuleType("shop.config")
conf.settings = settings
# Import only the transport, not application configuration and credentials.
sys.modules.setdefault("shop", shop)
sys.modules["shop.config"] = conf
spec = importlib.util.spec_from_file_location("shop.services.realtime", BASE / "shop/services/realtime.py")
realtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(realtime)

async def exercise():
    first = realtime.subscribe_order_events()
    second = realtime.subscribe_order_events()
    task_a = asyncio.create_task(anext(first))
    task_b = asyncio.create_task(anext(second))
    await asyncio.sleep(.03)
    assert len(realtime._local_subscribers) == 2
    await realtime.publish_support_changed(24, direction="in")
    one, two = await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=2)
    assert one == two
    assert one["threadId"] == 24
    assert one["direction"] == "in"
    assert one["kind"] == "support.changed"
    assert "text" not in one and "userId" not in one
    await first.aclose()
    await second.aclose()
    assert not realtime._local_subscribers

    third = realtime.subscribe_order_events()
    task = asyncio.create_task(anext(third))
    await asyncio.sleep(.02)
    await realtime.publish_order_changed(99, user_id=10, fields=("status",))
    order = await asyncio.wait_for(task, timeout=2)
    assert order["orderId"] == 99 and order["kind"] == "order.changed"
    await third.aclose()

    await realtime.publish_support_changed(0, direction="in")
    assert not realtime._local_subscribers

# Test actual router framing without importing FastAPI / DB dependencies.
router_tree = ast.parse((BASE / "api/routers/realtime.py").read_text())
frame_node = next(n for n in router_tree.body if isinstance(n, ast.FunctionDef) and n.name == "_frame")
frame_module = ast.fix_missing_locations(ast.Module(body=[frame_node], type_ignores=[]))
namespace = {"json": json}
exec(compile(frame_module, "realtime-frame", "exec"), namespace)
frame = namespace["_frame"]({"eventId": "a", "kind": "support.changed", "threadId": 24})
assert "event: support\n" in frame
assert '"threadId":24' in frame
assert "event: order\n" in namespace["_frame"]({"eventId": "b", "kind": "order.changed", "orderId": 11})

if __name__ == "__main__":
    asyncio.run(exercise())
    print("Support realtime: 11/11")
