from src.services import DynamoDBClient, WhatsAppClient, GeminiClient
import asyncio

async def receive_and_respond_message(user_phone_id: str, client_phone_number: str, client_message: str) -> None:
    dynamo_db_client = DynamoDBClient(user_phone_id, client_phone_number)
    whatsapp_client = WhatsAppClient(user_phone_id, client_phone_number)
    gemini_client = GeminiClient()

    history, _ = await asyncio.gather(
        dynamo_db_client.get_chat_history(),
        whatsapp_client.set_access_token()
    )

    gemini_response = await gemini_client.send_message_to_gemini(
        message = client_message,
        history = history
    )

    await asyncio.gather(
        whatsapp_client.send_message_to_whatsapp(
            message = gemini_response,
        ),
        dynamo_db_client.save_chat_history(
            new_message = client_message,
            new_response = gemini_response
        )
    )