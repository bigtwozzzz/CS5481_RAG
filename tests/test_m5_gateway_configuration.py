"""A gateway credential is bound to its explicit HTTPS service."""
import os
import unittest
from unittest.mock import patch

from scripts.m5_generation.api import ENDPOINT, M5Error, configured_endpoint, read_key


class GatewayConfigurationTests(unittest.TestCase):
    def test_default_provider_preserved(self):
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY':'fixture'}, clear=True):
            self.assertEqual(configured_endpoint(), ENDPOINT)
            self.assertEqual(read_key(), 'fixture')

    def test_gateway_selects_own_key_and_endpoint(self):
        with patch.dict(os.environ, {'M5_API_BASE':'https://example.test/v1/',
                                    'M5_API_KEY':'gateway-fixture',
                                    'DEEPSEEK_API_KEY':'other-fixture'}, clear=True):
            self.assertEqual(configured_endpoint(), 'https://example.test/v1/chat/completions')
            self.assertEqual(read_key(), 'gateway-fixture')

    def test_gateway_key_requires_base(self):
        with patch.dict(os.environ, {'M5_API_KEY':'fixture'}, clear=True):
            with self.assertRaises(M5Error) as raised:
                read_key()
            self.assertEqual(raised.exception.code, 'MISSING_API_BASE')

    def test_provider_key_cannot_fill_missing_gateway_key(self):
        with patch.dict(os.environ, {'M5_API_BASE':'https://example.test/v1',
                                    'DEEPSEEK_API_KEY':'fixture'}, clear=True):
            with self.assertRaises(M5Error):
                read_key()

    def test_unsafe_urls_rejected(self):
        for base in ('http://example.test/v1', 'https://user:pass@example.test/v1',
                     'https://example.test/v1?key=fixture', 'https://example.test/v1#fragment'):
            with self.subTest(base=base), patch.dict(os.environ, {'M5_API_BASE':base}, clear=True):
                with self.assertRaises(M5Error):
                    configured_endpoint()
