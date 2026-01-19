import os
import uuid
import shutil
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException
from livekit import api

from app.core.supabase import supabase
from app.core.ppt_processor import extract_text_slidewise, convert_ppt_to_images
from app.config import (
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    LIVEKIT_URL,
    BUCKET_IMAGES,
    SUPABASE_URL,
)

logger = logging.getLogger("api-routes-dia")
router = APIRouter()


@router.post("/upload-ppt")
async def upload_ppt(file: UploadFile = File(...)):
    """
    Step 1: Upload and Process PPT.
    Returns the presentation_id to be used for token generation.
    """
    if not file.filename.endswith(".pptx"):
        raise HTTPException(status_code=400, detail="Document must be in .pptx format.")

    presentation_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    work_dir = os.path.join("workdir", presentation_id)
    os.makedirs(work_dir, exist_ok=True)
    ppt_path = os.path.join(work_dir, file.filename)

    try:
        # Save and process file locally
        with open(ppt_path, "wb") as buffer:
            buffer.write(await file.read())

        image_files = convert_ppt_to_images(ppt_path, work_dir)
        slides_text = extract_text_slidewise(ppt_path)

        # Save Parent Presentation
        supabase.table("presentations").insert(
            {
                "id": presentation_id,
                "user_id": user_id,
                "title": file.filename,
                "total_slides": len(slides_text),
            }
        ).execute()

        # Save Individual Slides
        for i, slide_data in enumerate(slides_text):
            slide_no = slide_data["slide_number"]
            storage_path = f"{user_id}/{presentation_id}/slide_{slide_no}.jpg"

            with open(image_files[i], "rb") as image_content:
                supabase.storage.from_(BUCKET_IMAGES).upload(
                    path=storage_path,
                    file=image_content.read(),
                    file_options={"content-type": "image/jpeg"},
                )

            img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_IMAGES}/{storage_path}"

            supabase.table("slides").insert(
                {
                    "presentation_id": presentation_id,
                    "user_id": user_id,
                    "slide_number": slide_no,
                    "image_url": img_url,
                    "extracted_text": slide_data["text"],
                }
            ).execute()

        return {
            "status": "success",
            "presentation_id": presentation_id,
            "message": "PPT processed and slides saved to Supabase.",
        }

    except Exception as e:
        logger.error(f"Upload Failure: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)


@router.get("/get-presentation")
async def get_presentation(presentation_id: str):
    try:
        response = (
            supabase.table("slides")
            .select("image_url", "slide_number")
            .eq("presentation_id", presentation_id)
            .order("slide_number")
            .execute()
        )
        return response.data
    except Exception as e:
        raise Exception("Error fetching presentation slides from supabase: ", e)


@router.get("/livekit/token")
async def get_token(presentation_id: str, identity: str):
    """
    Step 2: Generate Token and start Avatar session.
    The presentation_id is required in metadata so the Agent can find the slides.
    """
    try:
        room_name = f"dia_session_{presentation_id[:8]}"

        # Create token and embed presentation_id in metadata
        token = (
            api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            .with_identity(identity)
            .with_metadata(presentation_id)
        )

        token.with_grants(api.VideoGrants(room_join=True, room=room_name))

        return {"token": token.to_jwt(), "url": LIVEKIT_URL, "room": room_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token error: {str(e)}")
