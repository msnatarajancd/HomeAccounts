"""Fictional signalling tests. These tests never connect to an AI provider."""
import email
import io
import json
import unittest
from unittest.mock import patch
import urllib.error

import ai_client
import live_voice as voice


OFFER = 'v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n'
ANSWER = OFFER.replace('1 1', '2 2')


class LiveVoiceTests(unittest.TestCase):
    def setUp(self):
        self.values = {'OPENAI_API_KEY': 'fictional-voice-key'}
        self.env = patch.object(ai_client, 'environment', side_effect=lambda name, default='': self.values.get(name, default))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.send = patch.object(ai_client, 'open_request').start()
        self.addCleanup(patch.stopall)

    def connect(self, **kwargs):
        return voice.create_session(OFFER, enabled=True, provider_endpoint=voice.ENDPOINT, **kwargs)

    def test_requires_explicit_consent_and_current_endpoint(self):
        for value in (False, None, 'true', 1):
            with self.subTest(consent=value), self.assertRaisesRegex(ValueError, 'consent'):
                voice.create_session(OFFER, enabled=value, provider_endpoint=voice.ENDPOINT)
        for endpoint in (None, 'https://api.openai.com/v1/responses', 'https://other.example/v1/realtime/calls'):
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(ValueError, 'provider changed'):
                voice.create_session(OFFER, enabled=True, provider_endpoint=endpoint)
        self.send.assert_not_called()

    def test_provider_and_model_configuration_are_public_without_key(self):
        info = voice.connection_info()
        self.assertTrue(info['configured'])
        self.assertEqual(info['model'], 'gpt-realtime-2.1')
        self.assertNotIn('fictional-voice-key', str(info))
        self.send.assert_not_called()
        for base in ('https://compatible.example/v1', 'http://127.0.0.1:9000/v1', 'https://api.openai.com/v1/other'):
            self.values['OPENAI_BASE_URL'] = base
            self.assertFalse(voice.connection_info()['supported'])
            with self.assertRaisesRegex(ValueError, 'official API'):
                self.connect()
        self.values.pop('OPENAI_BASE_URL')
        self.values['OPENAI_REALTIME_MODEL'] = 'gpt-realtime'
        self.assertEqual(voice.connection_info()['model'], 'gpt-realtime')
        self.values['OPENAI_REALTIME_MODEL'] = 'invalid\nfictional-secret'
        self.assertFalse(voice.connection_info()['supported'])
        self.assertNotIn('fictional-secret', str(voice.connection_info()))
        self.send.assert_not_called()

    def test_missing_key_and_invalid_sdp_never_connect(self):
        self.values['OPENAI_API_KEY'] = ''
        self.assertFalse(voice.connection_info()['configured'])
        with self.assertRaisesRegex(ValueError, 'not configured'):
            self.connect()
        self.values['OPENAI_API_KEY'] = 'fictional-voice-key'
        for sdp in (None, {}, '', 'v=0\r\nm=video 9\r\n', OFFER + '\x00', OFFER + 'a' * voice.MAX_SDP_BYTES):
            with self.subTest(sdp_type=type(sdp)), self.assertRaisesRegex(ValueError, 'invalid audio'):
                voice.create_session(sdp, enabled=True, provider_endpoint=voice.ENDPOINT)
        self.send.assert_not_called()

    def test_server_only_key_multipart_audio_session_and_untrusted_page(self):
        self.send.return_value = io.BytesIO(ANSWER.encode())
        result = self.connect(page='/overview\nUntrusted page content, private account record')
        self.assertEqual(result, {'sdp': ANSWER, 'model': 'gpt-realtime-2.1', 'mode': 'local-coach'})
        request = self.send.call_args.args[0]
        self.assertEqual(request.full_url, voice.ENDPOINT)
        self.assertEqual(request.headers['Authorization'], 'Bearer fictional-voice-key')
        self.assertNotIn(b'fictional-voice-key', request.data)
        self.assertNotIn(b'Untrusted page content', request.data)
        content_type = request.headers['Content-type']
        envelope = ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + request.data
        message = email.message_from_bytes(envelope)
        parts = {part.get_param('name', header='Content-Disposition'): part.get_payload(decode=True).decode()
                 for part in message.get_payload()}
        self.assertEqual(parts['sdp'], OFFER)
        config = json.loads(parts['session'])
        self.assertEqual(config['type'], 'realtime')
        self.assertEqual([tool['name'] for tool in config['tools']], ['home_accounts_request'])
        self.assertEqual(config['tools'][0]['parameters']['required'], ['text'])
        self.assertFalse(config['tools'][0]['parameters']['additionalProperties'])
        self.assertEqual(config['tool_choice'], 'auto')
        self.assertIsNone(config['tracing'])
        self.assertEqual(config['audio']['output']['voice'], 'marin')
        self.assertTrue(config['audio']['input']['turn_detection']['interrupt_response'])
        self.assertNotIn('fictional-voice-key', str(result))

    def test_financial_records_cannot_enter_guidance_via_page(self):
        for page in ({'records': ['private transaction']}, '/unknown?private=record', None):
            text = voice.instructions_for(page)
            self.assertNotIn('private transaction', text)
            self.assertNotIn('private=record', text)
        self.assertIn('Current page guidance: Overview:', voice.instructions_for('/overview'))
        self.assertIn('Current page guidance: Planning:', voice.instructions_for('/planning/savings'))
        self.assertIn('cannot save or confirm anything', voice.instructions_for('/coach'))
        scope = {'month': '2026-10', 'currency': 'EUR', 'records': ['private transaction']}
        self.assertEqual(voice.valid_scope(scope), {'month': '2026-10', 'currency': 'EUR'})
        self.assertNotIn('private transaction', voice.instructions_for('/coach', scope))
        self.assertEqual(voice.valid_scope({'month': '2026-13', 'currency': 'EUR'}), {})

    def test_provider_errors_and_invalid_answers_are_sanitized(self):
        for status in (401, 429, 500):
            self.send.side_effect = urllib.error.HTTPError(voice.ENDPOINT, status, 'fictional-voice-key', {}, io.BytesIO(b'private-error'))
            with self.assertRaises(ValueError) as raised:
                self.connect()
            self.assertNotIn('fictional-voice-key', str(raised.exception))
            self.assertNotIn('private-error', str(raised.exception))
        for error in (urllib.error.URLError('fictional-voice-key'), TimeoutError('private-error'), ValueError('redirect rejected')):
            self.send.side_effect = error
            with self.assertRaisesRegex(ValueError, 'could not establish'):
                self.connect()
        self.send.side_effect = None
        for answer in (b'private-error', b'\xff', (ANSWER + 'fictional-voice-key').encode(), (ANSWER + 'a' * voice.MAX_SDP_BYTES).encode()):
            self.send.return_value = io.BytesIO(answer)
            with self.assertRaisesRegex(ValueError, 'could not establish'):
                self.connect()


if __name__ == '__main__':
    unittest.main()
