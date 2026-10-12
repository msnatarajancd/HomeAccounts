"""Explicitly consented recorded dictation, held only in memory.

Only audio, a model and an optional language hint are sent. No account context,
files, transcript logs or credentials are returned to the browser.
"""
import base64
import binascii
import json
import re
import secrets
import urllib.error
import urllib.request

import ai_client


ENDPOINT = 'https://api.openai.com/v1/audio/transcriptions'
MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
MIME_EXTENSIONS = {'audio/webm': 'webm', 'audio/mp4': 'mp4',
                   'audio/ogg': 'ogg', 'audio/wav': 'wav'}


def model_name():
    value = ai_client.environment('OPENAI_TRANSCRIBE_MODEL', 'gpt-4o-mini-transcribe')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', value):
        raise ValueError('The dictation model configuration is invalid.')
    return value


def connection_info():
    """Public, secret-free availability. This performs no provider probe."""
    try:
        supported = (ai_client.base_url() == 'https://api.openai.com/v1'
                     and ai_client.provider_name().casefold() == 'openai')
        model = model_name()
        error = None if supported else 'Recorded dictation requires the OpenAI provider and official API endpoint.'
    except ValueError as exc:
        supported, model, error = False, None, str(exc)
    return {'configured': supported and ai_client.configured(), 'supported': supported,
            'provider': 'OpenAI', 'model': model, 'endpoint': ENDPOINT,
            'error': error, 'max_audio_bytes': MAX_AUDIO_BYTES,
            'mime_types': list(MIME_EXTENSIONS)}


def validate_audio(audio, mime):
    if not isinstance(mime, str) or len(mime) > 200:
        raise ValueError('Choose a supported audio recording format: WebM, MP4, Ogg or WAV.')
    mime = mime.split(';', 1)[0].strip().lower()
    if mime not in MIME_EXTENSIONS:
        raise ValueError('Choose a supported audio recording format: WebM, MP4, Ogg or WAV.')
    if (not isinstance(audio, str) or not audio
            or len(audio) > 4 * ((MAX_AUDIO_BYTES + 2) // 3)):
        raise ValueError('The recording is empty or too large. Record a shorter clip, up to 8 MB.')
    try:
        data = base64.b64decode(audio, validate=True)
    except (binascii.Error, ValueError, UnicodeError):
        raise ValueError('The audio recording could not be read. Record it again.') from None
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise ValueError('The recording is empty or too large. Record a shorter clip, up to 8 MB.')
    signatures = {
        'audio/webm': len(data) >= 12 and data.startswith(b'\x1a\x45\xdf\xa3'),
        'audio/mp4': len(data) >= 12 and data[4:8] == b'ftyp',
        'audio/ogg': len(data) >= 27 and data.startswith(b'OggS\x00'),
        'audio/wav': len(data) >= 12 and data.startswith(b'RIFF') and data[8:12] == b'WAVE',
    }
    if not signatures[mime]:
        raise ValueError('The recording does not match its audio format. Record it again using a supported browser.')
    return data, mime


def multipart_audio(data, mime, model, language):
    boundary = 'HomeAccountsDictation' + secrets.token_hex(20)
    fields = [('model', model), ('response_format', 'json')]
    if language:
        fields.append(('language', language))
    parts = []
    for name, value in fields:
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                      f'{value}\r\n').encode('utf-8'))
    parts.extend([
        (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
         f'filename="dictation.{MIME_EXTENSIONS[mime]}"\r\nContent-Type: {mime}\r\n\r\n').encode('ascii'),
        data, f'\r\n--{boundary}--\r\n'.encode('ascii'),
    ])
    return b''.join(parts), boundary


def transcribe(audio, mime, *, enabled=False, provider_endpoint=None, language=''):
    if enabled is not True:
        raise ValueError('Enable recorded dictation consent before sending audio to OpenAI. API usage may be charged.')
    info = connection_info()
    if not info['supported']:
        raise ValueError(info['error'])
    if provider_endpoint != ENDPOINT:
        raise ValueError('The dictation provider changed. Review the provider and enable dictation again.')
    if language not in ('', 'en', 'ta'):
        raise ValueError('Choose English or Tamil for the dictation language, or use automatic detection.')
    data, mime = validate_audio(audio, mime)
    key = ai_client.api_key()
    if not key:
        raise ValueError('OpenAI API access is not configured. Typed local chat remains available.')
    payload, boundary = multipart_audio(data, mime, info['model'], language)
    request = urllib.request.Request(ENDPOINT, data=payload, method='POST', headers={
        'Authorization': 'Bearer ' + key,
        'Content-Type': 'multipart/form-data; boundary=' + boundary,
        'Accept': 'application/json',
    })
    try:
        with ai_client.open_request(request, timeout=45) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError(ai_client.provider_error_message(exc, feature='dictation')) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ValueError('OpenAI dictation could not connect. Retry manually or continue typing.') from None
    try:
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError('Response exceeds limit.')
        result = json.loads(raw)
        text = result.get('text') if isinstance(result, dict) else None
        if not isinstance(text, str) or len(text) > 6000 or key in text or '\x00' in text:
            raise ValueError('Unexpected transcript.')
        text = text.strip()
    except (ValueError, TypeError, UnicodeError):
        raise ValueError('OpenAI dictation returned an unreadable transcript. Try a shorter recording or continue typing.') from None
    if not text:
        raise ValueError('No speech was recognized. Try a short recording and speak near the microphone, or continue typing.')
    return {'text': text}
