from chalice import Chalice
from os import environ
import asyncio
from src.services import receive_and_respond_message

VERIFY_TOKEN = environ['VERIFY_TOKEN']

app = Chalice(app_name='whats-bot-api')

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

    client_message = body \
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
    
    user_phone_id = body \
                .get('entry')[0] \
                .get('changes')[0] \
                .get('value') \
                .get('metadata') \
                .get('phone_number_id')
    
    asyncio.run(
        receive_and_respond_message(
            user_phone_id = user_phone_id,
            client_phone_number = client_phone_number,
            client_message = client_message
        )
    )
