from chalice import Chalice
import boto3
import google.generativeai as genai
import httpx
import os

VERIFY_TOKEN = os.environ['VERIFY_TOKEN']
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
WHATSAPP_ACCESS_TOKEN = os.environ['WHATSAPP_ACCESS_TOKEN']

app = Chalice(app_name='whats-bot-api')

class DynamoDBClient:

    def __init__(self, user_phone_number: str, client_phone_number: str) -> None:
        self.client = boto3.client('dynamodb')
        self.user_phone_number = user_phone_number
        self.client_phone_number = client_phone_number

    def get_history(self):
        return self.client.get_item(
            TableName='chat_history',
            Key={
                'user_phone_number': self.user_phone_number,
                'client_phone_number': self.client_phone_number
            },
            AttributesToGet=['history']
        )

    def save_history(self, old_history: list, new_message: str, new_response: str):
        self.client.update_item(
            TableName='chat_history',
            Key={
                'user_phone_number': self.user_phone_number,
                'client_phone_number': self.client_phone_number,
            },
            # UpdateExpression='SET history = list_append(history, :new_message, :new_response)',
            # ExpressionAttributeValues={
            #     ':new_message': [new_message],
            #     ':new_response': [new_response]
            # },
            AttributeUpdates={
                'history': old_history.extend(
                    [
                        {"role": "user", "parts": new_message},
                        {"role": "model", "parts": new_response}
                    ]
                )
            }
        )

def send_message_to_gemini(message: str, history: list):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.start_chat(history = history).send_message(message)
    return response.text

def send_message_to_whatsapp(user_phone_number_id: str, client_phone_number: str, message: str):
    url = f"https://graph.facebook.com/v21.0/{user_phone_number_id}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": client_phone_number,
        "type": "text",
        "text": {
            "preview_url": True,
            "body": message
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"
    }

    with httpx.Client() as client:
        response = client.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        raise RuntimeError(f"Failed to send message to WhatsApp. \nStatus Code: {response.status_code}. \nResponse: {response.text}")


@app.route('/webhook', methods=['GET'])
def webhook_verify():
    # Get all query parameters from the GET request
    query_params = app.current_request.query_params

    hub_verify_token = query_params.get('hub_verify_token')
    hub_mode = query_params.get('hub_mode')

    if hub_verify_token == VERIFY_TOKEN and hub_mode == 'subscribe':
        # Log a successful verification
        return query_params.get("hub_challenge")
    else:
        # Log an unsuccessful verification
        return {'error': 'Wrong verify token'}


@app.route('/message', methods=['POST'])
def message_handler():
    # Get the JSON body from the POST request
    body = app.current_request.json_body

    message = body \
                .get('entry')[0] \
                .get('changes')[0] \
                .get('value') \
                .get('messages')[0] \
                .get('text') \
                .get('body')

    client_phone_number = body \
                .get('entry')[0] \
                .get('changes')[0] \
                .get('value') \
                .get('contacts')[0] \
                .get('wa_id')

    client_name = body \
                .get('entry')[0] \
                .get('changes')[0] \
                .get('value') \
                .get('contacts')[0] \
                .get('profile') \
                .get('name')
    
    user_phone_number = body \
                .get('entry')[0] \
                .get('changes')[0] \
                .get('value') \
                .get('metadata') \
                .get('display_phone_number')
    
    user_phone_id = body \
                .get('entry')[0] \
                .get('changes')[0] \
                .get('value') \
                .get('metadata') \
                .get('phone_number_id')
    
    # dynamo_db = DynamoDBClient(user_phone_number, client_phone_number)
    # history = dynamo_db.get_history()

    # response = send_message_to_gemini(
    #     message = message,
    #     history = history
    # )

    # dynamo_db.save_history(
    #     old_history = history,
    #     new_message = message,
    #     new_response = response
    # )

    send_message_to_whatsapp(
        user_phone_number_id = user_phone_id,
        client_phone_number = client_phone_number,
        message = message
    )

    return {
        'message': message,
        'client_phone_number': client_phone_number,
        'client_name': client_name,
        'user_phone_number': user_phone_number,
        'user_phone_id': user_phone_id
    }

# The view function above will return {"hello": "world"}
# whenever you make an HTTP GET request to '/'.
#
# Here are a few more examples:
#
# @app.route('/hello/{name}')
# def hello_name(name):
#    # '/hello/james' -> {"hello": "james"}
#    return {'hello': name}
#
# @app.route('/users', methods=['POST'])
# def create_user():
#     # This is the JSON body the user sent in their POST request.
#     user_as_json = app.current_request.json_body
#     # We'll echo the json body back to the user in a 'user' key.
#     return {'user': user_as_json}
#
# See the README documentation for more examples.
#
