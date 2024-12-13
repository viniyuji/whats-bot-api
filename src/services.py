import aioboto3
from httpx import AsyncClient as HttpxClient
from os import environ
import asyncio

GEMINI_API_KEY = environ['GEMINI_API_KEY']
AWS_ACCESS_KEY_ID = environ['AWS_ACCESS_KEY_ID']
AWS_SECRET_ACCESS_KEY = environ['AWS_SECRET_ACCESS_KEY']
AWS_DEFAULT_REGION = environ['AWS_DEFAULT_REGION']

class DynamoDBClient:

    def __init__(self, user_phone_id: str, client_phone_number: str) -> None:
        self.user_phone_id = user_phone_id
        self.client_phone_number = client_phone_number
        self._chat_history = None
        self._client = None

    async def init_client(self) -> None:
        session = aioboto3.Session()
        self._client = await session.client(
            'dynamodb',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_DEFAULT_REGION
        ).__aenter__()

    async def close_client(self) -> None:
        await self._client.__aexit__(None, None, None)
        self._client = None

    # @staticmethod
    # def to_dynamodb_format(data):
    #     """Convert Python types to DynamoDB format."""
    #     if isinstance(data, str):
    #         return {"S": data}
    #     elif isinstance(data, dict):
    #         return {"M": {k: DynamoDBClient.to_dynamodb_format(v) for k, v in data.items()}}
    #     elif isinstance(data, list):
    #         return {"L": [DynamoDBClient.to_dynamodb_format(v) for v in data]}
    #     elif isinstance(data, int):
    #         return {"N": str(data)}  # DynamoDB stores numbers as strings
    #     elif data is None:
    #         return {"NULL": True}
    #     else:
    #         raise ValueError(f"Unsupported data type: {type(data)}")

    @staticmethod
    def from_dynamodb_format(data: dict) -> dict:
        """Convert DynamoDB format back to Python types."""
        if "S" in data:
            return data["S"]
        elif "M" in data:
            return {k: DynamoDBClient.from_dynamodb_format(v) for k, v in data["M"].items()}
        elif "L" in data:
            return [DynamoDBClient.from_dynamodb_format(v) for v in data["L"]]
        elif "N" in data:
            return int(data["N"]) if "." not in data["N"] else float(data["N"])
        elif "NULL" in data:
            return None
        else:
            raise ValueError(f"Unsupported DynamoDB type: {data}")

    async def get_user_data(self) -> tuple[str, str]:
        response = await self._client.get_item(
            TableName='users',
            Key={
                'user_phone_id': {'S': self.user_phone_id}
            }
        )
        user_input = response.get('Item', {}).get('input', {}).get('S', '')
        whatsapp_access_token = response.get('Item', {}).get('whatsapp_access_token', {}).get('S', '')
        return user_input, whatsapp_access_token

    async def get_chat_history(self) -> list:
        response = await self._client.get_item(
            TableName='chat_history',
            Key={
                'user_phone_id': {'S': self.user_phone_id},
                'client_phone_number': {'S': self.client_phone_number}
            },
            AttributesToGet=['history']
        )

        result = response.get('Item', {}).get('history', {}).get('L', [])
        self._chat_history = result
        return [DynamoDBClient.from_dynamodb_format(element) for element in result]

    async def save_chat_history(self, new_message: str, new_response: str) -> None:
        self._chat_history.extend(
            [
                {
                    'M': {
                        "role": {"S": "user"},
                        "parts": {"L": [
                            {"M": {"text": {"S": new_message}}}
                        ]}
                    }
                },
                {
                    'M': {
                        "role": {"S": "model"},
                        "parts": {"L": [
                            {"M": {"text": {"S": new_response}}}
                        ]}
                    }
                }
            ]
        )

        await self._client.update_item(
            TableName='chat_history',
            Key={
                'user_phone_id': {'S': self.user_phone_id},
                'client_phone_number': {'S': self.client_phone_number}
            },
            UpdateExpression="SET history = :history",
            ExpressionAttributeValues={
                ':history': {'L': self._chat_history}
            }
        )

class WhatsAppClient:

    def __init__(self, user_phone_id: str, client_phone_number: str) -> None:
        self.user_phone_id = user_phone_id
        self.client_phone_number = client_phone_number
    
    async def send_message_to_whatsapp(self, message: str, whatsapp_access_token: str) -> None:
        url = f"https://graph.facebook.com/v21.0/{self.user_phone_id}/messages"

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self.client_phone_number,
            "type": "text",
            "text": {
                "preview_url": True,
                "body": message
            }
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {whatsapp_access_token}"
        }

        async with HttpxClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()

class GeminiClient:

    @staticmethod
    async def send_message_to_gemini(user_input: str, message: str, history: list) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

        headers = {
            "Content-Type": "application/json"
        }

        contents = [
            {
                "role": "user",
                "parts": [
                    {
                        "text": user_input
                    }
                ]
            }
        ] + history + \
        [
            {
                "role": "user",
                "parts": [
                    {
                        "text": message
                    }
                ]
            }
        ]

        payload = {
            "contents": contents
        }

        async with HttpxClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()    

            return response.json().get('candidates')[0].get('content').get('parts')[0].get('text')

async def receive_and_respond_message(user_phone_id: str, client_phone_number: str, client_message: str) -> None:
    dynamo_db_client = DynamoDBClient(user_phone_id, client_phone_number)
    whatsapp_client = WhatsAppClient(user_phone_id, client_phone_number)
    gemini_client = GeminiClient()

    await dynamo_db_client.init_client()

    history, (user_input, whatsapp_access_token) = await asyncio.gather(
        dynamo_db_client.get_chat_history(),
        dynamo_db_client.get_user_data()
    )

    gemini_response = await gemini_client.send_message_to_gemini(
        message = client_message,
        history = history,
        user_input = user_input
    )

    await asyncio.gather(
        whatsapp_client.send_message_to_whatsapp(
            message = gemini_response,
            whatsapp_access_token = whatsapp_access_token
        ),
        dynamo_db_client.save_chat_history(
            new_message = client_message,
            new_response = gemini_response
        )
    )

    await dynamo_db_client.close_client()