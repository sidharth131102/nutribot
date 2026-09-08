"""Azure Blob Storage wrapper. The only file allowed to import azure.storage.blob.

No business logic here -- no user-scoping decisions, no validation, just verbs
against Azure. "Is this the right user's blob" is enforced at the Mongo-backed
UserScopedRepo layer (backend/db/mongo.py), never here -- this module trusts
whatever blob_path it's given, per invariant 4 (user isolation lives at the
data-access layer, not scattered across every module that happens to touch
user data).
"""
from azure.storage.blob.aio import BlobServiceClient

from backend.config import Settings


class BlobStorageClient:
    def __init__(self, settings: Settings):
        self._connection_string = settings.azure_storage_connection_string
        self._container_name = settings.azure_storage_container

    def _service_client(self) -> BlobServiceClient:
        return BlobServiceClient.from_connection_string(self._connection_string)

    async def upload(self, user_id: str, document_id: str, filename: str, content: bytes, content_type: str) -> str:
        """Returns the blob path used, namespaced {user_id}/{document_id}/{filename}."""
        blob_path = f"{user_id}/{document_id}/{filename}"
        async with self._service_client() as service:
            container = service.get_container_client(self._container_name)
            await container.upload_blob(
                name=blob_path,
                data=content,
                overwrite=True,
                content_type=content_type,
            )
        return blob_path

    async def download(self, blob_path: str) -> bytes:
        async with self._service_client() as service:
            container = service.get_container_client(self._container_name)
            stream = await container.download_blob(blob_path)
            return await stream.readall()

    async def delete(self, blob_path: str) -> None:
        async with self._service_client() as service:
            container = service.get_container_client(self._container_name)
            await container.delete_blob(blob_path)

    async def delete_prefix(self, user_id: str) -> None:
        """Deletes every blob under {user_id}/ -- used by account deletion.
        Doesn't depend on Mongo being queryable first, so it's retryable/idempotent
        even if something fails partway through account deletion."""
        async with self._service_client() as service:
            container = service.get_container_client(self._container_name)
            async for blob in container.list_blobs(name_starts_with=f"{user_id}/"):
                await container.delete_blob(blob.name)
