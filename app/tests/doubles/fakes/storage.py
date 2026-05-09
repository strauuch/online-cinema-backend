class FakeS3Storage:
    def __init__(self):
        self.storage = {}

    async def upload_file(self, file_name: str, file_data: bytes):
        self.storage[file_name] = file_data

    async def delete_file(self, file_name: str):
        self.storage.pop(file_name, None)

    async def get_file_url(self, file_name: str) -> str:
        return f"http://fake-s3.local/{file_name}"