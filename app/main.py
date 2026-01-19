# agent/main.py
import asyncio
import logging
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
)
from livekit.agents.voice import VoiceActivityVideoSampler, room_io
from llm.gemini import create_llm
from avatar.anam_avatar import create_avatar
from avatar.persona import SYSTEM_INSTRUCTIONS
from utils.safety import keep_alive
from core.supabase import supabase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dia-presenter-agent")
logger.setLevel(logging.INFO)


async def entrypoint(ctx: JobContext):
    """
    Core entrypoint for the AI Agent worker.
    """
    logger.info(f"🚀 Initializing agent for room: {ctx.room.name}")

    session = None
    avatar = None

    try:
        # 1. Connect to room
        await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)
        logger.info("✅ Successfully connected to LiveKit room.")

        # 2. Get presentation ID from participant metadata
        await asyncio.sleep(2.5)

        presentation_id = None
        for participant in ctx.room.remote_participants.values():
            if participant.metadata:
                presentation_id = participant.metadata
                logger.info(f"✅ Verified Presentation ID: {presentation_id}")
                break

        if not presentation_id:
            logger.error("❌ FATAL: No presentation_id found in metadata.")
            return

        # 3. Load slides from Supabase
        logger.info(f"🔍 Querying slides for: {presentation_id}")
        query_result = (
            supabase.table("slides")
            .select("*")
            .eq("presentation_id", presentation_id)
            .order("slide_number", desc=False)
            .execute()
        )

        slides = query_result.data
        if not slides:
            logger.error(f"❌ No slides found for presentation {presentation_id}")
            return
        logger.info(f"✅ Loaded {len(slides)} slides successfully.")

        # 4. Initialize LLM and Avatar
        llm = create_llm()
        logger.info("✅ Gemini LLM initialized.")

        avatar = create_avatar()
        logger.info("✅ Anam Avatar initialized.")

        # 5. Create Agent Session
        session = AgentSession(
            llm=llm,
            video_sampler=VoiceActivityVideoSampler(speaking_fps=0, silent_fps=0),
            preemptive_generation=False,
            min_endpointing_delay=2.0,
            max_endpointing_delay=5.0,
        )
        logger.info("✅ Agent session configured.")

        # Start avatar
        await avatar.start(session, room=ctx.room)
        logger.info("✅ Anam avatar started.")

        # Build instructions
        presenter_instructions = (
            f"{SYSTEM_INSTRUCTIONS}\n\n"
            "ROLE: You are presenting a slide deck to an audience.\n"
            "GOAL: Present each slide's content clearly and engagingly.\n"
            "STRICT LIMIT: Maximum 2 sentences per response.\n"
            "TONE: Professional, clear, and engaging."
        )

        # Start session
        await session.start(
            agent=Agent(instructions=presenter_instructions),
            room=ctx.room,
            room_input_options=room_io.RoomInputOptions(video_enabled=True),
        )
        logger.info("✅ Agent session started.")

        # 6. Present slides
        logger.info("🎬 Starting presentation sequence.")

        for idx, slide in enumerate(slides, start=1):
            slide_no = slide.get("slide_number", idx)
            image_url = slide.get("image_url", "")
            content_text = slide.get("extracted_text", "")

            if not image_url:
                logger.warning(f"⚠️ Slide {slide_no} has no image. Skipping.")
                continue

            try:
                # FIXED: Set both attributes
                await ctx.room.local_participant.set_attributes(
                    {
                        "current_slide_url": image_url,
                        "current_slide_number": str(slide_no),  # Frontend needs this!
                    }
                )
                logger.info(f"📊 Displaying Slide {slide_no}/{len(slides)}")
            except Exception as e:
                logger.error(f"❌ Failed to set slide attributes: {e}")
                continue

            try:
                # Generate speech
                slide_instruction = (
                    f"Slide {slide_no}: {content_text}\n\n"
                    "Present this slide's key points clearly in 1-2 sentences."
                )

                # FIXED: Correct method name
                speech_handle = session.generate_reply(instructions=slide_instruction)

                # FIXED: Use wait_for_playout() not wait_for_next_playout()
                await speech_handle.wait_for_playout()

                logger.info(f"✅ Completed slide {slide_no}.")
                await asyncio.sleep(2.0)

            except Exception as e:
                logger.error(f"❌ Error presenting slide {slide_no}: {e}")
                continue

        # 7. Final message
        try:
            logger.info("🎉 All slides presented.")
            final_speech = session.generate_reply(
                instructions="Thank you for your attention! I'd be happy to answer any questions."
            )
            await final_speech.wait_for_playout()  # FIXED: Correct method
        except Exception as e:
            logger.error(f"❌ Error in final message: {e}")

        logger.info("✅ Presentation complete. Entering Q&A mode.")
        await keep_alive(ctx)

    except asyncio.CancelledError:
        logger.info("🛑 Agent cancelled. Cleaning up...")
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        # Cleanup
        logger.info("🧹 Starting cleanup...")

        if session:
            try:
                await session.aclose()
                logger.info("✅ Session closed.")
            except Exception as e:
                logger.error(f"❌ Error closing session: {e}")

        try:
            await ctx.room.disconnect()
            logger.info("✅ Disconnected from room.")
        except Exception as e:
            logger.error(f"❌ Error disconnecting: {e}")

        logger.info("✅ Cleanup complete.")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            drain_timeout=1800,  # 30 minutes
        )
    )
