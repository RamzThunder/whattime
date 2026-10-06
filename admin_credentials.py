"""Token storage in the native OS vault; defaults to the administrator GitHub credential."""
import sys

SERVICE = 'com.whattime.schedule-admin'
ACCOUNT = 'github-token'


def native_vault():
    # Explicit native backends: never fall back to a plaintext file backend.
    if sys.platform == 'darwin':
        from keyring.backends.macOS import Keyring
        return Keyring()
    if sys.platform == 'win32':
        from keyring.backends.Windows import WinVaultKeyring
        return WinVaultKeyring()
    raise RuntimeError('토큰 저장은 macOS와 Windows에서 지원해요.')


class AdminCredentials:
    def __init__(self, vault=None, service=SERVICE, account=ACCOUNT):
        self._vault = vault
        self._service = service
        self._account = account

    def _backend(self):
        if self._vault is None:
            self._vault = native_vault()
        return self._vault

    def get(self):
        return self._backend().get_password(self._service, self._account) or ''

    def save(self, token):
        token = token.strip()
        if not token:
            raise ValueError('저장할 토큰을 입력하세요.')
        self._backend().set_password(self._service, self._account, token)

    def delete(self):
        if self.get():
            self._backend().delete_password(self._service, self._account)
