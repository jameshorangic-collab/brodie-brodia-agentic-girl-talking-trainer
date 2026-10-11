"""Minimal P02 roleplay hook: start one Park + Neutral conversation."""


def on_event(event, say_now, ask_voice):
    if event.get('type') == 'session' and event.get('state') == 'open':
        ask_voice('Greet the caller naturally as an adult you have just encountered in a park. Keep it to one short sentence and wait for their reply.')
