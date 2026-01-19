from livekit.plugins import anam
from config import ANAM_API_KEY, ANAM_AVATAR_ID


def create_avatar():
    return anam.AvatarSession(
        persona_config=anam.PersonaConfig(name="Dia", avatarId=ANAM_AVATAR_ID),
        api_key=ANAM_API_KEY,
        api_url="https://api.anam.ai",
    )
