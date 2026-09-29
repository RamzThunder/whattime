"""Standalone administrator UI. Run: python3 schedule_admin.py"""
import os
import sys
from schedule_documents import parse_schedule_document
from admin_credentials import AdminCredentials
from school_schedules import DEFAULT_SOURCE, GitHubPublisher, network_message, validate_feed


class AdminApi:
    def __init__(self):
        self.window = None
        self.publisher = GitHubPublisher()
        self._credentials = AdminCredentials()

    def import_schedule_document(self):
        import webview
        if self.window is None:
            return {'ok': False, 'error': '관리자 창을 다시 열어 주세요.'}
        try:
            selected = self.window.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=False,
                file_types=('Hangul documents (*.hwpx;*.hwp)', 'All files (*.*)'))
            if not selected:
                return {'ok': False, 'cancelled': True}
            path = selected[0] if isinstance(selected, (list, tuple)) else selected
            return {'ok': True, 'filename': os.path.basename(path),
                    'periods': parse_schedule_document(path)}
        except ValueError as error:
            return {'ok': False, 'error': str(error)}
        except Exception:
            return {'ok': False, 'error': '문서를 읽지 못했어요. 파일을 확인하거나 HWPX로 저장해 다시 불러오세요.'}

    def credential_status(self):
        try:
            return {'ok': True, 'saved': bool(self._credentials.get())}
        except Exception:
            return {'ok': False, 'error': '저장된 토큰을 읽지 못했어요. OS 자격 증명 접근을 허용하거나 토큰을 직접 입력하세요.'}

    def save_token(self, token):
        try:
            self._credentials.save(token)
            return {'ok': True, 'saved': True}
        except Exception:
            return {'ok': False, 'error': '토큰을 저장하지 못했어요. 입력값과 OS 자격 증명 접근 권한을 확인하세요.'}

    def delete_token(self):
        try:
            self._credentials.delete()
            return {'ok': True, 'saved': False}
        except Exception:
            return {'ok': False, 'error': '저장된 토큰을 삭제하지 못했어요. OS 자격 증명 접근 권한을 확인하세요.'}

    def _token(self, entered):
        if entered.strip():
            return entered.strip()
        try:
            return self._credentials.get()
        except Exception:
            raise ValueError('저장된 토큰에 접근할 수 없어요. 토큰을 직접 입력하세요.') from None

    def defaults(self):
        return DEFAULT_SOURCE

    def load(self, source, token):
        try:
            return {'ok': True, 'feed': self.publisher.load(source, self._token(token))}
        except Exception as error:
            return {'ok': False, 'error': network_message(error)}

    def validate(self, feed):
        try:
            return {'ok': True, 'feed': validate_feed(feed)}
        except Exception as error:
            return {'ok': False, 'error': network_message(error)}

    def publish(self, source, token, feed):
        try:
            return {'ok': True, **self.publisher.publish(source, self._token(token), feed)}
        except Exception as error:
            return {'ok': False, 'error': network_message(error)}


if __name__ == '__main__':
    import webview
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    api = AdminApi()
    api.window = webview.create_window('지금 몇교시야 · 특별시정 관리자',
                          os.path.join(base, 'schedule_admin.html'),
                          js_api=api, width=1080, height=820, min_size=(800, 640))
    webview.start(private_mode=True)
