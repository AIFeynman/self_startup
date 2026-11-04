"""阶段 0 探针自测：评分函数，加一个按百炼事件顺序回放的假服务（不联网）。"""
import asyncio
import base64
import importlib.util
import json
import sys
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("voice_probe", ROOT / "scripts/voice_probe.py")
probe = importlib.util.module_from_spec(_spec)
sys.modules["voice_probe"] = probe
_spec.loader.exec_module(probe)

PCM = (b"\x10\x20" * int(probe.RATE * 0.12))  # 不到 0.2 秒的「说话」，后面靠探针继续发的静音收尾


def test_scoring():
    assert probe.similarity("周四前，收尾。", "周四前收尾") == 1.0
    assert probe.keep_rate(["十二条|12条", "评测集"], "评测集只跑了12条") == 1.0
    assert probe.keep_rate(["周四", "演示"], "周四前收尾") == 0.5
    assert probe.keep_rate([], "随便") == 1.0
    assert probe.percentile([3.0, 1.0, 2.0], 50) == 2.0
    tail = int(probe.RATE * 0.3)
    assert abs(probe.trailing_silence_s(b"\x10\x20" * probe.RATE + bytes(tail * 2)) - 0.3) < 0.05
    assert probe.percentile([], 95) is None
    assert probe.route_of([{"name": "ask_claude"}], True) == "ask_claude"
    assert probe.route_of([], True) == "fast"
    assert probe.route_of([], False) == "silent"
    assert probe.route_ok("any", "silent") and not probe.route_ok("fast", "ask_claude")


def test_endpoint_accepts_bare_id_or_console_url(monkeypatch):
    want = "wss://ws-abc.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=m"
    for value in ("ws-abc", "https://ws-abc.cn-beijing.maas.aliyuncs.com/api/v1"):
        monkeypatch.setenv("DASHSCOPE_WORKSPACE_ID", value)
        assert probe.voice_rt.endpoint("m") == want


def test_tools_always_declare_required():
    # Flash 遇到缺 required 的无参工具，整轮回应会内部报错（2026-11-04 实测）
    for t in probe.voice_rt.TOOLS:
        assert isinstance(t["function"]["parameters"]["required"], list), t["function"]["name"]


def test_invented_only_counts_unforwarded_data_questions():
    case = {"must_not_invent": True}
    assert probe.invented(case, [], "你上周的复盘里说了三个问题")
    assert not probe.invented(case, [{"name": "ask_claude"}], "你上周的复盘我想一下")
    assert not probe.invented(case, [], "这个我得想一下")
    assert not probe.invented({}, [], "你上周说过")


def test_cases_are_complete():
    data = json.loads(probe.CASES.read_text("utf-8"))
    ids = [c["id"] for c in data["cases"]]
    assert len(ids) == len(set(ids)) and len(ids) >= 40
    tools = {t["function"]["name"] for t in probe.voice_rt.TOOLS}
    for c in data["cases"]:
        assert c["expect"] in tools | {"fast", "silent", "any"}, c["id"]
    assert {c["kind"] for c in data["cases"]} == {"寒暄", "控制", "常识", "资料", "建议", "术语", "噪声", "搜索"}


class FakeBailian:
    """mode: direct 直接答 / tool 先说一句再调工具 / silent 不回应 / failed 回应内部失败。说话算法：有声音之后来一帧全零就算说完。"""

    def __init__(self, mode="direct"):
        self.mode, self.sessions, self.outputs = mode, [], []

    async def __call__(self, ws):
        self.ws, self.task, self.spoke, self.n = ws, None, False, 0
        self.items: list[str] = []
        await self.emit("session.created")
        async for raw in ws:
            await self.on(json.loads(raw))

    async def emit(self, type_, **kw):
        await self.ws.send(json.dumps({"type": type_, **kw}, ensure_ascii=False))

    async def on(self, ev):
        t = ev["type"]
        if t == "session.update":
            self.sessions.append(ev["session"])
            await self.emit("session.updated")
        elif t == "input_audio_buffer.append":
            await self.on_audio(base64.b64decode(ev["audio"]))
        elif t == "conversation.item.create":
            item = ev["item"]
            if item["type"] == "function_call_output":
                self.outputs.append(item)
            else:
                self.items.append(item["content"][0]["text"])
        elif t == "response.create":
            said = self.items[-1].removeprefix("【慢思考结果】") if self.items else "好的，我想一下。"
            self.task = asyncio.create_task(self.respond(said, long="三步" in said))
        elif t == "response.cancel":
            if self.task:
                self.task.cancel()
                self.task = None
            await self.emit("response.done", response={"id": "r", "status": "cancelled"})
        elif t == "conversation.item.retrieve":
            await self.emit("conversation.item.retrieved", item={"id": ev["item_id"], "content": [{"transcript": "我建议分三步"}]})

    async def on_audio(self, pcm):
        loud = any(pcm)
        if loud and self.task:  # 模型说话时用户开口
            await self.emit("input_audio_buffer.speech_started")
        elif loud:
            self.spoke = True
        elif self.spoke:
            self.spoke = False
            await self.emit("input_audio_buffer.speech_started")
            await self.emit("conversation.item.input_audio_transcription.completed", item_id="u1", transcript="帮我想想这周先推哪件事")
            if self.mode == "silent":
                return
            if self.mode == "failed":
                await self.emit("response.done", response={"id": "r0", "status": "failed", "status_details": {"type": "failed"}})
                return
            if self.mode == "tool":
                await self.emit("response.output_item.added", item={"id": "c1", "type": "function_call"})
                await self.emit("response.function_call_arguments.done", call_id="call-1", name="ask_claude",
                                arguments='{"objective":"这周先推哪件事"}')
                await self.emit("response.done", response={"id": "r0", "status": "completed"})
            else:
                self.task = asyncio.create_task(self.respond("你好。"))

    async def respond(self, said, long=False):
        await self.emit("response.output_item.added", item={"id": "m1", "type": "message"})
        for _ in range(60 if long else 2):
            await self.emit("response.audio.delta", delta=base64.b64encode(bytes(960)).decode())
            await asyncio.sleep(0.05 if long else 0)
        await self.emit("response.audio_transcript.done", transcript=said)
        await self.emit("response.done", response={"id": "r", "status": "completed"})
        self.task = None


async def _with_server(fake, fn):
    async with websockets.serve(fake, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        return await fn(f"ws://127.0.0.1:{port}")


def test_direct_reply_measures_latency():
    fake = FakeBailian("direct")
    case = {"id": "x", "kind": "寒暄", "text": "帮我想想这周先推哪件事", "expect": "fast", "context": ["【你刚说过】先做中转"]}
    r = asyncio.run(_with_server(fake, lambda u: probe.run_case("m", case, PCM, u)))
    assert r["route"] == "fast" and r["route_ok"]
    assert r["first_audio_s"] is not None and r["first_audio_s"] >= 0
    assert r["heard_sim"] == 1.0 and r["reply"] == "你好。"
    assert fake.items == ["【你刚说过】先做中转"]
    assert fake.sessions[0]["tools"] == probe.voice_rt.TOOLS  # 真跑时要带上工具和提示词
    assert "慢思考" in fake.sessions[0]["instructions"]


def test_tool_call_answers_accepted_then_replies():
    fake = FakeBailian("tool")
    case = {"id": "x", "kind": "建议", "text": "帮我想想这周先推哪件事", "expect": "ask_claude", "keep": ["这周"]}
    r = asyncio.run(_with_server(fake, lambda u: probe.run_case("m", case, PCM, u)))
    assert r["route"] == "ask_claude" and r["route_ok"] and r["tool_s"] is not None
    assert fake.outputs[0]["call_id"] == "call-1" and r["objective_kept"] == 1.0
    assert not r["spoke_before_tool"]  # 这个假服务是先调工具再说话
    assert r["first_audio_s"] is not None  # 第二轮接上的话


def test_silent_when_model_does_not_respond(monkeypatch):
    monkeypatch.setattr(probe, "SETTLE_S", 0.3)
    case = {"id": "x", "kind": "噪声", "text": "嗯", "expect": "silent"}
    async def go(u):
        return await probe.run_case("m", case, PCM, u)
    r = asyncio.run(_with_server(FakeBailian("silent"), go))
    assert r["route"] == "silent" and r["route_ok"] and r["first_audio_s"] is None


def test_failed_response_is_an_error_not_silence():
    case = {"id": "x", "kind": "噪声", "text": "嗯", "expect": "silent"}
    r = asyncio.run(_with_server(FakeBailian("failed"), lambda u: probe.run_case("m", case, PCM, u)))
    assert r["route"] == "failed" and not r["route_ok"] and r["errors"]


def test_spoken_fidelity():
    item = {"id": "s", "text": "你在第二章第三节，还差四个练习。", "keep": ["第二章", "四个"]}
    s = asyncio.run(_with_server(FakeBailian(), lambda u: probe.run_spoken("m", item, u)))
    assert s["similarity"] == 1.0 and s["keep"] == 1.0 and s["first_audio_s"] is not None


def test_barge_in_detects_cancels_and_reads_context():
    b = asyncio.run(_with_server(FakeBailian(), lambda u: probe.run_barge("m", PCM, u)))
    assert b["detect_s"] is not None and b["status"] == "cancelled"
    assert b["audio_after_done"] == 0
    assert b["kept_item"]["content"][0]["transcript"] == "我建议分三步"


def test_run_all_pauses_when_most_recent_cases_fail(tmp_path, monkeypatch):
    # 连不上（没有服务在听）：每条都失败，第 5 条就该停，不要把 40 条都跑完
    audio = tmp_path / "audio"
    audio.mkdir()
    data = json.loads(probe.CASES.read_text("utf-8"))
    for c in data["cases"]:
        probe.save_wav(audio / f"{c['id']}.wav", PCM, probe.RATE)
    res = asyncio.run(probe.run_all(["m"], audio, tmp_path / "out", url="ws://127.0.0.1:9"))
    assert res["paused"] and len(res["rows"]) == 5


def test_run_all_writes_summary_for_both_models(tmp_path, monkeypatch):
    # 真跑要花钱，最后一步写汇总不能崩
    audio = tmp_path / "audio"
    audio.mkdir()
    cases = {
        "cases": [{"id": "a", "kind": "建议", "text": "帮我想想这周先推哪件事", "expect": "ask_claude"},
                  {"id": "b", "kind": "术语", "text": "帮我想想这周先推哪件事", "expect": "any", "terms": ["这周"]}],
        "spoken": [{"id": "s", "text": "你在第二章。", "keep": ["第二章"]}],
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases, ensure_ascii=False), "utf-8")
    monkeypatch.setattr(probe, "CASES", path)
    for name in ("a", "b", "barge-cut"):
        probe.save_wav(audio / f"{name}.wav", PCM, probe.RATE)
    out = tmp_path / "out"
    res = asyncio.run(_with_server(FakeBailian("tool"), lambda u: probe.run_all(["flash", "plus"], audio, out, url=u)))
    for m in ("flash", "plus"):
        s = res["summary"][m]
        assert s["cases"] == 2 and s["route_acc"] == 1.0 and s["tool_cases"] == 2
        assert s["spoken_keep_mean"] == 1.0 and s["barge"]["status"] == "cancelled"
    saved = json.loads((out / "result.json").read_text("utf-8"))
    assert len(saved["rows"]) == 4 and (out / "rows.jsonl").exists()
