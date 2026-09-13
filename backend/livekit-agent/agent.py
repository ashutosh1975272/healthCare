import json
import logging
import os
import uuid
from dotenv import load_dotenv

from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli, room_io
from livekit.agents import AgentStateChangedEvent, MetricsCollectedEvent, metrics
from livekit.agents import llm, stt, tts, inference
from livekit.agents.types import APIConnectOptions
from livekit.plugins import noise_cancellation, silero

from groq_llm import (
    LIMITED_MODE_MESSAGE,
    VOICE_SYSTEM_PROMPT,
    VOICE_WORKER_VERSION,
    GroqKeyInvalid,
    NvidiaUnavailable,
    UserGroqLLM,
    UserNvidiaLLM,
)
from key_loader import load_voice_keys

logger = logging.getLogger(__name__)
load_dotenv()

class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=VOICE_SYSTEM_PROMPT)


class _VoiceChatStream(llm.LLMStream):
    """Token-streaming adapter: Groq SSE deltas become LiveKit chunks.

    Chain per turn: Groq stream → NVIDIA single reply → limited-mode hint.
    Streaming (instead of one full-text chunk) lets TTS start synthesis on
    the first tokens, which is what makes the turn feel realtime. If every
    provider fails, a single short sentence is emitted so the turn never
    goes silent — and the next turn still listens.
    """

    def __init__(self, parent, *, chat_ctx, tools, conn_options, groq, nvidia):
        super().__init__(parent, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
        self._groq = groq
        self._nvidia = nvidia

    async def _run(self):
        from livekit.agents.llm import ChatChunk, ChoiceDelta

        stream_id = f"voice-{uuid.uuid4().hex[:8]}"
        first = True

        async def emit(text: str):
            nonlocal first
            chunk = ChatChunk(
                id=stream_id,
                delta=ChoiceDelta(content=text, role="assistant" if first else None),
            )
            first = False
            self._event_ch.send_nowait(chunk)

        messages: list[dict] = []
        try:
            messages, _ = self._chat_ctx.to_provider_format("openai")
        except Exception:
            logger.exception("Chat context format failed")
            messages = []

        groq_failed_401 = False
        if self._groq is not None:
            try:
                try:
                    async for delta in self._groq.chat_stream(messages, VOICE_SYSTEM_PROMPT):
                        if delta:
                            await emit(delta)
                finally:
                    if not first:
                        await emit(" ")
                if first:
                    logger.warning("Groq returned empty stream; trying NVIDIA fallback")
                else:
                    return
            except GroqKeyInvalid:
                groq_failed_401 = True
                logger.warning("Groq key rejected (401); trying NVIDIA fallback")
            except Exception:
                logger.exception("Groq chat failed; trying NVIDIA fallback")

        if self._nvidia is not None:
            try:
                text = await self._nvidia.chat(messages, VOICE_SYSTEM_PROMPT)
                if text:
                    await emit(text)
                    return
            except GroqKeyInvalid:
                logger.warning("NVIDIA key rejected (401)")
            except (NvidiaUnavailable, Exception):
                logger.exception("NVIDIA fallback failed")

        if first:
            if self._groq is None and self._nvidia is None:
                await emit(LIMITED_MODE_MESSAGE)
            elif groq_failed_401:
                await emit("Your Groq key was rejected. Please check it in Profile, AI Provider Keys.")
            else:
                await emit(
                    "I'm having trouble reaching my language model right now. Please try again shortly."
                )


class UserGroqVoiceLLM(llm.LLM):
    """LiveKit LLM node: per-user Groq key first, NVIDIA fallback.

    Either key may be None (DB miss + no server env). Both None means
    limited mode: the stream speaks a short hint instead of looping the
    old guidance sentence every turn.
    """

    def __init__(self, api_key: str | None, nvidia_key: str | None = None) -> None:
        super().__init__()
        self._groq = UserGroqLLM(api_key) if api_key else None
        self._nvidia = UserNvidiaLLM(nvidia_key) if nvidia_key else None

    @property
    def provider(self) -> str:
        return "groq"

    @property
    def model(self) -> str:
        return "openai/gpt-oss-120b"

    def chat(self, *, chat_ctx, tools, conn_options=APIConnectOptions(), parallel_tool_calls=None,
             tool_choice=None, extra_kwargs=None) -> llm.LLMStream:
        return _VoiceChatStream(
            self, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options,
            groq=self._groq, nvidia=self._nvidia,
        )


# Backward-compat alias (older imports reference the stream by old name).
_GroqChatStream = _VoiceChatStream


async def entrypoint(ctx: JobContext):
    logger.info(f"voice-worker {VOICE_WORKER_VERSION} (Groq first, NVIDIA fallback)")
    participant = await ctx.wait_for_participant()
    logger.info(f"Participant joined: {participant.identity}")

    database_url = os.environ.get("DATABASE_URL", "")
    secret_key = os.environ.get("SECRET_KEY", "")
    groq_key: str | None = None
    nvidia_key: str | None = None
    if database_url and secret_key:
        keys = await load_voice_keys(database_url, secret_key, participant.identity)
        groq_key, groq_source = keys["groq"]
        nvidia_key, nvidia_source = keys["nvidia"]
        logger.info(
            "Voice keys for user: groq=%s nvidia=%s",
            groq_source, nvidia_source,
        )
        if groq_key is None and nvidia_key is None:
            logger.info("No voice LLM key on file; limited mode with server hint.")
    else:
        logger.warning("DATABASE_URL/SECRET_KEY missing on worker; voice runs in limited mode.")

    context_file = "user_context.json"
    past_messages = []
    if os.path.exists(context_file):
        try:
            with open(context_file, "r") as f:
                data = json.load(f)
                past_messages = data.get(participant.identity, [])
            logger.info(f"Loaded {len(past_messages)} past messages for {participant.identity}")
        except Exception as e:
            logger.error(f"Failed to load user context: {e}")

    try:
        audio_input = room_io.AudioInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        )
    except Exception:
        logger.warning("BVC noise cancellation unavailable; continuing without it.")
        audio_input = room_io.AudioInputOptions()

    # STT/TTS: env-driven, free LiveKit models first. Comma-separated list
    # so you can swap without code. Default puts a free model at priority 0
    # (openai/* is free via LiveKit Cloud inference); Deepgram/Cartesia
    # stay as quality fallbacks. Change via LIVEKIT_STT_MODELS / LIVEKIT_TTS_MODELS.
    def _stt_models() -> list:
        raw = os.environ.get("LIVEKIT_STT_MODELS", "").strip() or os.environ.get("LIVEKIT_STT_MODEL", "").strip()
        ids = [s.strip() for s in raw.split(",") if s.strip()] if raw else []
        if not ids:
            ids = ["openai/whisper", "deepgram/nova-2"]
        out = []
        for mid in ids:
            try:
                out.append(inference.STT.from_model_string(mid))
            except Exception:
                logger.warning("STT model %s unavailable, skipping", mid)
        return out or [inference.STT.from_model_string("deepgram/nova-2")]

    def _tts_models() -> list:
        raw = os.environ.get("LIVEKIT_TTS_MODELS", "").strip() or os.environ.get("LIVEKIT_TTS_MODEL", "").strip()
        ids = [s.strip() for s in raw.split(",") if s.strip()] if raw else []
        if not ids:
            ids = ["openai/tts-1", "cartesia/sonic-2"]
        out = []
        for mid in ids:
            try:
                out.append(inference.TTS.from_model_string(mid))
            except Exception:
                logger.warning("TTS model %s unavailable, skipping", mid)
        return out or [inference.TTS.from_model_string("cartesia/sonic-2")]

    session = AgentSession(
        stt=stt.FallbackAdapter(_stt_models()),
        llm=UserGroqVoiceLLM(groq_key, nvidia_key=nvidia_key),
        tts=tts.FallbackAdapter(_tts_models()),
        vad=silero.VAD.load(
            min_silence_duration=0.5,
            prefix_padding_duration=0.3,
        ),
        turn_detection="vad",
        preemptive_generation=True,
        min_endpointing_delay=0.5,
        max_endpointing_delay=1.5,
    )

    for msg in past_messages:
        session.history.add_message(role=msg["role"], content=msg["content"])

    @session.on("agent_state_changed")
    def on_agent_state_changed(event: AgentStateChangedEvent):
        logger.info(f"Agent state changed from {event.old_state} to {event.new_state}")

    @session.on("metrics_collected")
    def on_metrics_collected(event: MetricsCollectedEvent):
        metrics.log_metrics(event.metrics, logger=logger)

    try:
        await session.start(
            agent=Assistant(),
            room=ctx.room,
            room_options=room_io.RoomOptions(audio_input=audio_input),
        )
    except Exception:
        logger.exception("Error starting session")
        return

    try:
        await session.generate_reply(
            instructions="Greet the user briefly and ask how you can help."
        )
    except Exception:
        logger.exception("Greeting reply failed")

    async def save_context(reason: str = ""):
        updated_messages = []
        for item in session.history.messages():
            content_str = ""
            content = item.content
            if isinstance(content, str):
                content_str = content
            elif isinstance(content, list):
                parts = []
                for c in content:
                    if isinstance(c, str):
                        parts.append(c)
                    else:
                        text = getattr(c, "text", None) or getattr(c, "content", None)
                        if isinstance(text, str) and text:
                            parts.append(text)
                content_str = " ".join(parts)

            if content_str:
                updated_messages.append({
                    "role": item.role,
                    "content": content_str,
                })

        try:
            data = {}
            if os.path.exists(context_file):
                with open(context_file, "r") as f:
                    data = json.load(f)

            data[participant.identity] = updated_messages

            with open(context_file, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Successfully saved {len(updated_messages)} messages context for participant {participant.identity}")
        except Exception as e:
            logger.error(f"Failed to save user context: {e}")

    ctx.add_shutdown_callback(save_context)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            num_idle_processes=0,
            load_threshold=1.0,
        )
    )
