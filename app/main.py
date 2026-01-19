# main.py (agent)
import asyncio
import logging
import sys
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

# Configure Advanced Logging for Production Monitoring
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dia-presenter-agent")
logger.setLevel(logging.INFO)


async def entrypoint(ctx: JobContext):
    """
    Core entrypoint for the AI Agent worker.
    Manages the orchestration between slides, Gemini LLM, and Anam Avatar.
    """
    logger.info(f"🚀 Initializing agent for room: {ctx.room.name}")

    # Initialize variables for cleanup
    session = None
    avatar = None

    try:
        # 1. Join Room and Auto-Subscribe to User
        try:
            await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)
            logger.info("✅ Successfully connected to LiveKit room.")
        except Exception as e:
            logger.error(f"❌ Failed to connect to room: {e}")
            return

        # 2. Extract Session Metadata
        await asyncio.sleep(2.5)

        presentation_id = None
        for participant in ctx.room.remote_participants.values():
            if participant.metadata:
                presentation_id = participant.metadata
                logger.info(
                    f"✅ Verified Presentation ID from metadata: {presentation_id}"
                )
                break

        if not presentation_id:
            logger.error(
                "❌ FATAL: No presentation_id found in room metadata. Closing worker."
            )
            return

        # 3. Synchronize Slide Data from Supabase
        logger.info(f"🔍 Querying slide manifest for: {presentation_id}")
        try:
            query_result = (
                supabase.table("slides")
                .select("*")
                .eq("presentation_id", presentation_id)
                .order("slide_number", desc=False)
                .execute()
            )

            slides = query_result.data
            if not slides:
                logger.error(
                    f"❌ Integrity Error: No slides found for presentation ID {presentation_id}"
                )
                return
            logger.info(f"✅ Loaded {len(slides)} slides successfully.")
        except Exception as e:
            logger.error(f"❌ Supabase Query Failed: {e}")
            return

        # 4. Initialize Brain (Gemini) and Visuals (Anam)
        try:
            llm = create_llm()
            logger.info("✅ Gemini LLM initialized successfully.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini LLM: {e}")
            return

        try:
            avatar = create_avatar()
            logger.info("✅ Anam Avatar initialized successfully.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Anam Avatar: {e}")
            return

        # 5. CONFIGURE AGENT SESSION
        try:
            session = AgentSession(
                llm=llm,
                video_sampler=VoiceActivityVideoSampler(speaking_fps=0, silent_fps=0),
                preemptive_generation=False,
                min_endpointing_delay=2.0,
                max_endpointing_delay=5.0,
            )
            logger.info("✅ Agent session configured.")
        except Exception as e:
            logger.error(f"❌ Failed to configure agent session: {e}")
            return

        # Attach the Anam plugin to intercept text and convert it to avatar video
        try:
            await avatar.start(session, room=ctx.room)
            logger.info("✅ Anam avatar plugin attached to session.")
        except Exception as e:
            logger.error(f"❌ Failed to start avatar: {e}")
            return

        # Build presenter instructions
        presenter_instructions = (
            f"{SYSTEM_INSTRUCTIONS}\n\n"
            "ROLE: You are presenting a slide deck to an audience.\n"
            "GOAL: Present each slide's content clearly and engagingly.\n"
            "STRICT LIMIT: Maximum 2 sentences per response. Wait for playout before continuing.\n"
            "TONE: Professional, clear, and engaging."
        )

        # Start the integrated AI service
        try:
            await session.start(
                agent=Agent(instructions=presenter_instructions),
                room=ctx.room,
                room_input_options=room_io.RoomInputOptions(video_enabled=True),
            )
            logger.info("✅ Agent session started successfully.")
        except Exception as e:
            logger.error(f"❌ Failed to start agent session: {e}")
            return

        # 6. THE SYNCHRONIZED PRESENTATION LOOP
        logger.info("🎬 Starting automated presentation sequence.")

        for idx, slide in enumerate(slides, start=1):
            slide_no = slide.get("slide_number", idx)
            image_url = slide.get("image_url", "")
            content_text = slide.get("extracted_text", "")

            if not image_url:
                logger.warning(f"⚠️ Slide {slide_no} has no image URL. Skipping.")
                continue

            try:
                # TRIGGER FRONTEND SYNC: Update local participant attributes
                await ctx.room.local_participant.set_attributes(
                    {
                        "current_slide_url": image_url,
                        "current_slide_number": str(slide_no),
                    }
                )
                logger.info(
                    f"📊 Displaying Slide {slide_no}/{len(slides)} to participants."
                )
            except Exception as e:
                logger.error(f"❌ Failed to set slide attributes: {e}")
                continue

            try:
                # Command Gemini to present the slide content
                slide_instruction = (
                    f"Slide {slide_no}: {content_text}\n\n"
                    "Present this slide's key points clearly in 1-2 sentences."
                )

                speech_handle = session.generate_reply(instructions=slide_instruction)
                await speech_handle.wait_for_next_playout()

                logger.info(f"✅ Completed presentation of slide {slide_no}.")
                await asyncio.sleep(2.0)

            except Exception as e:
                logger.error(f"❌ Error presenting slide {slide_no}: {e}")
                continue

        # 7. Final Handover
        try:
            logger.info("🎉 All slides presented. Thanking audience.")
            final_speech = session.generate_reply(
                instructions="Thank you for your attention! I'd be happy to answer any questions you may have about this presentation."
            )
            await final_speech.wait_for_next_playout()
        except Exception as e:
            logger.error(f"❌ Error in final message: {e}")

        logger.info("✅ Presentation sequence complete. Entering Q&A standby mode.")

        # Keep the process alive for user interaction
        await keep_alive(ctx)

    except asyncio.CancelledError:
        logger.info("🛑 Agent task cancelled. Cleaning up...")
    except Exception as e:
        logger.error(f"❌ Unexpected error in agent: {e}")
    finally:
        # CRITICAL: Always cleanup resources
        logger.info("🧹 Starting cleanup process...")

        # Stop avatar session
        if avatar:
            try:
                await avatar.stop()
                logger.info("✅ Avatar stopped successfully.")
            except Exception as e:
                logger.error(f"❌ Error stopping avatar: {e}")

        # Stop agent session
        if session:
            try:
                await session.stop()
                logger.info("✅ Agent session stopped successfully.")
            except Exception as e:
                logger.error(f"❌ Error stopping session: {e}")

        logger.info("✅ Cleanup complete. Agent shutting down.")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
