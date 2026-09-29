import unittest
from unittest.mock import Mock

from admin_credentials import AdminCredentials, SERVICE, ACCOUNT
from schedule_admin import AdminApi


class MemoryVault:
    def __init__(self):
        self.values = {}

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, password):
        self.values[service, account] = password

    def delete_password(self, service, account):
        del self.values[service, account]


class CredentialTests(unittest.TestCase):
    def test_save_reload_replace_delete(self):
        vault = MemoryVault()
        first = AdminCredentials(vault)
        first.save(' test-only-token ')
        second = AdminCredentials(vault)
        self.assertEqual(second.get(), 'test-only-token')
        second.save('replacement')
        self.assertEqual(first.get(), 'replacement')
        self.assertEqual(list(vault.values), [(SERVICE, ACCOUNT)])
        second.delete()
        self.assertEqual(first.get(), '')
        second.delete()  # Already absent is harmless.

    def test_empty_token_does_not_erase_existing(self):
        credentials = AdminCredentials(MemoryVault())
        credentials.save('existing')
        with self.assertRaises(ValueError): credentials.save(' ')
        self.assertEqual(credentials.get(), 'existing')

    def test_status_never_returns_secret_and_publisher_uses_saved_token(self):
        api = AdminApi()
        api._credentials = AdminCredentials(MemoryVault())
        self.assertEqual(api.save_token('test-only-token'), {'ok': True, 'saved': True})
        self.assertEqual(api.credential_status(), {'ok': True, 'saved': True})
        api.publisher = Mock()
        api.publisher.load.return_value = {'version': 1, 'schools': []}
        api.load({}, '')
        api.publisher.load.assert_called_once_with({}, 'test-only-token')
        api.load({}, 'entered-replacement')
        self.assertEqual(api.publisher.load.call_args.args[1], 'entered-replacement')
        self.assertEqual(api._credentials.get(), 'test-only-token')
        self.assertTrue(api.delete_token()['ok'])
        self.assertFalse(api.credential_status()['saved'])

    def test_vault_errors_do_not_expose_secrets(self):
        api = AdminApi()
        api._credentials = Mock()
        secret_message = 'secret-marker-not-to-be-returned'
        for method in ['get', 'save', 'delete']:
            getattr(api._credentials, method).side_effect = RuntimeError(secret_message)
        for result in [api.credential_status(), api.save_token('sample'), api.delete_token(), api.load({}, '')]:
            self.assertFalse(result['ok'])
            self.assertNotIn(secret_message, str(result))
