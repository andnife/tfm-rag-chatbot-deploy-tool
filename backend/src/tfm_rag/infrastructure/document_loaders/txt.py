class TxtLoader:
    mime_type = "text/plain"

    async def load(self, content: bytes) -> str:
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("latin-1")
