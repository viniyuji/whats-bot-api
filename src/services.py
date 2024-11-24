import aioboto3
import httpx
import os
from functools import lru_cache

GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
AWS_ACCESS_KEY_ID = os.environ['AWS_ACCESS_KEY_ID']
AWS_SECRET_ACCESS_KEY = os.environ['AWS_SECRET_ACCESS_KEY']
AWS_DEFAULT_REGION = os.environ['AWS_DEFAULT_REGION']

class DynamoDBClient:

    def __init__(self, user_phone_id: str, client_phone_number: str) -> None:
        self.user_phone_id = user_phone_id
        self.client_phone_number = client_phone_number
        self._chat_history = None

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

    async def get_chat_history(self) -> list:
        async with aioboto3.Session().client(
            'dynamodb',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_DEFAULT_REGION
        ) as client:
            response = await client.get_item(
                TableName='chat_history',
                Key={
                    'user_phone_id': {'S': self.user_phone_id},
                    'client_phone_number': {'S': self.client_phone_number}
                },
                AttributesToGet=['history']
            )

            try:
                result = response.get('Item').get('history').get('L')
                self._chat_history = result
                return [DynamoDBClient.from_dynamodb_format(element) for element in result]
            except AttributeError as e:
                print(e)
                self._chat_history = []
                return []

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

        async with aioboto3.Session().client(
            'dynamodb',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_DEFAULT_REGION
        ) as client:
            await client.update_item(
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
        self._whatsapp_access_token = None

    @staticmethod
    @lru_cache()
    async def _get_access_token(user_phone_id: str) -> str:
        '''
        Argument user_phone_id is used to cache the return of the method, independant of the class instance.
        It's an optimization to avoid calling the AWS Secrets Manager API multiple times.
        It could be an isolated function, as it's supposed to be a high order function, but it's here for the sake of organization.
        '''
        async with aioboto3.Session().client(
            'secretsmanager',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_DEFAULT_REGION
        ) as client:
            response = await client.get_secret_value(
                SecretId = f'user_phone_id/{user_phone_id}'
            )
            return response.get('SecretString')
        
    async def set_access_token(self) -> None:
        self._whatsapp_access_token = await self._get_access_token(self.user_phone_id)
        
    async def send_message_to_whatsapp(self, message: str) -> None:
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
            "Authorization": f"Bearer {self._whatsapp_access_token}"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)

            if response.status_code != 200:
                raise RuntimeError(f"Failed to send message to WhatsApp. \nStatus Code: {response.status_code}. \nResponse: {response.text}")

# class GeminiClient:

#     @staticmethod
#     async def send_message_to_gemini(message: str, history: list):
#         genai.configure(api_key=GEMINI_API_KEY)
#         model = genai.GenerativeModel("gemini-1.5-flash")
#         chat = model.start_chat(history = history)
#         response = await asyncio.to_thread(
#             chat.send_message(message)
#         )
#         return response.text

class GeminiClient:

    @staticmethod
    async def send_message_to_gemini(message: str, history: list) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

        headers = {
            "Content-Type": "application/json"
        }

        history.append(
            {
                "role": "user",
                "parts": [
                    {
                        "text": message
                    }
                ]
            }
        )

        payload = {
            "contents": history
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response = response.json()

            if response.get('error'):
                raise RuntimeError(response.get('error'))
            else:
                return response.get('candidates')[0].get('content').get('parts')[0].get('text')