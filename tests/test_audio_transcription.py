"""Fictional audio and mocked HTTP only; no real API, key lookup or recording."""
import base64
import email
import io
import json
import unittest
from unittest.mock import patch
import urllib.error

import ai_client
import audio_transcription as audio
import live_voice


CLIPS = {
    'audio/webm': b'\x1a\x45\xdf\xa3' + b'fictional-webm-header',
    'audio/mp4': b'\x00\x00\x00\x18ftypM4A ' + b'fictional-mp4',
    'audio/ogg': b'OggS\x00' + b'\x00' * 22 + b'fictional-ogg',
    'audio/wav': b'RIFF\x20\x00\x00\x00WAVE' + b'fictional-wav',
}
OFFER = 'v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n'


class AudioTranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.values = {'OPENAI_API_KEY': 'fictional-dictation-secret'}
        env = patch.object(ai_client, 'environment', side_effect=lambda name, default='': self.values.get(name, default))
        env.start()
        self.addCleanup(env.stop)
        send = patch.object(ai_client, 'open_request')
        self.send = send.start()
        self.addCleanup(send.stop)

    def transcribe(self, *, mime='audio/webm', clip=None, **kwargs):
        clip = CLIPS.get(mime.split(';', 1)[0], b'fictional') if clip is None else clip
        return audio.transcribe(base64.b64encode(clip).decode('ascii'), mime, enabled=True,
                                provider_endpoint=audio.ENDPOINT, **kwargs)

    def response(self, text):
        self.send.return_value = io.BytesIO(json.dumps({'text': text}, ensure_ascii=False).encode('utf-8'))

    def http_error(self, code, status=429):
        body = json.dumps({'error': {'code': code, 'message': 'private transcript fictional-dictation-secret'}}).encode()
        return urllib.error.HTTPError(audio.ENDPOINT, status, 'fictional-dictation-secret', {}, io.BytesIO(body))

    def test_explicit_consent_and_exact_provider_endpoint_required(self):
        encoded = base64.b64encode(CLIPS['audio/webm']).decode()
        for consent in (None, False, 'true', 1, [], {}):
            with self.subTest(consent=consent), self.assertRaisesRegex(ValueError, 'consent'):
                audio.transcribe(encoded, 'audio/webm', enabled=consent, provider_endpoint=audio.ENDPOINT)
        for endpoint in (None, 'https://other.example/v1/audio/transcriptions', audio.ENDPOINT + '?key=private'):
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(ValueError, 'provider changed'):
                audio.transcribe(encoded, 'audio/webm', enabled=True, provider_endpoint=endpoint)
        self.send.assert_not_called()

    def test_public_configuration_excludes_secrets_and_rejects_custom_provider(self):
        info = audio.connection_info()
        self.assertTrue(info['configured'])
        self.assertEqual(info['model'], 'gpt-4o-mini-transcribe')
        self.assertEqual(info['max_audio_bytes'], 8 * 1024 * 1024)
        self.assertNotIn('fictional-dictation-secret', str(info))
        for base in ('https://compatible.example/v1', 'http://127.0.0.1:9000/v1'):
            self.values['OPENAI_BASE_URL'] = base
            self.assertFalse(audio.connection_info()['supported'])
            with self.assertRaisesRegex(ValueError, 'official API'):
                self.transcribe()
        self.values.pop('OPENAI_BASE_URL')
        self.values['HOMEACCOUNTS_AI_PROVIDER'] = 'Compatible'
        self.assertFalse(audio.connection_info()['supported'])
        self.values.pop('HOMEACCOUNTS_AI_PROVIDER')
        self.values['OPENAI_TRANSCRIBE_MODEL'] = 'gpt-4o-transcribe'
        self.assertEqual(audio.connection_info()['model'], 'gpt-4o-transcribe')
        self.values['OPENAI_TRANSCRIBE_MODEL'] = 'bad\nfictional-dictation-secret'
        self.assertFalse(audio.connection_info()['configured'])
        self.assertNotIn('fictional-dictation-secret', str(audio.connection_info()))
        self.send.assert_not_called()

    def test_invalid_recordings_rejected_before_provider_call(self):
        for value in (None, {}, '', '*bad*', 'not base64', '\u00e9', 'data:audio/webm;base64,abcd'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                audio.transcribe(value, 'audio/webm', enabled=True, provider_endpoint=audio.ENDPOINT)
        for mime in ('video/webm', 'text/html', '', None, {}, 'audio/wav\r\nX-Secret: value'):
            with self.subTest(mime=mime), self.assertRaisesRegex(ValueError, 'format'):
                audio.transcribe('YQ==', mime, enabled=True, provider_endpoint=audio.ENDPOINT)
        for mime in CLIPS:
            with self.subTest(mime=mime), self.assertRaisesRegex(ValueError, 'does not match'):
                self.transcribe(mime=mime, clip=b'<html>not audio</html>' * 2)
        with self.assertRaisesRegex(ValueError, 'too large'):
            self.transcribe(clip=CLIPS['audio/webm'] + b'a' * audio.MAX_AUDIO_BYTES)
        # This length rounds to the same base64 bound as the maximum, exercising
        # the decoded limit separately from the encoded-length check.
        with self.assertRaisesRegex(ValueError, 'too large'):
            self.transcribe(clip=b'a' * (audio.MAX_AUDIO_BYTES + 1))
        self.send.assert_not_called()

    def test_missing_key_and_language_allowlist_prevent_requests(self):
        for language in ('fr', 'en-US', 'ta-IN', None, [], {'text':'private'}):
            with self.subTest(language=language), self.assertRaisesRegex(ValueError, 'English or Tamil'):
                self.transcribe(language=language)
        self.values['OPENAI_API_KEY'] = ''
        self.assertFalse(audio.connection_info()['configured'])
        with self.assertRaisesRegex(ValueError, 'not configured'):
            self.transcribe()
        self.send.assert_not_called()

    def test_valid_multipart_preserves_bytes_and_never_sends_account_context(self):
        for mime, clip in CLIPS.items():
            with self.subTest(mime=mime):
                self.response('  Fictional purchase yesterday  ')
                result = self.transcribe(mime=mime + ';codecs=opus', language='en')
                self.assertEqual(result, {'text': 'Fictional purchase yesterday'})
                request = self.send.call_args.args[0]
                self.assertEqual(request.full_url, audio.ENDPOINT)
                self.assertEqual(request.headers['Authorization'], 'Bearer fictional-dictation-secret')
                self.assertEqual(self.send.call_args.kwargs['timeout'], 45)
                self.assertNotIn(b'fictional-dictation-secret', request.data)
                envelope = ('Content-Type: ' + request.headers['Content-type'] + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + request.data
                message = email.message_from_bytes(envelope)
                parts = {part.get_param('name', header='Content-Disposition'): part for part in message.get_payload()}
                self.assertEqual(set(parts), {'model', 'response_format', 'language', 'file'})
                self.assertEqual(parts['file'].get_payload(decode=True), clip)
                self.assertEqual(parts['file'].get_content_type(), mime)
                self.assertEqual(parts['file'].get_filename(), 'dictation.' + audio.MIME_EXTENSIONS[mime])
                self.assertEqual(parts['response_format'].get_payload(decode=True), b'json')
                self.assertEqual(parts['language'].get_payload(decode=True), b'en')

    def test_tamil_auto_language_and_transcript_bounds(self):
        self.response('தமிழில் ஒரு சோதனை')
        self.assertEqual(self.transcribe(language='ta'), {'text': 'தமிழில் ஒரு சோதனை'})
        self.response('A' * 6000)
        self.assertEqual(len(self.transcribe()['text']), 6000)
        self.assertNotIn(b'name="language"', self.send.call_args.args[0].data)
        for value in ('', '   ', '\n'):
            self.response(value)
            with self.assertRaisesRegex(ValueError, 'No speech was recognized'):
                self.transcribe()
        for value in ('A' * 6001, 'fictional-dictation-secret', '\x00', None, ['bad']):
            self.response(value)
            with self.assertRaisesRegex(ValueError, 'unreadable transcript'):
                self.transcribe()
        for raw in (b'private transcript', b'\xff', b'[]', b'a' * (audio.MAX_RESPONSE_BYTES + 1)):
            self.send.return_value = io.BytesIO(raw)
            with self.assertRaisesRegex(ValueError, 'unreadable transcript'):
                self.transcribe()

    def test_credit_rate_and_auth_errors_are_distinct_and_sanitized(self):
        for code, status, expected in (
            ('credit_balance_exhausted', 429, 'prepaid credit balance is exhausted'),
            ('rate_limit_exceeded', 429, 'temporary rate limit'),
            ('insufficient_quota', 429, 'no available API quota'),
            ('project_spend_limit_exceeded', 429, 'spending limit'),
            ('invalid_api_key', 401, 'could not authenticate'),
            (None, 403, 'does not have access'),
            ('model_not_found', 404, 'configured model'),
            (None, 503, 'temporarily unavailable'),
        ):
            with self.subTest(code=code):
                self.send.side_effect = self.http_error(code, status)
                with self.assertRaisesRegex(ValueError, expected) as raised:
                    self.transcribe()
                self.assertNotIn('fictional-dictation-secret', str(raised.exception))
                self.assertNotIn('private transcript', str(raised.exception))
        for body in (b'fictional-dictation-secret', b'[]', b'{"error":[]}', b'{"error":{"code":{}}}'):
            error = urllib.error.HTTPError(audio.ENDPOINT, 400, 'private transcript', {}, io.BytesIO(body))
            message = ai_client.provider_error_message(error, feature='private transcript')
            self.assertIn('request was rejected', message)
            self.assertNotIn('private transcript', message)
            self.assertNotIn('fictional-dictation-secret', message)

    def test_text_and_live_voice_share_prepaid_credit_guidance(self):
        self.send.side_effect = self.http_error('credit_balance_exhausted')
        with self.assertRaisesRegex(ValueError, 'prepaid credit balance is exhausted'):
            ai_client.request_proposal('test', {}, {}, '', enabled=True)
        self.send.side_effect = self.http_error('credit_balance_exhausted')
        with self.assertRaisesRegex(ValueError, 'prepaid credit balance is exhausted'):
            live_voice.create_session(OFFER, enabled=True, provider_endpoint=live_voice.ENDPOINT)

    def test_connection_errors_do_not_relay_private_details(self):
        for error in (urllib.error.URLError('fictional-dictation-secret'), TimeoutError('private transcript'), ValueError('redirect private transcript')):
            self.send.side_effect = error
            with self.assertRaisesRegex(ValueError, 'could not connect') as raised:
                self.transcribe()
            self.assertNotIn('private transcript', str(raised.exception))
            self.assertNotIn('fictional-dictation-secret', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
