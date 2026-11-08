import uvicorn
from dotenv import load_dotenv

if __name__ == "__main__":
    load_dotenv()
    uvicorn.run(
        "incident_atlas.app:create_app", factory=True, host="127.0.0.1", port=8765
    )
